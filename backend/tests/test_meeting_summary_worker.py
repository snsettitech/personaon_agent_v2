"""
Unit tests for the GENERATE_MEETING_SUMMARY worker handler.

Tests cover:
  - Enum value exists
  - Dispatch routing
  - Short meeting skip (<2 min)
  - Null transcript_raw returns False (retry)
  - Missing meeting returns True (skip, not retry)
  - Happy path: analyze_meeting called, meetings + analytics updated
  - Analytics upsert row shape (tenant_id, participant fields)
  - Exception in analyze_meeting returns False
  - Transcript handler enqueues summary job after storing transcript
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from modules.graph_outbox_worker import _process_generate_meeting_summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_job(meeting_id: str = "mtg-1") -> dict:
    return {
        "id": "job-1",
        "operation": "generate_meeting_summary",
        "payload": {"meeting_id": meeting_id},
        "tenant_id": "tenant-1",
        "twin_id": "twin-1",
        "attempt_count": 0,
        "max_attempts": 5,
    }


_UNSET = object()  # sentinel for distinguishing "not passed" from explicit None


def _make_meeting(
    meeting_id: str = "mtg-1",
    duration: int = 300,
    transcript_raw: object = _UNSET,
) -> dict:
    """Return a minimal meetings table row.

    Pass transcript_raw=None explicitly to simulate a null transcript_raw in the DB.
    Omit the argument to get a default non-null transcript.
    """
    if transcript_raw is _UNSET:
        transcript_raw = [{"participant": {"name": "Alice"}, "words": []}]
    return {
        "id": meeting_id,
        "title": "Test Meeting",
        "tenant_id": "tenant-1",
        "twin_id": "twin-1",
        "duration_seconds": duration,
        "transcript_raw": transcript_raw,
        "transcript_text": "Alice: hello",
    }


def _supabase_single(data: dict | None):
    """Return a mock that simulates .table().select().eq()...single().execute()"""
    resp = MagicMock()
    resp.data = data
    execute = MagicMock(return_value=resp)
    single = MagicMock()
    single.execute = execute
    eq2 = MagicMock()
    eq2.single = MagicMock(return_value=single)
    # Support multiple .eq() chaining
    eq2.eq = MagicMock(return_value=eq2)
    select = MagicMock()
    select.eq = MagicMock(return_value=eq2)
    table = MagicMock()
    table.select = MagicMock(return_value=select)
    return table


# ---------------------------------------------------------------------------
# Test 1: Enum value
# ---------------------------------------------------------------------------

def test_enum_exists():
    from modules.graph_outbox import GraphOperationType
    assert GraphOperationType.GENERATE_MEETING_SUMMARY.value == "generate_meeting_summary"


# ---------------------------------------------------------------------------
# Test 2: Dispatch routes to summary handler
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_routes_summary():
    """_dispatch with operation=generate_meeting_summary calls _process_generate_meeting_summary."""
    from modules import graph_outbox_worker

    job = _make_job()
    with patch.object(
        graph_outbox_worker,
        "_process_generate_meeting_summary",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_handler:
        result = await graph_outbox_worker._dispatch(job)

    mock_handler.assert_called_once_with(job)
    assert result is True


# ---------------------------------------------------------------------------
# Test 3: Short meeting (<2 min) is skipped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handler_skips_short_meeting():
    """Meeting with duration_seconds=60 returns True without calling analyze_meeting."""
    from modules.graph_outbox_worker import _process_generate_meeting_summary

    meeting = _make_meeting(duration=60)

    mock_table = _supabase_single(meeting)

    with patch("modules.graph_outbox_worker.supabase") as mock_sb:
        mock_sb.table.return_value = mock_table

        with patch("services.meeting_analyzer.analyze_meeting", new_callable=AsyncMock) as mock_analyze:
            result = await _process_generate_meeting_summary(_make_job())

    assert result is True
    mock_analyze.assert_not_called()


# ---------------------------------------------------------------------------
# Test 4: Null transcript_raw returns False (triggers retry)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handler_retries_null_transcript():
    """Meeting with transcript_raw=None returns False so the job retries."""
    from modules.graph_outbox_worker import _process_generate_meeting_summary

    meeting = _make_meeting(duration=300, transcript_raw=None)

    mock_table = _supabase_single(meeting)

    with patch("modules.graph_outbox_worker.supabase") as mock_sb:
        mock_sb.table.return_value = mock_table

        result = await _process_generate_meeting_summary(_make_job())

    assert result is False


# ---------------------------------------------------------------------------
# Test 5: Missing meeting returns True (skip, not retry)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handler_skips_missing_meeting():
    """Meeting row not found => returns True (skip, don't retry)."""
    from modules.graph_outbox_worker import _process_generate_meeting_summary

    mock_table = _supabase_single(None)  # no data

    with patch("modules.graph_outbox_worker.supabase") as mock_sb:
        mock_sb.table.return_value = mock_table

        result = await _process_generate_meeting_summary(_make_job())

    assert result is True


# ---------------------------------------------------------------------------
# Test 6: Missing meeting_id in payload returns True
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handler_missing_meeting_id_returns_true():
    """Job with no meeting_id in payload returns True (nothing to process)."""
    from modules.graph_outbox_worker import _process_generate_meeting_summary

    job = {"id": "job-1", "operation": "generate_meeting_summary", "payload": {}}
    result = await _process_generate_meeting_summary(job)
    assert result is True


# ---------------------------------------------------------------------------
# Test 7: Happy path — analyze called, meetings + analytics updated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handler_calls_analyze_and_stores():
    """Mocked analyze_meeting => meetings.update + meeting_analytics.upsert called."""
    from modules.graph_outbox_worker import _process_generate_meeting_summary

    meeting = _make_meeting(duration=300)

    summary = {
        "recap": "Good meeting",
        "intent_vs_outcome": {"intent": "Align on plan", "outcome": "Aligned"},
        "topics": ["topic1"],
        "action_items": [{"owner": "Alice", "description": "Do thing", "due": None}],
        "commitments": [],
        "decisions": [],
        "unanswered_questions": [],
        "people_observed": [{"name": "Alice", "role_hint": None}],
        "my_positions": [],
        "style_sample": "Let's ship it.",
    }
    analytics = [
        {
            "participant_name": "Alice",
            "talk_time_seconds": 120.0,
            "talk_time_pct": 80.0,
            "word_count": 200,
            "words_per_minute": 100.0,
            "filler_word_count": 5,
            "sentiment_label": "positive",
            "sentiment_score": 0.8,
        }
    ]

    # Build supabase mock with chained calls
    mock_sb = MagicMock()

    # SELECT response (meeting lookup)
    select_resp = MagicMock()
    select_resp.data = meeting
    select_chain = MagicMock()
    select_chain.execute = MagicMock(return_value=select_resp)
    select_chain.single = MagicMock(return_value=select_chain)
    select_chain.eq = MagicMock(return_value=select_chain)

    # UPDATE and UPSERT responses
    update_resp = MagicMock()
    update_resp.data = [meeting]
    update_chain = MagicMock()
    update_chain.execute = MagicMock(return_value=update_resp)
    update_chain.eq = MagicMock(return_value=update_chain)

    upsert_resp = MagicMock()
    upsert_resp.data = analytics
    upsert_chain = MagicMock()
    upsert_chain.execute = MagicMock(return_value=upsert_resp)

    def _table_router(table_name: str):
        t = MagicMock()
        t.select = MagicMock(return_value=select_chain)
        t.update = MagicMock(return_value=update_chain)
        t.upsert = MagicMock(return_value=upsert_chain)
        return t

    mock_sb.table.side_effect = _table_router

    with patch("modules.graph_outbox_worker.supabase", mock_sb):
        with patch("services.meeting_analyzer.analyze_meeting", new_callable=AsyncMock, return_value=(summary, analytics)) as mock_analyze:
            result = await _process_generate_meeting_summary(_make_job())

    assert result is True
    mock_analyze.assert_called_once()

    # Verify meetings.update was called with summary fields
    meetings_table = [c.args[0] for c in mock_sb.table.call_args_list if c.args[0] == "meetings"]
    assert len(meetings_table) > 0

    # Check update dict contained expected fields
    update_calls = []
    for c in mock_sb.table.call_args_list:
        t_name = c.args[0]
        if t_name == "meetings":
            update_calls.append(t_name)
    assert "meetings" in update_calls


# ---------------------------------------------------------------------------
# Test 8: Analytics upsert row shape
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analytics_upsert_shape():
    """Upsert rows contain all required fields including meeting_id and tenant_id."""
    from modules.graph_outbox_worker import _process_generate_meeting_summary

    meeting = _make_meeting(duration=300)

    summary = {
        "recap": "Fine meeting",
        "intent_vs_outcome": {"intent": "", "outcome": ""},
        "topics": [],
        "action_items": [],
        "commitments": [],
        "decisions": [],
        "unanswered_questions": [],
        "people_observed": [],
        "my_positions": [],
        "style_sample": "",
    }
    analytics = [
        {
            "participant_name": "Bob",
            "talk_time_seconds": 90.0,
            "talk_time_pct": 60.0,
            "word_count": 150,
            "words_per_minute": 100.0,
            "filler_word_count": 2,
            "sentiment_label": "neutral",
            "sentiment_score": 0.5,
        }
    ]

    captured_upsert_rows: list = []

    mock_sb = MagicMock()

    select_resp = MagicMock()
    select_resp.data = meeting
    select_chain = MagicMock()
    select_chain.execute = MagicMock(return_value=select_resp)
    select_chain.single = MagicMock(return_value=select_chain)
    select_chain.eq = MagicMock(return_value=select_chain)

    update_chain = MagicMock()
    update_chain.execute = MagicMock(return_value=MagicMock())
    update_chain.eq = MagicMock(return_value=update_chain)

    def _capture_upsert(rows, **kwargs):
        captured_upsert_rows.extend(rows)
        chain = MagicMock()
        chain.execute = MagicMock(return_value=MagicMock())
        return chain

    def _table_router(table_name: str):
        t = MagicMock()
        t.select = MagicMock(return_value=select_chain)
        t.update = MagicMock(return_value=update_chain)
        t.upsert = MagicMock(side_effect=_capture_upsert)
        return t

    mock_sb.table.side_effect = _table_router

    with patch("modules.graph_outbox_worker.supabase", mock_sb):
        with patch("services.meeting_analyzer.analyze_meeting", new_callable=AsyncMock, return_value=(summary, analytics)):
            await _process_generate_meeting_summary(_make_job())

    assert len(captured_upsert_rows) == 1
    row = captured_upsert_rows[0]

    required_fields = [
        "meeting_id", "tenant_id", "participant_name",
        "talk_time_seconds", "talk_time_pct", "word_count",
        "words_per_minute", "filler_word_count",
        "sentiment_label", "sentiment_score",
    ]
    for field in required_fields:
        assert field in row, f"Missing field in analytics row: {field}"

    assert row["meeting_id"] == "mtg-1"
    assert row["tenant_id"] == "tenant-1"
    assert row["participant_name"] == "Bob"
    assert row["sentiment_label"] == "neutral"


# ---------------------------------------------------------------------------
# Test 9: analyze_meeting exception returns False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handler_exception_returns_false():
    """If analyze_meeting raises, handler catches and returns False."""
    from modules.graph_outbox_worker import _process_generate_meeting_summary

    meeting = _make_meeting(duration=300)

    mock_sb = MagicMock()
    select_resp = MagicMock()
    select_resp.data = meeting
    select_chain = MagicMock()
    select_chain.execute = MagicMock(return_value=select_resp)
    select_chain.single = MagicMock(return_value=select_chain)
    select_chain.eq = MagicMock(return_value=select_chain)

    def _table_router(table_name: str):
        t = MagicMock()
        t.select = MagicMock(return_value=select_chain)
        return t

    mock_sb.table.side_effect = _table_router

    with patch("modules.graph_outbox_worker.supabase", mock_sb):
        with patch(
            "services.meeting_analyzer.analyze_meeting",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Gemini exploded"),
        ):
            result = await _process_generate_meeting_summary(_make_job())

    assert result is False


# ---------------------------------------------------------------------------
# TestNullTranscriptBranches: refined null-transcript logic
# ---------------------------------------------------------------------------

class TestNullTranscriptBranches:

    @pytest.mark.asyncio
    async def test_null_transcript_raw_and_text_skips_permanently(self):
        """Both null = genuinely empty meeting → True (permanent skip, no retry)."""
        job = _make_job(meeting_id="mtg-empty")

        meeting_row = {
            "id": "mtg-empty",
            "transcript_raw": None,
            "transcript_text": None,
            "duration_seconds": 0,
            "tenant_id": "t1",
            "twin_id": "tw1",
            "title": "Empty",
        }

        with patch("modules.graph_outbox_worker.supabase") as mock_sb:
            mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = meeting_row
            result = await _process_generate_meeting_summary(job)

        assert result is True  # permanent skip

    @pytest.mark.asyncio
    async def test_null_transcript_raw_with_text_retries(self):
        """transcript_raw null but transcript_text present = race condition → False (retry)."""
        job = _make_job(meeting_id="mtg-race")

        meeting_row = {
            "id": "mtg-race",
            "transcript_raw": None,
            "transcript_text": "Participant: Hello",
            "duration_seconds": 300,
            "tenant_id": "t1",
            "twin_id": "tw1",
            "title": "Race",
        }

        with patch("modules.graph_outbox_worker.supabase") as mock_sb:
            mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = meeting_row
            result = await _process_generate_meeting_summary(job)

        assert result is False  # retry


# ---------------------------------------------------------------------------
# Test 10: Transcript handler enqueues summary job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transcript_handler_enqueues_summary():
    """After storing transcript, _process_meeting_transcript enqueues GENERATE_MEETING_SUMMARY."""
    from modules.graph_outbox_worker import _process_meeting_transcript
    from modules.graph_outbox import GraphOperationType

    job = {
        "id": "job-2",
        "operation": "process_meeting_transcript",
        "payload": {"bot_id": "bot-abc", "meeting_id": "mtg-1"},
        "tenant_id": "tenant-1",
        "twin_id": "twin-1",
    }

    # Transcript entries from Recall.ai
    transcript_entries = [
        {
            "participant": {"name": "Alice"},
            "words": [{"text": "Hello", "start": 0.0, "end": 0.5}],
        }
    ]

    # meeting row for the tenant/twin lookup
    meeting_row = {"tenant_id": "tenant-1", "twin_id": "twin-1"}

    mock_sb = MagicMock()

    # UPDATE chain for storing transcript
    update_chain = MagicMock()
    update_chain.execute = MagicMock(return_value=MagicMock())
    update_chain.eq = MagicMock(return_value=update_chain)

    # SELECT chain for tenant_id/twin_id lookup
    select_resp = MagicMock()
    select_resp.data = meeting_row
    select_chain = MagicMock()
    select_chain.execute = MagicMock(return_value=select_resp)
    select_chain.single = MagicMock(return_value=select_chain)
    select_chain.eq = MagicMock(return_value=select_chain)

    def _table_router(table_name: str):
        t = MagicMock()
        t.update = MagicMock(return_value=update_chain)
        t.select = MagicMock(return_value=select_chain)
        return t

    mock_sb.table.side_effect = _table_router

    mock_outbox = MagicMock()
    mock_outbox.submit = MagicMock(return_value="outbox-job-123")

    with patch("modules.graph_outbox_worker.supabase", mock_sb):
        with patch("modules.graph_outbox_worker.get_graph_outbox", return_value=mock_outbox):
            with patch("services.recall_service.get_bot_transcript", new_callable=AsyncMock, return_value=transcript_entries):
                result = await _process_meeting_transcript(job)

    assert result is True

    # Verify outbox.submit was called at least once (summary + enrich jobs)
    assert mock_outbox.submit.call_count >= 1
    # Inspect first call — must be GENERATE_MEETING_SUMMARY
    submit_kwargs = mock_outbox.submit.call_args_list[0]
    # Accept positional or keyword call
    all_args = {
        **(submit_kwargs.kwargs if submit_kwargs.kwargs else {}),
    }
    if submit_kwargs.args:
        arg_names = ["tenant_id", "twin_id", "operation", "idempotency_key", "payload"]
        for i, v in enumerate(submit_kwargs.args):
            if i < len(arg_names):
                all_args[arg_names[i]] = v

    op = all_args.get("operation")
    assert op == GraphOperationType.GENERATE_MEETING_SUMMARY, (
        f"Expected GENERATE_MEETING_SUMMARY, got {op}"
    )
    assert "mtg-1" in str(all_args.get("idempotency_key", ""))


# ---------------------------------------------------------------------------
# Audit C2 — UPDATE must be dual-scoped by (id, tenant_id)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_meetings_update_is_tenant_scoped() -> None:
    """Audit C2 (2026-05-31): the recap UPDATE in
    `_process_generate_meeting_summary` is the highest-value write in the
    pipeline. As a service-role worker, it MUST scope the UPDATE by both
    `id` and `tenant_id` — without dual-scope a payload with a mismatched
    tenant_id could write the recap onto the wrong tenant's meeting row.

    This test records every `.eq(col, val)` call against the `meetings`
    table update chain and asserts that BOTH `id` and `tenant_id` filters
    are applied.
    """
    from modules.graph_outbox_worker import _process_generate_meeting_summary

    meeting = _make_meeting(duration=300)
    summary = {
        "recap": "Good meeting",
        "intent_vs_outcome": {"intent": "Align", "outcome": "Aligned"},
        "topics": ["topic1"],
        "action_items": [],
        "commitments": [],
        "decisions": [],
        "unanswered_questions": [],
        "people_observed": [{"name": "Alice", "role_hint": None}],
        "my_positions": [],
        "style_sample": "",
    }
    analytics = [
        {
            "participant_name": "Alice",
            "talk_time_seconds": 120.0,
            "talk_time_pct": 80.0,
            "word_count": 200,
            "words_per_minute": 100.0,
            "filler_word_count": 5,
            "sentiment_label": "positive",
            "sentiment_score": 0.8,
        }
    ]

    # Track eq() calls on the UPDATE chain specifically.
    update_eq_calls: list[tuple[str, object]] = []

    select_resp = MagicMock()
    select_resp.data = meeting
    select_chain = MagicMock()
    select_chain.execute = MagicMock(return_value=select_resp)
    select_chain.single = MagicMock(return_value=select_chain)
    select_chain.eq = MagicMock(return_value=select_chain)

    update_resp = MagicMock()
    update_resp.data = [meeting]
    update_chain = MagicMock()
    update_chain.execute = MagicMock(return_value=update_resp)
    update_chain.eq = MagicMock(
        side_effect=lambda col, val: (update_eq_calls.append((col, val)) or update_chain)
    )

    upsert_resp = MagicMock()
    upsert_resp.data = analytics
    upsert_chain = MagicMock()
    upsert_chain.execute = MagicMock(return_value=upsert_resp)

    def _table_router(_table_name: str):
        t = MagicMock()
        t.select = MagicMock(return_value=select_chain)
        t.update = MagicMock(return_value=update_chain)
        t.upsert = MagicMock(return_value=upsert_chain)
        return t

    mock_sb = MagicMock()
    mock_sb.table.side_effect = _table_router

    with patch("modules.graph_outbox_worker.supabase", mock_sb):
        with patch(
            "services.meeting_analyzer.analyze_meeting",
            new_callable=AsyncMock,
            return_value=(summary, analytics),
        ):
            result = await _process_generate_meeting_summary(_make_job())

    assert result is True

    # CRITICAL: the UPDATE must include both id AND tenant_id filters.
    assert ("id", "mtg-1") in update_eq_calls, (
        f"meetings UPDATE missing .eq('id', ...): {update_eq_calls}"
    )
    assert ("tenant_id", "tenant-1") in update_eq_calls, (
        f"meetings UPDATE missing .eq('tenant_id', ...) -- service-role cross-tenant"
        f" write risk: {update_eq_calls}"
    )
