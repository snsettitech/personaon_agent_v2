"""W9b — Rule-based candidate generators for Heads Up notes.

Each function takes inputs already computed in generate_brief() and returns
a list of typed candidate dicts. Candidates are later fed to the LLM
rewriter (heads_up_rewriter.py) which produces Level-3 tone notes plus
citation pointers.

IN-SCOPE rule kinds (this file):
  - open_commitment              days_open > threshold
  - action_item_pending          open_items[] from prior recaps
  - agenda_signal_*              meeting organized by someone else
  - pdl_change                   diff vs cached snapshot (needs snapshot store)
  - kb_private_hit               async — private-tier KB hits

OUT-OF-SCOPE (deferred to follow-up PRs or W9d):
  - reschedule_pattern    -> needs meeting_event_history schema
  - prior_topic_tension   -> W9d (LLM classifier per recap)
  - news_event            -> W9d (sync web call breaks fast-path budget)
  - unresolved_topic      -> W9d (topic normalization required)

All rules return empty lists on missing/null inputs — never raise. The LLM
rewriter handles "0 candidates → 0 notes" cleanly.
"""

from __future__ import annotations

import logging
from typing import Any

# Imported here (rather than inline-imported) so unit tests can monkeypatch
# `heads_up_rules._kb_search` without touching the underlying module.
from adk_core.services.vector_store import search as _kb_search

logger = logging.getLogger(__name__)


# Days a commitment must be open before it becomes a Heads Up candidate.
# Strictly greater-than (>), so threshold-exactly is NOT yet a candidate —
# "still working on it" is the kinder reading.
OPEN_COMMITMENT_DAYS_THRESHOLD = 7


# ---------------------------------------------------------------------------
# Open commitments
# ---------------------------------------------------------------------------


def rule_open_commitments(
    open_commitments: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Surface open commitments past the days-open threshold."""
    if not open_commitments:
        return []
    out: list[dict[str, Any]] = []
    for c in open_commitments:
        try:
            days_open = int(c.get("days_open") or 0)
        except (TypeError, ValueError):
            days_open = 0
        if days_open <= OPEN_COMMITMENT_DAYS_THRESHOLD:
            continue
        description = (c.get("description") or "").strip()
        if not description:
            continue
        out.append({
            "kind": "open_commitment",
            "attendee": c.get("attendee") or c.get("owner") or "",
            "description": description,
            "days_open": days_open,
            "source_meeting_id": c.get("from_meeting_id"),
            "source_meeting_date": c.get("from_meeting_date"),
            "source_quote": c.get("source_quote") or description,
        })
    return out


# ---------------------------------------------------------------------------
# Pending action items (from prior recaps surfaced by W9a)
# ---------------------------------------------------------------------------


def rule_action_items_pending(
    prior_interactions: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Each open_item in a prior recap becomes a candidate.

    The LLM rewriter decides which become notes; stale ones from long ago
    are typically dropped under the restraint principle. We deliberately
    pass through ALL items rather than filtering by date here — keeps the
    rule pure and lets the LLM make the contextual call with the date in
    hand.
    """
    if not prior_interactions:
        return []
    out: list[dict[str, Any]] = []
    for interaction in prior_interactions:
        date = interaction.get("date") or ""
        title = interaction.get("meeting_title") or "prior meeting"
        # AUDIT FIX: carry through meeting_id so the rewriter's citation
        # synthesizer can populate source.ref. Without this every
        # action_item_pending note shipped with empty source.ref and
        # broke the eval citation contract.
        meeting_id = interaction.get("meeting_id") or ""
        for item in interaction.get("open_items") or []:
            desc = str(item).strip()
            if not desc:
                continue
            out.append({
                "kind": "action_item_pending",
                "description": desc,
                "from_meeting_title": title,
                "from_meeting_date": date,
                "from_meeting_id": meeting_id,
            })
    return out


# ---------------------------------------------------------------------------
# Agenda signal — user invited (not organizer) AND has prior context
# ---------------------------------------------------------------------------


def rule_agenda_signal(
    *,
    organizer_email: str | None,
    self_email: str | None,
    prior_interactions: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Fire when the meeting is organized by someone else AND we have prior
    context. Empty otherwise."""
    if not organizer_email or not self_email or not prior_interactions:
        return []
    if organizer_email.strip().lower() == self_email.strip().lower():
        return []
    last = prior_interactions[0]
    return [{
        "kind": "agenda_signal_other_organizer",
        "organizer_email": organizer_email,
        "prior_topic": last.get("meeting_title") or "prior meeting",
        "prior_date": last.get("date"),
    }]


# ---------------------------------------------------------------------------
# PDL change — requires snapshot store
# ---------------------------------------------------------------------------


def _normalize_pdl_field(value: str | None) -> str:
    """Strip + case-fold for diff comparison so trivial whitespace/case
    differences don't trigger a spurious 'change' candidate."""
    return (value or "").strip().lower()


def rule_pdl_change(
    *,
    attendee: str,
    current: dict[str, Any] | None,
    previous: dict[str, Any] | None,
    last_met: str | None,
) -> list[dict[str, Any]]:
    """Emit when current PDL snapshot differs from previous.

    Cold-start: if ``previous`` is None (first encounter with this person
    since W9b shipped), return empty. The snapshot writeback in
    generate_brief() persists the current value for the NEXT brief to diff.
    """
    if not current or not previous:
        return []
    cur_co = _normalize_pdl_field(current.get("company"))
    prev_co = _normalize_pdl_field(previous.get("company"))
    cur_role = _normalize_pdl_field(current.get("role"))
    prev_role = _normalize_pdl_field(previous.get("role"))
    if cur_co == prev_co and cur_role == prev_role:
        return []
    return [{
        "kind": "pdl_change",
        "attendee": attendee,
        "old_value": {
            "company": previous.get("company"),
            "role": previous.get("role"),
        },
        "new_value": {
            "company": current.get("company"),
            "role": current.get("role"),
        },
        "last_met": last_met,
    }]


# ---------------------------------------------------------------------------
# KB private-tier hit (async)
# ---------------------------------------------------------------------------


# Cap on each note_quote so the LLM prompt doesn't bloat. 280 chars matches
# the rule of thumb for "one tweet-length excerpt" — enough context for the
# rewriter to ground the note, not enough to leak whole notes.
_KB_QUOTE_CAP_CHARS = 280


async def rule_kb_private_hit(
    *,
    twin_id: str,
    meeting_title: str,
    attendees: list[Any] | None,
    max_hits: int = 3,
) -> list[dict[str, Any]]:
    """Surface private-tier KB hits relevant to the meeting topic + attendees.

    Constructs a query from meeting title + the top attendees' display names,
    runs it against the user's KB with ``allowed_tiers=["private"]`` only.
    Hits mean "the user has private notes about this conversation they may
    want to re-read before walking in."

    Failure handling: KB search errors return empty — the brief still ships
    without Heads Up notes from this source. Audit logs every failure with
    twin_id for triage.
    """
    # Compose a query from meeting title + top attendee names.
    # AUDIT FIX: require attendees-list to be a real list; some legacy
    # paths can pass a JSON-encoded string which would iterate per-char.
    if attendees is not None and not isinstance(attendees, list):
        attendees = None

    names: list[str] = []
    for a in (attendees or [])[:3]:
        if isinstance(a, dict):
            n = (a.get("displayName") or a.get("name") or "").strip()
            if n:
                names.append(n)
        elif isinstance(a, str):
            n = a.strip()
            if n:
                names.append(n)

    # AUDIT FIX: skip the KB search when the only query signal is the
    # default meeting_title ("Meeting" from brief.py when title is None
    # or "Untitled meeting"). Random KB hits on titleless meetings ship
    # noise into the Heads Up output.
    title_clean = (meeting_title or "").strip()
    _DEFAULT_TITLES = {"", "meeting", "untitled meeting"}
    has_title_signal = title_clean.lower() not in _DEFAULT_TITLES
    if not names and not has_title_signal:
        return []

    query = f"{title_clean} {' '.join(names)}".strip()
    if not query:
        return []

    try:
        chunks = await _kb_search(
            query=query,
            twin_id=twin_id,
            top_k=max_hits,
            allowed_tiers=["private"],
        )
    except Exception as exc:
        logger.warning(
            "[HeadsUp] kb_private_hit search failed twin=%s: %s", twin_id, exc
        )
        return []

    if not chunks:
        return []

    primary_attendee = names[0] if names else ""
    out: list[dict[str, Any]] = []
    for chunk in chunks:
        text = (chunk.get("text") or "").strip()
        if not text:
            continue
        out.append({
            "kind": "kb_private_hit",
            "attendee": primary_attendee,
            "topic": meeting_title,
            "note_quote": text[:_KB_QUOTE_CAP_CHARS],
            "note_source_id": chunk.get("source_id"),
            "note_filename": chunk.get("filename"),
            "tier": "private",
        })
    return out
