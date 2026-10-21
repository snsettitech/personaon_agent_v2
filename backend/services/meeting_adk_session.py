"""ADK Live session manager for native audio meeting bots.

One MeetingSession per meeting_id. Lifecycle:
  create_session()       — called from join_meeting_now() at bot creation time
  mark_player_ready()    — called when voice-agent-player.html audio-out WS connects
  enqueue_audio()        — called per audio_mixed_raw.data frame from Recall
  subscribe_audio_out()  — called by audio-out WS handler to receive PCM chunks
  teardown_session()     — called on bot leave / error / timeout
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from google.adk.agents import Agent, LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.tools import FunctionTool
from google.genai import types

from adk_core.app import get_session_service
from adk_core.services.vector_store import search as vector_search
from modules.observability import get_supabase_client
from services.persona_core import (
    load_persona_profile,
    build_system_instruction as _persona_build_system_instruction,
)
from services.meeting_context_prep import format_context_for_instruction

logger = logging.getLogger(__name__)

APP_NAME = "personaon"
_LIVE_MODEL = os.getenv(
    "MEETING_LIVE_MODEL",
    "gemini-2.5-flash-native-audio-preview-12-2025",
)
_SESSION_RECONNECT_SECONDS = 720  # 12 min — proactive reconnect before Gemini's ~15-min deadline
_PLAYER_READY_TIMEOUT = 120.0     # seconds to wait for voice-agent-player.html (Recall bot join takes 30-90s)
_INPUT_BUFFER_SIZE = 200          # max pre-ready PCM chunks (dropped when full)
_AUDIO_OUT_QUEUE_SIZE = 100       # per-subscriber output queue depth

_sessions: dict[str, MeetingSession] = {}


@dataclass
class MeetingSession:
    meeting_id: str
    twin_id: str
    voice_name: str
    live_request_queue: LiveRequestQueue
    player_ready_event: asyncio.Event
    # One queue per connected player page (normally exactly one).
    audio_out_queues: list[asyncio.Queue] = field(default_factory=list)
    # Bounded buffer: holds raw PCM while waiting for player_ready_event.
    input_buffer: asyncio.Queue = field(
        default_factory=lambda: asyncio.Queue(maxsize=_INPUT_BUFFER_SIZE)
    )
    adk_task: asyncio.Task | None = None
    # Updated each time the server emits a LiveServerSessionResumptionUpdate.
    resumption_handle: str | None = None
    # Accumulated transcript: {"speaker": str, "text": str, "ts": float}
    transcript_parts: list[dict] = field(default_factory=list)
    # When True: _fan_out_audio drops output so the bot is silent in the meeting.
    # Gemini keeps receiving audio and building context — only output is gated.
    output_muted: bool = False
    # Timestamp of last audio-in frame (monotonic). Used by idle watchdog.
    last_audio_ts: float = 0.0
    # Idle watchdog task — stored to allow cancellation on session teardown.
    watchdog_task: asyncio.Task | None = None
    # Question/response pairing for meeting_twin_responses writes.
    pending_question: str | None = None
    pending_question_ts: float | None = None
    turn_seq: int = 0   # incremented at output write time — one per twin response


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_persona(twin_id: str) -> dict[str, Any]:
    return await load_persona_profile(twin_id)


def _build_system_instruction(twin_name: str, persona_profile: dict) -> str:
    return _persona_build_system_instruction(twin_name, persona_profile, channel="meeting")


def _make_search_tool(twin_id: str) -> FunctionTool:
    async def search_knowledge_base(query: str, top_k: int = 5) -> list[dict]:
        """Search the persona's private knowledge base."""
        logger.info(
            "[MeetingADK] search_knowledge_base query=%r twin=%s", query[:80], twin_id
        )
        return await vector_search(query=query, twin_id=twin_id, top_k=top_k)

    return FunctionTool(func=search_knowledge_base)


def _build_run_config(voice_name: str, resumption_handle: str | None) -> RunConfig:
    return RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=[types.Modality.AUDIO],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
            )
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        # proactive_audio=True: allows Gemini to speak naturally in conversation.
        # The echo feedback loop is broken by include_bot_in_recording.audio=False in Recall config.
        proactivity=types.ProactivityConfig(proactive_audio=True),
        session_resumption=types.SessionResumptionConfig(handle=resumption_handle),
    )


def _fan_out_audio(session_state: MeetingSession, audio_bytes: bytes) -> None:
    if session_state.output_muted:
        return  # bot is muted — discard so no stale burst on unmute
    for q in list(session_state.audio_out_queues):
        try:
            q.put_nowait(audio_bytes)
        except asyncio.QueueFull:
            logger.warning(
                "[MeetingADK] audio-out queue full meeting=%s", session_state.meeting_id
            )


def _fan_out_control(session_state: MeetingSession, payload: dict) -> None:
    """Enqueue a JSON control frame to all audio-out subscribers.

    Unlike _fan_out_audio, this bypasses the output_muted gate — control
    frames (mute/unmute) must always reach the player page.
    """
    for q in list(session_state.audio_out_queues):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning(
                "[MeetingADK] control queue full meeting=%s payload=%s",
                session_state.meeting_id, payload,
            )


_DEFERRAL_PHRASES = [
    "i don't have information",
    "i'm not sure about",
    "that's outside what i",
    "i can't speak to",
    "would be better placed to answer",
    "i don't know",
    "i'm unable to",
]


def _detect_deferral(text: str) -> bool:
    """Heuristic: response is a deferral if it contains a known deferral phrase."""
    lower = text.lower()
    return any(phrase in lower for phrase in _DEFERRAL_PHRASES)


def _write_twin_response_sync(
    meeting_id: str,
    twin_id: str,
    turn_seq: int,
    question_text: str | None,
    response_text: str,
    is_deferral: bool,
) -> None:
    """Synchronous upsert — call via asyncio.to_thread from async contexts."""
    sb = get_supabase_client()
    try:
        sb.table("meeting_twin_responses").upsert(
            {
                "meeting_id": meeting_id,
                "twin_id": twin_id,
                "turn_seq": turn_seq,
                "question_text": question_text,
                "response_text": response_text,
                "is_deferral": is_deferral,
                "responded_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="meeting_id,turn_seq",
            ignore_duplicates=True,
        ).execute()
    except Exception as exc:
        logger.warning(
            "[MeetingADK] twin_response write failed meeting=%s turn=%d: %s",
            meeting_id,
            turn_seq,
            exc,
        )


async def _write_twin_response(
    meeting_id: str,
    twin_id: str,
    turn_seq: int,
    question_text: str | None,
    response_text: str,
    is_deferral: bool,
) -> None:
    """Upsert a twin response row without blocking the event loop."""
    await asyncio.to_thread(
        _write_twin_response_sync,
        meeting_id, twin_id, turn_seq, question_text, response_text, is_deferral,
    )


async def _idle_watchdog(session_state: MeetingSession, idle_seconds: float = 120.0) -> None:
    """Tear down the session if no audio-in frames arrive for idle_seconds.

    Recall sends continuous PCM (including silence) while connected, so
    frame absence means the meeting ended without a webhook firing.
    Only activates after player_ready to avoid firing before the bot joins.
    """
    check_interval = 30.0
    await asyncio.sleep(check_interval)
    while session_state.meeting_id in _sessions:
        elapsed = time.monotonic() - session_state.last_audio_ts
        # last_audio_ts == 0.0 means no audio has arrived yet — skip until first frame.
        if session_state.last_audio_ts > 0 and elapsed > idle_seconds:
            logger.warning(
                "[MeetingADK] idle timeout after %.0fs meeting=%s — tearing down",
                elapsed,
                session_state.meeting_id,
            )
            await teardown_session(session_state.meeting_id, reason="idle_timeout")
            return
        await asyncio.sleep(check_interval)


def _publish_event(meeting_id: str, payload: dict) -> None:
    """Module-level shim so tests can patch services.meeting_adk_session._publish_event.

    Delegates to routers.meeting_voice._publish_event via lazy import to preserve
    the circular-import guard that was previously inside _maybe_publish_transcript.
    """
    from routers.meeting_voice import _publish_event as _router_publish  # lazy — avoids circular import
    _router_publish(meeting_id, payload)


async def _maybe_publish_transcript(meeting_id: str, event: Any) -> None:
    """Capture input/output transcription from Gemini Live events.

    Publishes to the live dashboard and accumulates in session.transcript_parts
    for persistence to the DB on teardown.

    Input events: store pending_question + pending_question_ts on session.
    Output events: pair with pending question (30s window), write twin response row,
                   increment turn_seq.
    """
    try:
        session = _sessions.get(meeting_id)

        def _record(speaker: str, text: str) -> None:
            text = text.strip()
            if not text:
                return
            _publish_event(meeting_id, {"type": "transcript", "text": text, "speaker": speaker})
            if session is not None:
                session.transcript_parts.append(
                    {"speaker": speaker, "text": text, "ts": time.time()}
                )

        # ADK 1.27.2: transcription fields are on the event directly.
        # Guard: finished=False means Gemini is still streaming partial tokens for
        # the same utterance — skip to avoid storing cumulative duplicates in the DB.
        # finished=True (or None/unset) means the utterance is complete.
        input_tx = getattr(event, "input_transcription", None)
        if input_tx and input_tx.finished is not False:
            text = (input_tx.text or "").strip()
            _record("Participant", text)
            if session is not None and text:
                session.pending_question = text
                session.pending_question_ts = time.time()

        output_tx = getattr(event, "output_transcription", None)
        if output_tx and output_tx.finished is not False:
            response_text = (output_tx.text or "").strip()
            _record("Twin", response_text)
            if session is None and response_text:
                logger.warning(
                    "[MeetingADK] output event with no active session — twin response lost meeting=%s",
                    meeting_id,
                )
            if session is not None and response_text:
                # Increment turn sequence counter — one per completed twin response.
                session.turn_seq += 1
                current_turn = session.turn_seq

                # Pair with pending question if within the 30-second window.
                question: str | None = None
                if (
                    session.pending_question is not None
                    and session.pending_question_ts is not None
                    and time.time() - session.pending_question_ts <= 30.0
                ):
                    question = session.pending_question

                # Clear pending question regardless of window (stale question is gone).
                session.pending_question = None
                session.pending_question_ts = None

                await _write_twin_response(
                    meeting_id=meeting_id,
                    twin_id=session.twin_id,
                    turn_seq=current_turn,
                    question_text=question,
                    response_text=response_text,
                    is_deferral=_detect_deferral(response_text),
                )
        # Note: content.parts[].text fallback removed — response_modalities=AUDIO means
        # text parts never appear, and output_transcription already covers the Twin side.
    except Exception as exc:
        logger.warning("[MeetingADK] transcript event error meeting=%s: %s", meeting_id, exc)


async def _flush_transcript_to_db(meeting_id: str, parts: list[dict]) -> None:
    """Write accumulated transcript + duration to meetings table."""
    if not parts:
        return
    sb = get_supabase_client()
    try:
        lines = [f"{p['speaker']}: {p['text']}" for p in parts]
        transcript_text = "\n".join(lines)

        # Derive duration from first/last transcript timestamp so the summary
        # worker's minimum-duration check works for native audio meetings.
        duration_seconds = int(parts[-1]["ts"] - parts[0]["ts"]) if len(parts) >= 2 else 0

        await asyncio.to_thread(
            lambda: sb.table("meetings").update({
                "transcript_text": transcript_text,
                # transcript_raw is JSONB — pass the list directly (postgrest serialises it)
                "transcript_raw": parts,
                "duration_seconds": duration_seconds,
            }).eq("id", meeting_id).execute()
        )
        logger.info(
            "[MeetingADK] transcript saved meeting=%s parts=%d chars=%d duration=%ds",
            meeting_id,
            len(parts),
            len(transcript_text),
            duration_seconds,
        )
    except Exception as exc:
        logger.warning("[MeetingADK] transcript flush failed meeting=%s: %s", meeting_id, exc)


# ---------------------------------------------------------------------------
# Core ADK live loop
# ---------------------------------------------------------------------------


async def _run_adk_live(session_state: MeetingSession) -> None:
    """Outer loop: gates on player_ready, flushes input buffer, runs with 9-min reconnects."""
    meeting_id = session_state.meeting_id
    twin_id = session_state.twin_id

    # --- Gate: wait for voice-agent-player.html to open the audio-out WS ---
    try:
        await asyncio.wait_for(
            session_state.player_ready_event.wait(),
            timeout=_PLAYER_READY_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.error(
            "[MeetingADK] player_ready timeout after %.0fs meeting=%s — tearing down",
            _PLAYER_READY_TIMEOUT,
            meeting_id,
        )
        try:
            from routers.meeting_voice import _publish_event
            _publish_event(meeting_id, {
                "type": "error",
                "message": "Bot audio player did not connect in time. Please retry.",
            })
        except Exception:
            pass
        await teardown_session(meeting_id, reason="player_ready_timeout")
        return

    logger.warning("[MeetingADK] player ready — starting ADK live session meeting=%s model=%s", meeting_id, _LIVE_MODEL)
    session_state.watchdog_task = asyncio.create_task(
        _idle_watchdog(session_state),
        name=f"meeting_idle_watchdog_{meeting_id}",
    )

    # --- Load persona once (reused across reconnects) ---
    logger.warning("[MeetingADK] step1 loading persona twin=%s meeting=%s", twin_id, meeting_id)
    try:
        persona = await _load_persona(twin_id)
    except Exception as exc:
        logger.exception("[MeetingADK] step1 FAILED twin=%s meeting=%s: %s", twin_id, meeting_id, exc)
        await teardown_session(meeting_id, reason="persona_load_failed")
        return
    twin_name = persona.get("twin_name", "the presenter")
    voice_name = session_state.voice_name or persona.get("voice_name", "Kore")
    persona_profile = persona.get("persona_profile", {})
    logger.warning("[MeetingADK] step2 persona loaded twin_name=%r meeting=%s", twin_name, meeting_id)

    # Load pre-fetched KB context from context_prep (best-effort — null if worker hasn't finished)
    context_suffix = ""
    try:
        _sb = get_supabase_client()
        ctx_resp = await asyncio.to_thread(
            lambda: _sb.table("meetings").select("context_prep").eq("id", meeting_id).single().execute()
        )
        ctx_data = (ctx_resp.data or {}).get("context_prep")
        context_suffix = format_context_for_instruction(ctx_data)
        if context_suffix:
            chunk_count = len((ctx_data or {}).get("chunks") or [])
            logger.info("[MeetingADK] context_prep injected meeting=%s chunks=%d", meeting_id, chunk_count)
    except Exception as _ctx_exc:
        logger.warning("[MeetingADK] context_prep load skipped meeting=%s: %s", meeting_id, _ctx_exc)

    system_instruction = _build_system_instruction(twin_name, persona_profile) + context_suffix
    logger.warning("[MeetingADK] step3 building Agent+Runner meeting=%s", meeting_id)
    try:
        agent = Agent(
            name=f"meeting_{twin_id.replace('-', '_')}",
            model=_LIVE_MODEL,
            instruction=system_instruction,
            tools=[_make_search_tool(twin_id)],
        )
        runner = Runner(
            agent=agent,
            app_name=APP_NAME,
            session_service=get_session_service(),
        )
    except Exception as exc:
        logger.exception("[MeetingADK] step3 FAILED meeting=%s: %s", meeting_id, exc)
        await teardown_session(meeting_id, reason="agent_build_failed")
        return
    logger.warning("[MeetingADK] step4 runner ready meeting=%s", meeting_id)

    # --- Reconnect loop — restarts run_live every ~9 min ---
    while meeting_id in _sessions:
        lrq = LiveRequestQueue()
        session_state.live_request_queue = lrq

        # Flush any audio that arrived before player_ready (first iteration only).
        flushed = 0
        while not session_state.input_buffer.empty():
            try:
                pcm = session_state.input_buffer.get_nowait()
                lrq.send_realtime(types.Blob(data=pcm, mime_type="audio/pcm;rate=16000"))
                flushed += 1
            except asyncio.QueueEmpty:
                break
        if flushed:
            logger.warning(
                "[MeetingADK] flushed %d buffered chunks meeting=%s", flushed, meeting_id
            )

        logger.warning("[MeetingADK] step5 creating adk session meeting=%s", meeting_id)
        run_config = _build_run_config(voice_name, session_state.resumption_handle)
        try:
            session = await runner.session_service.create_session(
                app_name=APP_NAME,
                user_id=twin_id,
                state={},
                session_id=meeting_id,  # meeting_id is already a UUID; "meeting:" prefix breaks UUID column
            )
        except Exception as exc:
            logger.exception("[MeetingADK] step5 create_session FAILED meeting=%s: %s", meeting_id, exc)
            return
        logger.warning("[MeetingADK] step6 session created — calling run_live meeting=%s", meeting_id)

        reconnect_deadline = time.monotonic() + _SESSION_RECONNECT_SECONDS
        reconnecting = False

        logger.warning("[MeetingADK] run_live starting meeting=%s", meeting_id)
        try:
            async for event in runner.run_live(
                session=session,
                live_request_queue=lrq,
                run_config=run_config,
            ):
                # Store latest resumption handle for the next connection.
                # ADK 1.27.2: field is live_session_resumption_update; payload uses new_handle.
                resumption_update = getattr(event, "live_session_resumption_update", None)
                if resumption_update:
                    handle = getattr(resumption_update, "new_handle", None)
                    if handle:
                        session_state.resumption_handle = handle

                # Fan out audio PCM to all player page subscribers.
                content = getattr(event, "content", None)
                if content:
                    for part in content.parts or []:
                        inline = getattr(part, "inline_data", None)
                        if inline and inline.data:
                            # ADK delivers inline_data.data as raw bytes (not base64).
                            audio_bytes = (
                                base64.b64decode(inline.data)
                                if isinstance(inline.data, str)
                                else inline.data
                            )
                            _fan_out_audio(session_state, audio_bytes)

                # Publish Gemini transcription to live dashboard (runs on every event).
                await _maybe_publish_transcript(meeting_id, event)

                # Approach 10-min WebSocket cap — close queue to break run_live cleanly.
                if time.monotonic() >= reconnect_deadline:
                    logger.info("[MeetingADK] 9-min reconnect meeting=%s", meeting_id)
                    reconnecting = True
                    lrq.close()
                    break

        except asyncio.CancelledError:
            lrq.close()
            logger.info("[MeetingADK] session task cancelled meeting=%s", meeting_id)
            return
        except Exception as exc:
            exc_str = str(exc)
            # Gemini Live sends 1011 when the server-side session deadline fires.
            # Treat it as a reconnect signal rather than a fatal error so the bot
            # stays active for the rest of the meeting.
            is_deadline = "1011" in exc_str or "Deadline expired" in exc_str
            if is_deadline and meeting_id in _sessions:
                logger.warning(
                    "[MeetingADK] Gemini deadline hit — reconnecting meeting=%s", meeting_id
                )
                reconnecting = True
            else:
                logger.exception(
                    "[MeetingADK] run_live error meeting=%s: %s", meeting_id, exc
                )
                return

        if not reconnecting:
            logger.warning("[MeetingADK] run_live ended normally meeting=%s", meeting_id)
            break

        # Brief pause before reconnect to avoid hammering the API.
        await asyncio.sleep(1.0)

    logger.info("[MeetingADK] session loop exited meeting=%s", meeting_id)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def create_session(
    meeting_id: str,
    twin_id: str,
    voice_name: str = "Kore",
) -> None:
    """Create and start an ADK live session for a meeting.

    Call from join_meeting_now() immediately after bot creation so the ADK
    task is already waiting for player_ready when Output Media loads.
    """
    if meeting_id in _sessions:
        logger.warning("[MeetingADK] session already exists meeting=%s", meeting_id)
        return

    session_state = MeetingSession(
        meeting_id=meeting_id,
        twin_id=twin_id,
        voice_name=voice_name,
        live_request_queue=LiveRequestQueue(),
        player_ready_event=asyncio.Event(),
    )
    _sessions[meeting_id] = session_state
    session_state.adk_task = asyncio.create_task(
        _run_adk_live(session_state),
        name=f"meeting_adk_{meeting_id}",
    )
    logger.info(
        "[MeetingADK] session created meeting=%s twin=%s voice=%s",
        meeting_id,
        twin_id,
        voice_name,
    )


def get_session(meeting_id: str) -> MeetingSession | None:
    return _sessions.get(meeting_id)


def mark_player_ready(meeting_id: str) -> None:
    """Signal that voice-agent-player.html has connected — unblocks run_live."""
    session = _sessions.get(meeting_id)
    if session:
        session.player_ready_event.set()
        logger.info("[MeetingADK] player_ready meeting=%s", meeting_id)


def enqueue_audio(meeting_id: str, pcm_bytes: bytes) -> None:
    """Route incoming PCM from Recall audio_mixed_raw.data into the live session.

    Before player_ready: buffered (bounded — oldest chunks silently dropped when full).
    After player_ready: sent directly to LiveRequestQueue.
    """
    session = _sessions.get(meeting_id)
    if not session:
        return
    session.last_audio_ts = time.monotonic()
    if session.player_ready_event.is_set():
        try:
            session.live_request_queue.send_realtime(
                types.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000")
            )
        except Exception as exc:
            logger.warning(
                "[MeetingADK] send_realtime failed meeting=%s: %s", meeting_id, exc
            )
    else:
        try:
            session.input_buffer.put_nowait(pcm_bytes)
        except asyncio.QueueFull:
            pass  # bounded — silently drop oldest-style (queue rejects newest)


def subscribe_audio_out(meeting_id: str) -> asyncio.Queue | None:
    """Register a new audio-out subscriber. Returns its queue, or None if no session."""
    session = _sessions.get(meeting_id)
    if not session:
        return None
    q: asyncio.Queue[bytes | dict] = asyncio.Queue(maxsize=_AUDIO_OUT_QUEUE_SIZE)
    session.audio_out_queues.append(q)
    return q


def unsubscribe_audio_out(meeting_id: str, queue: asyncio.Queue) -> None:
    session = _sessions.get(meeting_id)
    if session:
        try:
            session.audio_out_queues.remove(queue)
        except ValueError:
            pass


def set_output_muted(meeting_id: str, muted: bool) -> None:
    """Gate audio output and signal the player page.

    Mute sequence (concurrency-safe):
      1. Set gate FIRST — closes _fan_out_audio before drain runs
      2. Drain queue — removes PCM already enqueued before gate closed
      3. Enqueue control frame — player suspends/resumes AudioContext

    Unmute sequence:
      1. Clear gate
      2. Enqueue control frame — player resumes AudioContext
    """
    session = _sessions.get(meeting_id)
    if not session:
        return
    # Gate first. Within a single asyncio event-loop thread there is no await
    # between here and the drain below, so _fan_out_audio cannot enqueue new PCM
    # between gate-set and drain completion.
    session.output_muted = muted
    if muted:
        for q in list(session.audio_out_queues):
            while not q.empty():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    break
        _fan_out_control(session, {"type": "mute"})
        logger.info("[MeetingADK] output muted meeting=%s", meeting_id)
    else:
        _fan_out_control(session, {"type": "unmute"})
        logger.info("[MeetingADK] output unmuted meeting=%s", meeting_id)


def send_mute_signal(meeting_id: str, muted: bool) -> None:
    """Send a text instruction to Gemini to stop/resume generating speech.

    Best-effort: reduces unnecessary token generation while muted.
    Gemini still processes audio input and maintains full session context.
    """
    session = _sessions.get(meeting_id)
    if not session:
        return
    text = (
        "You are now muted. Keep listening and building context but do not speak until unmuted."
        if muted else
        "You are now unmuted. Resume participating. You have full context of everything said while muted."
    )
    try:
        session.live_request_queue.send_content(
            content=types.Content(
                role="user",
                parts=[types.Part(text=text)],
            )
        )
    except Exception as exc:
        logger.debug("[MeetingADK] send_mute_signal failed meeting=%s: %s", meeting_id, exc)


async def teardown_session(meeting_id: str, reason: str = "normal") -> None:
    """Cancel the ADK task, persist transcript, and remove the session."""
    session = _sessions.pop(meeting_id, None)
    if not session:
        return
    if session.adk_task and not session.adk_task.done():
        session.adk_task.cancel()
        try:
            await session.adk_task
        except asyncio.CancelledError:
            pass
    if session.watchdog_task and not session.watchdog_task.done():
        session.watchdog_task.cancel()
        try:
            await session.watchdog_task
        except asyncio.CancelledError:
            pass
    try:
        session.live_request_queue.close()
    except Exception:
        pass
    logger.info(
        "[MeetingADK] session torn down meeting=%s reason=%s parts=%d",
        meeting_id,
        reason,
        len(session.transcript_parts),
    )
    await _flush_transcript_to_db(meeting_id, session.transcript_parts)
