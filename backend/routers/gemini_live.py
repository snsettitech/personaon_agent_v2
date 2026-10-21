"""Gemini Live function-calling endpoints for the Recall Output Media page."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import google.genai as genai
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from adk_core.services.vector_store import search as vector_search
from modules.observability import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gemini-live"])

_control_subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}


# ---------------------------------------------------------------------------
# Token signing (HMAC-SHA256, short-lived)
# ---------------------------------------------------------------------------

_TOKEN_TTL_SECONDS = int(os.getenv("GEMINI_LIVE_TOKEN_TTL", "1800"))  # 30 min default
_TOKEN_SECRET = os.getenv("GEMINI_LIVE_TOKEN_SECRET") or os.getenv("CRON_SECRET", "")


def _sign_meeting_token(twin_id: str, meeting_id: str, ttl_seconds: int | None = None) -> str:
    """Sign a short-lived token for a specific twin+meeting pairing."""
    if not _TOKEN_SECRET:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_LIVE_TOKEN_SECRET not configured",
        )
    ttl = ttl_seconds or _TOKEN_TTL_SECONDS
    exp = int(time.time()) + ttl
    payload = f"{twin_id}:{meeting_id}:{exp}"
    sig = hmac.new(
        _TOKEN_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}:{sig}"


def _verify_meeting_token(token: str, expected_twin_id: str) -> str:
    """Verify a meeting token. Returns meeting_id if valid, raises 401 otherwise."""
    if not token:
        raise HTTPException(status_code=401, detail="Missing api_key_token")
    if not _TOKEN_SECRET:
        raise HTTPException(status_code=500, detail="GEMINI_LIVE_TOKEN_SECRET not configured")

    parts = token.split(":")
    if len(parts) != 4:
        raise HTTPException(status_code=401, detail="Malformed token")

    twin_id, meeting_id, exp_str, sig = parts
    if twin_id != expected_twin_id:
        raise HTTPException(status_code=401, detail="Token twin mismatch")

    try:
        exp = int(exp_str)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Malformed token") from exc
    if time.time() > exp:
        raise HTTPException(status_code=401, detail="Token expired")

    payload = f"{twin_id}:{meeting_id}:{exp_str}"
    expected_sig = hmac.new(
        _TOKEN_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        raise HTTPException(status_code=401, detail="Invalid token signature")

    return meeting_id


def issue_meeting_token(twin_id: str, meeting_id: str, ttl_seconds: int | None = None) -> str:
    """Public helper used by bot creation code to mint a token for the webpage."""
    return _sign_meeting_token(twin_id, meeting_id, ttl_seconds)


def publish_control_event(meeting_id: str, action: str) -> None:
    """Publish a control event to all Gemini Live SSE subscribers for a meeting."""
    event = {"type": "control", "action": action}
    _publish_meeting_event(meeting_id, event)


def publish_transcript_event(
    meeting_id: str,
    *,
    speaker: str,
    text: str,
    timestamp: str | None = None,
) -> None:
    """Publish a transcript event to Gemini Live SSE subscribers for a meeting."""
    event = {
        "type": "transcript",
        "speaker": speaker,
        "text": text,
        "timestamp": timestamp or "",
    }
    _publish_meeting_event(meeting_id, event)


def _publish_meeting_event(meeting_id: str, event: dict[str, Any]) -> None:
    """Fan out an event to all meeting-scoped subscribers."""
    queues = _control_subscribers.get(meeting_id, [])
    for queue in queues:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(
                "[GeminiLive] subscriber queue full meeting=%s event_type=%s",
                meeting_id,
                event.get("type"),
            )


def _get_gemini_api_key() -> str:
    gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
    if not gemini_api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")
    return gemini_api_key


def _get_live_model() -> str:
    # gemini-live-2.5-flash-preview supports text-turn → audio-response (our use case).
    # The native-audio-preview variant requires raw PCM audio input which the headless
    # browser can't provide via getUserMedia.
    return os.getenv(
        "GEMINI_LIVE_MODEL",
        "gemini-live-2.5-flash-preview",
    )


def _create_auth_token(*, expire_at: datetime, new_session_expire_at: datetime) -> str:
    client = genai.Client(
        api_key=_get_gemini_api_key(),
        http_options={"api_version": "v1alpha"},
    )
    token = client.auth_tokens.create(
        config={
            "uses": 1,
            "expire_time": expire_at,
            "new_session_expire_time": new_session_expire_at,
        }
    )
    token_name = getattr(token, "name", "") or ""
    if not token_name:
        raise RuntimeError("Gemini auth token response missing token name")
    return token_name


# ---------------------------------------------------------------------------
# Request/response schemas
# ---------------------------------------------------------------------------


class SearchKnowledgeRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class SearchKnowledgeResponse(BaseModel):
    status: str
    chunks: list[dict]


class LogToolCallRequest(BaseModel):
    tool_name: str
    args: dict = Field(default_factory=dict)
    result_preview: str = Field(default="", max_length=500)


class LogClientEventRequest(BaseModel):
    event: str = Field(..., min_length=1, max_length=120)
    level: str = Field(default="info", pattern="^(debug|info|warning|error)$")
    details: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/v2/gemini-live/{twin_id}/search_knowledge")
async def search_knowledge(
    twin_id: str,
    body: SearchKnowledgeRequest,
    api_key_token: str = Query(..., description="Meeting-scoped token"),
) -> SearchKnowledgeResponse:
    """KB search endpoint Gemini Live calls via function_call toolCall event."""
    meeting_id = _verify_meeting_token(api_key_token, twin_id)

    try:
        results = await vector_search(
            query=body.query,
            twin_id=twin_id,
            top_k=body.top_k,
        )
    except Exception as exc:
        logger.exception(
            "[GeminiLive] search_knowledge failed twin=%s meeting=%s: %s",
            twin_id,
            meeting_id,
            exc,
        )
        raise HTTPException(status_code=500, detail="Knowledge search failed") from exc

    chunks = [
        {
            "text": r.get("text", ""),
            "score": r.get("score", 0.0),
            "source_id": r.get("source_id", ""),
            "source_type": r.get("source_type", "persona"),
        }
        for r in results
    ]

    logger.info(
        "[GeminiLive] search_knowledge twin=%s meeting=%s query=%.80s hits=%d",
        twin_id,
        meeting_id,
        body.query,
        len(chunks),
    )

    return SearchKnowledgeResponse(status="ok", chunks=chunks)


@router.post("/v2/gemini-live/{twin_id}/log_tool_call")
async def log_tool_call(
    twin_id: str,
    body: LogToolCallRequest,
    api_key_token: str = Query(..., description="Meeting-scoped token"),
) -> dict[str, str]:
    """Observability endpoint for browser toolCall/toolResponse events."""
    meeting_id = _verify_meeting_token(api_key_token, twin_id)

    logger.info(
        "[GeminiLive] tool_call twin=%s meeting=%s tool=%s args=%s preview=%.80s",
        twin_id,
        meeting_id,
        body.tool_name,
        json.dumps(body.args)[:200],
        body.result_preview,
    )

    return {"status": "ok"}


@router.post("/v2/gemini-live/{twin_id}/log_client_event")
async def log_client_event(
    twin_id: str,
    body: LogClientEventRequest,
    api_key_token: str = Query(..., description="Meeting-scoped token"),
) -> dict[str, str]:
    """Observability endpoint for Gemini webpage client lifecycle events."""
    meeting_id = _verify_meeting_token(api_key_token, twin_id)
    details_preview = json.dumps(body.details, default=str)[:800]

    if body.level == "error":
        log_fn = logger.error
    elif body.level == "warning":
        log_fn = logger.warning
    elif body.level == "debug":
        log_fn = logger.debug
    else:
        log_fn = logger.info

    log_fn(
        "[GeminiLive] client_event twin=%s meeting=%s event=%s details=%s",
        twin_id,
        meeting_id,
        body.event,
        details_preview,
    )

    return {"status": "ok"}


@router.get("/v2/gemini-live/{twin_id}/ephemeral-token")
async def ephemeral_token(
    twin_id: str,
    api_key_token: str = Query(..., description="Meeting-scoped token"),
) -> dict[str, Any]:
    """Return a Gemini Live ephemeral token for the browser to open its WSS."""
    meeting_id = _verify_meeting_token(api_key_token, twin_id)

    ttl_seconds = min(_TOKEN_TTL_SECONDS, 1800)
    now = datetime.now(timezone.utc)
    expires_at_dt = now + timedelta(seconds=ttl_seconds)
    new_session_expires_at_dt = now + timedelta(seconds=60)

    try:
        access_token = _create_auth_token(
            expire_at=expires_at_dt,
            new_session_expire_at=new_session_expires_at_dt,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "[GeminiLive] failed to create auth token twin=%s meeting=%s: %s",
            twin_id,
            meeting_id,
            exc,
        )
        raise HTTPException(
            status_code=502,
            detail="Failed to create Gemini auth token",
        ) from exc

    logger.info(
        "[GeminiLive] issued ephemeral token twin=%s meeting=%s ttl=%ds",
        twin_id,
        meeting_id,
        ttl_seconds,
    )

    return {
        "status": "ok",
        "access_token": access_token,
        "expires_at": int(expires_at_dt.timestamp()),
        "model": _get_live_model(),
    }


@router.get("/v2/gemini-live/{twin_id}/persona-config")
async def persona_config(
    twin_id: str,
    api_key_token: str = Query(..., description="Meeting-scoped token"),
) -> dict[str, Any]:
    """Return the persona profile + system instruction for the webpage."""
    meeting_id = _verify_meeting_token(api_key_token, twin_id)

    sb = get_supabase_client()
    try:
        resp = (
            sb.table("twins")
            .select("id, name, settings")
            .eq("id", twin_id)
            .single()
            .execute()
        )
    except Exception as exc:
        logger.exception("[GeminiLive] persona-config load failed twin=%s: %s", twin_id, exc)
        raise HTTPException(status_code=500, detail="Persona load failed") from exc

    if not resp.data:
        raise HTTPException(status_code=404, detail="Twin not found")

    settings = resp.data.get("settings") or {}
    persona_profile = settings.get("persona_profile") or {}
    voice_name = settings.get("gemini_voice") or "Kore"
    twin_name = resp.data.get("name") or "the user"

    role = persona_profile.get("role") or persona_profile.get("headline", "")
    topics = (
        persona_profile.get("expertise_keywords")
        or persona_profile.get("topics")
        or []
    )
    topics_str = ", ".join(topics[:5]) if isinstance(topics, list) else str(topics)[:200]

    system_instruction = (
        f"You are {twin_name}'s AI assistant joining a live meeting. "
        f"{twin_name} is {role}. "
        f"Primary topics you can speak to: {topics_str}. "
        "Respond only when addressed by name or asked a direct question that "
        "matches your topics. Keep answers to 1-3 sentences. If a question is "
        f"outside your topics, say you'll let {twin_name} answer directly. "
        "Call search_knowledge(query) before answering if you need to check "
        f"{twin_name}'s notes. Never interrupt - wait for a pause."
    )

    logger.info(
        "[GeminiLive] persona-config twin=%s meeting=%s voice=%s",
        twin_id,
        meeting_id,
        voice_name,
    )

    return {
        "status": "ok",
        "twin_name": twin_name,
        "voice_name": voice_name,
        "system_instruction": system_instruction,
    }


@router.get("/v2/gemini-live/{twin_id}/{meeting_id}/control-channel")
async def control_channel(
    twin_id: str,
    meeting_id: str,
    api_key_token: str = Query(..., description="Meeting-scoped token"),
) -> StreamingResponse:
    """SSE stream carrying mute/unmute/leave controls to the Gemini webpage."""
    token_meeting_id = _verify_meeting_token(api_key_token, twin_id)
    if token_meeting_id != meeting_id:
        raise HTTPException(status_code=401, detail="Token meeting mismatch")

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=20)
    _control_subscribers.setdefault(meeting_id, []).append(queue)

    async def event_stream():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                    event_type = str(event.get("type") or "control")
                    yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            meeting_subscribers = _control_subscribers.get(meeting_id, [])
            with contextlib.suppress(ValueError):
                meeting_subscribers.remove(queue)
            if not meeting_subscribers:
                _control_subscribers.pop(meeting_id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
