"""
Recall.ai API Client Service

Manages meeting bot lifecycle: create, fetch status, get transcript, delete.
Used by graph_outbox workers (SCHEDULE_MEETING_BOT, PROCESS_MEETING_TRANSCRIPT).

Recall.ai docs: https://docs.recall.ai/
Auth: Bearer token via RECALL_API_KEY env var.
"""

import logging
import os
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

RECALL_API_KEY = os.getenv("RECALL_API_KEY", "")
RECALL_API_REGION = os.getenv("RECALL_API_REGION", "us-east-1")
RECALL_BASE_URL = f"https://{RECALL_API_REGION}.recall.ai/api/v1"
BACKEND_BASE_URL = os.getenv(
    "CLOUD_RUN_SERVICE_URL",
    os.getenv("APP_BASE_URL", "http://localhost:8006"),
)

MEETING_INTELLIGENCE_ENABLED = (
    os.getenv("MEETING_INTELLIGENCE_ENABLED", "false").lower() == "true"
)

_TIMEOUT = 15.0


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Token {RECALL_API_KEY}",
        "Content-Type": "application/json",
    }


def format_bot_name(user_name: str) -> str:
    """Format bot display name as '[User]'s AI Assistant', max 100 chars."""
    name = f"{user_name}'s AI Assistant"
    return name[:100]


def _require_backend_base_url() -> str:
    if BACKEND_BASE_URL:
        return BACKEND_BASE_URL.rstrip("/")
    raise RuntimeError("CLOUD_RUN_SERVICE_URL or APP_BASE_URL must be configured for Recall.ai callbacks")


def _redacted_url(url: str) -> str:
    return url.split("?", 1)[0]


def _voice_agent_token(twin_id: str, meeting_id: str) -> str:
    try:
        from routers.gemini_live import issue_meeting_token

        return issue_meeting_token(twin_id, meeting_id)
    except Exception:
        logger.warning(
            "[RecallService] could not issue meeting token for voice agent twin_id=%s meeting_id=%s",
            twin_id,
            meeting_id,
        )
        return ""


async def create_bot(
    meeting_url: str,
    bot_name: str,
    metadata: dict | None = None,
    join_at: str | None = None,
) -> dict:
    """Create a Recall.ai bot to join a meeting.

    Args:
        meeting_url: The meeting link (Zoom/Meet/Teams).
        bot_name: Display name for the bot in the meeting (1-100 chars).
        metadata: Optional metadata dict (stored on bot, returned in webhooks).
        join_at: Optional ISO 8601 datetime for scheduled join.

    Returns:
        Bot creation response dict (includes 'id' field = bot_id).
    """
    # Use recording_config (current API) — transcription_options is deprecated v1.10
    # recallai_streaming: Recall's paid built-in transcription at $0.15/hr.
    # Chosen over the free `meeting_captions` provider for consistent diarization
    # across Zoom/Meet/Teams (captions quality varies by platform). See
    # docs/superpowers/plans/recall-probe-2026-05.md for the cost/quality analysis.
    #
    # No webhooks are registered on the bot itself. Bot LIFECYCLE events
    # (bot.joining_call / bot.in_call_recording / bot.done) are delivered ONLY via
    # the account-level webhook configured in the Recall dashboard → must point at
    # {prod}/v2/meetings/webhook/recall with a matching RECALL_WEBHOOK_SECRET. They
    # CANNOT be registered per-bot and CANNOT ride on realtime_endpoints (per Recall
    # docs). The transcript+recap pipeline triggers on bot.done, which fetches the
    # diarized transcript from Recall's API — so if that dashboard webhook is missing
    # the whole pipeline stalls at status=bot_joining (the prod failure on 2026-06-08).
    #
    # Live in-call transcript streaming (a per-bot realtime_endpoints transcript.data
    # webhook) is intentionally NOT wired here: Recall signs realtime webhooks with its
    # workspace-verification scheme, NOT the Svix format that transcript_webhook
    # currently verifies — they would 401. Deferred to a follow-up that implements
    # Recall realtime verification and is validated against live staging traffic.
    payload: dict = {
        "meeting_url": meeting_url,
        "bot_name": bot_name,
        "recording_config": {
            "transcript": {
                "provider": {
                    "recallai_streaming": {
                        "mode": "prioritize_accuracy",
                        "language_code": "auto",
                    }
                },
                "diarization": {
                    "use_separate_streams_when_available": True,
                },
            },
        },
    }
    if metadata:
        payload["metadata"] = metadata
    if join_at:
        payload["join_at"] = join_at

    logger.info(
        "[RecallService] create_bot meeting_url=%s bot_name=%s",
        meeting_url,
        bot_name,
    )

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{RECALL_BASE_URL}/bot/",
            headers=_headers(),
            json=payload,
        )
        if not resp.is_success:
            logger.error(
                "[RecallService] create_bot failed status=%s body=%s",
                resp.status_code,
                resp.text,
            )
            resp.raise_for_status()
        result = resp.json()
        logger.info("[RecallService] bot created id=%s", result.get("id"))
        return result


async def create_desktop_sdk_upload(
    metadata: dict | None = None,
    recording_config: dict | None = None,
) -> dict:
    """Create a Recall.ai Desktop SDK upload and return its upload token.

    The upload token is safe to return to the Electron app; the Recall API key
    stays on the backend.
    """
    payload: dict = {}
    if metadata:
        payload["metadata"] = metadata
    if recording_config:
        payload["recording_config"] = recording_config

    # Redact desktop_window_url from logs (client-supplied URLs may carry
    # OAuth tokens, session params, or internal path fragments).
    _safe_meta = {
        k: ("<redacted>" if k == "desktop_window_url" else v)
        for k, v in (metadata or {}).items()
    }
    logger.info("[RecallService] create_desktop_sdk_upload metadata=%s", _safe_meta)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{RECALL_BASE_URL}/sdk_upload/",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        result = resp.json()
        logger.info(
            "[RecallService] desktop sdk upload created id=%s recording_id=%s status=%s",
            result.get("id"),
            result.get("recording_id"),
            result.get("status"),
        )
        return result


async def get_recording(recording_id: str) -> dict:
    """Fetch a Recall.ai Recording object by its ID.

    Used by the Desktop SDK pipeline after `sdk_upload.complete` to read the
    `media_shortcuts` (video_mixed, transcript, participant_events) and
    `started_at`/`completed_at` timestamps.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{RECALL_BASE_URL}/recording/{recording_id}/",
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def download_transcript_json(transcript_url: str) -> list[dict]:
    """Download the diarised transcript JSON from a Recall.ai signed S3 URL.

    The URL is publicly readable (pre-signed) so we send no Authorization
    header — Recall's bucket would reject one if we did. Returns the canonical
    entries list (each entry has `participant.name` and `words[].text` plus
    timestamps) that `analyze_meeting()` and friends already consume, OR an
    empty list if the response was malformed.

    Used by the Desktop SDK pipeline to populate `meetings.transcript_raw` and
    `meetings.transcript_text` so the source-agnostic
    `_process_generate_meeting_summary` handler can run unchanged.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(transcript_url)
        resp.raise_for_status()
        data = resp.json()
    return data if isinstance(data, list) else []


async def get_bot(bot_id: str) -> dict:
    """Get bot status and metadata."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{RECALL_BASE_URL}/bot/{bot_id}/",
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def get_bot_transcript(bot_id: str) -> list[dict]:
    """Fetch the diarized transcript for a completed bot session.

    Uses the bot's recordings[].media_shortcuts.transcript.data.download_url
    (the legacy /bot/{id}/transcript/ endpoint returns 400).

    Returns list of transcript entries with participant + words array.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: get bot details to find the transcript download URL
        resp = await client.get(
            f"{RECALL_BASE_URL}/bot/{bot_id}/",
            headers=_headers(),
        )
        resp.raise_for_status()
        bot = resp.json()

        recordings = bot.get("recordings") or []
        if not recordings:
            logger.warning("[RecallService] no recordings for bot=%s", bot_id)
            return []

        shortcuts = recordings[0].get("media_shortcuts") or {}
        transcript_media = shortcuts.get("transcript") or {}
        download_url = (transcript_media.get("data") or {}).get("download_url")

        if not download_url:
            logger.warning(
                "[RecallService] transcript download_url missing for bot=%s", bot_id
            )
            return []

        # Step 2: download the pre-signed S3 URL (no auth header)
        transcript_resp = await client.get(download_url)
        transcript_resp.raise_for_status()
        return transcript_resp.json()


async def mute_bot(bot_id: str) -> None:
    """Silence the bot's audio output in the meeting via Recall's output_audio API."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{RECALL_BASE_URL}/bot/{bot_id}/output_audio/",
            headers=_headers(),
            json={"kind": "silence"},
        )
        resp.raise_for_status()
    logger.info("[RecallService] bot muted bot=%s", bot_id)


async def unmute_bot(bot_id: str) -> None:
    """Restore the bot's audio output in the meeting."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{RECALL_BASE_URL}/bot/{bot_id}/output_audio/",
            headers=_headers(),
            json={"kind": "play"},
        )
        resp.raise_for_status()
    logger.info("[RecallService] bot unmuted bot=%s", bot_id)


async def create_voice_bot(
    meeting_url: str,
    bot_name: str,
    twin_id: str,
    meeting_id: str,
    metadata: dict | None = None,
    join_at: str | None = None,
) -> dict:
    """Create a Recall.ai bot with Output Media (webpage), Deepgram STT, and web_4_core.

    The bot renders a voice-agent webpage that acts as the twin's audio bridge
    into the meeting. Native Deepgram streaming provides real-time transcription.

    Args:
        meeting_url: The meeting link (Zoom/Meet/Teams).
        bot_name: Display name for the bot (1-100 chars).
        twin_id: Twin whose persona the bot represents.
        meeting_id: Internal meeting ID for cache/context lookup.
        metadata: Optional metadata dict stored on the bot.
        join_at: Optional ISO 8601 datetime for scheduled join.

    Returns:
        Bot creation response dict (includes 'id' field = bot_id).
    """
    backend_base_url = _require_backend_base_url()
    params = {
        "twin_id": twin_id,
        "meeting_id": meeting_id,
    }
    api_key_token = _voice_agent_token(twin_id, meeting_id)
    if api_key_token:
        params["api_key_token"] = api_key_token
    webpage_url = (
        f"{backend_base_url}/static/voice-agent.html"
        f"?{urlencode(params)}"
    )
    webhook_url = f"{backend_base_url}/v2/meetings/webhook/transcript"

    payload: dict = {
        "meeting_url": meeting_url,
        "bot_name": bot_name,
        "output_media": {
            "camera": {
                "kind": "webpage",
                "config": {
                    "url": webpage_url,
                },
            },
        },
        "recording_config": {
            "transcript": {
                "provider": {
                    "deepgram_streaming": {
                        "model": "nova-3",
                        "language": "multi",
                    },
                },
            },
            "include_bot_in_recording": {
                "audio": True,
            },
            "realtime_endpoints": [
                {
                    "type": "webhook",
                    "url": webhook_url,
                    "events": ["transcript.data"],
                },
            ],
        },
        "variant": {
            "zoom": "web_4_core",
            "google_meet": "web_4_core",
            "microsoft_teams": "web_4_core",
        },
    }
    if metadata:
        payload["metadata"] = metadata
    if join_at:
        payload["join_at"] = join_at

    logger.info(
        "[RecallService] create_voice_bot meeting_url=%s twin_id=%s meeting_id=%s",
        meeting_url,
        twin_id,
        meeting_id,
    )

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{RECALL_BASE_URL}/bot/",
            headers=_headers(),
            json=payload,
        )
        if not resp.is_success:
            logger.error(
                "[RecallService] create_voice_bot failed status=%s body=%s",
                resp.status_code,
                resp.text,
            )
            resp.raise_for_status()
        result = resp.json()
        logger.info("[RecallService] voice bot created id=%s", result.get("id"))
        return result


async def create_gemini_live_bot(
    meeting_url: str,
    bot_name: str,
    twin_id: str,
    meeting_id: str,
    voice_name: str = "Kore",
    api_key_token: str = "",
    metadata: dict | None = None,
    join_at: str | None = None,
) -> dict:
    """Create a Recall.ai bot that renders voice-agent-gemini.html as its camera.

    Uses Deepgram streaming (nova-3) for realtime transcription — transcript.data
    webhook events feed the live dashboard and Gemini text-turn path. Gemini Live
    also attempts direct audio capture in the browser as a parallel path; whichever
    fires first wins. No ElevenLabs — Gemini Live handles TTS natively.

    Sibling to `create_voice_bot` — the existing function is preserved for
    fallback and for the voice-clone (premium) tier.

    Args:
        meeting_url: The meeting link (Zoom/Meet/Teams).
        bot_name: Display name for the bot (1-100 chars).
        twin_id: Twin whose persona the bot represents.
        meeting_id: Internal meeting ID for cache/context lookup.
        voice_name: Gemini Live prebuilt voice — one of Puck, Charon, Kore,
            Fenrir, Aoede, Leda, Orus, Zephyr. Defaults to Kore (neutral).
        api_key_token: Meeting-scoped token the webpage uses to fetch a
            Gemini Live ephemeral auth token via
            `/v2/gemini-live/{twin_id}/ephemeral-token`.
        metadata: Optional metadata dict stored on the bot.
        join_at: Optional ISO 8601 datetime for scheduled join.

    Returns:
        Bot creation response dict (includes 'id' field = bot_id).
    """
    backend_base_url = _require_backend_base_url()
    params = urlencode({
        "twin_id": twin_id,
        "meeting_id": meeting_id,
        "voice": voice_name,
        "api_key_token": api_key_token,
    })
    webpage_url = f"{backend_base_url}/static/voice-agent-gemini.html?{params}"
    webhook_url = f"{backend_base_url}/v2/meetings/webhook/transcript"

    payload: dict = {
        "meeting_url": meeting_url,
        "bot_name": bot_name,
        "output_media": {
            "camera": {
                "kind": "webpage",
                "config": {
                    "url": webpage_url,
                },
            },
        },
        "recording_config": {
            "transcript": {
                "provider": {
                    "deepgram_streaming": {
                        "model": "nova-3",
                        "language": "multi",
                    },
                }
            },
            "include_bot_in_recording": {
                "audio": True,
            },
            # Realtime endpoints: webhook receives transcript.data finals from
            # Deepgram, feeds live dashboard and Gemini text-turn path.
            "realtime_endpoints": [
                {
                    "type": "webhook",
                    "url": webhook_url,
                    "events": ["transcript.data"],
                },
            ],
        },
        "variant": {
            "zoom": "web_4_core",
            "google_meet": "web_4_core",
            "microsoft_teams": "web_4_core",
        },
    }
    if metadata:
        payload["metadata"] = metadata
    if join_at:
        payload["join_at"] = join_at

    logger.info(
        "[RecallService] create_gemini_live_bot meeting_url=%s twin_id=%s meeting_id=%s voice=%s",
        meeting_url,
        twin_id,
        meeting_id,
        voice_name,
    )

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{RECALL_BASE_URL}/bot/",
            headers=_headers(),
            json=payload,
        )
        if not resp.is_success:
            logger.error(
                "[RecallService] create_gemini_live_bot failed status=%s body=%s",
                resp.status_code,
                resp.text,
            )
            resp.raise_for_status()
        result = resp.json()
        logger.info("[RecallService] gemini-live bot created id=%s", result.get("id"))
        return result


async def create_native_audio_bot(
    meeting_url: str,
    bot_name: str,
    twin_id: str,
    meeting_id: str,
    voice_name: str = "Kore",
    metadata: dict | None = None,
    join_at: str | None = None,
) -> dict:
    """Create a Recall.ai bot for native audio-to-audio via ADK Live.

    Input path:  Recall streams raw PCM (audio_mixed_raw.data) via WebSocket to
                 our backend → ADK LiveRequestQueue → gemini-2.5-flash-native-audio.
    Output path: ADK emits PCM → audio-out WebSocket → voice-agent-player.html
                 (Output Media headless page) → AudioContext → Recall captures as bot mic.

    No Deepgram, no transcript webhook. Gemini handles STT/VAD/TTS natively.
    ElevenLabs greeting (cloned voice) is sent via the audio-out channel before
    ADK takes over — see services/meeting_adk_session.py for the session lifecycle.

    Args:
        meeting_url: The meeting link (Zoom/Meet/Teams).
        bot_name:    Display name for the bot (1-100 chars).
        twin_id:     Twin whose persona the bot represents.
        meeting_id:  Internal meeting ID; embedded in both WebSocket URLs.
        voice_name:  Gemini prebuilt voice (Kore, Puck, Charon, Fenrir, Aoede, …).
        metadata:    Optional metadata dict stored on the bot and returned in webhooks.
        join_at:     Optional ISO 8601 datetime for scheduled join.

    Returns:
        Bot creation response dict (includes 'id' field = bot_id).
    """
    from urllib.parse import urlencode

    # Output Media: PCM player page — receives Gemini audio via audio-out WS.
    # twin_name is passed so the page can show the persona name in the video tile.
    from urllib.parse import quote as _quote
    backend_base_url = _require_backend_base_url()
    player_url = (
        f"{backend_base_url}/static/voice-agent-player.html"
        f"?meeting_id={meeting_id}&twin_name={_quote(bot_name)}"
    )

    # audio-in WebSocket: Recall opens this connection and streams raw PCM frames.
    # twin_id and voice are query params so the WS handler can start the ADK session
    # without a DB lookup.
    ws_base = backend_base_url.replace("https://", "wss://").replace("http://", "ws://")
    audio_in_params = urlencode({"twin_id": twin_id, "voice": voice_name})
    audio_in_url = f"{ws_base}/ws/meeting/{meeting_id}/audio-in?{audio_in_params}"

    payload: dict = {
        "meeting_url": meeting_url,
        "bot_name": bot_name,
        "output_media": {
            "camera": {
                "kind": "webpage",
                "config": {"url": player_url},
            },
        },
        "recording_config": {
            # No transcript.provider — Gemini native audio handles STT internally.
            # audio_mixed_raw must be explicitly enabled for the websocket endpoint.
            # audio=False: exclude bot's own Output Media playback from the mixed stream
            # to prevent echo feedback that causes Gemini to loop on its own responses.
            "audio_mixed_raw": {},
            "include_bot_in_recording": {"audio": False},
            "realtime_endpoints": [
                {
                    "type": "websocket",
                    "url": audio_in_url,
                    "events": ["audio_mixed_raw.data"],
                },
            ],
        },
        "variant": {
            "zoom": "web_4_core",
            "google_meet": "web_4_core",
            "microsoft_teams": "web_4_core",
        },
    }
    if metadata:
        payload["metadata"] = metadata
    if join_at:
        payload["join_at"] = join_at

    logger.info(
        "[RecallService] create_native_audio_bot meeting_url=%s twin_id=%s meeting_id=%s voice=%s",
        meeting_url,
        twin_id,
        meeting_id,
        voice_name,
    )

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{RECALL_BASE_URL}/bot/",
            headers=_headers(),
            json=payload,
        )
        if not resp.is_success:
            logger.error(
                "[RecallService] create_native_audio_bot failed status=%s body=%s",
                resp.status_code,
                resp.text,
            )
            resp.raise_for_status()
        result = resp.json()
        logger.info(
            "[RecallService] native audio bot created id=%s", result.get("id")
        )
        return result


async def start_output_media(bot_id: str, webpage_url: str) -> dict:
    """Start Output Media on an existing bot (renders webpage as camera).

    Args:
        bot_id: The Recall.ai bot ID.
        webpage_url: Publicly-accessible URL of the voice-agent page.

    Returns:
        Output media creation response dict.
    """
    logger.info(
        "[RecallService] start_output_media bot_id=%s url=%s",
        bot_id,
        _redacted_url(webpage_url),
    )
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{RECALL_BASE_URL}/bot/{bot_id}/output_media/",
            headers=_headers(),
            json={
                "camera": {
                    "kind": "webpage",
                    "config": {"url": webpage_url},
                },
            },
        )
        resp.raise_for_status()
        return resp.json()


async def stop_output_media(bot_id: str) -> None:
    """Stop Output Media on a bot (removes camera webpage).

    Args:
        bot_id: The Recall.ai bot ID.
    """
    logger.info("[RecallService] stop_output_media bot_id=%s", bot_id)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.request(
            "DELETE",
            f"{RECALL_BASE_URL}/bot/{bot_id}/output_media/",
            headers=_headers(),
            json={"camera": True},
        )
        resp.raise_for_status()


async def delete_bot(bot_id: str) -> None:
    """Delete a bot (cancels if not yet joined, removes if completed)."""
    logger.info("[RecallService] delete_bot id=%s", bot_id)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(
            f"{RECALL_BASE_URL}/bot/{bot_id}/",
            headers=_headers(),
        )
        resp.raise_for_status()
