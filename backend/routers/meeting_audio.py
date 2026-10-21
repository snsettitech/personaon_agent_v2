"""WebSocket endpoints for native audio meeting bot (Phase 30).

Two endpoints:
  /ws/meeting/{meeting_id}/audio-in  — Recall.ai connects here and streams
      audio_mixed_raw.data PCM frames for the duration of the meeting.

  /ws/meeting/{meeting_id}/audio-out — voice-agent-player.html connects here
      to receive Gemini's PCM audio response as binary WebSocket frames.
      Sending {"type": "player_ready"} unblocks the ADK live session.

Bot creation sets both URLs at creation time (see recall_service.create_native_audio_bot).
The ADK session is created in join_meeting_now() before the bot joins, so it is
already waiting for player_ready when Output Media loads.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from services import meeting_adk_session as session_mgr

logger = logging.getLogger(__name__)

router = APIRouter(tags=["meeting-audio"])


# ---------------------------------------------------------------------------
# audio-in: Recall → backend (raw PCM from meeting participants)
# ---------------------------------------------------------------------------


@router.websocket("/ws/meeting/{meeting_id}/audio-in")
async def audio_in_ws(websocket: WebSocket, meeting_id: str) -> None:
    """Receive audio_mixed_raw.data frames from Recall.ai and feed them to ADK.

    Query params (set at bot creation time in create_native_audio_bot):
      twin_id   — required, used to create the ADK session
      voice     — optional Gemini voice name, defaults to 'Kore'
    """
    twin_id = websocket.query_params.get("twin_id", "")
    voice_name = websocket.query_params.get("voice", "Kore")

    if not twin_id:
        await websocket.close(code=4000, reason="twin_id query param required")
        return

    await websocket.accept()
    logger.info(
        "[MeetingAudio] audio-in connected meeting=%s twin=%s", meeting_id, twin_id
    )

    # Create the ADK session now if it wasn't already created by join_meeting_now().
    # (Handles the case where the bot is started without going through the REST API.)
    if not session_mgr.get_session(meeting_id):
        await session_mgr.create_session(meeting_id, twin_id, voice_name)

    frames_received = 0
    try:
        while True:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                break

            # Recall sends JSON frames: {"event": "audio_mixed_raw.data", "data": {...}}
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            event_name = msg.get("event", "")
            if event_name != "audio_mixed_raw.data":
                continue

            data = msg.get("data") or {}
            # Recall payload shape: data.data.buffer (base64 PCM)
            # Defensive: also handle data.buffer as a flat fallback.
            inner = data.get("data") or {}
            b64 = inner.get("buffer") or data.get("buffer") or ""
            if not b64:
                continue

            try:
                pcm_bytes = base64.b64decode(b64)
            except Exception:
                logger.warning(
                    "[MeetingAudio] audio-in base64 decode failed meeting=%s", meeting_id
                )
                continue

            session_mgr.enqueue_audio(meeting_id, pcm_bytes)
            frames_received += 1

    except Exception as exc:
        logger.exception(
            "[MeetingAudio] audio-in error meeting=%s: %s", meeting_id, exc
        )
    finally:
        # Do NOT teardown here — Recall reconnects audio-in mid-meeting and
        # tearing down kills the ADK session permanently (player_ready never
        # re-fires for the new connection). Session cleanup is handled by:
        #   • Recall leave/end webhook → teardown_session
        #   • player_ready timeout (120s) if player never connects
        #   • 9-min Gemini reconnect loop expiry
        logger.warning(
            "[MeetingAudio] audio-in disconnected meeting=%s frames=%d — session kept alive",
            meeting_id,
            frames_received,
        )


# ---------------------------------------------------------------------------
# audio-out: backend → voice-agent-player.html (Gemini PCM response)
# ---------------------------------------------------------------------------


@router.websocket("/ws/meeting/{meeting_id}/audio-out")
async def audio_out_ws(websocket: WebSocket, meeting_id: str) -> None:
    """Stream Gemini PCM audio chunks to voice-agent-player.html as binary frames.

    The player page sends {"type": "player_ready"} on open, which unblocks the
    ADK live session (10-second timeout — failure triggers bot teardown).
    """
    await websocket.accept()
    logger.info("[MeetingAudio] audio-out connected meeting=%s", meeting_id)

    queue = session_mgr.subscribe_audio_out(meeting_id)
    if queue is None:
        # No session yet — the bot may have been delayed. Wait briefly.
        for _ in range(20):
            await asyncio.sleep(0.25)
            queue = session_mgr.subscribe_audio_out(meeting_id)
            if queue:
                break
        if queue is None:
            logger.warning(
                "[MeetingAudio] audio-out: no session for meeting=%s — closing", meeting_id
            )
            await websocket.close(code=4004, reason="No active meeting session")
            return

    try:
        # First message from player page must be {"type": "player_ready"}.
        # We use wait_for with a timeout matching _PLAYER_READY_TIMEOUT in session_mgr.
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=125.0)
            msg = json.loads(raw)
            if msg.get("type") == "player_ready":
                session_mgr.mark_player_ready(meeting_id)
                logger.info("[MeetingAudio] player_ready received meeting=%s", meeting_id)
        except asyncio.TimeoutError:
            logger.warning(
                "[MeetingAudio] audio-out: player_ready not received meeting=%s", meeting_id
            )
            # Session manager's own timeout will handle teardown.
        except (json.JSONDecodeError, WebSocketDisconnect):
            pass

        # Stream binary PCM chunks (or control frames) to the player page.
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=30.0)
                if isinstance(item, bytes):
                    await websocket.send_bytes(item)
                else:
                    await websocket.send_text(json.dumps(item))
            except asyncio.TimeoutError:
                # Keepalive: send an empty ping so the WS doesn't time out.
                try:
                    await websocket.send_text("")
                except Exception:
                    break
            except WebSocketDisconnect:
                break

    except Exception as exc:
        logger.exception(
            "[MeetingAudio] audio-out error meeting=%s: %s", meeting_id, exc
        )
    finally:
        session_mgr.unsubscribe_audio_out(meeting_id, queue)
        logger.info("[MeetingAudio] audio-out disconnected meeting=%s", meeting_id)
