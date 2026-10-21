"""W9d — Deep research mode for the pre-meeting brief.

Runs the salvaged ``adk_core.agents.brief_agent`` (ADK ReAct loop) end-to-end
for one meeting. Returns the parsed JSON result, which the worker handler
then MERGES into the existing ``brief_json`` (never replaces).

Why a separate module: the fast path (``persona_core.brief.generate_brief``)
is a single Gemini call wrapped in async; the deep path drives a Runner with
5 tools and a 90s timeout. Keeping them in separate modules makes the
diff/test/audit surface clean.

Critical preflight handled here:
  - Pre-seeds session state (``AppKey.SUBJECT_NAME``, ``AppKey.RESEARCH_COMPANY``)
    so ``adk_core.tools.search_tools.scrape_page`` can do its subject-name
    + organisation matching filters. Without this, scrape results are
    silently downgraded.
  - Bounds the ReAct loop with a 90s asyncio timeout. Real deep runs
    take ~25-45s; 90s catches runaway tool loops.
  - Catches every exception → returns None. Callers persist nothing on
    failure (cached fast-path stays intact).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from typing import Any

import google.genai.types as genai_types
from google.adk.runners import Runner

from adk_core.model_names import default_model_name
from adk_core.agents.brief_agent import build_brief_agent
from adk_core.state_keys import AppKey
from adk_core.services.agent_service import APP_NAME, _get_session_service
from modules.telemetry import get_tracer

logger = logging.getLogger(__name__)
_tracer = get_tracer("brief")

# Cap the entire ReAct loop. Real deep runs measure ~25-45s; a runaway
# tool loop should not be allowed to hold a worker slot forever.
_DEEP_BRIEF_TIMEOUT_SECONDS = 90

# Model used for the deep ReAct loop. Override via env for experiments.
# Defaults to ADK_DEFAULT_MODEL, else the ADK chat model.
_DEEP_BRIEF_MODEL = os.getenv("DEEP_BRIEF_MODEL", "").strip() or default_model_name()


def _strip_markdown_fences(text: str) -> str:
    """Same helper used by brief.py — kept inline to keep this module
    free of cross-module imports beyond ADK + telemetry."""
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


def _primary_subject(meeting: dict[str, Any]) -> dict[str, str]:
    """Pick the first non-organizer attendee as the research subject.

    Mirrors ``persona_core.brief._extract_primary_attendee`` but returns
    a friendlier shape for session-state seeding.
    """
    attendees = meeting.get("attendees_json") or []
    organizer_email = (
        (meeting.get("organizer_email") or "").lower().strip() or None
    )
    if not isinstance(attendees, list):
        return {"name": "", "email": "", "company": ""}
    for a in attendees:
        if isinstance(a, dict):
            email = (a.get("email") or "").lower().strip()
            name = (
                a.get("displayName")
                or a.get("name")
                or ""
            ).strip()
            company = (a.get("company") or "").strip()
            if email and organizer_email and email == organizer_email:
                continue
            if name or email:
                return {"name": name, "email": email, "company": company}
        elif isinstance(a, str):
            name = a.strip()
            if name:
                return {"name": name, "email": "", "company": ""}
    return {"name": "", "email": "", "company": ""}


def _participant_names(meeting: dict[str, Any], cap: int = 4) -> list[str]:
    """Display names of up to `cap` attendees, excluding the organizer."""
    attendees = meeting.get("attendees_json") or []
    organizer_email = (
        (meeting.get("organizer_email") or "").lower().strip() or None
    )
    if not isinstance(attendees, list):
        return []
    out: list[str] = []
    for a in attendees:
        if isinstance(a, dict):
            email = (a.get("email") or "").lower().strip()
            name = (
                a.get("displayName")
                or a.get("name")
                or ""
            ).strip()
            if email and organizer_email and email == organizer_email:
                continue
            if name:
                out.append(name)
        elif isinstance(a, str):
            n = a.strip()
            if n:
                out.append(n)
        if len(out) >= cap:
            break
    return out


async def run_deep_brief(
    *,
    twin_id: str,
    tenant_id: str,
    meeting: dict[str, Any],
) -> dict[str, Any] | None:
    """Run the brief_agent ReAct loop for one meeting.

    Returns the parsed JSON result (matching the v2 brief contract shape)
    on success, or ``None`` on any failure (timeout, parse error, agent
    exception). Callers should treat ``None`` as "skip the merge — keep
    whatever fast-path brief is already cached".
    """
    meeting_id = meeting.get("id") or ""
    meeting_title = meeting.get("title") or "Meeting"
    participants = _participant_names(meeting)
    subject = _primary_subject(meeting)
    user_goal = (meeting.get("user_goal") or "").strip()
    user_context = (meeting.get("user_context") or "").strip()

    with _tracer.start_as_current_span("brief.deep.run") as span:
        span.set_attribute("meeting.id", meeting_id)
        span.set_attribute("twin.id", twin_id)
        span.set_attribute("brief.deep.model", _DEEP_BRIEF_MODEL)
        span.set_attribute("brief.deep.participants_count", len(participants))

        # Build the agent. Tools close over twin_id + tenant_id for KB
        # and past-meetings scoping.
        try:
            agent = build_brief_agent(
                model=_DEEP_BRIEF_MODEL,
                twin_id=twin_id,
                tenant_id=tenant_id,
                title=meeting_title,
                participants=participants,
                goal=user_goal,
                notes=user_context,
            )
        except Exception:
            # AUDIT FIX (PR #132 post-merge): logger.exception already
            # captures the traceback. Passing `exc` as a format arg re-
            # renders the exception body inline, which for ADK build
            # errors can include session-state fragments. Drop the
            # format arg; the traceback alone is sufficient and stays
            # behind Cloud Logging's structured-payload boundary.
            logger.exception(
                "[DeepBrief] agent build failed meeting=%s", meeting_id,
            )
            span.set_attribute("brief.deep.skip_reason", "build_error")
            return None

        # Session ID is per-run (no continuation — each deep brief is
        # a fresh ReAct loop). User ID is the twin owner; session DB
        # carries the per-tool state keys.
        user_id = f"twin:{twin_id}"
        session_id = f"deep_brief:{meeting_id}:{uuid.uuid4().hex[:8]}"

        session_svc = _get_session_service()
        # Pre-seed the session state with the keys that
        # search_tools.scrape_page reads. Without these, scrape filters
        # silently downgrade results (subject_mentioned=False on valid
        # pages, organisation match falls back to True permissively).
        initial_state = {
            AppKey.SUBJECT_NAME: subject.get("name", ""),
            AppKey.RESEARCH_COMPANY: subject.get("company", ""),
        }
        try:
            await session_svc.create_session(
                app_name=APP_NAME,
                user_id=user_id,
                session_id=session_id,
                state=initial_state,
            )
        except Exception as exc:
            logger.warning(
                "[DeepBrief] session create failed meeting=%s: %s",
                meeting_id, exc,
            )
            span.set_attribute("brief.deep.skip_reason", "session_error")
            return None

        runner = Runner(
            agent=agent,
            app_name=APP_NAME,
            session_service=session_svc,
        )

        # Trigger the ReAct loop with a minimal kick-off message — the
        # whole research strategy lives in the agent's system prompt.
        # We include the goal verbatim so the agent doesn't have to
        # re-derive it from session state.
        kickoff = (
            f"Research this meeting and produce the brief JSON. "
            f"Goal: {user_goal or '(none stated)'}"
        )
        user_content = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=kickoff)],
        )

        chunks: list[str] = []
        started_at = time.monotonic()
        try:
            async with asyncio.timeout(_DEEP_BRIEF_TIMEOUT_SECONDS):
                async for event in runner.run_async(
                    user_id=user_id,
                    session_id=session_id,
                    new_message=user_content,
                ):
                    if not event.content or not event.content.parts:
                        continue
                    for part in event.content.parts:
                        if getattr(part, "text", None):
                            chunks.append(part.text)
        except TimeoutError:
            logger.warning(
                "[DeepBrief] timeout after %ss meeting=%s",
                _DEEP_BRIEF_TIMEOUT_SECONDS,
                meeting_id,
            )
            span.set_attribute("brief.deep.skip_reason", "timeout")
            return None
        except Exception:
            # AUDIT FIX (PR #132 post-merge): drop `exc` format arg.
            # ADK Runner exceptions can wrap context that includes the
            # last agent message or session state in str(exc); the
            # traceback alone is sufficient and stays in structured
            # payload.
            logger.exception(
                "[DeepBrief] runner failed meeting=%s", meeting_id,
            )
            span.set_attribute("brief.deep.skip_reason", "runner_error")
            return None

        duration_s = time.monotonic() - started_at
        span.set_attribute("brief.deep.duration_s", round(duration_s, 2))

        # Pull the final text (last non-empty chunk). The agent prompt is
        # explicit: "JSON only — no surrounding text". Strip markdown
        # fences defensively in case the model wraps the output.
        final_text = ""
        for chunk in reversed(chunks):
            stripped = chunk.strip()
            if stripped:
                final_text = stripped
                break
        if not final_text:
            logger.warning(
                "[DeepBrief] no final text meeting=%s chunks=%d",
                meeting_id, len(chunks),
            )
            span.set_attribute("brief.deep.skip_reason", "no_output")
            return None

        cleaned = _strip_markdown_fences(final_text)
        try:
            parsed = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError) as exc:
            output_hash = hashlib.sha256(
                cleaned.encode("utf-8", errors="replace")
            ).hexdigest()[:12]
            logger.warning(
                "[DeepBrief] JSON parse failed meeting=%s error=%s "
                "output_len=%d output_hash=%s",
                meeting_id, type(exc).__name__, len(cleaned), output_hash,
            )
            span.set_attribute("brief.deep.skip_reason", "parse_error")
            return None

        if not isinstance(parsed, dict):
            span.set_attribute("brief.deep.skip_reason", "shape_error")
            return None

        # Surface a few useful span attrs for triage
        span.set_attribute(
            "brief.deep.talking_points_count",
            len(parsed.get("talking_points") or []),
        )
        span.set_attribute(
            "brief.deep.participant_insights_count",
            len(parsed.get("participant_insights") or []),
        )
        sources_used = parsed.get("sources_used") or {}
        span.set_attribute(
            "brief.deep.sources_used.web_results",
            int(sources_used.get("web_results") or 0),
        )
        span.set_attribute(
            "brief.deep.sources_used.kb_chunks",
            int(sources_used.get("kb_chunks") or 0),
        )
        return parsed
