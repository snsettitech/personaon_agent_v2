"""Interview Mode — AI agent interviews the user to deepen persona knowledge.

The interview agent reads the existing persona profile, identifies gaps,
and asks targeted questions. User answers are auto-saved to Pinecone
as FAQ entries, making the persona smarter with each exchange.

Uses the same ADK agent pipeline as chat, with a different system prompt.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from google.genai import types

from adk_core.services.agent_service import APP_NAME, _build_runner, _get_session_service, invalidate_agent
from adk_core.services.vector_store import upsert_faq
from modules.auth_guard import ensure_twin_active, require_tenant, verify_twin_ownership
from modules.observability import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["interview"])
INTERVIEW_TIMEOUT_SECONDS = 30
INTERVIEW_FAQ_ORIGIN = "interview"


# ── Models ──────────────────────────────────────────────────────────

class InterviewTurnRequest(BaseModel):
    """Request body for an interview turn."""
    message: str = Field(..., min_length=1, max_length=2000, description="User's answer")
    last_question: str | None = Field(None, description="The agent's previous question (for auto-save)")
    session_id: str | None = Field(None, description="Conversation session ID")


# ── Helpers ─────────────────────────────────────────────────────────

def _load_twin_profile(twin_id: str) -> dict:
    """Load twin profile from Supabase.

    Merges persona_profile (Firecrawl extraction) with public_profile (user-edited
    fields from the onboarding preview step) so that fields the user just filled in
    are not treated as gaps by _detect_gaps().
    """
    sb = get_supabase_client()
    resp = sb.table("twins").select("id, name, settings").eq("id", twin_id).single().execute()
    if not resp.data:
        from adk_core.errors import twin_not_found
        raise twin_not_found()
    settings = resp.data.get("settings") or {}

    persona = settings.get("persona_profile") or {}
    if isinstance(persona, str):
        try:
            persona = json.loads(persona)
        except (ValueError, TypeError):
            persona = {}

    public = settings.get("public_profile") or {}
    if isinstance(public, str):
        try:
            public = json.loads(public)
        except (ValueError, TypeError):
            public = {}

    # Merge: public_profile fields (user-edited) take precedence over persona_profile
    profile = {**persona}
    for field in ("occupation", "short_description", "personality_traits", "speaking_style"):
        val = public.get(field) or public.get({"occupation": "role"}.get(field, field))
        if val:
            profile[field] = val

    profile.setdefault("name", resp.data.get("name", ""))
    return profile


def _detect_gaps(profile: dict) -> list[dict]:
    """Identify missing or thin fields in the profile, ordered by importance."""
    gaps = []

    # Critical — the persona won't feel real without these
    critical = [
        (
            "occupation",
            "current role and where they work",
            "Ask: \"What's your current role and what do you do day-to-day?\"",
        ),
        (
            "short_description",
            "one-line summary of who they are",
            "Ask: \"How would you describe yourself in one sentence to a stranger?\"",
        ),
        (
            "speaking_style",
            "how they communicate (formal/casual, style, tone)",
            "Ask: \"How would close colleagues describe the way you communicate — direct, storytelling, data-driven?\"",
        ),
        (
            "personality_traits",
            "3-5 traits that define them",
            "Ask: \"What 3 words would someone who worked closely with you use to describe you?\"",
        ),
    ]
    for field, desc, opener in critical:
        val = profile.get(field)
        if not val or (isinstance(val, list) and len(val) == 0):
            gaps.append({"field": field, "priority": "HIGH", "what": desc, "opener": opener})

    # Important — adds depth and makes the persona richer
    important = [
        (
            "key_achievements",
            "proudest accomplishments",
            "Ask about their single proudest professional achievement",
        ),
        (
            "areas_of_expertise",
            "topics they know deeply",
            "Ask: \"What topics could you talk about for hours without notes?\"",
        ),
        (
            "work_experience",
            "career history (need 2+ roles)",
            "Ask about their career journey and how they got to where they are",
        ),
        (
            "contributions",
            "notable impact in their field",
            "Ask: \"What's the thing you've built or done that you're most proud of?\"",
        ),
    ]
    for field, desc, hint in important:
        val = profile.get(field)
        thin = not val or (isinstance(val, list) and len(val) < 2)
        if thin:
            gaps.append({"field": field, "priority": "MEDIUM", "what": desc, "opener": hint})

    return gaps


def _build_interviewer_prompt(profile: dict) -> str:
    """Build system prompt for the interviewer agent."""
    profile_json = json.dumps(profile, indent=2, ensure_ascii=False, default=str)
    gaps = _detect_gaps(profile)

    if gaps:
        high = [g for g in gaps if g["priority"] == "HIGH"]
        medium = [g for g in gaps if g["priority"] == "MEDIUM"]

        gap_lines = []
        if high:
            gap_lines.append("### CRITICAL GAPS (ask these first, in order):")
            for i, g in enumerate(high, 1):
                gap_lines.append(f"{i}. **{g['field']}** — {g['what']}")
                gap_lines.append(f"   Suggested opener: {g['opener']}")
        if medium:
            gap_lines.append("\n### IMPORTANT GAPS (ask after critical ones are covered):")
            for i, g in enumerate(medium, 1):
                gap_lines.append(f"{i}. **{g['field']}** — {g['what']}")
                gap_lines.append(f"   Hint: {g['opener']}")

        gap_section = "\n".join(gap_lines)
        start_instruction = (
            "Start immediately with the first CRITICAL GAP question above. "
            "Do not introduce yourself or explain what you're doing — just ask the question naturally."
        )
    else:
        gap_section = "### ALL KEY FIELDS ARE POPULATED\nThe profile is already rich. Dig deeper into opinions, stories, and worldview."
        start_instruction = (
            "The profile is well-filled. Start by asking about a specific opinion, story, or lesson "
            "that would make this persona feel more human and distinctive."
        )

    return f"""You are conducting a quick interview to build a rich AI persona for {profile.get('name', 'this person')}.

## WHAT WE ALREADY KNOW:
{profile_json}

## GAPS TO FILL:
{gap_section}

## HOW TO CONDUCT THE INTERVIEW:
- Ask ONE question at a time. Never bundle multiple questions.
- Be warm and conversational, not interrogative.
- After you receive an answer, briefly acknowledge it (1 sentence max), then ask the next gap question.
- If an answer is vague or very short, ask one follow-up before moving on.
- Work through HIGH gaps first, then MEDIUM gaps, then deepen with opinions/stories.
- After 12-15 exchanges (or when all gaps are covered), wrap up warmly and tell the user their persona is now much richer.
- Keep every question to 1-2 sentences max.

## START:
{start_instruction}
"""


def _sse(event_type: str, payload: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"


def _interview_error(code: str, message: str, *, recoverable: bool) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "recoverable": recoverable,
    }


# ── Streaming interview ────────────────────────────────────────────

@router.post("/v2/interview/{twin_id}/stream")
async def interview_stream(
    twin_id: str,
    request: InterviewTurnRequest,
    user: dict = Depends(require_tenant),
):
    """Stream an interview turn. Auto-saves Q&A to Pinecone knowledge."""
    verify_twin_ownership(twin_id, user)
    ensure_twin_active(twin_id)

    # Quota: charge twin owner for interview turns
    from modules.quota import check_and_increment_messages
    from modules.twin_namespace import get_twin_owner_id
    try:
        _owner_id = get_twin_owner_id(twin_id)
        if _owner_id:
            _allowed, _used, _cap = check_and_increment_messages(_owner_id)
            if not _allowed:
                raise HTTPException(
                    status_code=429,
                    detail=f"Monthly message limit of {_cap:,} reached. Upgrade at /dashboard/billing"
                )
    except HTTPException:
        raise
    except Exception as _qe:
        logger.warning("[interview] quota check failed — failing open: %r", _qe)

    profile = _load_twin_profile(twin_id)
    session_id = request.session_id or str(uuid.uuid4())

    # Auto-save the previous Q&A pair to Pinecone
    saved_qa = False
    if request.last_question and request.message:
        try:
            await upsert_faq(
                question=request.last_question,
                answer=request.message,
                twin_id=twin_id,
                origin=INTERVIEW_FAQ_ORIGIN,
            )
            invalidate_agent(twin_id)
            saved_qa = True
            logger.info(
                "[Interview] auto-saved Q&A for twin %s: q=%r",
                twin_id, request.last_question[:60],
            )
        except Exception as exc:
            logger.warning("[Interview] failed to save Q&A: %s", exc)

    async def generator():
        yield _sse("session", {"session_id": session_id, "saved_qa": saved_qa})

        try:
            # Build a fresh runner each turn so the gap-aware instruction stays current
            # and is baked into the Agent (not injected as a user Content part).
            # Injecting as a Content part would pollute session history with the full
            # prompt on every turn — the model would see stale gap lists from prior turns.
            interviewer_prompt = _build_interviewer_prompt(profile)
            runner = _build_runner(
                twin_id,
                {"_interview_instruction": interviewer_prompt},
                surface_class="interview",
            )

            # Use interview-specific session
            interview_user_id = f"interview:{user['user_id']}"
            session_svc = _get_session_service()
            session = await session_svc.get_session(
                app_name=APP_NAME, user_id=interview_user_id, session_id=session_id
            )
            if not session:
                session = await session_svc.create_session(
                    app_name=APP_NAME, user_id=interview_user_id, session_id=session_id
                )

            content = types.Content(
                role="user",
                parts=[types.Part(text=request.message)],
            )

            collected_text: list[str] = []
            async with asyncio.timeout(INTERVIEW_TIMEOUT_SECONDS):
                async for event in runner.run_async(
                    user_id=interview_user_id,
                    session_id=session.id,
                    new_message=content,
                ):
                    if event.content and event.content.parts:
                        for part in event.content.parts:
                            if part.text:
                                collected_text.append(part.text)
                                yield _sse("message", {"text": part.text})

            if not collected_text:
                yield _sse(
                    "error",
                    _interview_error(
                        "empty_response",
                        "The interview model returned no question.",
                        recoverable=True,
                    ),
                )

        except asyncio.TimeoutError:
            logger.warning("Interview stream timed out for twin %s", twin_id)
            yield _sse(
                "error",
                _interview_error(
                    "timeout",
                    "The interview request timed out.",
                    recoverable=True,
                ),
            )
        except Exception:
            logger.exception("Interview stream error")
            yield _sse(
                "error",
                _interview_error(
                    "stream_error",
                    "An error occurred during the interview.",
                    recoverable=True,
                ),
            )

        yield _sse("done", {"done": True})

    return StreamingResponse(generator(), media_type="text/event-stream")
