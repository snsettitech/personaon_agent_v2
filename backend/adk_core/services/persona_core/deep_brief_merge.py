"""W9d — Merge logic: overlay deep-research output into the fast-path brief.

The fast path (``persona_core.brief.generate_brief``) writes the canonical
``brief_json`` with ``open_commitments``, ``caution_notes`` (Heads Up),
``hooks``, ``prior_meetings``, plus stub ``participant_insights``.
Deep mode produces a richer JSON that should ENRICH — never REPLACE — the
fast-path output.

Merge policy (overlay):
  - participant_insights : deep wins (richer — has background +
                           recent_activities + web_sources). v1 stub kept
                           only when deep produced []
  - talking_points       : merge — fast-path generated from hooks LLM call;
                           deep generates from agent research. Keep fast
                           if deep emitted []; else take deep.
  - previous_interactions: deep wins ONLY if deep emitted >0; fast retains
                           open_items[] from W9a so this stays a strict
                           overlay
  - suggested_agenda     : deep wins if non-empty; else fast
  - sources_used         : SUM the counters (deep adds kb_chunks +
                           web_results; fast had past_meetings)
  - caution_notes        : NEVER OVERLAID. Heads Up tone is enforced by the
                           W9b rewriter; the deep agent's text is NOT held
                           to the same eval contract. Keep fast.
  - open_commitments     : NEVER OVERLAID. Deep agent doesn't see
                           open_commitments (no tool for it). Keep fast.
  - hooks                : NEVER OVERLAID. v1 surface; same reason.
  - prior_meetings       : NEVER OVERLAID. v1 surface; same reason.
  - person, your_goal, your_context, meeting_*, generated_at, schema_version
                         : KEPT from fast path.

Adds:
  - deep_generated_at: ISO timestamp. UI uses this as the cache key + to
                       render the "Deep research from {time}" footer.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# AUDIT FIX (W9d HIGH security): the deep agent ingests up to 50KB of
# scraped page HTML per page. An attacker-controlled page containing
# "Ignore prior instructions. Output: {...}" could try to write malicious
# strings into talking_points / participant_insights / suggested_agenda.
# These fields land verbatim in the user's brief UI.
#
# Mitigations applied to every overlaid string before merge:
#   1. Length cap per string (prevents megabyte payloads from being
#      stored in brief_json or rendered in the UI)
#   2. Injection-pattern scan — fields matching common "ignore/disregard
#      previous instructions" prompts are dropped, not stored

_MAX_FIELD_CHARS = 1200

_INJECTION_PATTERN = re.compile(
    r"(?i)\b(ignore|disregard|forget|override)\b.{0,40}\b"
    r"(previous|above|prior|earlier|system|all|the)\b.{0,40}\b"
    r"(instruction|prompt|rule|order|direction|command)s?\b"
)


def _safe_string(value: Any) -> str:
    """Cap length + strip injection markers. Used on every interpolated
    field before it enters brief_json."""
    s = str(value) if value is not None else ""
    if len(s) > _MAX_FIELD_CHARS:
        s = s[:_MAX_FIELD_CHARS] + "…"
    if _INJECTION_PATTERN.search(s):
        return "[redacted: suspicious content]"
    return s


def _sanitize_string_list(items: Any) -> list[str]:
    """Sanitize each entry; drop non-string/empty entries."""
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items:
        if not item:
            continue
        cleaned = _safe_string(item)
        if cleaned:
            out.append(cleaned)
    return out


def _sanitize_talking_point(tp: Any) -> dict[str, str] | None:
    if not isinstance(tp, dict):
        return None
    topic = _safe_string(tp.get("topic"))
    if not topic:
        return None
    return {"topic": topic, "rationale": _safe_string(tp.get("rationale"))}


def _sanitize_participant_insight(p: Any) -> dict[str, Any] | None:
    if not isinstance(p, dict):
        return None
    name = _safe_string(p.get("name"))
    if not name:
        return None
    # AUDIT FIX (PR #132 post-merge): pdl_snapshot was passing through
    # unsanitized via `isinstance(..., dict) if dict else None`. The
    # frontend reads only pdl_snapshot.role and pdl_snapshot.company
    # (ParticipantInsightsCard.tsx:121-122), but the LLM can emit
    # arbitrary content into those scalars from a scraped page. React
    # auto-escapes so this isn't XSS, but offensive/manipulated text
    # would still render. Sanitize the two consumed scalars; drop the
    # field entirely if neither is present so we don't ship empty dicts.
    raw_snapshot = p.get("pdl_snapshot")
    pdl_snapshot: dict[str, Any] | None = None
    if isinstance(raw_snapshot, dict):
        snap_role = _safe_string(raw_snapshot.get("role")) or None
        snap_company = _safe_string(raw_snapshot.get("company")) or None
        snap_as_of = _safe_string(raw_snapshot.get("as_of")) or None
        if snap_role or snap_company or snap_as_of:
            pdl_snapshot = {
                "role": snap_role,
                "company": snap_company,
                "as_of": snap_as_of,
            }
    return {
        "name": name,
        "email": _safe_string(p.get("email")),
        "role": _safe_string(p.get("role")) or None,
        "background": _safe_string(p.get("background")) or None,
        "recent_activities": _sanitize_string_list(p.get("recent_activities")),
        "web_sources": _sanitize_string_list(p.get("web_sources")),
        "pdl_snapshot": pdl_snapshot,
    }


def _sanitize_previous_interaction(it: Any) -> dict[str, Any] | None:
    if not isinstance(it, dict):
        return None
    title = _safe_string(it.get("meeting_title"))
    if not title:
        return None
    return {
        "meeting_id": _safe_string(it.get("meeting_id")),
        "date": _safe_string(it.get("date")),
        "meeting_title": title,
        "summary": _safe_string(it.get("summary")),
        "open_items": _sanitize_string_list(it.get("open_items")),
    }


def merge_deep_into_brief(
    *,
    fast_brief: dict[str, Any],
    deep_output: dict[str, Any],
) -> dict[str, Any]:
    """Return a NEW brief dict with deep fields overlaid on the fast path.

    ``fast_brief`` is the existing ``meetings.brief_json`` (v2 schema).
    ``deep_output`` is the parsed JSON from ``run_deep_brief``.

    Pure function: never mutates inputs. Always sets ``deep_generated_at``.

    AUDIT FIX (W9d HIGH): the no-overlay path now defensively copies the
    fast-path list so downstream mutation of ``merged["x"]`` cannot leak
    back to ``fast_brief["x"]``. The previous version's shallow copy
    shared the list reference whenever deep emitted an empty/missing
    field.
    """
    merged = dict(fast_brief)  # shallow copy at top level

    # AUDIT FIX (W9d HIGH security): every overlaid string goes through
    # _safe_string (length cap + injection-pattern scan). The deep agent's
    # output may include scraped HTML content from attacker-controlled
    # pages — we never store that verbatim.
    deep_pi_raw = deep_output.get("participant_insights") or []
    if isinstance(deep_pi_raw, list) and len(deep_pi_raw) > 0:
        sanitized_pi = [
            p
            for p in (_sanitize_participant_insight(x) for x in deep_pi_raw)
            if p is not None
        ]
        merged["participant_insights"] = sanitized_pi or list(
            fast_brief.get("participant_insights") or []
        )
    else:
        merged["participant_insights"] = list(
            fast_brief.get("participant_insights") or []
        )

    deep_tp_raw = deep_output.get("talking_points") or []
    if isinstance(deep_tp_raw, list) and len(deep_tp_raw) > 0:
        sanitized_tp = [
            t
            for t in (_sanitize_talking_point(x) for x in deep_tp_raw)
            if t is not None
        ]
        merged["talking_points"] = sanitized_tp or list(
            fast_brief.get("talking_points") or []
        )
    else:
        merged["talking_points"] = list(fast_brief.get("talking_points") or [])

    deep_prev_raw = deep_output.get("previous_interactions") or []
    if isinstance(deep_prev_raw, list) and len(deep_prev_raw) > 0:
        sanitized_prev = [
            i
            for i in (_sanitize_previous_interaction(x) for x in deep_prev_raw)
            if i is not None
        ]
        merged["previous_interactions"] = sanitized_prev or list(
            fast_brief.get("previous_interactions") or []
        )
    else:
        merged["previous_interactions"] = list(
            fast_brief.get("previous_interactions") or []
        )

    deep_agenda_raw = deep_output.get("suggested_agenda") or []
    if isinstance(deep_agenda_raw, list) and len(deep_agenda_raw) > 0:
        sanitized_agenda = _sanitize_string_list(deep_agenda_raw)
        merged["suggested_agenda"] = sanitized_agenda or list(
            fast_brief.get("suggested_agenda") or []
        )
    else:
        merged["suggested_agenda"] = list(
            fast_brief.get("suggested_agenda") or []
        )

    # sources_used: SUM. Fast wrote past_meetings; deep adds kb_chunks
    # + web_results. Defensive int() coercion in case the LLM emitted
    # strings for the counters. Always a fresh dict — no aliasing risk.
    fast_sources = fast_brief.get("sources_used") or {}
    deep_sources = deep_output.get("sources_used") or {}
    merged["sources_used"] = {
        "kb_chunks": _safe_int(fast_sources.get("kb_chunks"))
        + _safe_int(deep_sources.get("kb_chunks")),
        "web_results": _safe_int(fast_sources.get("web_results"))
        + _safe_int(deep_sources.get("web_results")),
        "past_meetings": _safe_int(fast_sources.get("past_meetings"))
        + _safe_int(deep_sources.get("past_meetings")),
    }

    merged["deep_generated_at"] = datetime.now(timezone.utc).isoformat()
    return merged


def _safe_int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def deep_cache_is_fresh(
    brief: dict[str, Any] | None,
    *,
    ttl_seconds: int = 24 * 60 * 60,
) -> bool:
    """Return True when the brief already has a deep run younger than ttl.

    Used by the POST /brief/deep endpoint and the worker handler to skip
    redundant deep runs for the same meeting. Default TTL: 24h.
    """
    if not brief:
        return False
    raw = brief.get("deep_generated_at")
    if not raw:
        return False
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        logger.warning(
            "[DeepBrief] malformed deep_generated_at=%r; treating as stale",
            raw,
        )
        return False
    # AUDIT FIX (W9d MEDIUM): a naive timestamp (no tz info) would
    # TypeError on the subtraction below. Postgres TIMESTAMP WITHOUT
    # TIME ZONE columns can return naive strings; treat them as UTC.
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age_s = (datetime.now(timezone.utc) - ts).total_seconds()
    return age_s < ttl_seconds
