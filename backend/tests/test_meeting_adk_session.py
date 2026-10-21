"""Tests for twin response pairing and deferral detection in meeting_adk_session."""
import asyncio
from unittest.mock import MagicMock, patch

from services import meeting_adk_session as mgr

_MTG_ID = "aaaaaaaa-0000-0000-0000-000000000001"
_TWIN_ID = "bbbbbbbb-0000-0000-0000-000000000001"


def _make_session(**kwargs) -> mgr.MeetingSession:
    defaults = dict(
        meeting_id=_MTG_ID,
        twin_id=_TWIN_ID,
        voice_name="Kore",
        live_request_queue=MagicMock(),
        player_ready_event=asyncio.Event(),
    )
    defaults.update(kwargs)
    return mgr.MeetingSession(**defaults)


class TestMeetingSessionFields:

    def test_pending_question_defaults_none(self):
        s = _make_session()
        assert s.pending_question is None

    def test_pending_question_ts_defaults_none(self):
        s = _make_session()
        assert s.pending_question_ts is None

    def test_turn_seq_defaults_zero(self):
        s = _make_session()
        assert s.turn_seq == 0


class TestDetectDeferral:

    def test_known_deferral_phrase(self):
        assert mgr._detect_deferral("I don't have information about that topic") is True

    def test_unknown_phrase_not_deferral(self):
        assert mgr._detect_deferral("Great question, the answer is 42") is False

    def test_case_insensitive(self):
        assert mgr._detect_deferral("I DON'T HAVE INFORMATION on this") is True

    def test_empty_string_not_deferral(self):
        assert mgr._detect_deferral("") is False

    def test_partial_match(self):
        assert mgr._detect_deferral("I'm not sure about the exact figure") is True


class TestWriteTwinResponse:

    def test_writes_row_to_db(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("services.meeting_adk_session.get_supabase_client", return_value=mock_sb):
            asyncio.run(mgr._write_twin_response(
                meeting_id=_MTG_ID,
                twin_id=_TWIN_ID,
                turn_seq=1,
                question_text="What is your approach?",
                response_text="I focus on first principles.",
                is_deferral=False,
            ))

        mock_sb.table.assert_called_with("meeting_twin_responses")
        call_args = mock_sb.table.return_value.upsert.call_args
        row = call_args[0][0]
        assert row["meeting_id"] == _MTG_ID
        assert row["twin_id"] == _TWIN_ID
        assert row["turn_seq"] == 1
        assert row["question_text"] == "What is your approach?"
        assert row["response_text"] == "I focus on first principles."
        assert row["is_deferral"] is False

    def test_upsert_on_conflict(self):
        """Uses on_conflict so re-emit is idempotent."""
        mock_sb = MagicMock()
        mock_sb.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("services.meeting_adk_session.get_supabase_client", return_value=mock_sb):
            asyncio.run(mgr._write_twin_response(_MTG_ID, _TWIN_ID, 1, None, "text", False))
            asyncio.run(mgr._write_twin_response(_MTG_ID, _TWIN_ID, 1, None, "text", False))

        assert mock_sb.table.return_value.upsert.call_count == 2
        kwargs = mock_sb.table.return_value.upsert.call_args_list[0][1]
        assert kwargs.get("on_conflict") == "meeting_id,turn_seq"

    def test_write_does_not_raise_on_db_error(self):
        """_write_twin_response must not propagate DB exceptions."""
        mock_sb = MagicMock()
        mock_sb.table.return_value.upsert.return_value.execute.side_effect = Exception("db down")
        with patch("services.meeting_adk_session.get_supabase_client", return_value=mock_sb):
            # must not raise
            asyncio.run(
                mgr._write_twin_response(_MTG_ID, _TWIN_ID, 1, None, "text", False)
            )


class TestMaybePublishTranscript:

    def _make_event(self, input_text=None, output_text=None, finished=True):
        """Build a minimal mock ADK event."""
        event = MagicMock()
        if input_text is not None:
            tx = MagicMock()
            tx.text = input_text
            tx.finished = finished
            event.input_transcription = tx
        else:
            event.input_transcription = None
        if output_text is not None:
            tx = MagicMock()
            tx.text = output_text
            tx.finished = finished
            event.output_transcription = tx
        else:
            event.output_transcription = None
        return event

    def test_input_sets_pending_question(self):
        session = _make_session()
        mgr._sessions[_MTG_ID] = session

        with patch("services.meeting_adk_session._publish_event", MagicMock()):
            asyncio.run(mgr._maybe_publish_transcript(_MTG_ID, self._make_event(input_text="What's your view?")))

        assert session.pending_question == "What's your view?"
        assert session.pending_question_ts is not None
        mgr._sessions.pop(_MTG_ID, None)

    def test_output_within_window_pairs_question(self):
        import time as time_module
        session = _make_session()
        session.pending_question = "What's your view?"
        session.pending_question_ts = time_module.time()
        mgr._sessions[_MTG_ID] = session

        written = []

        async def capture_write(meeting_id, twin_id, turn_seq, question_text, response_text, is_deferral):
            written.append({"question_text": question_text, "response_text": response_text})

        with patch("services.meeting_adk_session._write_twin_response", side_effect=capture_write):
            with patch("services.meeting_adk_session._publish_event", MagicMock()):
                asyncio.run(mgr._maybe_publish_transcript(_MTG_ID, self._make_event(output_text="I think X")))

        assert len(written) == 1
        assert written[0]["question_text"] == "What's your view?"
        assert written[0]["response_text"] == "I think X"
        assert session.pending_question is None
        assert session.turn_seq == 1
        mgr._sessions.pop(_MTG_ID, None)

    def test_output_outside_window_question_text_is_none(self):
        import time as time_module
        session = _make_session()
        session.pending_question = "Old question"
        session.pending_question_ts = time_module.time() - 35.0
        mgr._sessions[_MTG_ID] = session

        written = []

        async def capture_write(meeting_id, twin_id, turn_seq, question_text, response_text, is_deferral):
            written.append({"question_text": question_text})

        with patch("services.meeting_adk_session._write_twin_response", side_effect=capture_write):
            with patch("services.meeting_adk_session._publish_event", MagicMock()):
                asyncio.run(mgr._maybe_publish_transcript(_MTG_ID, self._make_event(output_text="My answer")))

        assert written[0]["question_text"] is None
        mgr._sessions.pop(_MTG_ID, None)

    def test_output_no_pending_question(self):
        session = _make_session()
        mgr._sessions[_MTG_ID] = session

        written = []

        async def capture_write(meeting_id, twin_id, turn_seq, question_text, response_text, is_deferral):
            written.append({"question_text": question_text})

        with patch("services.meeting_adk_session._write_twin_response", side_effect=capture_write):
            with patch("services.meeting_adk_session._publish_event", MagicMock()):
                asyncio.run(mgr._maybe_publish_transcript(_MTG_ID, self._make_event(output_text="Proactive remark")))

        assert written[0]["question_text"] is None
        mgr._sessions.pop(_MTG_ID, None)

    def test_turn_seq_increments_per_output(self):
        import time as time_module
        session = _make_session()
        mgr._sessions[_MTG_ID] = session

        async def noop_write(*args, **kwargs):
            pass

        with patch("services.meeting_adk_session._write_twin_response", side_effect=noop_write):
            with patch("services.meeting_adk_session._publish_event", MagicMock()):
                for i in range(3):
                    session.pending_question = f"Q{i}"
                    session.pending_question_ts = time_module.time()
                    asyncio.run(mgr._maybe_publish_transcript(_MTG_ID, self._make_event(output_text=f"A{i}")))

        assert session.turn_seq == 3
        mgr._sessions.pop(_MTG_ID, None)

    def test_input_partial_not_stored(self):
        session = _make_session()
        session.pending_question = "original"
        mgr._sessions[_MTG_ID] = session

        with patch("services.meeting_adk_session._publish_event", MagicMock()):
            asyncio.run(mgr._maybe_publish_transcript(
                _MTG_ID, self._make_event(input_text="partial...", finished=False)
            ))

        assert session.pending_question == "original"
        mgr._sessions.pop(_MTG_ID, None)

    def test_output_partial_not_written(self):
        """output_transcription with finished=False must not write a DB row or increment turn_seq."""
        session = _make_session()
        mgr._sessions[_MTG_ID] = session

        write_called = []

        async def capture_write(*args, **kwargs):
            write_called.append(True)

        with patch("services.meeting_adk_session._write_twin_response", side_effect=capture_write):
            with patch("services.meeting_adk_session._publish_event", MagicMock()):
                asyncio.run(mgr._maybe_publish_transcript(
                    _MTG_ID, self._make_event(output_text="partial...", finished=False)
                ))

        assert len(write_called) == 0, "_write_twin_response must not be called for partial output"
        assert session.turn_seq == 0, "turn_seq must not increment for partial output"
        mgr._sessions.pop(_MTG_ID, None)
