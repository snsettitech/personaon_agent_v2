"""Shared per-person context computation (Phase 2 — People-memory USP).

Single source of truth for the per-contact "what do I know / owe / discuss"
context, used by BOTH:
  - the contact analysis endpoint (routers/contacts.py) — fills memory_mentions
  - the persona chat injection (routers/chat.py) — grounds the agent in real
    meeting-derived people memory

Keeping the open-loops + memory computation here avoids drift between the
dashboard Person Detail view and what the persona "remembers" in chat.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

from services.name_match import is_name_variant

logger = logging.getLogger(__name__)

# Cap applied independently to each open-loop bucket.
OPEN_LOOPS_CAP = 25

# Cap on approved memory facts surfaced per contact.
MEMORY_MENTIONS_CAP = 25

# Memory candidate columns mirrored to the frontend Candidate shape.
_MEMORY_FIELDS = (
    "id, meeting_id, contact_id, kind, subject, predicate, text, "
    "confidence, status, created_at"
)


class PersonContext:
    """Computed per-person context. Plain container (not a Pydantic model) so it
    can carry the already-validated OpenLoop dicts the endpoint builds."""

    def __init__(
        self,
        *,
        you_owe: list[dict[str, Any]],
        they_owe: list[dict[str, Any]],
        skipped_count: int,
        truncated: bool,
        memory_mentions: list[dict[str, Any]],
    ) -> None:
        self.you_owe = you_owe
        self.they_owe = they_owe
        self.skipped_count = skipped_count
        self.truncated = truncated
        self.memory_mentions = memory_mentions


def days_open_from_start(meeting_start: str | None) -> int:
    """floor((now - meeting_start) / day), minimum 0."""
    if not meeting_start:
        return 0
    try:
        start = datetime.fromisoformat(meeting_start.replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - start
        return max(0, math.floor(diff.total_seconds() / 86400))
    except Exception:
        return 0


def compute_open_loops(
    meeting_rows: list[dict[str, Any]],
    *,
    owner_name: str,
    contact_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, bool]:
    """Walk meeting action_items and bucket them by assignee role.

    Returns (you_owe, they_owe, skipped_count, truncated). Each loop is a plain
    dict: {text, meeting: {id, title, meeting_start}, days_open, assignee_role}.
    """
    you_owe: list[dict[str, Any]] = []
    they_owe: list[dict[str, Any]] = []
    skipped_count = 0

    for m in meeting_rows:
        action_items = m.get("action_items")
        if not action_items or not isinstance(action_items, list):
            continue

        meeting_ref = {
            "id": m["id"],
            "title": m.get("title"),
            "meeting_start": m.get("meeting_start"),
        }
        days = days_open_from_start(m.get("meeting_start"))

        for item in action_items:
            if not isinstance(item, dict):
                continue
            if item.get("completed") is True:
                continue
            text = item.get("text") or item.get("description") or ""
            if not text or not isinstance(text, str):
                continue
            assignee = item.get("assignee") or ""
            if not isinstance(assignee, str):
                assignee = ""

            if owner_name and is_name_variant(assignee, owner_name):
                role = "you"
                bucket = you_owe
            elif contact_name and is_name_variant(assignee, contact_name):
                role = "them"
                bucket = they_owe
            else:
                skipped_count += 1
                continue

            bucket.append({
                "text": text.strip(),
                "meeting": meeting_ref,
                "days_open": days,
                "assignee_role": role,
            })

    truncated = len(you_owe) > OPEN_LOOPS_CAP or len(they_owe) > OPEN_LOOPS_CAP
    return you_owe[:OPEN_LOOPS_CAP], they_owe[:OPEN_LOOPS_CAP], skipped_count, truncated


def fetch_memory_mentions(
    supabase: Any,
    *,
    twin_id: str,
    tenant_id: str,
    contact: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return approved memory_candidates that mention this contact.

    Matches on contact name and/or email (case-insensitive substring) against
    the candidate text/subject. Prefers a direct contact_id link when present,
    falling back to name/email text matching for facts the extractor stored
    without a contact link. Capped at MEMORY_MENTIONS_CAP. Never raises — a
    transient DB error degrades to an empty list (chat/analysis still work).
    """
    contact_id = contact.get("id")
    name = (contact.get("name") or "").strip()
    email = (contact.get("email") or "").strip()

    try:
        resp = (
            supabase.table("memory_candidates")
            .select(_MEMORY_FIELDS)
            .eq("twin_id", twin_id)
            .eq("tenant_id", tenant_id)
            .eq("status", "approved")
            .order("created_at", desc=True)
            .limit(200)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
    except Exception as exc:
        logger.warning(
            "[person_context] memory_candidates lookup failed twin=%s err=%s",
            twin_id, type(exc).__name__,
        )
        return []

    name_lc = name.lower()
    email_lc = email.lower()
    matched: list[dict[str, Any]] = []
    for r in rows:
        is_match = bool(contact_id and r.get("contact_id") == contact_id)
        if not is_match:
            haystack = f"{r.get('text') or ''} {r.get('subject') or ''}".lower()
            is_match = bool(
                (name_lc and name_lc in haystack)
                or (email_lc and email_lc in haystack)
            )
        if is_match:
            matched.append(r)
        if len(matched) >= MEMORY_MENTIONS_CAP:
            break

    return matched[:MEMORY_MENTIONS_CAP]


def build_person_context(
    supabase: Any,
    *,
    twin_id: str,
    tenant_id: str,
    contact: dict[str, Any],
    meeting_rows: list[dict[str, Any]],
    owner_name: str,
) -> PersonContext:
    """Compute open loops + approved memory mentions for a contact in one place."""
    you_owe, they_owe, skipped, truncated = compute_open_loops(
        meeting_rows,
        owner_name=owner_name,
        contact_name=contact.get("name") or "",
    )
    mentions = fetch_memory_mentions(
        supabase, twin_id=twin_id, tenant_id=tenant_id, contact=contact,
    )
    return PersonContext(
        you_owe=you_owe,
        they_owe=they_owe,
        skipped_count=skipped,
        truncated=truncated,
        memory_mentions=mentions,
    )


def render_person_context_block(
    *,
    contact: dict[str, Any],
    context: PersonContext,
) -> str:
    """Render a compact, LLM-facing context block for chat injection.

    Returns a plain-text block (or "" if there is nothing useful to inject).
    Describes: who they are, last talked, meeting count, open loops (you owe /
    they owe), and top approved memory facts.
    """
    name = (contact.get("name") or "this person").strip()
    parts: list[str] = []

    header_bits: list[str] = [f"You know {name}"]
    email = (contact.get("email") or "").strip()
    if email:
        header_bits.append(f"({email})")
    meeting_count = contact.get("meeting_count") or 0
    if meeting_count:
        header_bits.append(
            f"— {meeting_count} meeting{'s' if meeting_count != 1 else ''} together"
        )
    last_seen = contact.get("last_seen_at")
    if last_seen:
        header_bits.append(f"; last talked {last_seen}")
    parts.append(" ".join(header_bits) + ".")

    if context.you_owe:
        parts.append("You owe " + name + ":")
        for loop in context.you_owe[:5]:
            parts.append(f"  - {loop['text']}")
    if context.they_owe:
        parts.append(name + " owes you:")
        for loop in context.they_owe[:5]:
            parts.append(f"  - {loop['text']}")

    if context.memory_mentions:
        parts.append(f"What you remember about {name}:")
        for m in context.memory_mentions[:5]:
            text = (m.get("text") or "").strip()
            if text:
                parts.append(f"  - {text}")

    has_detail = bool(context.you_owe or context.they_owe or context.memory_mentions)
    if not has_detail and not meeting_count:
        # Nothing useful beyond a bare name — don't pollute the prompt.
        return ""

    body = "\n".join(parts)
    return (
        "\n\n--- PERSON CONTEXT (real history with someone the user mentioned; "
        "treat as your own memory, the user cannot see this block) ---\n"
        + body
        + "\n--- END PERSON CONTEXT ---"
    )


# ---------------------------------------------------------------------------
# Chat injection: resolve a contact referenced in the user's message
# ---------------------------------------------------------------------------

# Cap how many resolved contacts we inject per turn — usually 1, but a message
# could legitimately name two people. Keeps the prompt bounded.
_MAX_RESOLVED_CONTACTS = 2

_CONTACT_FIELDS = (
    "id, name, email, meeting_count, last_seen_at, allow_mention"
)


def _resolve_owner_name_for_chat(supabase: Any, tenant_id: str) -> str:
    """Owner display name for assignee role matching (mirrors contacts router)."""
    try:
        u_resp = (
            supabase.table("users")
            .select("full_name, email")
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        u_row = (getattr(u_resp, "data", None) or [None])[0] or {}
        name = (u_row.get("full_name") or "").strip()
        if not name and u_row.get("email"):
            name = u_row["email"].split("@")[0]
        return name
    except Exception:
        return ""


def _match_contacts_in_message(message: str, contacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return contacts whose name or email is referenced in the message.

    Case-insensitive. A contact matches if its full name, any name token of >=3
    chars, or its email appears in the message text.
    """
    msg_lc = message.lower()
    matched: list[dict[str, Any]] = []
    for c in contacts:
        name = (c.get("name") or "").strip().lower()
        email = (c.get("email") or "").strip().lower()
        hit = bool((name and name in msg_lc) or (email and email in msg_lc))
        if not hit and name:
            for tok in name.replace("-", " ").split():
                if len(tok) >= 3 and tok in msg_lc:
                    hit = True
                    break
        if hit:
            matched.append(c)
        if len(matched) >= _MAX_RESOLVED_CONTACTS:
            break
    return matched


def resolve_people_context_block(
    supabase: Any,
    *,
    twin_id: str,
    tenant_id: str,
    message: str,
) -> str:
    """Resolve any contact referenced in `message` and render a context block.

    Gated per-contact by `allow_mention`. Returns "" when no allowed contact is
    referenced or nothing useful can be said. Never raises — best-effort
    enrichment that must not break the chat turn.
    """
    if not message or not message.strip():
        return ""
    try:
        resp = (
            supabase.table("contacts")
            .select(_CONTACT_FIELDS)
            .eq("twin_id", twin_id)
            .eq("tenant_id", tenant_id)
            .is_("deleted_at", "null")
            .eq("allow_mention", True)
            .limit(500)
            .execute()
        )
        contacts = getattr(resp, "data", None) or []
    except Exception as exc:
        logger.warning(
            "[person_context] contacts lookup failed twin=%s err=%s",
            twin_id, type(exc).__name__,
        )
        return ""

    matched = _match_contacts_in_message(message, contacts)
    if not matched:
        return ""

    owner_name = _resolve_owner_name_for_chat(supabase, tenant_id)

    blocks: list[str] = []
    for contact in matched:
        meeting_rows = _fetch_contact_meeting_rows(
            supabase, twin_id=twin_id, tenant_id=tenant_id, contact_id=contact["id"],
        )
        ctx = build_person_context(
            supabase,
            twin_id=twin_id,
            tenant_id=tenant_id,
            contact=contact,
            meeting_rows=meeting_rows,
            owner_name=owner_name,
        )
        block = render_person_context_block(contact=contact, context=ctx)
        if block:
            blocks.append(block)

    return "".join(blocks)


def _fetch_contact_meeting_rows(
    supabase: Any,
    *,
    twin_id: str,
    tenant_id: str,
    contact_id: str,
) -> list[dict[str, Any]]:
    """Fetch the meetings (with action_items) linked to a contact. Best-effort."""
    try:
        link_resp = (
            supabase.table("contact_meetings")
            .select("meeting_id")
            .eq("contact_id", contact_id)
            .eq("tenant_id", tenant_id)
            .eq("twin_id", twin_id)
            .execute()
        )
        links = getattr(link_resp, "data", None) or []
    except Exception:
        return []
    if not links:
        return []
    meeting_ids = [lnk["meeting_id"] for lnk in links]
    try:
        m_resp = (
            supabase.table("meetings")
            .select("id, title, meeting_start, meeting_end, status, action_items")
            .in_("id", meeting_ids)
            .eq("tenant_id", tenant_id)
            .neq("status", "deleted")
            .order("meeting_start", desc=True)
            .execute()
        )
        return getattr(m_resp, "data", None) or []
    except Exception:
        return []
