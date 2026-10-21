"""W9b — Heads Up LLM rewriter.

Takes rule-fired candidate dicts, sends one batched Gemini call with the
locked system prompt, parses the JSON response, synthesizes citations
mechanically from the candidate (NOT from LLM free-text), and runs every
note through the anti-pattern post-filter.

Hardening rules (all enforced here, not in callers):
  1. Empty candidates -> empty result, no LLM call
  2. LLM exception (timeout/network) -> empty result + log
  3. JSON parse failure -> empty result + log
  4. Anti-pattern in note text -> drop note + log (heads_up_safety filter)
  5. source_candidate_idx out of range -> drop note + log
  6. Notes capped at 3 — strongest 3 only

The rewriter NEVER ships raw rule-generator output to users. If anything
fails between input and final notes, the result is empty.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
from typing import Any

import google.genai as genai
import google.genai.types as genai_types

from adk_core.model_names import chat_model_name
from adk_core.services.persona_core.heads_up_prompt import (
    OUTPUT_SCHEMA,
    SYSTEM_PROMPT,
    build_user_prompt,
)
from adk_core.services.persona_core.heads_up_safety import filter_safe_notes
from modules.telemetry import get_tracer

logger = logging.getLogger(__name__)
_tracer = get_tracer("brief")

# Gemini model used for the rewriter. Flash chosen for fast latency on the
# critical brief-generation path; the 6 principles + few-shot examples in the
# system prompt are within Flash's instruction-following envelope.
_HEADS_UP_MODEL = os.getenv("HEADS_UP_MODEL", "").strip() or chat_model_name()

# Max notes per brief regardless of what the LLM returns. Tone discipline
# (the eval contract) says 3 is the max.
_MAX_NOTES = 3

# AUDIT FIX (HIGH): module-level singleton cached behind a lock instead of
# constructing a fresh genai.Client on every call. The previous per-call
# pattern caused connection pool growth + credential re-init on every brief,
# meaningful overhead under cron-fanout load.
_genai_client_singleton: genai.Client | None = None
_genai_client_lock = threading.Lock()


def _get_genai_client() -> genai.Client:
    """Return the cached Gemini client, creating it on first call.

    Hoisted (not inlined) so tests can monkeypatch it. Patched by
    test_heads_up_rewriter.py. The double-checked locking pattern
    avoids the lock on the hot path after first construction.
    """
    global _genai_client_singleton
    if _genai_client_singleton is not None:
        return _genai_client_singleton
    with _genai_client_lock:
        if _genai_client_singleton is not None:
            return _genai_client_singleton
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY not configured")
        _genai_client_singleton = genai.Client(api_key=api_key)
        return _genai_client_singleton


def _strip_markdown_fences(text: str) -> str:
    """LLMs sometimes wrap JSON in ```json``` fences despite the prompt
    forbidding it. Mirrors the helper in brief.py — kept inline to avoid
    cross-module dependency."""
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


def _hash_for_log(text: str) -> str:
    return hashlib.sha256(
        (text or "").encode("utf-8", errors="replace")
    ).hexdigest()[:12]


def _build_source_dict(candidate: dict[str, Any]) -> dict[str, Any]:
    """Mechanically derive ``{kind, ref, ref_type, quote}`` from a candidate.

    Citation is built from the candidate's structured fields, never from
    LLM free-text. This eliminates citation hallucination — the LLM can
    pick the wrong candidate but can't invent source content.

    ref preference order (first non-empty wins):
      - source_meeting_id  (open_commitment, meeting_outcome_pattern, ...)
      - from_meeting_id    (action_item_pending)
      - note_source_id     (kb_private_hit)
      - source_id          (personal_context, news_event)
      - prior_date         (agenda_signal — date string, last resort)

    AUDIT FIX (MEDIUM): include ``ref_type`` so the W9c UI can branch on
    "this ref is a meeting_id" vs "this ref is a note_id" vs "this ref
    is just a date" — without string-sniffing. The frontend renders
    different links per type.

    quote preference order:
      - source_quote
      - note_quote
      - email_quote
      - last_recap_quote
      - recap_quote
      - description (last-resort summary)
    """
    ref = ""
    ref_type = "none"
    if candidate.get("source_meeting_id"):
        ref = candidate["source_meeting_id"]
        ref_type = "meeting_id"
    elif candidate.get("from_meeting_id"):
        ref = candidate["from_meeting_id"]
        ref_type = "meeting_id"
    elif candidate.get("note_source_id"):
        ref = candidate["note_source_id"]
        ref_type = "note_id"
    elif candidate.get("source_id"):
        ref = candidate["source_id"]
        ref_type = "source_id"
    elif candidate.get("prior_date"):
        ref = candidate["prior_date"]
        ref_type = "date"

    quote = (
        candidate.get("source_quote")
        or candidate.get("note_quote")
        or candidate.get("email_quote")
        or candidate.get("last_recap_quote")
        or candidate.get("recap_quote")
        or candidate.get("description")
        or ""
    )
    return {
        "kind": candidate.get("kind", "unknown"),
        "ref": str(ref),
        "ref_type": ref_type,
        "quote": str(quote),
    }


async def rewrite_to_caution_notes(
    *,
    candidates: list[dict[str, Any]],
    meeting_title: str,
) -> list[dict[str, Any]]:
    """Rewrite rule candidates into Level-3 caution_notes via Gemini.

    Returns a list of ``{text, source: {kind, ref, quote}}`` dicts.
    Empty list on any failure path — callers can safely assign the result
    to ``brief["caution_notes"]`` without conditionals.
    """
    meeting_hash = _hash_for_log(meeting_title)
    with _tracer.start_as_current_span("brief.heads_up") as span:
        span.set_attribute("heads_up.candidate_count", len(candidates))
        # AUDIT FIX (MEDIUM): record the configured model on every span so
        # operators can spot misconfiguration (HEADS_UP_MODEL set to a
        # nonexistent name) when caution_notes ship empty.
        span.set_attribute("heads_up.model", _HEADS_UP_MODEL)

        if not candidates:
            span.set_attribute("heads_up.kept_count", 0)
            span.set_attribute("heads_up.skip_reason", "no_candidates")
            return []

        user_prompt = build_user_prompt(
            candidates=candidates, meeting_title=meeting_title
        )

        # Gemini call. Anything raised becomes "empty result" — we NEVER ship
        # raw rule-generator output (which contains accusatory phrasing like
        # "user repeatedly failed to respond...").
        try:
            client = _get_genai_client()
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=_HEADS_UP_MODEL,
                contents=user_prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.2,
                    response_mime_type="application/json",
                    response_schema=OUTPUT_SCHEMA,
                ),
            )
        except Exception as exc:
            # AUDIT FIX (MEDIUM): elevate rate-limit errors to ERROR so
            # they appear in alert dashboards. Operators were blind to
            # 429 storms because the rewriter silently returned [].
            exc_str = str(exc).lower()
            is_rate_limit = (
                "429" in exc_str
                or "rate limit" in exc_str
                or "resource_exhausted" in exc_str
                or "quota" in exc_str
            )
            if is_rate_limit:
                logger.error(
                    "[HeadsUp] Gemini RATE LIMITED meeting_hash=%s error=%s",
                    meeting_hash, type(exc).__name__,
                )
                span.set_attribute("heads_up.skip_reason", "rate_limited")
            else:
                logger.warning(
                    "[HeadsUp] Gemini call failed meeting_hash=%s error=%s",
                    meeting_hash, type(exc).__name__,
                )
                span.set_attribute("heads_up.skip_reason", "llm_error")
            span.set_attribute("heads_up.kept_count", 0)
            return []

        # Parse the JSON response. Markdown-fence + bare-text recovery.
        # AUDIT FIX (CRITICAL): response.text itself can raise ValueError
        # ("no parts") when Gemini's safety filter blocks the response.
        # Must be inside the try/except — previously the access happened
        # outside the block and the exception propagated through
        # asyncio.gather, killing the entire brief.
        try:
            raw_text = _strip_markdown_fences(response.text or "")
            parsed = json.loads(raw_text) if raw_text else {}
        except (json.JSONDecodeError, ValueError, AttributeError) as exc:
            logger.warning(
                "[HeadsUp] response parse failed meeting_hash=%s error=%s",
                meeting_hash, type(exc).__name__,
            )
            span.set_attribute("heads_up.kept_count", 0)
            span.set_attribute("heads_up.skip_reason", "parse_error")
            return []

        raw_notes = parsed.get("caution_notes") or []
        if not isinstance(raw_notes, list):
            span.set_attribute("heads_up.kept_count", 0)
            span.set_attribute("heads_up.skip_reason", "shape_error")
            return []

        # Synthesize citations + validate idx range. Notes with invalid idx
        # are dropped (not silently re-pointed) — the LLM gave us bad data.
        with_citations: list[dict[str, Any]] = []
        for raw in raw_notes:
            if not isinstance(raw, dict):
                continue
            text = (raw.get("text") or "").strip()
            if not text:
                continue
            idx = raw.get("source_candidate_idx")
            if not isinstance(idx, int) or idx < 0 or idx >= len(candidates):
                logger.warning(
                    "[HeadsUp] dropping note with invalid source_candidate_idx=%r "
                    "candidates=%d meeting_hash=%s note_len=%d note_hash=%s",
                    idx, len(candidates), meeting_hash, len(text), _hash_for_log(text),
                )
                continue
            with_citations.append({
                "text": text,
                "source": _build_source_dict(candidates[idx]),
            })

        # Anti-pattern post-filter (defense-in-depth — the system prompt
        # forbids these, but the LLM can still slip).
        safe_notes, _dropped = filter_safe_notes(with_citations)

        # Hard cap at 3 — the eval contract's max.
        final = safe_notes[:_MAX_NOTES]

        span.set_attribute("heads_up.raw_count", len(raw_notes))
        span.set_attribute("heads_up.kept_count", len(final))
        span.set_attribute("heads_up.dropped_count", len(with_citations) - len(safe_notes))
        return final
