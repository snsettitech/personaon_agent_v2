"""Pre-meeting Brief engine (Phase 30-L / P1.2).

Generates a ``BriefContract``-shaped dict for a single meeting. The shape is
intentionally JSON-native (plain dict + lists) so we can persist it directly
to ``meetings.brief_json`` without an intermediate serializer.

Pipeline:

1. Fetch the meeting row if the caller didn't pre-fetch it.
2. Extract the primary non-organizer attendee (``name``, ``email``).
3. Enrich that attendee via People Data Labs (best-effort — graceful miss).
4. Carry-forward: pull recent recaps that share at least one attendee with
   this meeting (same query shape as ``persona_core.recap``).
5. Pull open commitments from those recaps (commitments owed by ``me`` that
   don't appear as completed in any subsequent recap).
6. Single Gemini call to synthesise 3-5 leading hooks. Falls back to a
   deterministic commitment-only hook list on any LLM failure.
7. Return the assembled ``BriefContract`` dict.

TODO(P1.2.1): wire the 15-min-pre-meeting scheduler. Today the brief is
generated lazily on first ``GET /v2/meetings/{twin_id}/{meeting_id}/brief``
hit and the email is enqueued at the same time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import google.genai as genai
import google.genai.types as genai_types

from adk_core.model_names import chat_model_name
from modules.telemetry import get_tracer

logger = logging.getLogger(__name__)
_tracer = get_tracer("brief")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Cap on prior-meeting carry-forward (matches recap.py).
PRIOR_RECAP_LIMIT = 5
PRIOR_RECAP_SCAN_LIMIT = 20

# Schema-v2 rollout flag. Read from env at call time (not module import)
# so test fixtures + staged rollouts can toggle without re-importing.
# Defaults to FALSE — production must explicitly opt in. Staging deploy
# should set BRIEF_SCHEMA_V2_ENABLED=true; promote to prod after 24h soak.
def _schema_v2_enabled() -> bool:
    return os.getenv("BRIEF_SCHEMA_V2_ENABLED", "false").lower() in {
        "true",
        "1",
        "yes",
        "on",
    }


# W9b — Heads Up engine flag. Independent of BRIEF_SCHEMA_V2_ENABLED so we can
# ship v2 schema (additive fields, no user-visible change) before flipping
# Heads Up generation (Gemini call + user-facing text). Both must be true for
# caution_notes to populate. Defaults FALSE — production opt-in only.
def _heads_up_enabled() -> bool:
    return os.getenv("HEADS_UP_ENABLED", "false").lower() in {
        "true",
        "1",
        "yes",
        "on",
    }


def _empty_brief_contract(
    *,
    meeting_id: str,
    title: str,
    start: Any,
) -> dict[str, Any]:
    """Canonical empty brief shape.

    v2 fields are additive — frontend code reads with ``?? defaults`` so a
    v1 brief in storage still renders. Both shapes share the same identity
    + content keys; v2 layers structured artifacts on top.
    """
    base: dict[str, Any] = {
        "schema_version": 2 if _schema_v2_enabled() else 1,
        "meeting_id": meeting_id,
        "meeting_title": title,
        "meeting_start": start,
        # v1 keys — kept until W9c ships and the UI fully reads v2
        "person": None,
        "your_goal": None,
        "your_context": None,
        "prior_meetings": [],
        "hooks": [],
        "open_commitments": [],
        "generated_at": None,
    }
    if _schema_v2_enabled():
        base["participant_insights"] = []
        base["talking_points"] = []
        base["previous_interactions"] = []
        base["suggested_agenda"] = []
        base["caution_notes"] = []
        base["sources_used"] = {
            "kb_chunks": 0,
            "web_results": 0,
            "past_meetings": 0,
        }
    return base

# Allowed labels for hooks — keep this short list aligned with the prompt so
# the UI can group / colour-code by label without surprises.
ALLOWED_HOOK_LABELS = {"Bring", "Probe", "They care about", "Worth knowing"}

HOOKS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "hooks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["label", "text"],
            },
        },
    },
    "required": ["hooks"],
}


HOOKS_PROMPT_TEMPLATE = """You are preparing a meeting brief. Generate 3-5 short hooks the user should lead with.

Meeting: {meeting_title}
User's stated goal: {user_goal}

Person being met:
{person_summary}

Recent signals about them:
{signals}

Prior meetings (most recent first):
{prior_recaps_block}

Open commitments still owed by the user:
{open_commitments_block}

Return JSON with a "hooks" array. Each hook has a "label" (one of "Bring", "Probe", "They care about", "Worth knowing") and "text" (one sentence). Prioritize:
1. Open commitments first (e.g. "Bring: the cohort data you promised on May 3").
2. Then 1-2 substantive probes informed by the signals.
3. Then 1 "they care about" line.

Be specific, not generic. No greetings. No filler.
"""


# ---------------------------------------------------------------------------
# Gemini client (mirrors recap.py)
# ---------------------------------------------------------------------------


def _get_genai_client() -> genai.Client:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not configured")
    return genai.Client(api_key=api_key)


def _strip_markdown_fences(text: str) -> str:
    stripped = (text or "").strip()
    if not stripped.startswith("```"):
        return stripped
    parts = stripped.split("```", 2)
    if len(parts) < 2:
        return stripped
    inner = parts[1]
    if inner.startswith("json"):
        inner = inner[4:]
    if inner.endswith("```"):
        inner = inner[:-3]
    return inner.strip()


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------


async def _fetch_meeting_row(
    meeting_id: str,
    twin_id: str,
    *,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    """Fetch a single meeting row, scoped to its twin (+ tenant if known).

    Defense-in-depth: when the caller knows the tenant_id (lazy GET from
    authenticated request; cron worker from job row), pass it to add a
    second filter. Without this, an attacker who learned a meeting_id +
    twin_id pair across tenant boundaries could still load the row.
    """
    from modules.observability import get_supabase_client

    sb = get_supabase_client()
    try:
        query = (
            sb.table("meetings")
            .select(
                "id, title, meeting_start, meeting_end, attendees_json, "
                "organizer_email, user_goal, user_context, twin_id, tenant_id"
            )
            .eq("id", meeting_id)
            .eq("twin_id", twin_id)
        )
        if tenant_id:
            query = query.eq("tenant_id", tenant_id)
        resp = await asyncio.to_thread(
            lambda: query.maybe_single().execute()
        )
    except Exception as exc:
        logger.warning("[Brief] meeting fetch failed meeting=%s: %s", meeting_id, exc)
        return None
    return resp.data if resp and resp.data else None


def _generate_agenda(
    *,
    your_goal: str | None,
    talking_points: list[dict[str, Any]],
    open_commitments: list[dict[str, Any]],
    prior_count: int,
    cap: int = 6,
) -> list[str]:
    """Rule-based agenda generator.

    Order: warm-up (if prior context) -> commitments -> main goal -> top
    talking points -> wrap. No LLM call — agenda quality is a function of
    upstream signal quality, not phrasing creativity. The LLM-driven
    agenda variant ships with W9d (deep research mode).
    """
    items: list[str] = []
    if prior_count > 0:
        items.append("Quick catch-up since last meeting")

    for c in (open_commitments or [])[:2]:
        desc = (c.get("description") or "").strip()
        if desc:
            items.append(f"Status on: {desc}")

    goal_clean = (your_goal or "").strip()
    if goal_clean and goal_clean not in items:
        items.append(goal_clean)

    seen_lower = {it.lower() for it in items}
    for tp in (talking_points or [])[:3]:
        topic = (tp.get("topic") or "").strip()
        if topic and topic.lower() not in seen_lower:
            items.append(topic)
            seen_lower.add(topic.lower())

    if items:
        items.append("Next steps + timing")
    return items[:cap]


def _prior_recaps_to_interactions(
    prior_recaps: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Map prior_recaps (internal shape) to v2 ``previous_interactions[]``.

    Crucial behavior change vs v1: surfaces ``action_items`` (which the v1
    UI fetched and then discarded) as ``open_items[]``. These feed the W9b
    Heads Up rule generator and are also shown in the W9c UI under
    "From last time".
    """
    if not prior_recaps:
        return []
    out: list[dict[str, Any]] = []
    for r in prior_recaps:
        raw_items = r.get("action_items") or []
        if isinstance(raw_items, str):
            raw_items = [raw_items]
        elif not isinstance(raw_items, list):
            raw_items = []
        out.append({
            # AUDIT FIX: include meeting_id so rule_action_items_pending can
            # carry it through to source.ref in the caution_note citation.
            # Without this, every action_item_pending note shipped with
            # source.ref="" and failed the eval's citation contract.
            "meeting_id": r.get("meeting_id", ""),
            "date": r.get("date", ""),
            "meeting_title": r.get("title", ""),
            "summary": r.get("summary", ""),
            "open_items": [str(a).strip() for a in raw_items if a],
        })
    return out


async def _build_heads_up_candidates(
    *,
    twin_id: str,
    meeting: dict[str, Any],
    open_commitments: list[dict[str, Any]],
    previous_interactions: list[dict[str, Any]],
    effective_self_email: str | None,
) -> list[dict[str, Any]]:
    """Compose the rule-fired candidate list for the Heads Up rewriter.

    Combines sync rule outputs with the async KB lookup. Failure-isolated
    — if any one rule raises, only that rule's candidates are lost; the
    other rules still contribute.

    NOTE on `pdl_change`: W9b lands the snapshot writeback (Task 6) but
    doesn't yet read the PREVIOUS snapshot for diffing. That requires
    looking up the most recent prior brief for the same attendee across
    all the user's meetings — punt to a follow-up PR. For W9b shipping
    purposes, rule_pdl_change is wired but always returns [] (no prev).
    """
    from adk_core.services.persona_core.heads_up_rules import (
        rule_action_items_pending,
        rule_agenda_signal,
        rule_kb_private_hit,
        rule_open_commitments,
    )

    candidates: list[dict[str, Any]] = []
    # Sync rules — pure functions, no I/O
    try:
        candidates.extend(rule_open_commitments(open_commitments))
    except Exception as exc:
        logger.warning("[HeadsUp] rule_open_commitments failed: %s", exc)
    try:
        candidates.extend(rule_action_items_pending(previous_interactions))
    except Exception as exc:
        logger.warning("[HeadsUp] rule_action_items_pending failed: %s", exc)
    try:
        candidates.extend(rule_agenda_signal(
            organizer_email=meeting.get("organizer_email"),
            self_email=effective_self_email,
            prior_interactions=previous_interactions,
        ))
    except Exception as exc:
        logger.warning("[HeadsUp] rule_agenda_signal failed: %s", exc)

    # Async KB rule — already wraps its own errors and returns [] on failure
    try:
        kb_candidates = await rule_kb_private_hit(
            twin_id=twin_id,
            meeting_title=meeting.get("title") or "",
            attendees=meeting.get("attendees_json"),
        )
        candidates.extend(kb_candidates)
    except Exception as exc:
        logger.warning("[HeadsUp] rule_kb_private_hit raised unexpectedly: %s", exc)

    return candidates


def _hooks_to_talking_points(hooks: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Map v1 ``hooks[{label, text}]`` to v2 ``talking_points[{topic, rationale}]``.

    The label/text shape stays for one release cycle; the field rename brings
    the brief in line with the salvaged brief_agent.py contract so the W9c UI
    can read a single shape regardless of which engine generated the brief.
    """
    if not hooks:
        return []
    out: list[dict[str, Any]] = []
    for h in hooks:
        if not isinstance(h, dict):
            continue
        topic = (h.get("text") or "").strip()
        if not topic:
            continue
        out.append({
            "topic": topic,
            "rationale": (h.get("label") or "").strip(),
        })
    return out


def _extract_participant_insights(
    attendees: list[Any] | None,
    *,
    organizer_email: str | None = None,
    self_email: str | None = None,
    cap: int = 4,
) -> list[dict[str, Any]]:
    """Build up to ``cap`` participant_insight stubs from ``attendees_json``.

    Each entry mirrors the salvaged brief_agent.py schema:
    ``{name, email, role, background, recent_activities[], web_sources[]}``.
    PDL/web enrichment is deliberately NOT done here — W9a stays rule-based
    and fast; richer per-participant enrichment lands in W9d (deep mode).

    Self-exclusion via ``self_email`` is a privacy guard so the user never
    sees themselves in their own meeting brief.
    """
    if not attendees or not isinstance(attendees, list):
        return []

    # When the caller didn't pass self_email, fall back to organizer_email
    # as the self-exclude proxy. This matches _extract_primary_attendee's
    # behavior — for meetings the user organized, the organizer IS the user.
    self_norm = (self_email or organizer_email or "").lower().strip() or None
    out: list[dict[str, Any]] = []
    for a in attendees:
        if isinstance(a, dict):
            email = (a.get("email") or "").lower().strip()
            name = (a.get("displayName") or a.get("name") or email.split("@")[0] or "").strip()
        elif isinstance(a, str):
            email = ""
            name = a.strip()
        else:
            continue

        if not name and not email:
            continue
        if self_norm and email == self_norm:
            continue

        out.append({
            "name": name or email,
            "email": email,
            "role": None,
            "background": None,
            "recent_activities": [],
            "web_sources": [],
            # W9b: snapshot of PDL enrichment for this attendee. Populated by
            # generate_brief() after the live PDL call succeeds; the NEXT
            # brief diffs current vs this snapshot to fire rule_pdl_change.
            # None means "no baseline yet" — cold-start case, no candidate.
            "pdl_snapshot": None,
        })
        if len(out) >= cap:
            break
    return out


def _extract_primary_attendee(meeting: dict[str, Any]) -> dict[str, str | None]:
    """Pick the first non-organizer attendee from ``attendees_json``.

    Returns ``{"name": ..., "email": ...}`` — either may be ``None``.
    """
    attendees = meeting.get("attendees_json") or []
    organizer_email = (meeting.get("organizer_email") or "").lower().strip() or None

    if not isinstance(attendees, list):
        return {"name": None, "email": None}

    for a in attendees:
        if isinstance(a, dict):
            email = (a.get("email") or "").lower().strip() or None
            name = (a.get("displayName") or a.get("name") or "").strip() or None
        elif isinstance(a, str):
            email = None
            name = a.strip() or None
        else:
            continue

        if not email and not name:
            continue
        if email and organizer_email and email == organizer_email:
            continue
        return {"name": name, "email": email}

    return {"name": None, "email": None}


async def _fetch_prior_recaps_for_brief(meeting: dict[str, Any]) -> list[dict[str, Any]]:
    """Up to ``PRIOR_RECAP_LIMIT`` recent recaps that share an attendee.

    Returns a list of dicts with shape ``{date, title, summary, commitments,
    meeting_id}`` ready for both prompt assembly and UI rendering.
    """
    from modules.observability import get_supabase_client

    twin_id = meeting.get("twin_id")
    attendees = meeting.get("attendees_json") or []
    if not twin_id or not isinstance(attendees, list) or not attendees:
        return []

    attendee_keys: list[str] = []
    for a in attendees:
        if isinstance(a, dict):
            if a.get("email"):
                attendee_keys.append(str(a["email"]).lower())
            if a.get("name"):
                attendee_keys.append(str(a["name"]).lower())
            if a.get("displayName"):
                attendee_keys.append(str(a["displayName"]).lower())
        elif isinstance(a, str):
            attendee_keys.append(a.lower())

    if not attendee_keys:
        return []

    sb = get_supabase_client()
    try:
        resp = await asyncio.to_thread(
            lambda: (
                sb.table("meetings")
                .select(
                    "id, title, created_at, meeting_start, recap, commitments, "
                    "action_items, attendees_json"
                )
                .eq("twin_id", twin_id)
                .neq("id", meeting["id"])
                .not_.is_("recap", "null")
                .order("created_at", desc=True)
                .limit(PRIOR_RECAP_SCAN_LIMIT)
                .execute()
            )
        )
    except Exception as exc:
        logger.warning("[Brief] prior recaps fetch failed twin=%s: %s", twin_id, exc)
        return []

    out: list[dict[str, Any]] = []
    for row in (resp.data or []):
        row_attendees = row.get("attendees_json") or []
        row_keys: list[str] = []
        for a in row_attendees:
            if isinstance(a, dict):
                if a.get("email"):
                    row_keys.append(str(a["email"]).lower())
                if a.get("name"):
                    row_keys.append(str(a["name"]).lower())
                if a.get("displayName"):
                    row_keys.append(str(a["displayName"]).lower())
            elif isinstance(a, str):
                row_keys.append(a.lower())
        if not any(k in attendee_keys for k in row_keys):
            continue

        summary = (row.get("recap") or "").strip()
        if not summary:
            continue
        date_iso = (row.get("meeting_start") or row.get("created_at") or "")
        out.append({
            "meeting_id": row.get("id"),
            "date": date_iso[:10],
            "title": row.get("title") or "Untitled meeting",
            "summary": summary,
            "commitments": row.get("commitments") or [],
            "action_items": row.get("action_items") or [],
        })
        if len(out) >= PRIOR_RECAP_LIMIT:
            break
    return out


def _extract_open_commitments(
    prior_recaps: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Pull commitments where the user (``me`` / ``i``) is on the hook.

    Heuristic v1: any commitment with ``by`` in {"me", "i"} (case-insensitive)
    on a prior recap is considered open. We don't yet correlate with a
    completion claim — that's P1.2.2. ``days_open`` is days between the
    source meeting date and ``now``.
    """
    now = now or datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []

    for recap in prior_recaps:
        commitments = recap.get("commitments") or []
        if not isinstance(commitments, list):
            continue
        try:
            recap_date = datetime.fromisoformat((recap.get("date") or "") + "T00:00:00+00:00")
        except (TypeError, ValueError):
            recap_date = now

        for c in commitments:
            if not isinstance(c, dict):
                continue
            by = str(c.get("by") or "").strip().lower()
            if by not in {"me", "i"}:
                continue
            what = str(c.get("what") or "").strip()
            if not what:
                continue
            days_open = max(0, (now.date() - recap_date.date()).days)
            out.append({
                "description": what,
                "days_open": days_open,
                "from_meeting_id": recap.get("meeting_id"),
                "from_meeting_date": recap.get("date"),
            })

    return out


# ---------------------------------------------------------------------------
# PDL → person + signals
# ---------------------------------------------------------------------------


def _build_signals_from_pdl(pdl: dict[str, Any]) -> list[str]:
    """Synthesise 2-3 short signal lines from a PDL person record."""
    signals: list[str] = []
    headline = (pdl.get("headline") or "").strip()
    if headline:
        signals.append(headline)

    experience = pdl.get("experience") or []
    if isinstance(experience, list) and experience:
        latest = experience[0] if isinstance(experience[0], dict) else {}
        company = (
            (latest.get("company") or {}).get("name")
            if isinstance(latest.get("company"), dict)
            else None
        )
        title = (latest.get("title") or {}).get("name") if isinstance(latest.get("title"), dict) else None
        if title and company:
            signals.append(f"Currently {title} at {company}")
        elif company:
            signals.append(f"Currently at {company}")

    location = (pdl.get("location_name") or "").strip()
    if location and len(signals) < 3:
        signals.append(f"Based in {location}")

    return signals[:3]


def _build_person_block(
    attendee: dict[str, str | None],
    pdl: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compose the ``person`` block of the BriefContract from attendee + PDL."""
    name = attendee.get("name") or (pdl or {}).get("full_name") or ""
    email = attendee.get("email") or ""
    role = ""
    company = ""
    bio = ""
    signals: list[str] = []

    if isinstance(pdl, dict):
        role = (pdl.get("job_title") or "").strip()
        company = (pdl.get("job_company_name") or "").strip()
        bio = (pdl.get("summary") or "").strip()
        signals = _build_signals_from_pdl(pdl)

    return {
        "name": name,
        "email": email,
        "role": role,
        "company": company,
        "bio": bio,
        "signals": signals,
    }


# ---------------------------------------------------------------------------
# Hooks (Gemini call)
# ---------------------------------------------------------------------------


def _format_prior_recaps_for_prompt(prior_recaps: list[dict[str, Any]]) -> str:
    if not prior_recaps:
        return "(none)"
    lines: list[str] = []
    for r in prior_recaps:
        date = r.get("date") or "?"
        title = r.get("title") or "Meeting"
        summary = (r.get("summary") or "").strip()[:280]
        lines.append(f"- {date} · {title}: {summary}")
    return "\n".join(lines)


def _format_open_commitments_for_prompt(open_commitments: list[dict[str, Any]]) -> str:
    if not open_commitments:
        return "(none)"
    return "\n".join(
        f"- {c['description']} (open {c['days_open']} days)" for c in open_commitments
    )


def _format_person_summary(person: dict[str, Any]) -> str:
    parts: list[str] = []
    name = person.get("name") or ""
    role = person.get("role") or ""
    company = person.get("company") or ""
    bio = person.get("bio") or ""
    if name:
        head = name
        if role and company:
            head += f" — {role} at {company}"
        elif role:
            head += f" — {role}"
        elif company:
            head += f" — {company}"
        parts.append(head)
    if bio:
        parts.append(bio)
    return "\n".join(parts) if parts else "(no public profile data found)"


def _fallback_hooks(open_commitments: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Deterministic hooks if the Gemini call fails or returns nothing usable."""
    hooks: list[dict[str, str]] = []
    for c in open_commitments[:3]:
        hooks.append({
            "label": "Bring",
            "text": f"{c['description']} — open {c['days_open']} days.",
        })
    # No generic "Probe" filler — an empty list is honest. When there's no real
    # signal, _generate_brief_inner suppresses hooks entirely and the UI shows the
    # "new contact" state instead of fabricated talking points.
    return hooks


def _sanitize_hooks(raw_hooks: list[Any]) -> list[dict[str, str]]:
    """Constrain LLM output to ``{label, text}`` with known labels."""
    out: list[dict[str, str]] = []
    for h in raw_hooks or []:
        if not isinstance(h, dict):
            continue
        label = str(h.get("label") or "").strip()
        text = str(h.get("text") or "").strip()
        if not text:
            continue
        if label not in ALLOWED_HOOK_LABELS:
            label = "Worth knowing"
        out.append({"label": label, "text": text})
        if len(out) >= 5:
            break
    return out


async def _generate_hooks(
    *,
    meeting_title: str,
    user_goal: str,
    person: dict[str, Any],
    prior_recaps: list[dict[str, Any]],
    open_commitments: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Single Gemini call for hooks. Returns ``_fallback_hooks(...)`` on failure."""
    prompt = HOOKS_PROMPT_TEMPLATE.format(
        meeting_title=meeting_title or "Meeting",
        user_goal=user_goal or "(not provided)",
        person_summary=_format_person_summary(person),
        signals="\n".join(f"- {s}" for s in (person.get("signals") or [])) or "(none)",
        prior_recaps_block=_format_prior_recaps_for_prompt(prior_recaps),
        open_commitments_block=_format_open_commitments_for_prompt(open_commitments),
    )

    try:
        response = await asyncio.to_thread(
            _get_genai_client().models.generate_content,
            model=chat_model_name(),
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=HOOKS_SCHEMA,
            ),
        )
        raw = _strip_markdown_fences(response.text or "")
        parsed = json.loads(raw) if raw else {}
        hooks = _sanitize_hooks(parsed.get("hooks") or [])
        if hooks:
            return hooks
        logger.info("[Brief] gemini returned no hooks; using fallback")
        return _fallback_hooks(open_commitments)
    except Exception as exc:
        logger.warning("[Brief] hooks generation failed: %s", exc)
        return _fallback_hooks(open_commitments)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def generate_brief(
    *,
    twin_id: str,
    meeting_id: str,
    meeting: dict[str, Any] | None = None,
    requester: str | None = None,  # noqa: ARG001 — reserved for audit
    context: str | None = None,
    self_email: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Build a BriefContract dict for one meeting.

    Args:
      twin_id: Twin owning the brief.
      meeting_id: Meeting being briefed.
      meeting: Pre-fetched meeting row. When None, fetched internally.
      context: Caller-supplied prep notes (overrides meeting.user_context).
      self_email: Owner's email — used to exclude the user from
        ``participant_insights[]``. When None, resolved from the twin's
        tenant. Critical for meetings the user was INVITED to (where the
        organizer is someone else and the user's own email is in attendees).

    The brief gracefully degrades:
      * PDL miss → person block has empty bio/role/company/signals.
      * Gemini failure → hooks fall back to commitment-only deterministic list.
      * No prior history → prior_meetings is an empty list.

    Returns the dict-shaped contract (see module docstring).
    """
    with _tracer.start_as_current_span("brief.generate") as span:
        span.set_attribute("meeting.id", meeting_id)
        span.set_attribute("twin.id", twin_id)
        span.set_attribute("brief.schema_version", 2 if _schema_v2_enabled() else 1)
        return await _generate_brief_inner(
            twin_id=twin_id,
            meeting_id=meeting_id,
            meeting=meeting,
            context=context,
            self_email=self_email,
            tenant_id=tenant_id,
            span=span,
        )


async def _resolve_twin_owner_email(
    twin_id: str,
    *,
    tenant_id: str | None = None,
) -> str | None:
    """Resolve the twin's owner email via a tenant-scoped two-step lookup.

    Audit finding: the previous nested-select pattern (``users(email)``)
    required a foreign key from twins → users. No such FK exists — both
    tables reference ``tenants(id)``, not each other — so PostgREST
    silently returned ``None`` for users every time, making the
    self-exclusion fix a no-op in production.

    This version does two scoped queries:
      1. twins.id = twin_id (+ tenant_id when supplied) → owner tenant_id
      2. users.id = owner_tenant_id → email

    The optional ``tenant_id`` argument is a defense-in-depth scope so
    this function cannot reveal an email across tenant boundaries when
    the caller knows the tenant context.

    Returns None on any miss/error so the brief still ships.
    """
    from modules.observability import get_supabase_client

    sb = get_supabase_client()
    try:
        twin_query = sb.table("twins").select("tenant_id").eq("id", twin_id)
        if tenant_id:
            twin_query = twin_query.eq("tenant_id", tenant_id)
        twin_resp = await asyncio.to_thread(
            lambda: twin_query.maybe_single().execute()
        )
        owner_tenant_id = (
            (twin_resp.data or {}).get("tenant_id") if twin_resp else None
        )
        if not owner_tenant_id:
            return None

        user_resp = await asyncio.to_thread(
            lambda: (
                sb.table("users")
                .select("email")
                .eq("id", owner_tenant_id)
                .maybe_single()
                .execute()
            )
        )
        if not user_resp or not user_resp.data:
            return None
        return user_resp.data.get("email")
    except Exception as exc:
        logger.warning(
            "[Brief] twin owner email lookup failed twin=%s: %s", twin_id, exc
        )
        return None


async def _generate_brief_inner(
    *,
    twin_id: str,
    meeting_id: str,
    meeting: dict[str, Any] | None,
    context: str | None,
    self_email: str | None,
    tenant_id: str | None,
    span: Any,
) -> dict[str, Any]:
    if not meeting:
        fetched = await _fetch_meeting_row(meeting_id, twin_id, tenant_id=tenant_id)
        if not fetched:
            raise ValueError(f"meeting not found meeting_id={meeting_id} twin_id={twin_id}")
        meeting = fetched

    attendee = _extract_primary_attendee(meeting)

    # PDL — best effort, non-fatal.
    pdl: dict[str, Any] | None = None
    if attendee.get("email"):
        try:
            from services.enrichment import pdl_client
            pdl = await pdl_client.enrich_by_email(attendee["email"])
        except Exception as exc:
            logger.warning("[Brief] PDL enrich failed email=%s: %s", attendee.get("email"), exc)
            pdl = None

    person = _build_person_block(attendee, pdl)

    # Carry-forward.
    prior_recaps = await _fetch_prior_recaps_for_brief(meeting)
    open_commitments = _extract_open_commitments(prior_recaps)

    user_goal = (meeting.get("user_goal") or "").strip() or None
    user_context = (context or meeting.get("user_context") or "").strip() or None

    # ----- v2 + Heads Up preflight computations -----
    # We pre-compute participant_insights, previous_interactions, and the
    # heads_up candidate list BEFORE the parallel LLM calls so:
    #   1. The heads_up rewriter has all its inputs ready
    #   2. The hooks call and the heads_up rewriter call run via
    #      asyncio.gather (one LLM round-trip instead of two serial)
    participant_insights: list[dict[str, Any]] = []
    previous_interactions: list[dict[str, Any]] = []
    heads_up_candidates: list[dict[str, Any]] = []
    effective_self_email: str | None = None
    if _schema_v2_enabled():
        meeting_tenant_id = meeting.get("tenant_id")
        effective_self_email = self_email or await _resolve_twin_owner_email(
            twin_id, tenant_id=meeting_tenant_id
        )
        participant_insights = _extract_participant_insights(
            meeting.get("attendees_json"),
            organizer_email=meeting.get("organizer_email"),
            self_email=effective_self_email,
        )
        previous_interactions = _prior_recaps_to_interactions(prior_recaps)
        if _heads_up_enabled():
            heads_up_candidates = await _build_heads_up_candidates(
                twin_id=twin_id,
                meeting=meeting,
                open_commitments=open_commitments,
                previous_interactions=previous_interactions,
                effective_self_email=effective_self_email,
            )

    # ----- parallel LLM calls (hooks + heads_up rewriter) -----
    meeting_title = meeting.get("title") or "Meeting"

    # AUDIT FIX: capture flag values ONCE before the gather. Reading
    # os.getenv inside the closures created a TOCTOU window if env toggled
    # between preflight (candidate build) and execution. Now both sides
    # see the same truth.
    heads_up_should_run = bool(
        _schema_v2_enabled() and _heads_up_enabled() and heads_up_candidates
    )

    async def _hooks_coro() -> list[dict[str, str]]:
        return await _generate_hooks(
            meeting_title=meeting_title,
            user_goal=user_goal or "",
            person=person,
            prior_recaps=prior_recaps,
            open_commitments=open_commitments,
        )

    async def _heads_up_coro() -> list[dict[str, Any]]:
        # Short-circuit without LLM call when disabled OR no candidates
        # (the captured boolean above guarantees both checks agree).
        if not heads_up_should_run:
            return []
        from adk_core.services.persona_core.heads_up_rewriter import (
            rewrite_to_caution_notes,
        )
        return await rewrite_to_caution_notes(
            candidates=heads_up_candidates, meeting_title=meeting_title,
        )

    # AUDIT FIX (CRITICAL): return_exceptions=True so:
    #   (a) one coroutine's failure can't cancel the other mid-LLM-call
    #   (b) CancelledError from Cloud Run SIGTERM is observable here
    #       instead of aborting the entire brief generation
    # Both inner coroutines have their own try/except — anything that
    # leaks out here is fatal (CancelledError, KeyboardInterrupt) and
    # we degrade gracefully to empty results rather than 500.
    hooks_result, caution_result = await asyncio.gather(
        _hooks_coro(), _heads_up_coro(), return_exceptions=True,
    )
    if isinstance(hooks_result, BaseException):
        logger.warning(
            "[Brief] hooks coroutine raised meeting=%s: %s",
            meeting_id, hooks_result,
        )
        hooks = _fallback_hooks(open_commitments)
    else:
        hooks = hooks_result
    if isinstance(caution_result, BaseException):
        logger.warning(
            "[Brief] heads_up coroutine raised meeting=%s: %s",
            meeting_id, caution_result,
        )
        caution_notes: list[dict[str, Any]] = []
    else:
        caution_notes = caution_result

    # Slop gate. With no real signal about this person — no prior meetings, no open
    # commitments, no stated goal, no profile signals — the hooks LLM can only emit
    # generic filler ("ask what outcomes they're hoping for"). Suppress hooks here so
    # talking_points and suggested_agenda fall out empty downstream and the UI renders
    # the honest "new contact — your first meeting" state instead of fabricated points.
    _goal_real = bool(
        user_goal
        and user_goal.strip()
        and user_goal.strip().lower() not in ("", "(not provided)")
    )
    has_signal = bool(
        prior_recaps
        or open_commitments
        or _goal_real
        or (person and person.get("signals"))
    )
    if not has_signal:
        hooks = []

    # The UI consumes ``prior_meetings`` directly; trim the heavier fields
    # the prompt needed but the page doesn't. Each entry also carries a
    # status flag ("open" / "done") so the UI can render a status pill
    # signalling whether the user has any unresolved commitments from
    # that meeting.
    open_meeting_ids = {
        c.get("from_meeting_id")
        for c in open_commitments
        if c.get("from_meeting_id")
    }
    prior_for_ui = [
        {
            "meeting_id": r.get("meeting_id"),
            "date": r.get("date"),
            "title": r.get("title"),
            "summary": r.get("summary"),
            "status": "open" if r.get("meeting_id") in open_meeting_ids else "done",
        }
        for r in prior_recaps
    ]

    brief = _empty_brief_contract(
        meeting_id=meeting.get("id") or meeting_id,
        title=meeting_title,
        start=meeting.get("meeting_start"),
    )
    brief["person"] = person
    brief["your_goal"] = user_goal
    brief["your_context"] = user_context
    brief["prior_meetings"] = prior_for_ui
    brief["hooks"] = hooks
    brief["open_commitments"] = open_commitments
    brief["generated_at"] = datetime.now(timezone.utc).isoformat()
    # v2 fields — populated only when the schema flag is on
    if _schema_v2_enabled():
        # AUDIT FIX (HIGH): write the PDL snapshot into the local
        # participant_insights list BEFORE assigning to brief, so the
        # mutation operates on data we own rather than the brief dict's
        # reference-shared list. Pattern aligns with the project's
        # immutability rule.
        if pdl and attendee.get("email"):
            target_email = attendee["email"].lower().strip()
            snapshot = {
                "company": pdl.get("job_company_name"),
                "role": pdl.get("job_title"),
                "as_of": brief["generated_at"],
            }
            for insight in participant_insights:
                if (insight.get("email") or "").lower().strip() == target_email:
                    insight["pdl_snapshot"] = snapshot
                    break

        brief["participant_insights"] = participant_insights
        brief["talking_points"] = _hooks_to_talking_points(hooks)
        brief["previous_interactions"] = previous_interactions
        # Same slop gate: no real signal → no fabricated agenda. The UI's "new
        # contact" state replaces it.
        brief["suggested_agenda"] = (
            _generate_agenda(
                your_goal=user_goal,
                talking_points=brief["talking_points"],
                open_commitments=open_commitments,
                prior_count=len(prior_for_ui),
            )
            if has_signal
            else []
        )
        # sources_used.past_meetings reflects prior_meetings we surfaced.
        # kb_chunks + web_results stay 0 in W9a fast path; W9d deep mode
        # populates them via brief_agent.py's ReAct tool counters.
        brief["sources_used"]["past_meetings"] = len(prior_for_ui)
        # W9b: caution_notes from the parallel rewriter call. Empty unless
        # both BRIEF_SCHEMA_V2_ENABLED and HEADS_UP_ENABLED are true.
        brief["caution_notes"] = caution_notes
    logger.info(
        "[Brief] generated meeting=%s twin=%s prior=%d hooks=%d commitments=%d pdl=%s",
        meeting_id, twin_id,
        len(prior_for_ui), len(hooks), len(open_commitments), "yes" if pdl else "no",
    )
    span.set_attribute("brief.prior_count", len(prior_for_ui))
    span.set_attribute("brief.hooks_count", len(hooks))
    span.set_attribute("brief.commitments_count", len(open_commitments))
    span.set_attribute("brief.pdl_hit", pdl is not None)
    if _schema_v2_enabled():
        span.set_attribute("brief.participants_count", len(brief.get("participant_insights", [])))
        span.set_attribute("brief.agenda_count", len(brief.get("suggested_agenda", [])))
    return brief
