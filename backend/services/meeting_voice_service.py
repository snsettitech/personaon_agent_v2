"""
Meeting Voice Service

Provides the backend voice pipeline for twin meeting participation:
  - generate_meeting_response(): raw Gemini API response with KB context + deferral (MTG-32)
  - stream_tts(): ElevenLabs WebSocket streaming TTS (Flash v2.5, pcm_24000)
  - warm_meeting_cache / get_cached_context / clear_meeting_cache: pre-meeting KB cache

CRITICAL: Uses raw google.genai Client, NOT ADK Runner/Agent/chat_stream.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from collections.abc import AsyncGenerator
from typing import Any

import google.genai as genai
import google.genai.types as genai_types
import websockets

from adk_core.services.vector_store import search as kb_search
from modules.observability import get_supabase_client
from services.meeting_analyzer import _get_genai_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
_KB_MIN_CHUNKS = 2
_KB_MIN_SCORE = 0.5
_MAX_OUTPUT_TOKENS = 150
_MEETING_LLM_MODEL = os.getenv("MEETING_LLM_MODEL", "gemini-3.5-flash-lite")
_CACHE_TTL_SECONDS = 7200  # 2 hours

DEFERRAL_TEMPLATE = (
    "That's a great question -- let me have {user_name} follow up on that directly."
)

_SYSTEM_PROMPT_TEMPLATE = (
    "You are {user_name}'s AI assistant speaking in a meeting. "
    "Answer concisely in 2-3 sentences max based on the following knowledge base context. "
    "If you can elaborate, offer to do so. "
    "Speak naturally, not like a chatbot.\n\n"
    "KB Context:\n{chunk_texts}"
)


# ---------------------------------------------------------------------------
# Response generation (raw Gemini, MTG-32 deferral)
# ---------------------------------------------------------------------------


async def generate_meeting_response(
    transcript_text: str,
    twin_id: str,
    user_name: str,
    persona_profile: dict,
    warm_chunks: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    """Generate a persona-grounded meeting response via raw Gemini API.

    Implements MTG-32 deferral logic: if fewer than _KB_MIN_CHUNKS chunks
    score above _KB_MIN_SCORE, yields the deferral template and returns.

    Args:
        transcript_text: The transcript segment to respond to.
        twin_id: Twin ID for KB search.
        user_name: Display name of the twin's owner (for deferral message).
        persona_profile: Twin's persona profile dict.
        warm_chunks: Optional pre-fetched KB chunks from warm cache.

    Yields:
        Text chunks of the generated response (or deferral message).
    """
    try:
        # 1. KB search
        search_results = await kb_search(
            query=transcript_text, twin_id=twin_id, top_k=5
        )

        # 2. Merge warm chunks (deduplicate by text content)
        if warm_chunks:
            existing_texts = {c.get("text", "") for c in search_results}
            for chunk in warm_chunks:
                if chunk.get("text", "") not in existing_texts:
                    search_results.append(chunk)
                    existing_texts.add(chunk.get("text", ""))

        # 3. MTG-32 deferral: check KB coverage
        high_score_chunks = [
            c for c in search_results if c.get("score", 0) > _KB_MIN_SCORE
        ]
        if len(high_score_chunks) < _KB_MIN_CHUNKS:
            logger.info(
                "[MeetingVoice] deferring — only %d chunks above %.1f (need %d) "
                "twin_id=%s query=%.80s",
                len(high_score_chunks),
                _KB_MIN_SCORE,
                _KB_MIN_CHUNKS,
                twin_id,
                transcript_text,
            )
            yield DEFERRAL_TEMPLATE.format(user_name=user_name)
            return

        # 4. Build system prompt with KB context
        chunk_texts = "\n---\n".join(
            c.get("text", "") for c in high_score_chunks
        )
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            user_name=user_name, chunk_texts=chunk_texts
        )

        # 5. Stream via raw Gemini API
        client = _get_genai_client()
        config = genai_types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=_MAX_OUTPUT_TOKENS,
            system_instruction=system_prompt,
        )

        def _collect_stream() -> list[str]:
            return [
                chunk.text
                for chunk in client.models.generate_content_stream(
                    model=_MEETING_LLM_MODEL,
                    contents=transcript_text,
                    config=config,
                )
                if chunk.text
            ]

        chunks = await asyncio.to_thread(_collect_stream)
        for chunk in chunks:
            yield chunk

    except Exception as exc:
        logger.exception(
            "[MeetingVoice] generate_meeting_response failed twin_id=%s: %s",
            twin_id,
            exc,
        )
        yield DEFERRAL_TEMPLATE.format(user_name=user_name)


# ---------------------------------------------------------------------------
# ElevenLabs WebSocket TTS streaming
# ---------------------------------------------------------------------------


async def stream_tts(
    text_chunks: AsyncGenerator[str, None],
    voice_id: str,
) -> AsyncGenerator[bytes, None]:
    """Stream text chunks to ElevenLabs WebSocket TTS and yield PCM audio.

    Connects to the ElevenLabs streaming input endpoint with Flash v2.5
    and pcm_24000 output format. Sends text as it arrives and yields
    decoded audio bytes as ElevenLabs returns them.

    Args:
        text_chunks: Async generator of text strings from LLM.
        voice_id: ElevenLabs voice ID (IVC or pre-made).

    Yields:
        Raw PCM audio bytes (24kHz, 16-bit).
    """
    api_key = ELEVENLABS_API_KEY or os.getenv("ELEVENLABS_API_KEY", "")
    if not api_key:
        logger.error("[MeetingVoice] ELEVENLABS_API_KEY not configured")
        return

    ws_url = (
        f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"
        f"?model_id=eleven_flash_v2_5&output_format=pcm_24000"
    )

    producer_task: asyncio.Task | None = None

    try:
        async with websockets.connect(
            ws_url,
            additional_headers={"xi-api-key": api_key},
        ) as ws:
            # Send init message
            init_msg = {
                "text": " ",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                },
                "generation_config": {
                    "chunk_length_schedule": [50, 90, 120, 150],
                },
            }
            await ws.send(json.dumps(init_msg))

            # Producer: send text chunks, then flush + close
            async def _producer() -> None:
                try:
                    async for text in text_chunks:
                        if text:
                            await ws.send(json.dumps({
                                "text": f"{text} ",
                                "try_trigger_generation": True,
                            }))
                    # Flush final audio
                    await ws.send(json.dumps({"text": "", "flush": True}))
                    # Signal end of input
                    await ws.send(json.dumps({"text": ""}))
                except Exception as exc:
                    logger.exception(
                        "[MeetingVoice] TTS producer error: %s", exc
                    )

            producer_task = asyncio.create_task(_producer())

            # Consumer: receive audio chunks
            async for raw_msg in ws:
                try:
                    data = json.loads(raw_msg)
                except (json.JSONDecodeError, TypeError):
                    continue

                if "audio" in data and data["audio"]:
                    yield base64.b64decode(data["audio"])

                if data.get("isFinal"):
                    break

    except Exception as exc:
        logger.exception("[MeetingVoice] stream_tts failed: %s", exc)
    finally:
        if producer_task and not producer_task.done():
            producer_task.cancel()
            try:
                await producer_task
            except asyncio.CancelledError:
                pass


# ---------------------------------------------------------------------------
# Pre-meeting cache
# ---------------------------------------------------------------------------

_meeting_cache: dict[str, dict] = {}


async def warm_meeting_cache(twin_id: str, meeting_id: str) -> bool:
    """Pre-load twin profile and top KB chunks for a meeting.

    Stores the result in an in-memory TTL cache keyed by meeting_id.
    The cache entry expires after _CACHE_TTL_SECONDS (2 hours).

    Args:
        twin_id: Twin whose context to pre-load.
        meeting_id: Meeting to cache context for.

    Returns:
        True if cache was warmed successfully, False on error.
    """
    try:
        sb = get_supabase_client()
        resp = (
            sb.table("twins")
            .select("id, name, settings")
            .eq("id", twin_id)
            .single()
            .execute()
        )
        if not resp.data:
            logger.warning(
                "[MeetingVoice] warm_meeting_cache: twin not found twin_id=%s",
                twin_id,
            )
            return False

        twin = resp.data
        settings = twin.get("settings") or {}
        persona_profile = settings.get("persona_profile") or {}
        if isinstance(persona_profile, str):
            try:
                persona_profile = json.loads(persona_profile)
            except (ValueError, TypeError):
                persona_profile = {}
        persona_profile.setdefault("name", twin.get("name", ""))

        # Extract expertise keywords for trigger detection
        expertise_keywords: list[str] = []
        if isinstance(persona_profile, dict):
            for field in ("expertise", "skills", "specialties", "topics"):
                val = persona_profile.get(field)
                if isinstance(val, list):
                    expertise_keywords.extend(str(v) for v in val)
                elif isinstance(val, str) and val:
                    expertise_keywords.append(val)

        # Pre-fetch top KB chunks
        query = " ".join(expertise_keywords[:10]) if expertise_keywords else (
            persona_profile.get("name", "expertise knowledge")
        )
        warm_chunks = await kb_search(query=query, twin_id=twin_id, top_k=20)

        voice_id = settings.get("voice_id", "")

        _meeting_cache[meeting_id] = {
            "twin_id": twin_id,
            "twin_name": twin.get("name", ""),
            "persona_profile": persona_profile,
            "voice_id": voice_id,
            "warm_chunks": warm_chunks,
            "expertise_keywords": expertise_keywords,
            "cached_at": time.time(),
        }

        logger.info(
            "[MeetingVoice] cache warmed meeting_id=%s twin_id=%s chunks=%d keywords=%d",
            meeting_id,
            twin_id,
            len(warm_chunks),
            len(expertise_keywords),
        )
        return True

    except Exception as exc:
        logger.exception(
            "[MeetingVoice] warm_meeting_cache failed twin_id=%s meeting_id=%s: %s",
            twin_id,
            meeting_id,
            exc,
        )
        return False


def get_cached_context(meeting_id: str) -> dict | None:
    """Return cached meeting context if it exists and is within TTL.

    Args:
        meeting_id: Meeting to look up.

    Returns:
        Cached context dict, or None if expired/missing.
    """
    entry = _meeting_cache.get(meeting_id)
    if entry is None:
        return None
    age = time.time() - entry.get("cached_at", 0)
    if age > _CACHE_TTL_SECONDS:
        logger.info(
            "[MeetingVoice] cache expired meeting_id=%s age=%.0fs",
            meeting_id,
            age,
        )
        del _meeting_cache[meeting_id]
        return None
    return entry


def clear_meeting_cache(meeting_id: str) -> None:
    """Remove a meeting's cached context.

    Args:
        meeting_id: Meeting to clear from cache.
    """
    removed = _meeting_cache.pop(meeting_id, None)
    if removed:
        logger.info("[MeetingVoice] cache cleared meeting_id=%s", meeting_id)
