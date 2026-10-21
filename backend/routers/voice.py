"""Voice Clone & TTS endpoints using ElevenLabs.

- Clone: upload audio → ElevenLabs Instant Voice Clone → store voice_id
- TTS: text → speech using cloned voice → return audio bytes
- Status: check if voice is cloned
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from modules.auth_guard import require_tenant, verify_twin_ownership
from modules.observability import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice"])

# Warn in logs when ElevenLabs voice count reaches this threshold (shared account limit).
# ElevenLabs Starter plan allows 30 voices; warn at 25 to give time to act.
_ELEVENLABS_VOICE_WARN_THRESHOLD = 25
_ELEVENLABS_API_BASE = "https://api.elevenlabs.io"
_BACKEND_API_URL = os.getenv(
    "API_URL",
    os.getenv(
        "CLOUD_RUN_SERVICE_URL",
        "https://personaon-api-v2-217236881712.us-central1.run.app",
    ),
)


# ── Models ──────────────────────────────────────────────────────────

class TTSRequest(BaseModel):
    """Request body for text-to-speech."""
    text: str = Field(..., min_length=1, max_length=5000)


class VoiceStatusResponse(BaseModel):
    """Voice clone status."""
    cloned: bool
    voice_id: str | None = None
    voice_name: str | None = None


# ── ElevenLabs client ───────────────────────────────────────────────

def _get_client():
    """Get ElevenLabs client or raise if not configured."""
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Voice cloning is not configured. ELEVENLABS_API_KEY is missing.",
        )
    try:
        from elevenlabs.client import ElevenLabs
        return ElevenLabs(api_key=api_key)
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="ElevenLabs package not installed.",
        )


def _get_twin_settings(twin_id: str, tenant_id: str = "") -> dict:
    """Load twin settings from Supabase. Pass tenant_id for scoped read defense."""
    sb = get_supabase_client()
    query = sb.table("twins").select("id, name, settings").eq("id", twin_id)
    if tenant_id:
        query = query.eq("tenant_id", tenant_id)
    resp = query.single().execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Twin not found")
    return resp.data


def _update_twin_settings(twin_id: str, settings: dict, tenant_id: str = "") -> None:
    """Update twin settings in Supabase. Pass tenant_id for scoped write defense."""
    sb = get_supabase_client()
    query = sb.table("twins").update({"settings": settings}).eq("id", twin_id)
    if tenant_id:
        query = query.eq("tenant_id", tenant_id)
    query.execute()


# ── ElevenLabs agent helpers ────────────────────────────────────────

async def _create_elevenlabs_agent(voice_id: str, twin_name: str, api_key: str) -> str | None:
    """Create a dedicated ElevenLabs Conversational AI agent for a twin.
    Returns agent_id on success, None on failure (non-fatal).
    """
    webhook_secret = os.getenv("ELEVENLABS_WEBHOOK_SECRET", "")
    payload = {
        "name": f"PersonaOn - {twin_name}",
        "conversation_config": {
            "agent": {
                "prompt": {
                    "prompt": (
                        "You are a PersonaOn digital twin. Respond naturally "
                        "and conversationally. Keep responses concise - 1-3 "
                        "sentences for voice. Do not use markdown or bullet points."
                    ),
                    "llm": "custom-llm",
                    "custom_llm": {
                        "url": f"{_BACKEND_API_URL}/v1/chat/completions",
                        "request_headers": {
                            "X-PersonaOn-Token": webhook_secret,
                        },
                        "api_type": "chat_completions",
                    },
                },
                "language": "en",
            },
            "tts": {
                "model_id": "eleven_turbo_v2",
                "voice_id": voice_id,
            },
            "asr": {
                "quality": "high",
                "user_input_audio_format": "pcm_16000",
            },
            "turn": {
                "turn_timeout": 7,
                "mode": "turn",
            },
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{_ELEVENLABS_API_BASE}/v1/convai/agents/create",
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
            )
        if resp.status_code == 200:
            return resp.json().get("agent_id")
        logger.warning(
            "[Voice] ElevenLabs agent create failed status=%d body=%s",
            resp.status_code, resp.text[:300],
        )
        return None
    except Exception as exc:
        logger.warning("[Voice] ElevenLabs agent create error (non-fatal): %s", exc)
        return None


async def _delete_elevenlabs_agent(agent_id: str, api_key: str) -> None:
    """Delete an ElevenLabs Conversational AI agent. Non-fatal on failure."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(
                f"{_ELEVENLABS_API_BASE}/v1/convai/agents/{agent_id}",
                headers={"xi-api-key": api_key},
            )
        if resp.status_code != 200:
            logger.warning(
                "[Voice] ElevenLabs agent delete failed agent_id=%s status=%d",
                agent_id, resp.status_code,
            )
    except Exception as exc:
        logger.warning("[Voice] ElevenLabs agent delete error agent_id=%s: %s", agent_id, exc)


# ── Endpoints ───────────────────────────────────────────────────────

@router.get("/v2/voice/{twin_id}/status", response_model=VoiceStatusResponse)
async def voice_status(
    twin_id: str,
    user: dict = Depends(require_tenant),
) -> VoiceStatusResponse:
    """Check if a voice clone exists for this twin."""
    verify_twin_ownership(twin_id, user)
    twin = _get_twin_settings(twin_id, tenant_id=user.get("tenant_id", ""))
    settings = twin.get("settings") or {}
    voice_id = settings.get("voice_id")
    voice_name = settings.get("voice_name")
    return VoiceStatusResponse(
        cloned=bool(voice_id),
        voice_id=voice_id,
        voice_name=voice_name,
    )


@router.post("/v2/voice/{twin_id}/clone")
async def clone_voice(
    twin_id: str,
    audio: UploadFile = File(..., description="Audio file (mp3, wav, m4a) — 30-180 seconds"),
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """Clone a voice from an uploaded audio sample.

    Sends the audio to ElevenLabs Instant Voice Cloning API.
    Stores the resulting voice_id in twin settings.
    """
    verify_twin_ownership(twin_id, user)

    # Validate file type
    allowed_types = {"audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/m4a", "audio/webm"}
    content_type = audio.content_type or ""
    if content_type not in allowed_types and not audio.filename.endswith((".mp3", ".wav", ".m4a", ".webm")):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format: {content_type}. Use MP3, WAV, M4A, or WebM.",
        )

    # Read audio bytes
    audio_bytes = await audio.read()
    if len(audio_bytes) < 10_000:  # ~10KB minimum
        raise HTTPException(status_code=400, detail="Audio file is too short. Record at least 30 seconds.")
    if len(audio_bytes) > 50_000_000:  # 50MB max
        raise HTTPException(status_code=400, detail="Audio file is too large. Maximum 50MB.")

    twin = _get_twin_settings(twin_id, tenant_id=user.get("tenant_id", ""))
    twin_name = twin.get("name", "Persona")
    settings = twin.get("settings") or {}

    client = _get_client()
    voice_name = f"PersonaOn - {twin_name}"

    # Fix: delete orphaned voice before creating a new one.
    # Without this, every re-clone leaks a voice slot on the shared ElevenLabs account.
    old_voice_id = settings.get("voice_id")
    if old_voice_id:
        try:
            client.voices.delete(old_voice_id)
            logger.info("[Voice] deleted old voice %s before re-clone for twin %s", old_voice_id, twin_id)
        except Exception as del_exc:
            logger.warning("[Voice] failed to delete old voice %s (non-fatal): %s", old_voice_id, del_exc)

    # Delete old ElevenLabs agent before re-clone (mirrors old_voice_id deletion above)
    old_agent_id = settings.get("elevenlabs_agent_id")
    if old_agent_id:
        await _delete_elevenlabs_agent(old_agent_id, os.getenv("ELEVENLABS_API_KEY", ""))
        logger.info("[Voice] deleted old agent %s before re-clone for twin %s", old_agent_id, twin_id)

    try:
        # ElevenLabs SDK v2 instant voice clone returns only voice_id.
        voice = client.voices.ivc.create(
            name=voice_name,
            files=[audio_bytes],
            description=f"Cloned voice for {twin_name} on PersonaOn",
        )
    except Exception as exc:
        logger.exception("ElevenLabs clone failed for twin %s", twin_id)
        error_msg = str(exc)
        if "quota" in error_msg.lower() or "limit" in error_msg.lower():
            raise HTTPException(
                status_code=429,
                detail="Voice clone quota reached. Upgrade your ElevenLabs plan.",
            )
        raise HTTPException(status_code=502, detail=f"Voice cloning failed: {error_msg}")

    # Store voice_id in twin settings
    settings["voice_id"] = voice.voice_id
    settings["voice_name"] = voice_name

    # Deepgram live calls use raw ElevenLabs TTS with voice_id, so creating
    # a Conversational AI agent is now legacy-only and opt-in for rollback.
    if os.getenv("VOICE_CREATE_ELEVENLABS_AGENT", "").strip().lower() == "true":
        new_agent_id = await _create_elevenlabs_agent(
            voice_id=voice.voice_id,
            twin_name=twin_name,
            api_key=os.getenv("ELEVENLABS_API_KEY", ""),
        )
        if new_agent_id:
            settings["elevenlabs_agent_id"] = new_agent_id
            logger.info("[Voice] created ElevenLabs agent for twin %s -> agent_id=%s", twin_id, new_agent_id)
        else:
            logger.warning("[Voice] could not create ElevenLabs agent for twin %s (non-fatal)", twin_id)

    # CRITICAL: single _update_twin_settings call persists voice state.
    _update_twin_settings(twin_id, settings, tenant_id=user.get("tenant_id", ""))

    logger.info("[Voice] cloned voice for twin %s → voice_id=%s", twin_id, voice.voice_id)

    # Fix: warn in logs when the shared ElevenLabs account is nearing its voice quota.
    try:
        all_voices = client.voices.get_all()
        voice_count = len(all_voices.voices)
        if voice_count >= _ELEVENLABS_VOICE_WARN_THRESHOLD:
            logger.warning(
                "[Voice] ElevenLabs voice quota nearing limit: %d voices on account "
                "(threshold=%d). Review and delete unused voices.",
                voice_count, _ELEVENLABS_VOICE_WARN_THRESHOLD,
            )
        else:
            logger.info("[Voice] ElevenLabs voice count: %d", voice_count)
    except Exception as quota_exc:
        logger.debug("[Voice] could not fetch voice count (non-fatal): %s", quota_exc)

    # GCS backup — inline with timeout (asyncio.create_task doesn't work on Cloud Run,
    # graph_outbox can't carry 50MB audio bytes through a job payload)
    try:
        import asyncio

        from modules.gcs_storage import upload_file_bytes

        _tenant_id = user.get("tenant_id", "unknown")
        _audio_filename = audio.filename or f"voice_sample_{twin_id}.webm"
        _audio_content_type = audio.content_type or "audio/webm"

        gcs_uri = await asyncio.wait_for(
            asyncio.to_thread(
                upload_file_bytes,
                file_bytes=audio_bytes,
                tenant_id=_tenant_id,
                twin_id=twin_id,
                source_id="voice_samples",
                filename=_audio_filename,
                content_type=_audio_content_type,
            ),
            timeout=10.0,
        )
        # Re-read settings to avoid overwriting concurrent changes (TOCTOU)
        sb = get_supabase_client()
        fresh = sb.table("twins").select("settings").eq("id", twin_id).eq(
            "tenant_id", user.get("tenant_id", ""),
        ).single().execute()
        fresh_settings = dict((fresh.data or {}).get("settings") or {})
        fresh_settings["voice_sample_gcs_uri"] = gcs_uri
        _update_twin_settings(twin_id, fresh_settings, tenant_id=user.get("tenant_id", ""))
        logger.info("[GCS] voice sample uploaded for twin %s → %s", twin_id, gcs_uri)
    except Exception as gcs_err:
        logger.error("[GCS] voice sample upload failed for twin %s (non-fatal): %s", twin_id, gcs_err)

    return {
        "status": "cloned",
        "voice_id": voice.voice_id,
        "voice_name": voice_name,
    }


@router.post("/v2/voice/{twin_id}/tts")
async def text_to_speech(
    twin_id: str,
    request: TTSRequest,
    user: dict = Depends(require_tenant),
) -> StreamingResponse:
    """Generate speech from text using the twin's cloned voice."""
    verify_twin_ownership(twin_id, user)

    twin = _get_twin_settings(twin_id, tenant_id=user.get("tenant_id", ""))
    settings = twin.get("settings") or {}
    voice_id = settings.get("voice_id")

    if not voice_id:
        raise HTTPException(status_code=400, detail="No voice cloned for this persona. Clone your voice first.")

    client = _get_client()

    try:
        # ElevenLabs SDK v2: use text_to_speech.convert()
        audio_generator = client.text_to_speech.convert(
            text=request.text,
            voice_id=voice_id,
            model_id="eleven_multilingual_v2",
        )
        audio_bytes = b"".join(audio_generator)
    except Exception as exc:
        logger.exception("ElevenLabs TTS failed for twin %s", twin_id)
        raise HTTPException(status_code=502, detail=f"Text-to-speech failed: {str(exc)}")

    return StreamingResponse(
        iter([audio_bytes]),
        media_type="audio/mpeg",
        headers={"Content-Disposition": "inline; filename=persona-speech.mp3"},
    )


@router.post("/v2/voice/{twin_id}/tts/public")
async def text_to_speech_public(
    twin_id: str,
    request: TTSRequest,
) -> StreamingResponse:
    """Public TTS endpoint — no auth required.

    Only works if the twin has a cloned voice (voice_id in settings).
    Intended for the public persona chat page.
    """
    twin = _get_twin_settings(twin_id)
    settings = twin.get("settings") or {}
    voice_id = settings.get("voice_id")

    if not voice_id:
        raise HTTPException(status_code=400, detail="No voice cloned for this persona.")

    # Rate-limit text length for public endpoint (prevent abuse)
    if len(request.text) > 2000:
        raise HTTPException(status_code=400, detail="Text too long for public TTS. Maximum 2000 characters.")

    client = _get_client()

    try:
        audio_generator = client.text_to_speech.convert(
            text=request.text,
            voice_id=voice_id,
            model_id="eleven_multilingual_v2",
        )
        audio_bytes = b"".join(audio_generator)
    except Exception as exc:
        logger.exception("ElevenLabs TTS (public) failed for twin %s", twin_id)
        raise HTTPException(status_code=502, detail=f"Text-to-speech failed: {str(exc)}")

    return StreamingResponse(
        iter([audio_bytes]),
        media_type="audio/mpeg",
        headers={"Content-Disposition": "inline; filename=persona-speech.mp3"},
    )


@router.delete("/v2/voice/{twin_id}/clone")
async def delete_voice(
    twin_id: str,
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """Delete the cloned voice from ElevenLabs and remove from twin settings."""
    verify_twin_ownership(twin_id, user)

    twin = _get_twin_settings(twin_id, tenant_id=user.get("tenant_id", ""))
    settings = twin.get("settings") or {}
    voice_id = settings.get("voice_id")

    if not voice_id:
        return {"status": "no_voice", "message": "No voice to delete"}

    # Delete the dedicated ElevenLabs agent if one exists
    agent_id = settings.get("elevenlabs_agent_id")
    if agent_id:
        await _delete_elevenlabs_agent(agent_id, os.getenv("ELEVENLABS_API_KEY", ""))
        logger.info("[Voice] deleted ElevenLabs agent %s for twin %s", agent_id, twin_id)

    # Try to delete from ElevenLabs
    try:
        client = _get_client()
        client.voices.delete(voice_id)
    except Exception as exc:
        logger.warning("Failed to delete voice %s from ElevenLabs: %s", voice_id, exc)

    # Remove from settings regardless
    settings.pop("voice_id", None)
    settings.pop("voice_name", None)
    settings.pop("elevenlabs_agent_id", None)
    _update_twin_settings(twin_id, settings, tenant_id=user.get("tenant_id", ""))

    return {"status": "deleted", "voice_id": voice_id}
