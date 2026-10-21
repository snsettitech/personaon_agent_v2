"""Person profile endpoint — Wave 6 (Phase 1).

Returns everything needed for one person's profile page:
- identity (from `nodes`)
- meetings (via `meeting_participants` + `attendees_json` containment)
- open commitments split into "you owe" vs "they owe"
- a status strip: last-talked, you-owe, next-meeting

All scoped per tenant + twin. Read-only.

Out of scope for v1: PDL / Humantic enrichment (deferred to W8).

DEPRECATED (Phase 2 — People USP): the dashboard People surface is now served
by `routers/contacts.py` (`/v2/twins/{twin_id}/contacts/...`), which reads from
the `contacts` + `contact_meetings` tables. This `/v2/people/{node_id}` endpoint
reads from the parallel `nodes` store and is superseded — do NOT add new callers.
A `contacts`↔`nodes` unification + removal is deferred to a later cleanup phase;
no data migration is performed here.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from modules.observability import supabase
from routers.meetings import _get_current_user, _require_meeting_intelligence

logger = logging.getLogger(__name__)

router = APIRouter(tags=["people"])

PRIOR_RECAP_LIMIT = 50  # max meetings per person we surface
RECENT_COMMITMENT_DAYS = 180  # cap on how old an "open" commitment can be


def _humanize_days_since(iso: str | None) -> str:
    """Render '2026-05-20T18:00Z' as 'today' / '12d ago' / etc."""
    if not iso:
        return "—"
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "—"
    now = datetime.now(timezone.utc)
    diff_days = (now - ts).days
    if diff_days < 0:
        # Future
        if abs(diff_days) == 0:
            return "today"
        if abs(diff_days) == 1:
            return "tomorrow"
        return f"in {abs(diff_days)}d"
    if diff_days == 0:
        return "today"
    if diff_days == 1:
        return "yesterday"
    if diff_days < 30:
        return f"{diff_days}d ago"
    if diff_days < 365:
        months = diff_days // 30
        return f"{months}mo ago"
    return f"{diff_days // 365}y ago"


def _truncate(text: str | None, max_len: int = 30) -> str:
    """Trim to N chars with ellipsis. Returns '—' if empty."""
    if not text:
        return "—"
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _is_assignee_me(value: str | None) -> bool:
    """True when a commitment.by field denotes the user."""
    if not value:
        return False
    return value.strip().lower() in {"me", "i", "self", "you"}


def _matches_person(value: str | None, person_name: str | None, person_email: str | None) -> bool:
    """True if a commitment.to / action.owner refers to this person.

    Match rules (strict — false positives cross-bleed onto other person profiles):
      - exact lowercase email match
      - exact lowercase full-name match

    First-name-only matches were removed: any twin with two contacts sharing a
    first name (David Chen + David Park) would otherwise see each other's
    commitments. Surface attribution clarity > recall here.
    """
    if not value:
        return False
    v = value.strip().lower()
    if not v:
        return False
    if person_email and v == person_email.lower():
        return True
    if person_name and v == person_name.lower():
        return True
    return False


@router.get(
    "/v2/people/{twin_id}/{person_node_id}",
    dependencies=[Depends(_require_meeting_intelligence)],
)
async def get_person_profile(
    twin_id: str,
    person_node_id: str,
    request: Request,
) -> dict[str, Any]:
    """Return all data needed to render one person's profile page."""
    user = _get_current_user(request)
    tenant_id = user.get("tenant_id") or user.get("id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant context")

    # 1. Ownership check on twin
    twin_check = (
        supabase.table("twins")
        .select("id")
        .eq("id", twin_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    if not twin_check.data:
        raise HTTPException(status_code=403, detail="Forbidden")

    # 2. Node row, scoped by twin (nodes table has no tenant_id; tenant scope
    #    is enforced via the twin we just validated).
    node_resp = (
        supabase.table("nodes")
        .select("id, name, properties, type")
        .eq("id", person_node_id)
        .eq("twin_id", twin_id)
        .maybe_single()
        .execute()
    )
    if not node_resp.data:
        raise HTTPException(status_code=404, detail="Person not found")
    node = node_resp.data
    if node.get("type") not in {"person", "Person"}:
        # Defensive: this endpoint is people-only.
        raise HTTPException(status_code=404, detail="Person not found")

    props = node.get("properties") or {}
    person_email = (props.get("email") or "").strip() or None
    person_name = (node.get("name") or "").strip() or None

    # 3. Meetings via meeting_participants (where bot ran + speakers resolved)
    parts_resp = (
        supabase.table("meeting_participants")
        .select("meeting_id, participant_name, participant_email")
        .eq("person_node_id", person_node_id)
        .execute()
    )
    participant_meeting_ids = {
        row["meeting_id"] for row in (parts_resp.data or []) if row.get("meeting_id")
    }

    # 4. Calendar-only meetings via attendees_json containment.
    #    Use the same tenant-scoped filter for safety even though twin_id is
    #    enough (defense-in-depth per feedback_tenant_scope_mutations.md).
    cal_meetings: list[dict[str, Any]] = []
    if person_email:
        cal_resp = (
            supabase.table("meetings")
            .select(
                "id, title, meeting_start, meeting_end, status, summary, "
                "recap, action_items, commitments, attendees_json, recall_bot_id"
            )
            .eq("twin_id", twin_id)
            .eq("tenant_id", tenant_id)
            .filter("attendees_json", "cs", f'[{{"email":"{person_email}"}}]')
            .order("meeting_start", desc=True)
            .limit(PRIOR_RECAP_LIMIT)
            .execute()
        )
        cal_meetings = cal_resp.data or []

    # 5. Hydrate participant_meeting_ids (meetings where bot ran but maybe
    #    attendees_json didn't have this person — e.g., joined via meet_link).
    participant_only_ids = participant_meeting_ids - {m["id"] for m in cal_meetings}
    if participant_only_ids:
        part_resp = (
            supabase.table("meetings")
            .select(
                "id, title, meeting_start, meeting_end, status, summary, "
                "recap, action_items, commitments, attendees_json, recall_bot_id"
            )
            .in_("id", list(participant_only_ids))
            .eq("twin_id", twin_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        cal_meetings.extend(part_resp.data or [])

    # Dedupe + sort desc by meeting_start.
    seen_ids: set[str] = set()
    unique_meetings: list[dict[str, Any]] = []
    for m in cal_meetings:
        mid = m.get("id")
        if not mid or mid in seen_ids:
            continue
        seen_ids.add(mid)
        unique_meetings.append(m)
    unique_meetings.sort(
        key=lambda m: m.get("meeting_start") or "",
        reverse=True,
    )
    unique_meetings = unique_meetings[:PRIOR_RECAP_LIMIT]

    # 6. Open commitments — both directions.
    #    "you owe" = commitments where by ∈ {me, i, self} AND meeting is in this person's set
    #    "they owe" = commitments where to references this person's name/email
    now = datetime.now(timezone.utc)
    you_owe: list[dict[str, Any]] = []
    they_owe: list[dict[str, Any]] = []

    for m in unique_meetings:
        commitments = m.get("commitments") or []
        if not isinstance(commitments, list):
            continue
        meeting_start_iso = m.get("meeting_start") or ""
        try:
            m_dt = datetime.fromisoformat(meeting_start_iso.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            m_dt = now
        days_open = max(0, (now.date() - m_dt.date()).days)
        if days_open > RECENT_COMMITMENT_DAYS:
            continue

        # Count non-self attendees on this meeting. A "1:1" for the purposes of
        # the null-`to` fallback is "twin owner + exactly one other person".
        # In group meetings the null-`to` assumption would bleed the same
        # commitment onto every person profile, so we gate strictly.
        attendees = m.get("attendees_json") or []
        non_self_count = 0
        if isinstance(attendees, list):
            for a in attendees:
                if isinstance(a, dict) and not a.get("self"):
                    non_self_count += 1
                elif isinstance(a, str):
                    non_self_count += 1
        is_one_on_one = non_self_count <= 1

        for c in commitments:
            if not isinstance(c, dict):
                continue
            what = (c.get("what") or "").strip()
            if not what:
                continue
            commitment_entry = {
                "what": what,
                "from_meeting_id": m.get("id"),
                "from_meeting_title": m.get("title"),
                "from_meeting_date": (meeting_start_iso or "")[:10],
                "days_open": days_open,
            }
            if _is_assignee_me(c.get("by")):
                # The user owes — surface if the commitment is "to" this person.
                # Null-`to` only safe to attribute when the meeting was a 1:1.
                if _matches_person(c.get("to"), person_name, person_email):
                    you_owe.append(commitment_entry)
                elif not c.get("to") and is_one_on_one:
                    you_owe.append(commitment_entry)
            elif _matches_person(c.get("by"), person_name, person_email):
                they_owe.append(commitment_entry)

    # 7. Status-strip facts
    meetings_count = len(unique_meetings)
    recorded_count = sum(1 for m in unique_meetings if m.get("recall_bot_id"))

    # "Last talked" must only count meetings that ACTUALLY happened —
    # past-dated AND either completed or recorded. Otherwise a future
    # scheduled calendar event would render as "last talked in 3d",
    # which is nonsense for a "last" timestamp.
    now_iso = now.isoformat()
    happened_meetings = [
        m for m in unique_meetings
        if (
            m.get("meeting_start")
            and m["meeting_start"] < now_iso
            and (
                m.get("status") in {"completed", "processing", "failed"}
                or m.get("recall_bot_id")
            )
        )
    ]
    last_met_iso = next(
        (m.get("meeting_start") for m in happened_meetings),
        None,
    )
    first_met_iso = next(
        (
            m.get("meeting_start")
            for m in sorted(
                happened_meetings,
                key=lambda x: x.get("meeting_start") or "",
            )
        ),
        None,
    )

    upcoming = [
        m for m in unique_meetings
        if m.get("meeting_start") and m["meeting_start"] > now.isoformat()
    ]
    next_meeting = sorted(
        upcoming, key=lambda m: m.get("meeting_start") or ""
    )[0] if upcoming else None

    status_strip = {
        "last_talked_label": _humanize_days_since(last_met_iso) if last_met_iso else "never",
        "you_owe_label": (
            _truncate(you_owe[0]["what"], 30) if you_owe else "—"
        ),
        "next_label": (
            _truncate(next_meeting.get("title"), 30) if next_meeting else "—"
        ),
    }

    # 8. Timeline projection — drop heavy recap fields, keep what the UI needs.
    timeline = [
        {
            "id": m["id"],
            "title": m.get("title"),
            "meeting_start": m.get("meeting_start"),
            "meeting_end": m.get("meeting_end"),
            "status": m.get("status"),
            "has_recap": bool(m.get("recap") or m.get("summary")),
            "has_recording": bool(m.get("recall_bot_id")),
        }
        for m in unique_meetings
    ]

    return {
        "status": "ok",
        "data": {
            "person": {
                "id": node["id"],
                "name": person_name or (person_email.split("@")[0] if person_email else "Unknown"),
                "email": person_email,
                "meeting_count": meetings_count,
                "recorded_count": recorded_count,
                "first_met_at": first_met_iso,
                "last_met_at": last_met_iso,
            },
            "status_strip": status_strip,
            "open_commitments": {
                "you_owe": you_owe[:10],
                "they_owe": they_owe[:10],
            },
            "timeline": timeline,
        },
    }
