"""Voice call routing for live persona calls.

Current Deepgram flow:
  Browser -> PersonaOn WebSocket -> Deepgram Voice Agent
  Deepgram -> PersonaOn OpenAI-compatible LLM endpoint -> chat_stream()
  Deepgram -> ElevenLabs raw TTS endpoint using the persona voice_id

Legacy ElevenLabs Conversational AI token endpoints remain for rollback.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
import asyncio
import base64
import hashlib
import hmac
from collections import defaultdict
from collections.abc import AsyncGenerator, AsyncIterator
from urllib.parse import quote
import httpx
import websockets
from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from adk_core.services.agent_service import chat_stream
from modules.auth_guard import require_tenant, verify_twin_ownership
from modules.observability import get_supabase_client
from modules.share_links import (
    _fetch_twin_row,
    is_publicly_accessible_twin_record,
    validate_share_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice-call"])


def _check_voice_allowed(twin_id: str) -> None:
    """Raise HTTP 402 if the twin owner's plan doesn't include voice."""
    from modules.twin_namespace import get_twin_owner_id
    from modules.quota import get_quota
    try:
        owner_id = get_twin_owner_id(twin_id)
        if owner_id:
            q = get_quota(owner_id)
            if q.get("voice_cap", 0) == 0:
                raise HTTPException(
                    status_code=402,
                    detail="Voice calls require Pro plan. Upgrade at /dashboard/billing",
                )
    except HTTPException:
        raise
    except Exception as exc:
        # Fail open — don't block voice if quota check errors
        logger.warning(
            "[VoiceCall] voice quota check failed twin=%s error=%r — failing open", twin_id, exc
        )

# Marker pattern written into the ElevenLabs agent system prompt override
# so our endpoint knows which twin to query.
_TWIN_ID_RE = re.compile(r'\[TWIN_ID:([0-9a-f\-]{36})\]', re.IGNORECASE)

# Per-IP rate limit for the public call-token endpoint (1 token/minute/IP)
_public_rate: dict[str, list[float]] = defaultdict(list)
_PUBLIC_RATE_LIMIT = 5      # max 5 signed URLs per window per IP
_PUBLIC_RATE_WINDOW = 300   # 5-minute window


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class _OpenAIMessage(BaseModel):
    role: str
    content: str


class _OpenAIChatRequest(BaseModel):
    model: str = "personaon"
    messages: list[_OpenAIMessage]
    stream: bool = True
    max_tokens: int | None = None
    temperature: float | None = None
    # ElevenLabs passes custom_llm_extra_body from the client as elevenlabs_extra_body.
    # We use this to pass twin_id cleanly without injecting it into the system prompt.
    elevenlabs_extra_body: dict | None = None


class CallTokenResponse(BaseModel):
    signed_url: str
    session_id: str
    twin_id: str
    voice_id: str | None = None


class CallSessionResponse(BaseModel):
    provider: str
    session_id: str
    twin_id: str
    websocket_url: str
    voice_available: bool = True
    audio_input: dict
    audio_output: dict
    expires_at: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VOICE_MODE_OVERRIDE = (
    "This is a live spoken call. Answer in the persona's natural voice, "
    "using short conversational sentences. Do not use markdown, bullets, "
    "tables, citations, source labels, or bracketed metadata. Keep most "
    "answers to 1-3 sentences unless the caller asks for detail."
)

_VOICE_LLM_SENTINEL = "[CITATIONS_JSON:"
_CALL_SESSION_TTL_SECONDS = 10 * 60


def _clean_env_secret(value: str | None) -> str:
    return (value or "").strip()


def _get_api_key() -> str:
    key = _clean_env_secret(os.getenv("ELEVENLABS_API_KEY"))
    if not key:
        raise HTTPException(status_code=503, detail="ElevenLabs not configured.")
    return key


def _get_deepgram_api_key() -> str:
    key = _clean_env_secret(os.getenv("DEEPGRAM_API_KEY"))
    if not key:
        raise HTTPException(status_code=503, detail="Deepgram not configured.")
    return key


def _get_voice_call_provider() -> str:
    return os.getenv("VOICE_CALL_PROVIDER", "deepgram").strip().lower() or "deepgram"


def _get_voice_llm_secret() -> str:
    return _clean_env_secret(os.getenv("VOICE_LLM_WEBHOOK_SECRET")) or _clean_env_secret(
        os.getenv("ELEVENLABS_WEBHOOK_SECRET")
    )


def _get_voice_session_secret() -> str:
    secret = _clean_env_secret(os.getenv("VOICE_CALL_SESSION_SECRET")) or _clean_env_secret(
        os.getenv("ELEVENLABS_WEBHOOK_SECRET")
    )
    if not secret:
        raise HTTPException(status_code=503, detail="Voice call session signing is not configured.")
    return secret


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _sign_call_session_token(
    *,
    session_id: str,
    twin_id: str,
    is_public: bool,
    expires_at: int,
) -> str:
    payload = {
        "session_id": session_id,
        "twin_id": twin_id,
        "is_public": is_public,
        "expires_at": expires_at,
    }
    payload_raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_part = _b64url_encode(payload_raw)
    signature = hmac.new(
        _get_voice_session_secret().encode("utf-8"),
        payload_part.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{payload_part}.{_b64url_encode(signature)}"


def _verify_call_session_token(token: str) -> dict:
    try:
        payload_part, signature_part = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid voice call session.") from exc

    expected = hmac.new(
        _get_voice_session_secret().encode("utf-8"),
        payload_part.encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        supplied = _b64url_decode(signature_part)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid voice call session.") from exc
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="Invalid voice call session.")

    try:
        payload = json.loads(_b64url_decode(payload_part))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid voice call session.") from exc

    if int(payload.get("expires_at") or 0) < int(time.time()):
        raise HTTPException(status_code=401, detail="Voice call session expired.")
    return payload


def _backend_url_from_request(request: Request | WebSocket | None = None) -> str:
    configured = os.getenv("BACKEND_API_URL") or os.getenv("PUBLIC_BACKEND_URL")
    if configured:
        return configured.rstrip("/")

    if request is None:
        raise HTTPException(status_code=503, detail="Backend public URL is not configured.")

    scheme = _public_http_scheme_from_request(request)
    host = _first_header_value(request, "x-forwarded-host") or _first_header_value(request, "host")
    if not host:
        raise HTTPException(status_code=503, detail="Backend public URL is not configured.")
    return f"{scheme}://{host}".rstrip("/")


def _websocket_url_from_request(request: Request, session_id: str, token: str) -> str:
    configured = os.getenv("VOICE_CALL_WS_BASE_URL")
    if configured:
        base = _normalize_websocket_base_url(configured)
        return f"{base}/ws/voice-call/{session_id}?token={quote(token)}"

    scheme = "wss" if _public_http_scheme_from_request(request) == "https" else "ws"
    host = _first_header_value(request, "x-forwarded-host") or _first_header_value(request, "host")
    if not host:
        raise HTTPException(status_code=503, detail="Voice call WebSocket URL is not configured.")
    return f"{scheme}://{host}/ws/voice-call/{session_id}?token={quote(token)}"


def _first_header_value(request: Request | WebSocket, header_name: str) -> str:
    value = request.headers.get(header_name, "")
    return value.split(",", 1)[0].strip()


def _public_http_scheme_from_request(request: Request | WebSocket) -> str:
    forwarded_proto = (
        _first_header_value(request, "x-forwarded-proto")
        or _first_header_value(request, "x-forwarded-protocol")
        or _first_header_value(request, "x-url-scheme")
    ).lower()
    if forwarded_proto in {"http", "https"}:
        return forwarded_proto
    if request.headers.get("front-end-https", "").lower() in {"on", "true", "1"}:
        return "https"
    if isinstance(request, WebSocket):
        return "https" if request.url.scheme in {"wss", "https"} else "http"
    return "https" if request.url.scheme == "https" else "http"


def _normalize_websocket_base_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.startswith("https://"):
        return f"wss://{base.removeprefix('https://')}"
    if base.startswith("http://"):
        return f"ws://{base.removeprefix('http://')}"
    return base


def _build_deepgram_settings(*, twin_id: str, voice_id: str, backend_url: str) -> dict:
    elevenlabs_key = _get_api_key()
    llm_secret = _get_voice_llm_secret()
    listen_model = os.getenv("DEEPGRAM_VOICE_LISTEN_MODEL", "flux-general-en")
    listen_version = os.getenv("DEEPGRAM_VOICE_LISTEN_VERSION", "v2")
    tts_model_id = os.getenv("ELEVENLABS_TTS_MODEL_ID", "eleven_flash_v2_5")

    llm_url = (
        f"{backend_url.rstrip('/')}/v1/voice/llm/chat/completions"
        f"?twin_id={quote(twin_id)}"
    )
    tts_url = f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/multi-stream-input"

    return {
        "type": "Settings",
        "tags": ["personaon", "voice-call", twin_id],
        "audio": {
            "input": {"encoding": "linear16", "sample_rate": 16000},
            "output": {"encoding": "linear16", "sample_rate": 24000, "container": "none"},
        },
        "agent": {
            "listen": {
                "provider": {
                    "type": "deepgram",
                    "model": listen_model,
                    "version": listen_version,
                },
            },
            "think": {
                "provider": {
                    "type": "open_ai",
                    "model": os.getenv("VOICE_CALL_LLM_MODEL", "personaon"),
                    "temperature": float(os.getenv("VOICE_CALL_LLM_TEMPERATURE", "0.4")),
                },
                "endpoint": {
                    "url": llm_url,
                    "headers": {"X-PersonaOn-Token": llm_secret},
                },
                "prompt": _VOICE_MODE_OVERRIDE,
                "context_length": "max",
            },
            "speak": {
                "provider": {
                    "type": "eleven_labs",
                    "model_id": tts_model_id,
                    "language_code": os.getenv("ELEVENLABS_TTS_LANGUAGE_CODE", "en-US"),
                },
                "endpoint": {
                    "url": tts_url,
                    "headers": {"xi-api-key": elevenlabs_key},
                },
            },
        },
    }


async def _iter_visible_voice_chunks(
    text_chunks: AsyncIterator[str],
) -> AsyncGenerator[str, None]:
    """Yield streamed text until the citation sentinel starts, even across chunks."""
    pending = ""
    holdback = len(_VOICE_LLM_SENTINEL) + 2
    async for chunk in text_chunks:
        if not chunk:
            continue
        pending += chunk
        sentinel_idx = pending.find(_VOICE_LLM_SENTINEL)
        if sentinel_idx >= 0:
            visible = pending[:sentinel_idx]
            if visible.endswith("\n"):
                visible = visible[:-1]
            if visible:
                yield visible
            return
        if len(pending) > holdback:
            emit = pending[:-holdback]
            pending = pending[-holdback:]
            if emit:
                yield emit

    sentinel_idx = pending.find(_VOICE_LLM_SENTINEL)
    if sentinel_idx >= 0:
        pending = pending[:sentinel_idx].rstrip()
    if pending:
        yield pending


def _load_twin_settings(twin_id: str) -> dict:
    """Load twin settings from Supabase — single read for voice_id + agent_id.
    Returns the settings dict (may be empty if twin not found or on error).
    """
    sb = get_supabase_client()
    try:
        resp = (
            sb.table("twins")
            .select("settings")
            .eq("id", twin_id)
            .single()
            .execute()
        )
    except Exception:
        return {}
    if not resp.data:
        return {}
    return resp.data.get("settings") or {}


def _get_twin_agent_id(twin_id: str, settings: dict | None = None) -> str:
    """Return the ElevenLabs agent_id for this twin.

    Priority:
    1. twins.settings.elevenlabs_agent_id (per-persona agent with IVC voice baked in)
    2. ELEVENLABS_AGENT_ID env var (shared fallback for twins without voice clones)

    Raises 503 if neither is configured.
    """
    if settings is None:
        settings = _load_twin_settings(twin_id)
    agent_id = settings.get("elevenlabs_agent_id")
    if agent_id:
        return agent_id
    shared = os.getenv("ELEVENLABS_AGENT_ID")
    if shared:
        return shared
    raise HTTPException(status_code=503, detail="No ElevenLabs agent configured for this twin.")


def _get_webhook_secret() -> str:
    return os.getenv("ELEVENLABS_WEBHOOK_SECRET", "")


def _check_public_rate_limit(ip: str) -> bool:
    now = time.time()
    window_start = now - _PUBLIC_RATE_WINDOW
    _public_rate[ip] = [t for t in _public_rate[ip] if t > window_start]
    if len(_public_rate[ip]) >= _PUBLIC_RATE_LIMIT:
        return False
    _public_rate[ip].append(now)
    return True


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _extract_twin_id(messages: list[_OpenAIMessage]) -> str | None:
    """Extract twin_id from [TWIN_ID:uuid] marker in any system message."""
    for msg in messages:
        if msg.role == "system":
            m = _TWIN_ID_RE.search(msg.content)
            if m:
                return m.group(1)
    return None


def _load_twin_context(twin_id: str) -> tuple[dict, list[dict]]:
    """Load profile and active actions for a twin (mirrors chat.py)."""
    sb = get_supabase_client()
    try:
        resp = (
            sb.table("twins")
            .select("id, name, status, settings")
            .eq("id", twin_id)
            .single()
            .execute()
        )
    except Exception as exc:
        logger.exception("[VoiceCall] failed to load twin %s from Supabase: %s", twin_id, exc)
        raise HTTPException(status_code=503, detail="Twin context temporarily unavailable")
    if not resp.data:
        raise HTTPException(status_code=404, detail="Twin not found")

    twin = resp.data
    settings = twin.get("settings") or {}
    profile = settings.get("persona_profile") or {}
    if isinstance(profile, str):
        try:
            profile = json.loads(profile)
        except (ValueError, TypeError):
            profile = {}
    profile.setdefault("name", twin.get("name", ""))

    public_profile = settings.get("public_profile") or {}
    if isinstance(public_profile, dict):
        career_context = public_profile.get("career_context", "")
        if career_context and isinstance(career_context, str):
            profile["career_context"] = career_context

    all_actions = settings.get("actions") or []
    active_actions = [a for a in all_actions if a.get("is_active", True)]
    return profile, active_actions



async def _get_signed_url(
    *,
    agent_id: str,
    api_key: str,
) -> str:
    """Call ElevenLabs API to get a signed conversation URL for an agent.

    Overrides (voice_id, twin_id) are sent client-side via the WebSocket
    conversation_initiation_client_data message — not in the signed URL request.
    Correct endpoint: GET /v1/convai/conversation/get_signed_url?agent_id=...
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://api.elevenlabs.io/v1/convai/conversation/get_signed_url",
            headers={"xi-api-key": api_key},
            params={"agent_id": agent_id},
        )
        if resp.status_code != 200:
            logger.error(
                "[VoiceCall] ElevenLabs signed URL error status=%d body=%s",
                resp.status_code, resp.text[:300],
            )
            raise HTTPException(status_code=502, detail="Failed to create voice call session.")
        data = resp.json()

    signed_url = data.get("signed_url")
    if not signed_url:
        raise HTTPException(status_code=502, detail="ElevenLabs returned no signed URL.")
    return signed_url


async def _verify_voice_exists(voice_id: str, api_key: str) -> bool:
    """Return True if the voice still exists on ElevenLabs, False if it was deleted (404).

    - 200 → True (voice exists)
    - 404 → False (voice deleted — clear stale id and block call)
    - 401/403 → HTTPException(503) — API key problem, not a "voice gone" scenario
    - 5xx / timeout / network error → True (fail-open; don't gate calls on ElevenLabs instability)
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"https://api.elevenlabs.io/v1/voices/{voice_id}",
                headers={"xi-api-key": api_key},
            )
        if resp.status_code == 200:
            return True
        if resp.status_code == 404:
            return False
        if resp.status_code in (401, 403):
            logger.error(
                "[VoiceCall] ElevenLabs API key rejected during voice check (status=%d)",
                resp.status_code,
            )
            raise HTTPException(status_code=503, detail="Voice service authentication failed.")
        # 5xx or unexpected — fail open
        logger.warning(
            "[VoiceCall] unexpected status %d checking voice %s (assuming valid)",
            resp.status_code, voice_id,
        )
        return True
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("[VoiceCall] could not verify voice %s (assuming valid): %s", voice_id, exc)
        return True


def _clear_stale_voice_id(twin_id: str, stale_voice_id: str) -> None:
    """Remove voice_id + voice_name from twin settings after confirming voice is gone.

    Guards against a TOCTOU race: only clears if the stored voice_id still matches
    the stale one we verified as deleted. If the owner already re-cloned, the new
    voice_id is preserved.

    Self-healing: next page visit shows the re-clone prompt instead of a broken
    Call button. Non-fatal — logs a warning on failure, never raises.
    """
    try:
        sb = get_supabase_client()
        resp = (
            sb.table("twins")
            .select("settings, tenant_id")
            .eq("id", twin_id)
            .single()
            .execute()
        )
        if not resp.data:
            return
        stored_tenant_id = resp.data.get("tenant_id", "")
        settings = dict(resp.data.get("settings") or {})
        # TOCTOU guard: only clear if voice_id hasn't been replaced by a fresh clone
        if settings.get("voice_id") != stale_voice_id:
            logger.info(
                "[VoiceCall] voice_id already updated for twin %s — skipping stale clear",
                twin_id,
            )
            return
        settings.pop("voice_id", None)
        settings.pop("voice_name", None)
        (
            sb.table("twins")
            .update({"settings": settings})
            .eq("id", twin_id)
            .eq("tenant_id", stored_tenant_id)
            .execute()
        )
        logger.info("[VoiceCall] cleared stale voice_id from twin %s settings", twin_id)
    except Exception as exc:
        logger.warning("[VoiceCall] failed to clear stale voice_id for twin %s: %s", twin_id, exc)


# ---------------------------------------------------------------------------
# POST /v1/chat/completions  — ElevenLabs calls this as the custom LLM
# ---------------------------------------------------------------------------

@router.post("/v1/chat/completions")
async def openai_chat_completions(
    request: Request,
    body: _OpenAIChatRequest,
) -> StreamingResponse:
    """OpenAI-compatible chat endpoint called by ElevenLabs Conversational AI.

    Authentication: X-PersonaOn-Token header must match ELEVENLABS_WEBHOOK_SECRET.
    Twin identification: [TWIN_ID:uuid] marker in the system message.
    """
    # -- Auth ----------------------------------------------------------------
    secret = _get_webhook_secret()
    if secret:
        token = request.headers.get("X-PersonaOn-Token", "")
        if token != secret:
            logger.warning("[VoiceCall] invalid webhook token from %s", _get_client_ip(request))
            raise HTTPException(status_code=401, detail="Unauthorized")

    # -- Extract twin_id -----------------------------------------------------
    # Primary: from elevenlabs_extra_body (set via customLlmExtraBody in startSession).
    # Fallback: legacy [TWIN_ID:uuid] marker in system prompt (kept for compatibility).
    twin_id: str | None = None
    if body.elevenlabs_extra_body:
        twin_id = body.elevenlabs_extra_body.get("twin_id")
    if not twin_id:
        twin_id = _extract_twin_id(body.messages)
    if not twin_id:
        logger.warning("[VoiceCall] no twin_id in request (neither elevenlabs_extra_body nor system prompt)")
        raise HTTPException(status_code=400, detail="Missing twin_id in request.")

    # -- Extract last user message -------------------------------------------
    user_message = ""
    for msg in reversed(body.messages):
        if msg.role == "user":
            user_message = msg.content.strip()
            break
    if not user_message:
        raise HTTPException(status_code=400, detail="No user message in request.")

    # -- Load twin context ---------------------------------------------------
    profile, actions = _load_twin_context(twin_id)

    # Use conversation_id from ElevenLabs header if provided (for ADK session continuity)
    conv_id = (
        request.headers.get("X-Conversation-Id")
        or request.headers.get("x-elevenlabs-conversation-id")
        or str(uuid.uuid4())
    )
    session_id = f"voice:{conv_id}"
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    # -- Stream ADK response as OpenAI SSE -----------------------------------
    async def generator():
        # Accumulate the full response before yielding a single content delta.
        # Per-chunk sentinel stripping is unsafe: [CITATIONS_JSON:...] can straddle
        # two consecutive chunks, causing ElevenLabs TTS to speak the raw sentinel text.
        # ElevenLabs buffers before speaking regardless, so one chunk vs many has no
        # perceptible latency difference from the caller's perspective.
        chunks: list[str] = []
        try:
            async for chunk in chat_stream(
                twin_id=twin_id,
                profile_dict=profile,
                user_id="voice_caller",
                session_id=session_id,
                message=user_message,
                surface="visitor",
                tenant_id=None,
                mode_override=None,
                actions=actions,
            ):
                chunks.append(chunk)

        except Exception:
            logger.exception("[VoiceCall] chat_stream error twin=%s", twin_id)
            error_delta = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": ""}, "index": 0, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(error_delta)}\n\n"
            return

        full_text = re.sub(
            r'\n?\[CITATIONS_JSON:.+\]$', '', "".join(chunks), flags=re.DOTALL,
        ).rstrip()

        if full_text:
            delta = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": full_text}, "index": 0, "finish_reason": None}],
            }
            yield f"data: {json.dumps(delta)}\n\n"

        stop_delta = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(stop_delta)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/v1/voice/llm/chat/completions")
async def voice_llm_chat_completions(
    request: Request,
    body: _OpenAIChatRequest,
    twin_id: str | None = Query(default=None),
) -> StreamingResponse:
    """OpenAI-compatible streaming endpoint used by Deepgram Voice Agent."""
    secret = _get_voice_llm_secret()
    if secret:
        token = request.headers.get("X-PersonaOn-Token", "")
        if token != secret:
            logger.warning("[VoiceCall] invalid voice LLM token from %s", _get_client_ip(request))
            raise HTTPException(status_code=401, detail="Unauthorized")

    if not twin_id and body.elevenlabs_extra_body:
        twin_id = body.elevenlabs_extra_body.get("twin_id")
    if not twin_id:
        twin_id = _extract_twin_id(body.messages)
    if not twin_id:
        raise HTTPException(status_code=400, detail="Missing twin_id in request.")

    user_message = ""
    for msg in reversed(body.messages):
        if msg.role == "user":
            user_message = msg.content.strip()
            break
    if not user_message:
        raise HTTPException(status_code=400, detail="No user message in request.")

    profile, actions = _load_twin_context(twin_id)
    conv_id = (
        request.headers.get("X-Conversation-Id")
        or request.headers.get("x-deepgram-conversation-id")
        or str(uuid.uuid4())
    )
    session_id = f"voice:{conv_id}"
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    async def generator() -> AsyncGenerator[str, None]:
        try:
            raw_chunks = chat_stream(
                twin_id=twin_id,
                profile_dict=profile,
                user_id="voice_caller",
                session_id=session_id,
                message=user_message,
                surface="visitor",
                tenant_id=None,
                mode_override=_VOICE_MODE_OVERRIDE,
                actions=actions,
            )
            async for chunk in _iter_visible_voice_chunks(raw_chunks):
                if not chunk:
                    continue
                delta = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "choices": [{"delta": {"content": chunk}, "index": 0, "finish_reason": None}],
                }
                yield f"data: {json.dumps(delta)}\n\n"
        except Exception:
            logger.exception("[VoiceCall] Deepgram voice LLM error twin=%s", twin_id)
            error_delta = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": ""}, "index": 0, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(error_delta)}\n\n"
            yield "data: [DONE]\n\n"
            return

        stop_delta = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(stop_delta)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _issue_deepgram_call_session(
    *,
    twin_id: str,
    request: Request,
    is_public: bool,
    settings: dict,
) -> CallSessionResponse:
    if _get_voice_call_provider() != "deepgram":
        raise HTTPException(status_code=503, detail="Deepgram live calls are not enabled.")

    _get_deepgram_api_key()
    elevenlabs_key = _get_api_key()
    voice_id = settings.get("voice_id")
    if not voice_id:
        detail = (
            "This persona does not have a voice configured."
            if is_public
            else "No voice cloned for this persona. Clone your voice first."
        )
        raise HTTPException(status_code=400, detail=detail)

    if not await _verify_voice_exists(voice_id, elevenlabs_key):
        _clear_stale_voice_id(twin_id, voice_id)
        detail = (
            "Voice no longer available -- please contact the persona owner."
            if is_public
            else "Voice no longer available -- please re-clone your voice."
        )
        raise HTTPException(status_code=400, detail=detail)

    session_id = str(uuid.uuid4())
    expires_at = int(time.time()) + _CALL_SESSION_TTL_SECONDS
    token = _sign_call_session_token(
        session_id=session_id,
        twin_id=twin_id,
        is_public=is_public,
        expires_at=expires_at,
    )
    return CallSessionResponse(
        provider="deepgram",
        session_id=session_id,
        twin_id=twin_id,
        websocket_url=_websocket_url_from_request(request, session_id, token),
        voice_available=True,
        audio_input={"encoding": "linear16", "sample_rate": 16000},
        audio_output={"encoding": "linear16", "sample_rate": 24000},
        expires_at=expires_at,
    )


@router.get("/v2/voice/{twin_id}/call-session", response_model=CallSessionResponse)
async def get_call_session(
    twin_id: str,
    request: Request,
    user: dict = Depends(require_tenant),
) -> CallSessionResponse:
    """Create a Deepgram-backed live call session for an authenticated owner."""
    verify_twin_ownership(twin_id, user)
    _check_voice_allowed(twin_id)
    settings = _load_twin_settings(twin_id)
    return await _issue_deepgram_call_session(
        twin_id=twin_id,
        request=request,
        is_public=False,
        settings=settings,
    )


@router.get("/v2/voice/{twin_id}/call-session/public", response_model=CallSessionResponse)
async def get_call_session_public(
    twin_id: str,
    request: Request,
    share_token: str | None = Query(default=None),
) -> CallSessionResponse:
    """Create a Deepgram-backed live call session for a public visitor."""
    _check_voice_allowed(twin_id)
    ip = _get_client_ip(request)
    if not _check_public_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many call requests. Try again in a moment.")

    twin = _fetch_twin_row(twin_id)
    if not twin:
        raise HTTPException(status_code=404, detail="Twin not found.")

    is_accessible = is_publicly_accessible_twin_record(twin)
    if not is_accessible and (not share_token or not validate_share_token(share_token, twin_id)):
        raise HTTPException(status_code=403, detail="This persona is not publicly accessible.")

    return await _issue_deepgram_call_session(
        twin_id=twin_id,
        request=request,
        is_public=True,
        settings=twin.get("settings") or {},
    )


async def _await_deepgram_event(deepgram_ws, expected_type: str, timeout_seconds: float = 10.0) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        raw = await asyncio.wait_for(deepgram_ws.recv(), timeout=max(0.1, deadline - time.time()))
        if isinstance(raw, bytes):
            continue
        try:
            msg = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        msg_type = msg.get("type")
        if msg_type == expected_type:
            return msg
        if msg_type == "Error":
            raise RuntimeError(msg.get("description") or "Deepgram Voice Agent error")
    raise TimeoutError(f"Timed out waiting for Deepgram {expected_type}")


async def _meter_voice_call(twin_id: str, started_at: float) -> None:
    try:
        from modules.twin_namespace import get_twin_owner_id
        from modules.quota import check_and_increment_voice

        owner_id = get_twin_owner_id(twin_id)
        if not owner_id:
            return
        seconds = max(1, int(time.time() - started_at))
        check_and_increment_voice(owner_id, seconds)
    except Exception as exc:
        logger.warning("[VoiceCall] failed to meter voice call twin=%s error=%r", twin_id, exc)


@router.websocket("/ws/voice-call/{session_id}")
async def voice_call_ws(websocket: WebSocket, session_id: str) -> None:
    """Browser <-> PersonaOn <-> Deepgram Voice Agent audio bridge."""
    token = websocket.query_params.get("token", "")
    try:
        payload = _verify_call_session_token(token)
    except HTTPException:
        await websocket.close(code=4001, reason="Invalid voice call session")
        return

    if payload.get("session_id") != session_id:
        await websocket.close(code=4001, reason="Invalid voice call session")
        return

    twin_id = str(payload.get("twin_id") or "")
    started_at = time.time()
    await websocket.accept()

    try:
        settings = _load_twin_settings(twin_id)
        voice_id = settings.get("voice_id")
        if not voice_id:
            await websocket.send_json({"type": "error", "message": "This persona does not have a voice configured."})
            await websocket.close(code=4000, reason="No voice configured")
            return

        deepgram_key = _get_deepgram_api_key()
        deepgram_settings = _build_deepgram_settings(
            twin_id=twin_id,
            voice_id=voice_id,
            backend_url=_backend_url_from_request(websocket),
        )
        deepgram_url = os.getenv("DEEPGRAM_AGENT_URL", "wss://agent.deepgram.com/v1/agent/converse")
        await websocket.send_json({"type": "status", "status": "connecting"})

        async with websockets.connect(
            deepgram_url,
            additional_headers={"Authorization": f"Token {deepgram_key}"},
        ) as deepgram_ws:
            await _await_deepgram_event(deepgram_ws, "Welcome")
            await deepgram_ws.send(json.dumps(deepgram_settings))
            await _await_deepgram_event(deepgram_ws, "SettingsApplied")
            await websocket.send_json({"type": "status", "status": "listening"})

            stop_event = asyncio.Event()

            async def _frontend_to_deepgram() -> None:
                while not stop_event.is_set():
                    msg = await websocket.receive()
                    if msg.get("type") == "websocket.disconnect":
                        stop_event.set()
                        break
                    audio_bytes = msg.get("bytes")
                    if audio_bytes:
                        await deepgram_ws.send(audio_bytes)
                        continue
                    text = msg.get("text")
                    if not text:
                        continue
                    try:
                        data = json.loads(text)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if data.get("type") == "end":
                        stop_event.set()
                        break

            async def _deepgram_to_frontend() -> None:
                async for raw in deepgram_ws:
                    if stop_event.is_set():
                        break
                    if isinstance(raw, bytes):
                        await websocket.send_bytes(raw)
                        continue
                    try:
                        data = json.loads(raw)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    msg_type = data.get("type")
                    if msg_type == "ConversationText":
                        await websocket.send_json({
                            "type": "transcript",
                            "role": data.get("role"),
                            "text": data.get("content", ""),
                        })
                    elif msg_type == "UserStartedSpeaking":
                        await websocket.send_json({"type": "user_started_speaking"})
                    elif msg_type == "AgentThinking":
                        await websocket.send_json({"type": "status", "status": "thinking"})
                    elif msg_type == "AgentStartedSpeaking":
                        await websocket.send_json({
                            "type": "status",
                            "status": "speaking",
                            "latency": {
                                "total": data.get("total_latency"),
                                "tts": data.get("tts_latency"),
                                "ttt": data.get("ttt_latency"),
                            },
                        })
                    elif msg_type == "AgentAudioDone":
                        await websocket.send_json({"type": "audio_done"})
                        await websocket.send_json({"type": "status", "status": "listening"})
                    elif msg_type == "Warning":
                        await websocket.send_json({"type": "warning", "message": data.get("description", "")})
                    elif msg_type == "Error":
                        await websocket.send_json({"type": "error", "message": data.get("description", "Voice call failed.")})
                        stop_event.set()
                        break

            async def _keepalive() -> None:
                while not stop_event.is_set():
                    await asyncio.sleep(5)
                    await deepgram_ws.send(json.dumps({"type": "KeepAlive"}))

            tasks = [
                asyncio.create_task(_frontend_to_deepgram()),
                asyncio.create_task(_deepgram_to_frontend()),
                asyncio.create_task(_keepalive()),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                task.result()

    except WebSocketDisconnect:
        logger.info("[VoiceCall] browser websocket disconnected session=%s twin=%s", session_id, twin_id)
    except Exception as exc:
        logger.exception("[VoiceCall] websocket bridge failed session=%s twin=%s: %s", session_id, twin_id, exc)
        try:
            await websocket.send_json({"type": "error", "message": "Voice call failed. Please try again."})
        except Exception:
            pass
    finally:
        await _meter_voice_call(twin_id, started_at)


# ---------------------------------------------------------------------------
# GET /v2/voice/{twin_id}/call-token  — authenticated owner
# ---------------------------------------------------------------------------

@router.get("/v2/voice/{twin_id}/call-token", response_model=CallTokenResponse)
async def get_call_token(
    twin_id: str,
    user: dict = Depends(require_tenant),
) -> CallTokenResponse:
    """Generate a signed ElevenLabs conversation URL for an authenticated owner.

    Returns a short-lived signed URL the frontend passes to useConversation().
    """
    verify_twin_ownership(twin_id, user)
    _check_voice_allowed(twin_id)

    api_key = _get_api_key()
    settings = _load_twin_settings(twin_id)
    voice_id = settings.get("voice_id")
    agent_id = _get_twin_agent_id(twin_id, settings=settings)

    if not voice_id:
        raise HTTPException(
            status_code=400,
            detail="No voice cloned for this persona. Clone your voice first.",
        )

    # Fix: verify the voice still exists on ElevenLabs before issuing a token.
    # voice_id in settings goes stale if the voice was deleted (plan change, manual deletion).
    # A confirmed 404 self-heals by clearing the stale voice_id so the UI shows re-clone prompt.
    if not await _verify_voice_exists(voice_id, api_key):
        _clear_stale_voice_id(twin_id, voice_id)
        raise HTTPException(
            status_code=400,
            detail="Voice no longer available — please re-clone your voice.",
        )

    signed_url = await _get_signed_url(agent_id=agent_id, api_key=api_key)

    logger.info("[VoiceCall] issued call token twin=%s", twin_id)
    return CallTokenResponse(
        signed_url=signed_url,
        session_id=str(uuid.uuid4()),
        twin_id=twin_id,
        voice_id=voice_id,
    )


# ---------------------------------------------------------------------------
# GET /v2/voice/{twin_id}/call-token/public  — public visitor
# ---------------------------------------------------------------------------

@router.get("/v2/voice/{twin_id}/call-token/public", response_model=CallTokenResponse)
async def get_call_token_public(
    twin_id: str,
    request: Request,
    share_token: str | None = Query(default=None),
) -> CallTokenResponse:
    """Generate a signed ElevenLabs conversation URL for a public visitor.

    Access granted when:
      - share_token is valid, OR
      - twin is marketplace-public (is_public=true in settings)

    Rate-limited: 5 tokens per IP per 5-minute window.
    """
    _check_voice_allowed(twin_id)
    ip = _get_client_ip(request)
    if not _check_public_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many call requests. Try again in a moment.")

    twin = _fetch_twin_row(twin_id)
    if not twin:
        raise HTTPException(status_code=404, detail="Twin not found.")

    is_accessible = is_publicly_accessible_twin_record(twin)
    if not is_accessible and (not share_token or not validate_share_token(share_token, twin_id)):
        raise HTTPException(status_code=403, detail="This persona is not publicly accessible.")

    settings = twin.get("settings") or {}
    voice_id = settings.get("voice_id")
    if not voice_id:
        raise HTTPException(
            status_code=400,
            detail="This persona does not have a voice configured.",
        )

    api_key = _get_api_key()
    agent_id = _get_twin_agent_id(twin_id, settings=settings)

    # Fix: verify the voice still exists on ElevenLabs before issuing a token.
    if not await _verify_voice_exists(voice_id, api_key):
        _clear_stale_voice_id(twin_id, voice_id)
        raise HTTPException(
            status_code=400,
            detail="Voice no longer available — please contact the persona owner.",
        )

    signed_url = await _get_signed_url(agent_id=agent_id, api_key=api_key)

    logger.info("[VoiceCall] issued public call token twin=%s ip=%s", twin_id, ip)
    return CallTokenResponse(
        signed_url=signed_url,
        session_id=str(uuid.uuid4()),
        twin_id=twin_id,
        voice_id=voice_id,
    )
