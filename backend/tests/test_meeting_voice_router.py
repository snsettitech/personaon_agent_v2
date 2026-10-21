"""Tests for meeting_voice router — Phase 29.

Covers:
- toggle-attendance: happy path (attend=true, attend=false), 401, 403, DB error
- mute: happy path mute/unmute, 401
- transcript webhook: valid event stored + published, wrong event type ignored,
  empty transcript ignored, invalid JSON returns ok
- _publish_event: fan-out to multiple subscribers, QueueFull handled gracefully
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.meeting_voice import router


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _build_app(user: dict | None = None, twin_ok: bool = True) -> FastAPI:
    """Build a test FastAPI app wired with the meeting_voice router.

    Injects a fake auth middleware that sets request.state.user.
    """
    app = FastAPI()

    @app.middleware("http")
    async def _inject_user(request, call_next):
        if user is not None:
            request.state.user = user
        return await call_next(request)

    if not twin_ok:
        from fastapi import HTTPException

        def _bad_ownership(*args, **kwargs):
            raise HTTPException(status_code=403, detail="Not your twin")

        app.state._bad_ownership = _bad_ownership

    app.include_router(router)
    return app


def _client(user: dict | None = None, twin_ok: bool = True) -> TestClient:
    return TestClient(_build_app(user=user, twin_ok=twin_ok), raise_server_exceptions=False)


_AUTHED_USER = {"id": "user-1", "email": "test@example.com"}
_TWIN_ID = "twin-aaa"
_MTG_ID = "mtg-bbb"


# ---------------------------------------------------------------------------
# toggle-attendance
# ---------------------------------------------------------------------------


class TestToggleAttendance:

    def _mock_sb(self):
        sb = MagicMock()
        sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock()
        return sb

    def test_attend_true_returns_ok_and_enqueues_cache(self):
        mock_sb = self._mock_sb()
        mock_outbox = MagicMock()

        with (
            patch("routers.meeting_voice.get_supabase_client", return_value=mock_sb),
            patch("routers.meeting_voice.verify_twin_ownership"),
            patch("routers.meeting_voice.get_graph_outbox", return_value=mock_outbox),
        ):
            c = _client(user=_AUTHED_USER)
            resp = c.post(
                f"/v2/meetings/{_TWIN_ID}/{_MTG_ID}/toggle-attendance",
                json={"attend": True},
            )

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "data": {"twin_attends": True}}
        mock_outbox.enqueue.assert_called_once()
        call_kwargs = mock_outbox.enqueue.call_args.kwargs
        assert call_kwargs["payload"]["meeting_id"] == _MTG_ID

    def test_attend_false_does_not_enqueue_cache(self):
        mock_sb = self._mock_sb()
        mock_outbox = MagicMock()

        with (
            patch("routers.meeting_voice.get_supabase_client", return_value=mock_sb),
            patch("routers.meeting_voice.verify_twin_ownership"),
            patch("routers.meeting_voice.get_graph_outbox", return_value=mock_outbox),
        ):
            c = _client(user=_AUTHED_USER)
            resp = c.post(
                f"/v2/meetings/{_TWIN_ID}/{_MTG_ID}/toggle-attendance",
                json={"attend": False},
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["twin_attends"] is False
        mock_outbox.enqueue.assert_not_called()

    def test_unauthenticated_returns_401(self):
        """No user in request.state → 401."""
        with (
            patch("routers.meeting_voice.get_supabase_client", return_value=self._mock_sb()),
            patch("routers.meeting_voice.verify_twin_ownership"),
        ):
            c = _client(user=None)
            resp = c.post(
                f"/v2/meetings/{_TWIN_ID}/{_MTG_ID}/toggle-attendance",
                json={"attend": True},
            )
        assert resp.status_code == 401

    def test_ownership_check_failure_returns_403(self):
        """verify_twin_ownership raises 403."""
        from fastapi import HTTPException

        with (
            patch("routers.meeting_voice.get_supabase_client", return_value=self._mock_sb()),
            patch(
                "routers.meeting_voice.verify_twin_ownership",
                side_effect=HTTPException(status_code=403, detail="Not your twin"),
            ),
        ):
            c = _client(user=_AUTHED_USER)
            resp = c.post(
                f"/v2/meetings/{_TWIN_ID}/{_MTG_ID}/toggle-attendance",
                json={"attend": True},
            )
        assert resp.status_code == 403

    def test_db_exception_returns_500(self):
        """DB update exception → 500."""
        mock_sb = MagicMock()
        mock_sb.table.side_effect = RuntimeError("DB down")

        with (
            patch("routers.meeting_voice.get_supabase_client", return_value=mock_sb),
            patch("routers.meeting_voice.verify_twin_ownership"),
        ):
            c = _client(user=_AUTHED_USER)
            resp = c.post(
                f"/v2/meetings/{_TWIN_ID}/{_MTG_ID}/toggle-attendance",
                json={"attend": True},
            )
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# mute endpoint
# ---------------------------------------------------------------------------


class TestMuteTwin:

    def test_mute_returns_ok(self):
        with (
            patch("routers.meeting_voice.verify_twin_ownership"),
        ):
            c = _client(user=_AUTHED_USER)
            resp = c.post(
                f"/v2/meetings/{_TWIN_ID}/{_MTG_ID}/mute",
                json={"muted": True},
            )
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "data": {"muted": True}}

    def test_unmute_returns_ok(self):
        with (
            patch("routers.meeting_voice.verify_twin_ownership"),
        ):
            c = _client(user=_AUTHED_USER)
            resp = c.post(
                f"/v2/meetings/{_TWIN_ID}/{_MTG_ID}/mute",
                json={"muted": False},
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["muted"] is False

    def test_mute_publishes_event(self):
        """Mute publishes twin_status event to live subscribers."""
        import asyncio
        from routers import meeting_voice as mv

        q: asyncio.Queue = asyncio.Queue()
        mv._live_subscribers[_MTG_ID] = [q]

        try:
            with patch("routers.meeting_voice.verify_twin_ownership"):
                c = _client(user=_AUTHED_USER)
                c.post(
                    f"/v2/meetings/{_TWIN_ID}/{_MTG_ID}/mute",
                    json={"muted": True},
                )
            assert not q.empty()
        finally:
            mv._live_subscribers.pop(_MTG_ID, None)

    def test_mute_publishes_gemini_control_event(self):
        with (
            patch("routers.meeting_voice.verify_twin_ownership"),
            patch("routers.gemini_live.publish_control_event") as mock_publish_control,
        ):
            c = _client(user=_AUTHED_USER)
            resp = c.post(
                f"/v2/meetings/{_TWIN_ID}/{_MTG_ID}/mute",
                json={"muted": True},
            )

        assert resp.status_code == 200
        mock_publish_control.assert_called_once_with(_MTG_ID, "mute")

    def test_unauthenticated_returns_401(self):
        with patch("routers.meeting_voice.verify_twin_ownership"):
            c = _client(user=None)
            resp = c.post(
                f"/v2/meetings/{_TWIN_ID}/{_MTG_ID}/mute",
                json={"muted": True},
            )
        assert resp.status_code == 401

    def test_mute_sends_control_frame_to_audio_queue(self):
        """Muting enqueues a {"type":"mute"} frame to audio-out queues after draining PCM."""
        import asyncio
        from services import meeting_adk_session as mgr

        q: asyncio.Queue = asyncio.Queue()
        # Pre-load a PCM chunk that should be drained
        q.put_nowait(b"\x00" * 100)

        session = mgr.MeetingSession(
            meeting_id=_MTG_ID,
            twin_id=_TWIN_ID,
            voice_name="Kore",
            live_request_queue=MagicMock(),
            player_ready_event=asyncio.Event(),
        )
        session.audio_out_queues.append(q)
        mgr._sessions[_MTG_ID] = session

        try:
            mgr.set_output_muted(_MTG_ID, True)
            # PCM chunk was drained
            assert q.qsize() == 1  # only the control frame remains
            frame = q.get_nowait()
            assert frame == {"type": "mute"}
            assert session.output_muted is True
        finally:
            mgr._sessions.pop(_MTG_ID, None)

    def test_unmute_sends_control_frame(self):
        """Unmuting enqueues {"type":"unmute"} frame."""
        import asyncio
        from services import meeting_adk_session as mgr

        q: asyncio.Queue = asyncio.Queue()
        session = mgr.MeetingSession(
            meeting_id=_MTG_ID,
            twin_id=_TWIN_ID,
            voice_name="Kore",
            live_request_queue=MagicMock(),
            player_ready_event=asyncio.Event(),
        )
        session.output_muted = True
        session.audio_out_queues.append(q)
        mgr._sessions[_MTG_ID] = session

        try:
            mgr.set_output_muted(_MTG_ID, False)
            assert session.output_muted is False
            assert q.qsize() == 1
            frame = q.get_nowait()
            assert frame == {"type": "unmute"}
        finally:
            mgr._sessions.pop(_MTG_ID, None)

    def test_mute_gate_set_before_drain(self):
        """Gate is set before drain — concurrent producer cannot sneak PCM after drain."""
        import asyncio
        from services import meeting_adk_session as mgr

        gate_was_set_during_drain = []

        q: asyncio.Queue = asyncio.Queue()
        # Pre-load a PCM chunk so the drain loop body actually runs
        q.put_nowait(b"\x00" * 100)

        session = mgr.MeetingSession(
            meeting_id=_MTG_ID,
            twin_id=_TWIN_ID,
            voice_name="Kore",
            live_request_queue=MagicMock(),
            player_ready_event=asyncio.Event(),
        )
        session.audio_out_queues.append(q)
        mgr._sessions[_MTG_ID] = session

        original_get = q.get_nowait

        def spy_get():
            # Called during drain — record whether gate is already set at dequeue time
            gate_was_set_during_drain.append(session.output_muted)
            return original_get()

        q.get_nowait = spy_get  # type: ignore[method-assign]

        try:
            mgr.set_output_muted(_MTG_ID, True)
            assert len(gate_was_set_during_drain) >= 1, "Drain body must have run"
            assert all(gate_was_set_during_drain), "Gate must be True before dequeue runs"
        finally:
            mgr._sessions.pop(_MTG_ID, None)

    def test_mute_does_not_call_send_mute_signal(self):
        """send_mute_signal must not be called — it pollutes Gemini context."""
        import asyncio
        from services import meeting_adk_session as mgr

        session = mgr.MeetingSession(
            meeting_id=_MTG_ID,
            twin_id=_TWIN_ID,
            voice_name="Kore",
            live_request_queue=MagicMock(),
            player_ready_event=asyncio.Event(),
        )
        mgr._sessions[_MTG_ID] = session
        try:
            with (
                patch("routers.meeting_voice.verify_twin_ownership"),
                patch.object(mgr, "send_mute_signal") as mock_signal,
            ):
                c = _client(user=_AUTHED_USER)
                c.post(f"/v2/meetings/{_TWIN_ID}/{_MTG_ID}/mute", json={"muted": True})
            mock_signal.assert_not_called()
        finally:
            mgr._sessions.pop(_MTG_ID, None)

    def test_mute_does_not_call_recall_mute_api(self):
        """mute_bot/unmute_bot return 400 for native audio bots — must not be called."""
        import asyncio
        from services import meeting_adk_session as mgr

        session = mgr.MeetingSession(
            meeting_id=_MTG_ID,
            twin_id=_TWIN_ID,
            voice_name="Kore",
            live_request_queue=MagicMock(),
            player_ready_event=asyncio.Event(),
        )
        mgr._sessions[_MTG_ID] = session
        try:
            with (
                patch("routers.meeting_voice.verify_twin_ownership"),
                patch("services.recall_service.mute_bot") as mock_mute,
                patch("services.recall_service.unmute_bot") as mock_unmute,
            ):
                c = _client(user=_AUTHED_USER)
                c.post(f"/v2/meetings/{_TWIN_ID}/{_MTG_ID}/mute", json={"muted": True})
                c.post(f"/v2/meetings/{_TWIN_ID}/{_MTG_ID}/mute", json={"muted": False})
            mock_mute.assert_not_called()
            mock_unmute.assert_not_called()
        finally:
            mgr._sessions.pop(_MTG_ID, None)


# ---------------------------------------------------------------------------
# transcript webhook
# ---------------------------------------------------------------------------


_WEBHOOK_SECRET = "whsec_" + base64.b64encode(b"test-secret-32-bytes-long-padding").decode()


def _signed_headers(body: bytes) -> dict:
    """Svix-style signature headers (the webhook now rejects unsigned requests)."""
    wid, ts = "msg-voice-test", str(int(time.time()))
    key = base64.b64decode(_WEBHOOK_SECRET[6:])
    msg = f"{wid}.{ts}.{body.decode()}"
    sig = base64.b64encode(hmac.new(key, msg.encode(), hashlib.sha256).digest()).decode()
    return {
        "webhook-id": wid,
        "webhook-timestamp": ts,
        "webhook-signature": f"v1,{sig}",
        "Content-Type": "application/json",
    }


class TestTranscriptWebhook:

    @pytest.fixture(autouse=True)
    def _webhook_secret(self):
        with patch("services.recall_auth.RECALL_WEBHOOK_SECRET", _WEBHOOK_SECRET):
            yield

    def _send(self, payload: dict, client: TestClient | None = None) -> object:
        if client is None:
            client = _client(user=None)  # webhook is unauthenticated (signature-verified)
        body = json.dumps(payload).encode()
        return client.post(
            "/v2/meetings/webhook/transcript", content=body, headers=_signed_headers(body)
        )

    def _mock_sb(self, meeting_id: str = _MTG_ID) -> MagicMock:
        insert_chain = MagicMock()
        insert_chain.insert.return_value.execute.return_value = MagicMock()

        meeting_lookup = MagicMock()
        meeting_lookup.select.return_value.eq.return_value.single.return_value.execute.return_value = SimpleNamespace(
            data={"id": meeting_id}
        )

        mock_sb = MagicMock()
        mock_sb.table.side_effect = lambda name: {
            "meeting_transcript_live": insert_chain,
            "meetings": meeting_lookup,
        }[name]
        return mock_sb

    def test_valid_event_returns_ok(self):
        mock_sb = self._mock_sb()

        payload = {
            "event": "transcript.data",
            "data": {
                "bot_id": "bot-123",
                "transcript": {
                    "original_transcript": "Hello everyone",
                    "speaker": "Alice",
                    "timestamp": "2026-04-16T10:00:00Z",
                },
            },
        }

        with patch("routers.meeting_voice.get_supabase_client", return_value=mock_sb):
            resp = self._send(payload)

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        mock_sb.table.assert_any_call("meeting_transcript_live")

    def test_non_transcript_event_ignored(self):
        """Events that are not transcript.data are silently discarded."""
        mock_sb = MagicMock()

        payload = {
            "event": "bot.status_change",
            "data": {"bot_id": "bot-999"},
        }

        with patch("routers.meeting_voice.get_supabase_client", return_value=mock_sb):
            resp = self._send(payload)

        assert resp.status_code == 200
        mock_sb.table.assert_not_called()

    def test_empty_transcript_text_ignored(self):
        """Empty transcript text is discarded without DB insert."""
        mock_sb = MagicMock()

        payload = {
            "event": "transcript.data",
            "data": {
                "bot_id": "bot-456",
                "transcript": {
                    "original_transcript": "",
                    "speaker": "Bob",
                },
            },
        }

        with patch("routers.meeting_voice.get_supabase_client", return_value=mock_sb):
            resp = self._send(payload)

        assert resp.status_code == 200
        mock_sb.table.assert_not_called()

    def test_partial_transcript_ignored(self):
        """Deepgram partial events (is_final=False) are discarded without DB insert."""
        mock_sb = MagicMock()

        payload = {
            "event": "transcript.data",
            "data": {
                "bot_id": "bot-partial",
                "transcript": {
                    "original_transcript": "Hello every",
                    "speaker": "Alice",
                    "is_final": False,
                },
            },
        }

        with patch("routers.meeting_voice.get_supabase_client", return_value=mock_sb):
            resp = self._send(payload)

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        mock_sb.table.assert_not_called()

    def test_final_transcript_processed(self):
        """Deepgram final events (is_final=True) are stored and published."""
        mock_sb = self._mock_sb()

        payload = {
            "event": "transcript.data",
            "data": {
                "bot_id": "bot-final",
                "transcript": {
                    "words": [
                        {"text": "Hello", "start_time": 0.1, "end_time": 0.4},
                        {"text": "everyone", "start_time": 0.5, "end_time": 0.9},
                    ],
                    "speaker": "Alice",
                    "is_final": True,
                },
            },
        }

        with patch("routers.meeting_voice.get_supabase_client", return_value=mock_sb):
            resp = self._send(payload)

        assert resp.status_code == 200
        mock_sb.table.assert_any_call("meeting_transcript_live")

    def test_invalid_json_returns_ok(self):
        """Malformed request body returns 200 ok (don't 422 Recall.ai)."""
        c = _client(user=None)
        resp = c.post(
            "/v2/meetings/webhook/transcript",
            content=b"not-json",
            headers=_signed_headers(b"not-json"),
        )
        assert resp.status_code == 200

    def test_transcript_published_to_event_bus(self):
        """Valid transcript publishes event to matching meeting_id subscribers."""
        from routers import meeting_voice as mv

        bot_id = "bot-789"
        meeting_id = "mtg-789"
        q: asyncio.Queue = asyncio.Queue()
        mv._live_subscribers[meeting_id] = [q]

        mock_sb = self._mock_sb(meeting_id=meeting_id)

        payload = {
            "event": "transcript.data",
            "data": {
                "bot_id": bot_id,
                "transcript": {
                    "original_transcript": "Published text",
                    "speaker": "Carol",
                    "timestamp": "2026-04-16T11:00:00Z",
                },
            },
        }

        try:
            with (
                patch("routers.meeting_voice.get_supabase_client", return_value=mock_sb),
                patch("routers.gemini_live.publish_transcript_event") as mock_publish_transcript,
            ):
                resp = self._send(payload)

            assert resp.status_code == 200
            assert not q.empty()
            event = q.get_nowait()
            assert event["type"] == "transcript"
            assert event["text"] == "Published text"
            assert event["speaker"] == "Carol"
            mock_publish_transcript.assert_called_once_with(
                meeting_id,
                speaker="Carol",
                text="Published text",
                timestamp="2026-04-16T11:00:00Z",
            )
        finally:
            mv._live_subscribers.pop(meeting_id, None)

    def test_db_failure_does_not_crash(self):
        """DB insert failure is caught; webhook still returns 200."""
        mock_sb = MagicMock()
        mock_sb.table.side_effect = RuntimeError("DB connection lost")

        payload = {
            "event": "transcript.data",
            "data": {
                "bot_id": "bot-fail",
                "transcript": {
                    "original_transcript": "Some speech",
                    "speaker": "Dave",
                    "timestamp": "",
                },
            },
        }

        with patch("routers.meeting_voice.get_supabase_client", return_value=mock_sb):
            resp = self._send(payload)

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# _publish_event internals
# ---------------------------------------------------------------------------


class TestPublishEvent:

    def test_fan_out_to_multiple_queues(self):
        """Event is put in every subscriber queue for the meeting."""
        from routers import meeting_voice as mv

        q1: asyncio.Queue = asyncio.Queue()
        q2: asyncio.Queue = asyncio.Queue()
        meeting_id = "mtg-fanout"
        mv._live_subscribers[meeting_id] = [q1, q2]

        try:
            mv._publish_event(meeting_id, {"type": "test", "value": 42})

            assert not q1.empty()
            assert not q2.empty()
            assert q1.get_nowait()["value"] == 42
            assert q2.get_nowait()["value"] == 42
        finally:
            mv._live_subscribers.pop(meeting_id, None)

    def test_no_subscribers_is_noop(self):
        """Publishing to meeting with no subscribers does not raise."""
        from routers import meeting_voice as mv

        mv._publish_event("mtg-no-subs-xyz", {"type": "ping"})  # must not raise

    def test_queue_full_does_not_raise(self):
        """QueueFull exception is swallowed; other queues still receive."""
        from routers import meeting_voice as mv

        full_q: asyncio.Queue = asyncio.Queue(maxsize=1)
        full_q.put_nowait({"type": "filler"})  # fill it

        ok_q: asyncio.Queue = asyncio.Queue()
        meeting_id = "mtg-full-queue"
        mv._live_subscribers[meeting_id] = [full_q, ok_q]

        try:
            mv._publish_event(meeting_id, {"type": "overflow"})  # must not raise

            # ok_q should still receive the event
            assert not ok_q.empty()
        finally:
            mv._live_subscribers.pop(meeting_id, None)


# ---------------------------------------------------------------------------
# join-now / leave
# ---------------------------------------------------------------------------


class TestJoinMeetingNow:

    def _mock_supabase(self, meeting_id: str = "mtg-join") -> MagicMock:
        twin_chain = MagicMock()
        twin_chain.select.return_value.eq.return_value.single.return_value.execute.return_value = SimpleNamespace(
            data={"name": "Alice"}
        )

        meetings_chain = MagicMock()
        meetings_chain.insert.return_value.execute.return_value = SimpleNamespace(data=[{"id": meeting_id}])
        meetings_chain.update.return_value.eq.return_value.execute.return_value = MagicMock()

        mock_sb = MagicMock()
        mock_sb.table.side_effect = lambda name: {
            "twins": twin_chain,
            "meetings": meetings_chain,
        }[name]
        return mock_sb

    def test_join_now_flag_on_uses_gemini_path(self):
        mock_sb = self._mock_supabase()

        with (
            patch("routers.meeting_voice.get_supabase_client", return_value=mock_sb),
            patch("routers.meeting_voice.verify_twin_ownership"),
            patch("routers.meeting_voice._load_twin_settings", return_value={"gemini_voice": "Aoede"}),
            patch("routers.gemini_live.issue_meeting_token", return_value="meeting-token") as mock_issue_token,
            patch("services.recall_service.create_gemini_live_bot", new_callable=AsyncMock, return_value={"id": "bot-gemini"}) as mock_gemini,
            patch.dict("os.environ", {"MEETING_GEMINI_LIVE_ENABLED": "true"}),
        ):
            c = _client(user={"id": "user-1", "tenant_id": "tenant-1"})
            resp = c.post(
                f"/v2/meetings/{_TWIN_ID}/join-now",
                json={"meet_link": "https://meet.google.com/abc"},
            )

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["bot_path"] == "gemini_live"
        mock_issue_token.assert_called_once_with(_TWIN_ID, "mtg-join")
        kwargs = mock_gemini.await_args.kwargs
        assert kwargs["voice_name"] == "Aoede"
        assert kwargs["api_key_token"] == "meeting-token"

    def test_join_now_no_flags_uses_transcript_only(self):
        """When both MEETING_NATIVE_AUDIO_ENABLED and MEETING_GEMINI_LIVE_ENABLED are
        unset/false, the dispatcher must short-circuit to create_bot (transcript-only).
        Voice/gemini/native_audio paths must NOT be invoked."""
        mock_sb = self._mock_supabase(meeting_id="mtg-transcript")

        with (
            patch.dict("os.environ", {
                "MEETING_NATIVE_AUDIO_ENABLED": "false",
                "MEETING_GEMINI_LIVE_ENABLED": "false",
            }, clear=False),
            patch("routers.meeting_voice.get_supabase_client", return_value=mock_sb),
            patch("routers.meeting_voice.verify_twin_ownership"),
            patch("services.recall_service.create_bot", new_callable=AsyncMock,
                  return_value={"id": "bot-transcript"}) as mock_transcript,
            patch("services.recall_service.create_voice_bot", new_callable=AsyncMock) as mock_voice,
            patch("services.recall_service.create_gemini_live_bot", new_callable=AsyncMock) as mock_gemini,
            patch("services.recall_service.create_native_audio_bot", new_callable=AsyncMock) as mock_native,
        ):
            c = _client(user={"id": "user-1", "tenant_id": "tenant-1"})
            resp = c.post(
                f"/v2/meetings/{_TWIN_ID}/join-now",
                json={"meet_link": "https://meet.google.com/abc"},
            )

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["bot_path"] == "transcript", (
            f"expected transcript, got {resp.json()['data']['bot_path']}"
        )
        mock_transcript.assert_awaited_once()
        mock_voice.assert_not_called()
        mock_gemini.assert_not_called()
        mock_native.assert_not_called()


class TestLeaveMeeting:

    def test_leave_removes_bot_and_publishes_control(self):
        meetings_chain = MagicMock()
        meetings_chain.select.return_value.eq.return_value.single.return_value.execute.return_value = SimpleNamespace(
            data={"recall_bot_id": "bot-123"}
        )
        meetings_chain.update.return_value.eq.return_value.execute.return_value = MagicMock()

        mock_sb = MagicMock()
        mock_sb.table.return_value = meetings_chain

        with (
            patch("routers.meeting_voice.get_supabase_client", return_value=mock_sb),
            patch("routers.meeting_voice.verify_twin_ownership"),
            patch("services.recall_service.delete_bot", new_callable=AsyncMock) as mock_delete_bot,
            patch("routers.gemini_live.publish_control_event") as mock_publish_control,
        ):
            c = _client(user=_AUTHED_USER)
            resp = c.post(f"/v2/meetings/{_TWIN_ID}/{_MTG_ID}/leave")

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["left"] is True
        mock_delete_bot.assert_awaited_once_with("bot-123")
        mock_publish_control.assert_called_once_with(_MTG_ID, "leave")
