"""
Meeting Voice Router -- Phase 29

WebSocket endpoints:
  /ws/voice-agent/{meeting_id}      -- voice-agent.html <-> backend pipeline
  /ws/meeting/{meeting_id}/live     -- live dashboard event stream

REST endpoints:
  POST /v2/meetings/{twin_id}/{meeting_id}/toggle-attendance
  POST /v2/meetings/{twin_id}/{meeting_id}/mute
  POST /v2/meetings/webhook/transcript
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from modules.auth_guard import verify_twin_ownership
from modules.graph_outbox import GraphOperationType, get_graph_outbox
from modules.observability import get_supabase_client
from services.recall_auth import verify_recall_webhook
from services.meeting_voice_service import (
    clear_meeting_cache,
    generate_meeting_response,
    get_cached_context,
    stream_tts,
    warm_meeting_cache,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["meeting-voice"])


# ---------------------------------------------------------------------------
# In-module event bus for live dashboard subscribers
# ---------------------------------------------------------------------------

_live_subscribers: dict[str, list[asyncio.Queue]] = {}

# Active voice-agent WebSockets keyed by meeting_id — lets webhook forward
# transcripts and dashboard controls to the running bot webpage.
_voice_agent_ws: dict[str, WebSocket] = {}


def _publish_event(meeting_id: str, event: dict) -> None:
    """Publish an event to all live dashboard subscribers for a meeting."""
    queues = _live_subscribers.get(meeting_id, [])
    for q in queues:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(
                "[MeetingVoice] live subscriber queue full meeting_id=%s",
                meeting_id,
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_current_user(request: Request) -> dict[str, Any]:
    """Extract authenticated user from request state or Authorization header."""
    from modules.auth_guard import authenticate_request, get_token_from_header, AuthenticationError

    user = getattr(request.state, "user", None)
    if user:
        return user

    authorization = request.headers.get("authorization", "")
    token = get_token_from_header(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        auth_context = authenticate_request(token)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    # Enrich with tenant_id
    if not auth_context.get("tenant_id"):
        from modules.auth_guard import resolve_tenant_id
        import contextlib
        with contextlib.suppress(Exception):
            auth_context["tenant_id"] = resolve_tenant_id(
                user_id=auth_context.get("user_id"),
                email=auth_context.get("email"),
                create_if_missing=False,
            )

    return auth_context


def _extract_expertise_keywords(persona_profile: dict | None) -> list[str]:
    """Pull trigger keywords from multiple persona_profile fields.

    Falls back through expertise_keywords → expertise → topics → skills →
    role/headline/industry word splits so the TriggerDetector almost always
    has *something* to match even for auto-generated personas.
    """
    profile = persona_profile or {}

    # Preferred structured fields
    for field in ("expertise_keywords", "expertise", "topics", "skills"):
        val = profile.get(field)
        if isinstance(val, list) and val:
            return [str(v).strip().lower() for v in val if str(v).strip()]
        if isinstance(val, str) and val.strip():
            return [t.strip().lower() for t in val.split(",") if t.strip()]

    # Derived fallbacks — tokenize free-text role/headline/industry
    fallback_keywords: list[str] = []
    for field in ("role", "headline", "industry", "title", "current_role"):
        val = profile.get(field)
        if isinstance(val, str) and val.strip():
            # Split on common delimiters, lowercase, drop short stopwords
            tokens = [
                t.strip(" .,;:-").lower()
                for t in val.replace("/", " ").replace("|", " ").split()
                if len(t.strip(" .,;:-")) > 3
            ]
            fallback_keywords.extend(tokens)

    # Deduplicate while preserving order; cap at 10
    seen: set[str] = set()
    deduped: list[str] = []
    for k in fallback_keywords:
        if k not in seen:
            seen.add(k)
            deduped.append(k)
    return deduped[:10]


def _build_intro_text(user_name: str, persona_profile: dict | None) -> str:
    """Compose a short spoken intro for the twin on meeting join.

    Pulls top expertise topics from persona_profile when available; falls
    back to a generic line. Kept short (2 sentences) per Phase 29 spec.
    """
    name = (user_name or "").strip() or "the presenter"
    profile = persona_profile or {}

    # Try common persona_profile shapes for expertise topics
    topics_raw = (
        profile.get("expertise_keywords")
        or profile.get("expertise")
        or profile.get("topics")
        or profile.get("skills")
        or []
    )
    if isinstance(topics_raw, str):
        topics_list = [t.strip() for t in topics_raw.split(",") if t.strip()]
    elif isinstance(topics_raw, list):
        topics_list = [str(t).strip() for t in topics_raw if str(t).strip()]
    else:
        topics_list = []

    if topics_list:
        top = topics_list[:3]
        topics_phrase = (
            f" I can help with {', '.join(top[:-1])}, and {top[-1]}"
            if len(top) > 1
            else f" I can help with {top[0]}"
        )
    else:
        topics_phrase = ""

    return (
        f"Hi everyone, I'm {name}'s AI assistant.{topics_phrase}. "
        "Just address me by name if you'd like me to jump in."
    )


def _load_twin_settings(twin_id: str) -> dict:
    """Load twin settings from Supabase -- single read for voice_id + profile."""
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


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ToggleAttendanceBody(BaseModel):
    attend: bool


class MuteBody(BaseModel):
    muted: bool


class JoinNowBody(BaseModel):
    meet_link: str


# ---------------------------------------------------------------------------
# REST: ad-hoc join — create meeting row + send bot immediately
# ---------------------------------------------------------------------------


@router.post("/v2/meetings/{twin_id}/join-now")
async def join_meeting_now(
    twin_id: str,
    body: JoinNowBody,
    request: Request,
) -> dict:
    """Immediately send a bot to a meeting URL.

    Creates a meeting row, dispatches create_voice_bot, and returns the meeting_id
    so the caller can open the live dashboard.
    """
    from datetime import datetime, timezone

    from services.recall_service import create_voice_bot

    user = _get_current_user(request)
    verify_twin_ownership(twin_id, user)
    tenant_id = user.get("tenant_id")

    sb = get_supabase_client()

    # Load twin name for bot display name
    twin_name = "AI Twin"
    try:
        twin_lookup = (
            sb.table("twins").select("name").eq("id", twin_id).single().execute()
        )
        if twin_lookup.data and twin_lookup.data.get("name"):
            twin_name = twin_lookup.data["name"]
    except Exception as exc:
        logger.warning("[MeetingVoice] twin name lookup failed: %s", exc)
    bot_name = f"{twin_name}'s AI Assistant"[:100]

    # Create meeting row
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        insert_resp = (
            sb.table("meetings")
            .insert({
                "twin_id": twin_id,
                "tenant_id": tenant_id,
                "meet_link": body.meet_link,
                "title": "Instant meeting",
                "status": "scheduled",
                "twin_attends": True,
                "meeting_start": now_iso,
            })
            .execute()
        )
        if not insert_resp.data:
            raise HTTPException(status_code=500, detail="Failed to create meeting row")
        meeting_id = insert_resp.data[0]["id"]
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[MeetingVoice] join-now insert failed twin_id=%s", twin_id)
        raise HTTPException(status_code=500, detail="Failed to create meeting") from exc

    # Send bot — dispatch paths (in order of preference, gated by feature flags):
    #   0. Transcript-only (default when no flags set) — recap engine consumes transcript,
    #      bot does not speak. Task 0.1 of meeting-loop-graduation.
    #   1. Gemini Live native audio — when MEETING_NATIVE_AUDIO_ENABLED=true
    #   2. Gemini Live web-page bridge — when MEETING_GEMINI_LIVE_ENABLED=true
    #   3. Voice bot (Recall + Deepgram + ElevenLabs) — preserved fallback
    #   4. Transcript-only bot — last-resort fallback
    import os as _os
    from services.recall_service import create_bot, create_gemini_live_bot, create_native_audio_bot
    from routers.gemini_live import issue_meeting_token
    from services import meeting_adk_session as _adk_session

    _native_audio_enabled = _os.getenv("MEETING_NATIVE_AUDIO_ENABLED", "false").lower() == "true"
    _gemini_enabled = _os.getenv("MEETING_GEMINI_LIVE_ENABLED", "false").lower() == "true"
    bot_path = "unknown"

    if not _native_audio_enabled and not _gemini_enabled:
        # Default path: transcript-only. The recap engine (Task P1.4.A) consumes the
        # transcript; bot does not speak. No persona/Gemini Live cost incurred.
        try:
            bot = await create_bot(
                meeting_url=body.meet_link,
                bot_name=bot_name,
                metadata={"twin_id": twin_id, "meeting_id": meeting_id, "tenant_id": tenant_id},
            )
            bot_path = "transcript"
            logger.info(
                "[MeetingVoice] join-now TRANSCRIPT bot created meeting_id=%s bot_id=%s",
                meeting_id,
                bot.get("id"),
            )
        except Exception as exc:
            logger.exception(
                "[MeetingVoice] join-now transcript bot creation failed meeting_id=%s",
                meeting_id,
            )
            sb.table("meetings").update({"status": "failed"}).eq("id", meeting_id).execute()
            raise HTTPException(status_code=502, detail=f"Bot creation failed: {exc}") from exc
    else:
        # Existing cascade: native_audio → gemini_live → voice → transcript_fallback.
        # Preserved verbatim for staging where flags are explicitly enabled.
        if _native_audio_enabled:
            try:
                voice_settings = _load_twin_settings(twin_id)
                voice_name = voice_settings.get("gemini_voice") or "Kore"
                bot = await create_native_audio_bot(
                    meeting_url=body.meet_link,
                    bot_name=bot_name,
                    twin_id=twin_id,
                    meeting_id=meeting_id,
                    voice_name=voice_name,
                    metadata={"twin_id": twin_id, "meeting_id": meeting_id, "tenant_id": tenant_id},
                )
                # Start ADK session now so it waits for player_ready before the bot joins.
                await _adk_session.create_session(meeting_id, twin_id, voice_name)
                bot_path = "native_audio"
                logger.info(
                    "[MeetingVoice] join-now NATIVE_AUDIO bot created meeting_id=%s bot_id=%s voice=%s",
                    meeting_id,
                    bot.get("id"),
                    voice_name,
                )
            except Exception as na_exc:
                logger.warning(
                    "[MeetingVoice] join-now NATIVE_AUDIO bot failed, falling back: %s", na_exc
                )
                _native_audio_enabled = False

        if not _native_audio_enabled and _gemini_enabled:
            try:
                # Pick twin's chosen voice from settings, default Kore
                voice_settings = _load_twin_settings(twin_id)
                voice_name = voice_settings.get("gemini_voice") or "Kore"
                # Mint a meeting-scoped token the webpage uses to fetch the
                # ephemeral Gemini API key + persona config.
                api_key_token = issue_meeting_token(twin_id, meeting_id)
                bot = await create_gemini_live_bot(
                    meeting_url=body.meet_link,
                    bot_name=bot_name,
                    twin_id=twin_id,
                    meeting_id=meeting_id,
                    voice_name=voice_name,
                    api_key_token=api_key_token,
                    metadata={"twin_id": twin_id, "meeting_id": meeting_id, "tenant_id": tenant_id},
                )
                bot_path = "gemini_live"
                logger.info(
                    "[MeetingVoice] join-now GEMINI_LIVE bot created meeting_id=%s bot_id=%s voice=%s",
                    meeting_id,
                    bot.get("id"),
                    voice_name,
                )
            except Exception as gl_exc:
                logger.warning(
                    "[MeetingVoice] join-now GEMINI_LIVE bot failed, falling back to voice bot: %s",
                    gl_exc,
                )
                _gemini_enabled = False  # force through to legacy path below

        if bot_path == "unknown":
            try:
                bot = await create_voice_bot(
                    meeting_url=body.meet_link,
                    bot_name=bot_name,
                    twin_id=twin_id,
                    meeting_id=meeting_id,
                    metadata={"twin_id": twin_id, "meeting_id": meeting_id, "tenant_id": tenant_id},
                )
                bot_path = "voice"
                logger.info(
                    "[MeetingVoice] join-now VOICE bot created meeting_id=%s bot_id=%s",
                    meeting_id,
                    bot.get("id"),
                )
            except Exception as voice_exc:
                logger.warning(
                    "[MeetingVoice] join-now VOICE bot failed, falling back to transcript bot: %s",
                    voice_exc,
                )
                try:
                    bot = await create_bot(
                        meeting_url=body.meet_link,
                        bot_name=bot_name,
                        metadata={"twin_id": twin_id, "meeting_id": meeting_id, "tenant_id": tenant_id},
                    )
                    bot_path = "transcript_fallback"
                    logger.info(
                        "[MeetingVoice] join-now TRANSCRIPT fallback bot created meeting_id=%s bot_id=%s",
                        meeting_id,
                        bot.get("id"),
                    )
                except Exception as exc:
                    logger.exception("[MeetingVoice] join-now bot creation failed meeting_id=%s", meeting_id)
                    sb.table("meetings").update({"status": "failed"}).eq("id", meeting_id).execute()
                    raise HTTPException(status_code=502, detail=f"Bot creation failed: {exc}") from exc

    bot_id = bot.get("id")
    sb.table("meetings").update({"recall_bot_id": bot_id, "status": "bot_joining"}).eq("id", meeting_id).execute()
    logger.info(
        "[MeetingVoice] join-now bot_id=%s meeting_id=%s path=%s",
        bot_id,
        meeting_id,
        bot_path,
    )

    return {"status": "ok", "data": {"meeting_id": meeting_id, "bot_id": bot_id, "bot_path": bot_path}}


# ---------------------------------------------------------------------------
# WebSocket: voice-agent.html <-> backend pipeline
# ---------------------------------------------------------------------------


@router.websocket("/ws/voice-agent/{meeting_id}")
async def voice_agent_ws(websocket: WebSocket, meeting_id: str) -> None:
    """WebSocket endpoint for the voice-agent webpage rendered inside the Recall.ai bot.

    The webpage sends transcript segments; we respond with audio chunks.
    Query params: twin_id (required).
    """
    twin_id = websocket.query_params.get("twin_id")
    if not twin_id:
        await websocket.close(code=4000, reason="twin_id query param required")
        return

    api_key_token = websocket.query_params.get("api_key_token", "")
    token_auth_required = bool(os.getenv("GEMINI_LIVE_TOKEN_SECRET") or os.getenv("CRON_SECRET"))
    if api_key_token or token_auth_required:
        from routers.gemini_live import _verify_meeting_token

        try:
            token_meeting_id = _verify_meeting_token(api_key_token, twin_id)
        except HTTPException:
            await websocket.close(code=4001, reason="Not authorized")
            return
        if token_meeting_id != meeting_id:
            await websocket.close(code=4001, reason="Not authorized")
            return

    await websocket.accept()
    _voice_agent_ws[meeting_id] = websocket
    logger.info(
        "[MeetingVoice] voice-agent WS connected meeting_id=%s twin_id=%s",
        meeting_id,
        twin_id,
    )

    muted = False

    try:
        # Load or warm cache
        cached = get_cached_context(meeting_id)
        if not cached:
            await warm_meeting_cache(twin_id, meeting_id)
            cached = get_cached_context(meeting_id)

        # Load twin settings for voice_id
        if cached:
            voice_id = cached.get("voice_id", "")
            persona_profile = cached.get("persona_profile", {})
            user_name = cached.get("twin_name", "")
            warm_chunks = cached.get("warm_chunks", [])
        else:
            settings = _load_twin_settings(twin_id)
            voice_id = settings.get("voice_id", "")
            persona_profile = settings.get("persona_profile") or {}
            user_name = persona_profile.get("name", "the presenter")
            warm_chunks = []

        # Fallback to a default voice when twin has no clone yet (for UAT).
        # ElevenLabs "Rachel" (21m00Tcm4TlvDq8ikWAM) unless overridden via env.
        import os as _os
        if not voice_id:
            voice_id = _os.getenv("FALLBACK_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
            logger.info(
                "[MeetingVoice] twin %s has no cloned voice — using fallback voice_id=%s",
                twin_id,
                voice_id,
            )

        # Derive trigger keywords from persona_profile so the webpage's
        # TriggerDetector actually matches real topics, not an empty list.
        expertise_keywords = _extract_expertise_keywords(persona_profile)

        # Send twin_config once on connect so voice-agent.html can configure
        # its TriggerDetector with the real name + expertise keywords.
        # Without this the detector defaults to name='Assistant' + [], so
        # nothing ever triggers (root cause of the "bot not responding" bug).
        await websocket.send_json({
            "type": "twin_config",
            "twin_name": user_name or "the presenter",
            "expertise_keywords": expertise_keywords,
        })
        logger.info(
            "[MeetingVoice] sent twin_config meeting_id=%s name=%s keywords=%d",
            meeting_id,
            user_name,
            len(expertise_keywords),
        )

        # Main message loop
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            msg_type = msg.get("type", "")

            if msg_type == "mute":
                muted = True
                _publish_event(meeting_id, {"type": "twin_status", "status": "muted"})
                logger.info("[MeetingVoice] twin muted meeting_id=%s", meeting_id)
                continue

            if msg_type == "unmute":
                muted = False
                _publish_event(meeting_id, {"type": "twin_status", "status": "listening"})
                logger.info("[MeetingVoice] twin unmuted meeting_id=%s", meeting_id)
                continue

            if msg_type == "leave":
                logger.info("[MeetingVoice] twin leaving meeting_id=%s", meeting_id)
                break

            if msg_type == "intro":
                # Spoken introduction on first detected speech. Built from the
                # twin's name and top expertise topics in persona_profile so
                # everyone in the room knows who the persona is and how to
                # address it.
                intro_text = _build_intro_text(user_name, persona_profile)
                _publish_event(meeting_id, {
                    "type": "transcript",
                    "text": intro_text,
                    "speaker": f"{user_name}'s AI Assistant",
                    "timestamp": time.time(),
                })
                await websocket.send_json({
                    "type": "twin_response",
                    "response": intro_text,
                })
                await websocket.send_json({"type": "status", "status": "speaking"})
                _publish_event(meeting_id, {"type": "twin_status", "status": "speaking"})

                if voice_id:
                    async def _intro_gen() -> Any:
                        yield intro_text

                    async for audio_bytes in stream_tts(_intro_gen(), voice_id):
                        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
                        await websocket.send_json({
                            "type": "audio",
                            "audio_b64": audio_b64,
                        })

                await websocket.send_json({"type": "status", "status": "listening"})
                _publish_event(meeting_id, {"type": "twin_status", "status": "listening"})
                logger.info(
                    "[MeetingVoice] intro played meeting_id=%s len=%d",
                    meeting_id, len(intro_text),
                )
                continue

            if msg_type == "transcript" and not muted:
                transcript_text = msg.get("text", "").strip()
                speaker = msg.get("speaker", "unknown")
                if not transcript_text:
                    continue

                # Publish transcript event to live dashboard
                _publish_event(meeting_id, {
                    "type": "transcript",
                    "text": transcript_text,
                    "speaker": speaker,
                    "timestamp": time.time(),
                })

                # Status: thinking
                await websocket.send_json({"type": "status", "status": "thinking"})
                _publish_event(meeting_id, {"type": "twin_status", "status": "thinking"})

                # Generate response
                full_response_text = ""
                response_gen = generate_meeting_response(
                    transcript_text=transcript_text,
                    twin_id=twin_id,
                    user_name=user_name,
                    persona_profile=persona_profile,
                    warm_chunks=warm_chunks,
                )

                # Collect text for twin_response event, pipe to TTS
                text_chunks: list[str] = []
                async for chunk in response_gen:
                    text_chunks.append(chunk)
                full_response_text = "".join(text_chunks)

                if voice_id and text_chunks:
                    # Status: speaking
                    await websocket.send_json({"type": "status", "status": "speaking"})
                    _publish_event(meeting_id, {"type": "twin_status", "status": "speaking"})

                    # Create async generator from collected chunks for TTS
                    async def _text_gen() -> Any:
                        for c in text_chunks:
                            yield c

                    async for audio_bytes in stream_tts(_text_gen(), voice_id):
                        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
                        await websocket.send_json({
                            "type": "audio",
                            "audio_b64": audio_b64,
                        })
                elif not voice_id:
                    # No voice -- send text response instead
                    await websocket.send_json({
                        "type": "text_response",
                        "text": full_response_text,
                    })

                # Status: listening (done responding)
                await websocket.send_json({"type": "status", "status": "listening"})
                _publish_event(meeting_id, {"type": "twin_status", "status": "listening"})

                # Send twin_response summary
                twin_response_event = {
                    "type": "twin_response",
                    "question": transcript_text,
                    "response": full_response_text,
                    "speaker": speaker,
                }
                await websocket.send_json(twin_response_event)
                _publish_event(meeting_id, twin_response_event)

    except WebSocketDisconnect:
        logger.info(
            "[MeetingVoice] voice-agent WS disconnected meeting_id=%s", meeting_id
        )
    except Exception as exc:
        logger.exception(
            "[MeetingVoice] voice-agent WS error meeting_id=%s: %s",
            meeting_id,
            exc,
        )
    finally:
        _voice_agent_ws.pop(meeting_id, None)
        clear_meeting_cache(meeting_id)


# ---------------------------------------------------------------------------
# WebSocket: live dashboard event stream
# ---------------------------------------------------------------------------


@router.websocket("/ws/meeting/{meeting_id}/live")
async def meeting_live_ws(websocket: WebSocket, meeting_id: str) -> None:
    """Live dashboard WebSocket -- relays meeting events to the frontend.

    Auth via query param 'token' (JWT validated against request.state pattern).
    Sends ping every 30 seconds for keepalive.
    """
    token = websocket.query_params.get("token", "")
    if not token:
        await websocket.close(code=4001, reason="Not authenticated")
        return
    try:
        from modules.auth_guard import authenticate_request, AuthenticationError
        authenticate_request(token)
    except Exception:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await websocket.accept()
    logger.info(
        "[MeetingVoice] live dashboard WS connected meeting_id=%s", meeting_id
    )

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    if meeting_id not in _live_subscribers:
        _live_subscribers[meeting_id] = []
    _live_subscribers[meeting_id].append(queue)

    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                # Send keepalive ping
                await websocket.send_json({"type": "ping", "timestamp": time.time()})
    except WebSocketDisconnect:
        logger.info(
            "[MeetingVoice] live dashboard WS disconnected meeting_id=%s",
            meeting_id,
        )
    except Exception as exc:
        logger.exception(
            "[MeetingVoice] live dashboard WS error meeting_id=%s: %s",
            meeting_id,
            exc,
        )
    finally:
        if meeting_id in _live_subscribers:
            try:
                _live_subscribers[meeting_id].remove(queue)
            except ValueError:
                pass
            if not _live_subscribers[meeting_id]:
                del _live_subscribers[meeting_id]


# ---------------------------------------------------------------------------
# REST: toggle twin attendance
# ---------------------------------------------------------------------------


@router.post("/v2/meetings/{twin_id}/{meeting_id}/toggle-attendance")
async def toggle_twin_attendance(
    twin_id: str,
    meeting_id: str,
    body: ToggleAttendanceBody,
    request: Request,
) -> dict:
    """Toggle whether a twin attends a specific meeting.

    If attend=true and the meeting is upcoming, enqueues a WARM_MEETING_CACHE
    job to pre-load KB context.
    """
    user = _get_current_user(request)
    verify_twin_ownership(twin_id, user)
    tenant_id = user.get("tenant_id")

    sb = get_supabase_client()
    try:
        resp = (
            sb.table("meetings")
            .update({"twin_attends": body.attend})
            .eq("id", meeting_id)
            .eq("twin_id", twin_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
    except Exception as exc:
        logger.exception(
            "[MeetingVoice] toggle-attendance DB update failed meeting_id=%s: %s",
            meeting_id,
            exc,
        )
        raise HTTPException(status_code=500, detail="Failed to update attendance")

    # If enabling attendance, enqueue cache warm job + bot dispatch
    if body.attend:
        # Fetch meeting context — we need meet_link, meeting_start, recall_bot_id
        # to decide whether to dispatch a bot.
        meeting_ctx: dict | None = None
        try:
            ctx_resp = (
                sb.table("meetings")
                .select("meet_link,meeting_start,recall_bot_id")
                .eq("id", meeting_id)
                .eq("twin_id", twin_id)
                .eq("tenant_id", tenant_id)
                .single()
                .execute()
            )
            meeting_ctx = ctx_resp.data or None
        except Exception as exc:
            logger.warning(
                "[MeetingVoice] toggle-attendance ctx fetch failed meeting=%s: %s",
                meeting_id, exc,
            )

        try:
            outbox = get_graph_outbox()
            outbox.enqueue(
                operation=GraphOperationType.WARM_MEETING_CACHE,
                twin_id=twin_id,
                payload={"meeting_id": meeting_id, "twin_id": twin_id},
            )
            logger.info(
                "[MeetingVoice] enqueued WARM_MEETING_CACHE twin_id=%s meeting_id=%s",
                twin_id,
                meeting_id,
            )
        except Exception as exc:
            logger.warning(
                "[MeetingVoice] failed to enqueue warm cache job: %s", exc
            )

        # Dispatch the Recall bot when we have a meet_link, a future start, and
        # no existing bot. Idempotency key keyed by meeting_id so re-toggling
        # never dispatches twice.
        if meeting_ctx:
            from datetime import datetime, timezone as _tz
            meet_link = meeting_ctx.get("meet_link") or ""
            existing_bot = meeting_ctx.get("recall_bot_id")
            start_iso = meeting_ctx.get("meeting_start") or ""
            is_future = False
            if start_iso:
                try:
                    start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
                    is_future = start_dt > datetime.now(_tz.utc)
                except (TypeError, ValueError):
                    is_future = False

            if meet_link and not existing_bot and is_future:
                try:
                    outbox = get_graph_outbox()
                    outbox.submit(
                        tenant_id=tenant_id,
                        twin_id=twin_id,
                        operation=GraphOperationType.SCHEDULE_MEETING_BOT,
                        idempotency_key=f"meeting_bot:{meeting_id}",
                        payload={
                            "meeting_id": meeting_id,
                            "twin_id": twin_id,
                            "meet_link": meet_link,
                            "proposed_start": start_iso,
                            "tenant_id": tenant_id,
                        },
                        priority=5,
                    )
                    logger.info(
                        "[MeetingVoice] enqueued SCHEDULE_MEETING_BOT twin=%s meeting=%s",
                        twin_id, meeting_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "[MeetingVoice] bot dispatch enqueue failed meeting=%s: %s",
                        meeting_id, exc,
                    )
            elif not meet_link:
                logger.info(
                    "[MeetingVoice] toggle-attendance: no meet_link, skipping bot dispatch meeting=%s",
                    meeting_id,
                )
            elif existing_bot:
                logger.info(
                    "[MeetingVoice] toggle-attendance: bot already dispatched (recall_bot=%s), skipping meeting=%s",
                    existing_bot, meeting_id,
                )
            elif not is_future:
                logger.info(
                    "[MeetingVoice] toggle-attendance: meeting_start in past, skipping bot dispatch meeting=%s",
                    meeting_id,
                )

    return {"status": "ok", "data": {"twin_attends": body.attend}}


# ---------------------------------------------------------------------------
# REST: mute / unmute twin
# ---------------------------------------------------------------------------


@router.post("/v2/meetings/{twin_id}/{meeting_id}/mute")
async def mute_twin(
    twin_id: str,
    meeting_id: str,
    body: MuteBody,
    request: Request,
) -> dict:
    """Mute or unmute a twin in a meeting.

    Native audio path (ADK session active): gates audio output server-side via
    set_output_muted, which signals the player page via WebSocket control frame.
    send_mute_signal and Recall output_audio API are intentionally not called
    (see inline comments).

    Legacy voice-agent WS path: forwards a control message to the running webpage.
    Both paths publish to the live dashboard bus.
    """
    from routers.gemini_live import publish_control_event
    from services import meeting_adk_session as _session_mgr

    user = _get_current_user(request)
    verify_twin_ownership(twin_id, user)

    event_type = "mute" if body.muted else "unmute"

    adk_session = _session_mgr.get_session(meeting_id)
    if adk_session is not None:
        # Native audio path: gate output and signal player page via WS control frame.
        # send_mute_signal removed — it injected Gemini context that lingered across reconnects.
        # mute_bot/unmute_bot removed — they return HTTP 400 for native audio bots.
        _session_mgr.set_output_muted(meeting_id, body.muted)
    else:
        # Legacy voice-agent WS path
        voice_ws = _voice_agent_ws.get(meeting_id)
        if voice_ws is not None:
            try:
                await voice_ws.send_json({"type": event_type})
            except Exception as exc:
                logger.warning(
                    "[MeetingVoice] mute control send failed meeting_id=%s: %s",
                    meeting_id, exc,
                )

    publish_control_event(meeting_id, event_type)
    _publish_event(meeting_id, {"type": "twin_status", "status": event_type})

    logger.info(
        "[MeetingVoice] twin %s meeting_id=%s twin_id=%s",
        event_type, meeting_id, twin_id,
    )

    return {"status": "ok", "data": {"muted": body.muted}}


class LeaveBody(BaseModel):
    pass


@router.post("/v2/meetings/{twin_id}/{meeting_id}/leave")
async def leave_meeting(
    twin_id: str,
    meeting_id: str,
    request: Request,
) -> dict:
    """Instruct the twin to leave the meeting. Deletes the Recall.ai bot and
    closes the voice-agent WebSocket."""
    from services.recall_service import delete_bot
    from routers.gemini_live import publish_control_event
    import services.meeting_adk_session as _adk_session

    user = _get_current_user(request)
    verify_twin_ownership(twin_id, user)

    sb = get_supabase_client()
    try:
        mtg_lookup = (
            sb.table("meetings")
            .select("recall_bot_id")
            .eq("id", meeting_id)
            .single()
            .execute()
        )
        bot_id = (mtg_lookup.data or {}).get("recall_bot_id")
    except Exception as exc:
        logger.warning("[MeetingVoice] leave lookup failed: %s", exc)
        bot_id = None

    # Flush ADK transcript before deleting the bot. For native audio bots,
    # bot.done may never fire after delete (no recording to process), so we
    # must tear down here. teardown_session is idempotent — bot.done calling
    # it again is a safe no-op because _sessions.pop returns None on the
    # second call.
    try:
        await _adk_session.teardown_session(meeting_id, reason="leave_endpoint")
    except Exception as exc:
        logger.warning("[MeetingVoice] teardown_session failed meeting=%s: %s", meeting_id, exc)

    if bot_id:
        try:
            await delete_bot(bot_id)
            logger.info("[MeetingVoice] deleted recall bot=%s", bot_id)
        except Exception as exc:
            logger.warning("[MeetingVoice] delete_bot failed bot=%s: %s", bot_id, exc)

    voice_ws = _voice_agent_ws.get(meeting_id)
    if voice_ws is not None:
        try:
            await voice_ws.send_json({"type": "leave"})
        except Exception:
            pass

    publish_control_event(meeting_id, "leave")

    try:
        sb.table("meetings").update({"status": "processing"}).eq("id", meeting_id).execute()
    except Exception as exc:
        logger.warning("[MeetingVoice] leave status update failed: %s", exc)

    _publish_event(meeting_id, {"type": "twin_status", "status": "left"})

    return {"status": "ok", "data": {"left": True}}


# ---------------------------------------------------------------------------
# REST: transcript webhook (from Recall.ai realtime_endpoints)
# ---------------------------------------------------------------------------


@router.post("/v2/meetings/webhook/transcript")
async def transcript_webhook(request: Request) -> dict:
    """Receive transcript.data events from Recall.ai realtime_endpoints."""
    raw_body = await request.body()
    webhook_id = request.headers.get("webhook-id", "")
    webhook_timestamp = request.headers.get("webhook-timestamp", "")
    webhook_signature = request.headers.get("webhook-signature", "")

    if not verify_recall_webhook(raw_body, webhook_id, webhook_timestamp, webhook_signature):
        logger.warning("[MeetingVoice] transcript webhook invalid signature webhook_id=%s", webhook_id)
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        body = json.loads(raw_body)
    except Exception:
        logger.warning("[MeetingVoice] transcript webhook: invalid JSON body")
        return {"status": "ok"}

    # Extract transcript data from Recall.ai event
    event_type = body.get("event", "")
    data = body.get("data", {})

    logger.info(
        "[MeetingVoice] transcript webhook hit event=%s bot_id=%s",
        event_type,
        data.get("bot_id", ""),
    )

    if event_type != "transcript.data":
        return {"status": "ok"}

    transcript_obj = data.get("transcript", {}) or {}

    # Deepgram streaming fires partial events as words arrive and a final event
    # at end of utterance. Only process finals to avoid flooding Gemini with
    # mid-sentence partial turns that cause duplicate responses.
    if not transcript_obj.get("is_final", True):
        return {"status": "ok"}
    # Recall.ai sends words as array of {text, start_time, end_time} — reconstruct
    words = transcript_obj.get("words") or []
    transcript_text = " ".join(
        w.get("text", "") for w in words if isinstance(w, dict)
    ).strip()
    # Fallback for alternate shapes
    if not transcript_text:
        transcript_text = (
            transcript_obj.get("original_transcript")
            or transcript_obj.get("text")
            or ""
        )
    speaker = transcript_obj.get("speaker") or transcript_obj.get("participant_name", "unknown")
    # Timestamp: use first word's start_time if available, else empty
    timestamp = str(words[0].get("start_time", "")) if words else transcript_obj.get("timestamp", "")
    bot_id = data.get("bot_id", "")

    if not transcript_text:
        return {"status": "ok"}

    logger.info(
        "[MeetingVoice] transcript webhook bot_id=%s speaker=%s text=%.80s",
        bot_id,
        speaker,
        transcript_text,
    )

    # Store in meeting_transcript_live table
    sb = get_supabase_client()
    try:
        sb.table("meeting_transcript_live").insert({
            "bot_id": bot_id,
            "speaker": speaker,
            "text": transcript_text,
            "timestamp": timestamp,
        }).execute()
    except Exception as exc:
        logger.warning(
            "[MeetingVoice] transcript storage failed bot_id=%s: %s",
            bot_id,
            exc,
        )

    # Look up meeting_id from bot_id so we can route to the voice-agent WS
    # and dashboard subscribers (both keyed by meeting_id).
    meeting_id = ""
    try:
        mtg_lookup = (
            sb.table("meetings").select("id").eq("recall_bot_id", bot_id).single().execute()
        )
        if mtg_lookup.data:
            meeting_id = mtg_lookup.data["id"]
    except Exception as exc:
        logger.warning(
            "[MeetingVoice] meeting lookup failed for bot_id=%s: %s", bot_id, exc
        )

    # Publish to live dashboard subscribers (keyed by meeting_id)
    if meeting_id:
        _publish_event(meeting_id, {
            "type": "transcript",
            "text": transcript_text,
            "speaker": speaker,
            "timestamp": timestamp,
            "bot_id": bot_id,
        })

        # Mirror transcript into the Gemini Live SSE stream so the
        # output-media webpage can feed text turns to Gemini directly.
        try:
            from routers.gemini_live import publish_transcript_event

            publish_transcript_event(
                meeting_id,
                speaker=speaker,
                text=transcript_text,
                timestamp=str(timestamp or ""),
            )
        except Exception as exc:
            logger.warning(
                "[MeetingVoice] gemini transcript publish failed meeting_id=%s: %s",
                meeting_id,
                exc,
            )

        # Forward to the voice-agent WebSocket as a raw speaker utterance.
        # The webpage runs TriggerDetector on these and only echoes back
        # type='transcript' if a trigger fires, avoiding per-word response loops.
        voice_ws = _voice_agent_ws.get(meeting_id)
        if voice_ws is not None:
            try:
                await voice_ws.send_json({
                    "type": "speaker_transcript",
                    "text": transcript_text,
                    "speaker": speaker,
                })
            except Exception as exc:
                logger.warning(
                    "[MeetingVoice] voice-agent WS send failed meeting_id=%s: %s",
                    meeting_id,
                    exc,
                )

    return {"status": "ok"}
