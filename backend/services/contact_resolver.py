"""
Phase F.2 — Identity-linking service.

Walks a meeting's participants, upserts contacts by (twin_id, lower(email))
when email is present. No-email participants are skipped (best-effort).
Future: fuzzy name+org matching when LinkedIn enrichment lands.

Phase F.3 — Name-only contacts (recap-people extractor).
`upsert_name_only_contacts` creates/updates contacts that have no email,
deduplicating at the application level by (twin_id, lower(name), email IS NULL).

Phase F.4 — contact_meetings join + soft-delete.
`_link_contact_to_meeting` persists contact↔meeting associations.
Both link paths respect `contacts.deleted_at` to prevent resurrection.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from modules.observability import supabase

logger = logging.getLogger(__name__)


def _link_contact_to_meeting(
    tenant_id: str, twin_id: str, contact_id: str, meeting_id: str, source: str
) -> None:
    """Best-effort idempotent INSERT into contact_meetings. UNIQUE catches dups."""
    if not (tenant_id and twin_id and contact_id and meeting_id):
        return
    try:
        supabase.table("contact_meetings").insert({
            "tenant_id": tenant_id,
            "twin_id": twin_id,
            "contact_id": contact_id,
            "meeting_id": meeting_id,
            "source": source,
        }).execute()
    except Exception as exc:
        # Most common: 23505 unique_violation when this (contact, meeting)
        # row already exists. That's idempotent — swallow silently.
        msg = str(exc).lower()
        if "duplicate" in msg or "unique" in msg or "23505" in msg:
            return
        logger.info("[contact_resolver] contact_meeting link failed err=%s",
                    type(exc).__name__)


def link_meeting_contacts(meeting_id: str, tenant_id: str, twin_id: str) -> dict[str, int]:
    """
    Upsert contacts for each participant of a completed meeting.

    Returns counts of contacts created vs updated.
    Idempotent: re-running on the same meeting after a participant has already
    been linked is a no-op (UNIQUE(twin_id, lower(email)) catches duplicates).
    Respects deleted_at: soft-deleted contacts are skipped (not resurrected).
    """
    if not (meeting_id and tenant_id and twin_id):
        return {"created": 0, "updated": 0, "skipped": 0}

    # Fetch participants for this meeting
    try:
        resp = (
            supabase.table("meeting_participants")
            .select("id, participant_name, participant_email, contact_id")
            .eq("meeting_id", meeting_id)
            .execute()
        )
        participants = getattr(resp, "data", None) or []
    except Exception as exc:
        logger.warning("[contact_resolver] participants fetch failed meeting=%s err=%s",
                       meeting_id, type(exc).__name__)
        return {"created": 0, "updated": 0, "skipped": 0}

    created = 0
    updated = 0
    skipped = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for p in participants:
        email = (p.get("participant_email") or "").strip().lower()
        name = (p.get("participant_name") or "").strip()
        if not email:
            # No email = can't dedupe identity reliably. Skip until LinkedIn lands.
            skipped += 1
            continue
        if not name:
            name = email.split("@")[0]  # best-effort fallback

        # Look for existing contact by (twin_id, lower(email)).
        # BUG-4 fix: use ilike for case-insensitive match — aligns with the
        # unique index on lower(email) and handles any historical mixed-case rows.
        # Also select deleted_at to respect soft-deletes (Phase F.4).
        try:
            existing_resp = (
                supabase.table("contacts")
                .select("id, meeting_count, deleted_at")
                .eq("twin_id", twin_id)
                .eq("tenant_id", tenant_id)
                .ilike("email", email)
                .limit(1)
                .execute()
            )
            existing = (getattr(existing_resp, "data", None) or [None])[0]
        except Exception as exc:
            logger.warning("[contact_resolver] existing-lookup failed email=%s err=%s",
                           email, type(exc).__name__)
            skipped += 1
            continue

        # Phase F.4: if the contact is soft-deleted, do NOT resurrect it.
        if existing and existing.get("deleted_at"):
            skipped += 1
            continue

        # BUG-1 fix: track whether this participant was already linked before this
        # run. If contact_id was already set, this is a re-run / retry /
        # backfill — do NOT increment meeting_count a second time.
        already_linked = bool(p.get("contact_id"))
        contact_id: str | None = None

        if existing:
            # Update last_seen_at; only increment meeting_count on first link.
            contact_id = existing["id"]
            update_data: dict[str, Any] = {
                "last_seen_at": now_iso,
                "updated_at": now_iso,
            }
            if not already_linked:
                # First-time link for this participant → this meeting counts.
                update_data["meeting_count"] = (existing.get("meeting_count") or 0) + 1
            # If already_linked, skip the count bump — re-run / retry / backfill on
            # an already-linked participant must not inflate meeting_count.
            try:
                supabase.table("contacts").update(update_data).eq(
                    "id", contact_id,
                ).eq("tenant_id", tenant_id).execute()
                updated += 1
            except Exception as exc:
                logger.warning("[contact_resolver] update failed contact=%s err=%s",
                               contact_id, type(exc).__name__)
                skipped += 1
                continue
        else:
            # Insert new contact
            try:
                ins = supabase.table("contacts").insert({
                    "tenant_id": tenant_id,
                    "twin_id": twin_id,
                    "name": name,
                    "email": email,
                    "first_seen_at": now_iso,
                    "last_seen_at": now_iso,
                    "meeting_count": 1,
                }).execute()
                ins_row = (getattr(ins, "data", None) or [None])[0]
                contact_id = ins_row["id"] if ins_row else None
                created += 1
            except Exception as exc:
                logger.warning("[contact_resolver] insert failed email=%s err=%s",
                               email, type(exc).__name__)
                skipped += 1
                continue

        # Backfill meeting_participants.contact_id
        if contact_id and p.get("contact_id") != contact_id:
            try:
                supabase.table("meeting_participants").update({
                    "contact_id": contact_id,
                }).eq("id", p["id"]).execute()
            except Exception as exc:
                logger.info("[contact_resolver] backfill participant link failed: %s",
                            type(exc).__name__)

        # Phase F.4: persist contact↔meeting association
        if contact_id:
            _link_contact_to_meeting(
                tenant_id=tenant_id,
                twin_id=twin_id,
                contact_id=contact_id,
                meeting_id=meeting_id,
                source="participant",
            )

    logger.info("[contact_resolver] meeting=%s created=%d updated=%d skipped=%d",
                meeting_id, created, updated, skipped)
    return {"created": created, "updated": updated, "skipped": skipped}


def upsert_name_only_contacts(
    tenant_id: str,
    twin_id: str,
    people: list[dict[str, Any]],
    meeting_id: str,
    meeting_started_iso: str | None = None,
) -> dict[str, int]:
    """Upsert NO-EMAIL contacts (name-only) for the People surface.

    Dedup at the application level by (twin_id, lower(name)) WHERE email IS NULL
    — the table's unique index is partial on lower(email) so name duplicates are
    NOT prevented by Postgres. Skips empty / overly-long names.

    Phase F.4: writes to contact_meetings join for every create/update, respects
    deleted_at on existing contacts (no resurrection of soft-deleted rows).

    Returns counts {created, updated, skipped}.
    """
    if not (tenant_id and twin_id and people):
        return {"created": 0, "updated": 0, "skipped": 0}

    now_iso = datetime.now(timezone.utc).isoformat()
    seen_iso = (meeting_started_iso or now_iso).strip() or now_iso

    created = 0
    updated = 0
    skipped = 0
    for p in people:
        name = (p.get("name") or "").strip() if isinstance(p, dict) else ""
        if not name or len(name) < 2 or len(name) > 80:
            skipped += 1
            continue
        # Look for existing email-null contact with the same lowered name.
        # Phase F.4: also select deleted_at to respect soft-deletes.
        try:
            existing_resp = (
                supabase.table("contacts")
                .select("id, deleted_at, meeting_count")
                .eq("twin_id", twin_id)
                .eq("tenant_id", tenant_id)
                .is_("email", "null")
                .ilike("name", name)
                .limit(1)
                .execute()
            )
            existing = (getattr(existing_resp, "data", None) or [None])[0]
        except Exception as exc:
            logger.warning(
                "[contact_resolver] name-only lookup failed name=%s err=%s",
                name, type(exc).__name__,
            )
            skipped += 1
            continue

        # Phase F.4: if found and soft-deleted, skip — do not resurrect.
        if existing and existing.get("deleted_at"):
            skipped += 1
            continue

        # BUG-A fix: also check for an EMAIL-BEARING contact with the same
        # name. If found and alive, treat as already-tracked — don't insert a
        # duplicate no-email row. The email contact wins identity (richer data).
        if not existing:
            try:
                shadow_resp = (
                    supabase.table("contacts")
                    .select("id, deleted_at")
                    .eq("twin_id", twin_id)
                    .eq("tenant_id", tenant_id)
                    .not_.is_("email", "null")
                    .ilike("name", name)
                    .limit(1)
                    .execute()
                )
                shadow = (getattr(shadow_resp, "data", None) or [None])[0]
                if shadow:
                    # Phase F.4: if shadow is soft-deleted, skip it too.
                    if shadow.get("deleted_at"):
                        skipped += 1
                        continue
                    # Bump last_seen_at on the email-bearing contact instead
                    # of creating a parallel name-only row.
                    supabase.table("contacts").update({
                        "last_seen_at": seen_iso,
                        "updated_at": now_iso,
                    }).eq("id", shadow["id"]).eq("tenant_id", tenant_id).execute()
                    updated += 1
                    # Phase F.4: link the shadow contact to this meeting
                    _link_contact_to_meeting(
                        tenant_id=tenant_id,
                        twin_id=twin_id,
                        contact_id=shadow["id"],
                        meeting_id=meeting_id,
                        source="recap",
                    )
                    continue
            except Exception as exc:
                logger.info(
                    "[contact_resolver] shadow-check failed name=%s err=%s",
                    name, type(exc).__name__,
                )
                # Fall through to insert — safer to risk a duplicate than to
                # silently drop a name we know we saw.

        if existing:
            # We can't tell from here whether this meeting was already counted
            # for this contact (no participant row). Conservative: bump
            # last_seen_at, leave meeting_count alone to avoid the double-count
            # footgun (per BUG-1 pattern from the email path).
            try:
                supabase.table("contacts").update({
                    "last_seen_at": seen_iso,
                    "updated_at": now_iso,
                }).eq("id", existing["id"]).eq("tenant_id", tenant_id).execute()
                updated += 1
                # Phase F.4: link to meeting
                _link_contact_to_meeting(
                    tenant_id=tenant_id,
                    twin_id=twin_id,
                    contact_id=existing["id"],
                    meeting_id=meeting_id,
                    source="recap",
                )
            except Exception as exc:
                logger.warning(
                    "[contact_resolver] name-only update failed id=%s err=%s",
                    existing["id"], type(exc).__name__,
                )
                skipped += 1
        else:
            try:
                ins = supabase.table("contacts").insert({
                    "tenant_id": tenant_id,
                    "twin_id": twin_id,
                    "name": name,
                    "email": None,
                    "first_seen_at": seen_iso,
                    "last_seen_at": seen_iso,
                    "meeting_count": 1,
                }).execute()
                ins_row = (getattr(ins, "data", None) or [None])[0]
                new_contact_id = ins_row["id"] if ins_row else None
                created += 1
                # Phase F.4: link new contact to meeting
                if new_contact_id:
                    _link_contact_to_meeting(
                        tenant_id=tenant_id,
                        twin_id=twin_id,
                        contact_id=new_contact_id,
                        meeting_id=meeting_id,
                        source="recap",
                    )
            except Exception as exc:
                logger.warning(
                    "[contact_resolver] name-only insert failed name=%s err=%s",
                    name, type(exc).__name__,
                )
                skipped += 1
    return {"created": created, "updated": updated, "skipped": skipped}
