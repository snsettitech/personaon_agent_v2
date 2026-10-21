"""Tests for graph_outbox worker handlers: scheduled meeting bots and transcript ingestion."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _build_supabase(*, twin_data: dict | None = None, meeting_id: str = "mtg-1") -> tuple[MagicMock, MagicMock, MagicMock]:
    twin_chain = MagicMock()
    twin_chain.select.return_value = twin_chain
    twin_chain.eq.return_value = twin_chain
    twin_chain.single.return_value = twin_chain
    twin_chain.execute.return_value = SimpleNamespace(
        data=twin_data or {"name": "Alice", "settings": {}}
    )

    meetings_chain = MagicMock()
    meetings_chain.insert.return_value = meetings_chain
    meetings_chain.update.return_value = meetings_chain
    meetings_chain.eq.return_value = meetings_chain
    meetings_chain.execute.side_effect = [
        SimpleNamespace(data=[{"id": meeting_id}]),
        SimpleNamespace(data=[{"id": meeting_id}]),
    ]

    sb = MagicMock()

    def _table(name: str) -> MagicMock:
        if name == "twins":
            return twin_chain
        if name == "meetings":
            return meetings_chain
        raise AssertionError(f"Unexpected table lookup: {name}")

    sb.table.side_effect = _table
    return sb, twin_chain, meetings_chain


@pytest.mark.asyncio
async def test_schedule_bot_no_flags_uses_transcript_only(monkeypatch):
    """When MEETING_GEMINI_LIVE_ENABLED and MEETING_NATIVE_AUDIO_ENABLED are unset,
    _process_schedule_meeting_bot must short-circuit to create_bot (transcript-only),
    not create_voice_bot."""
    monkeypatch.delenv("MEETING_GEMINI_LIVE_ENABLED", raising=False)
    monkeypatch.delenv("MEETING_NATIVE_AUDIO_ENABLED", raising=False)
    job = {
        "id": "job-1",
        "tenant_id": "tenant-1",
        "payload": {
            "twin_id": "twin-1",
            "tenant_id": "tenant-1",
            "booking_id": "booking-1",
            "meet_link": "https://meet.google.com/abc",
            "visitor_name": "Alice",
            "proposed_start": "2026-04-15T14:00:00Z",
        },
    }
    mock_sb, _, meetings_chain = _build_supabase()

    with (
        patch("modules.graph_outbox_worker.supabase", mock_sb),
        patch("modules.graph_outbox_worker.create_bot", new_callable=AsyncMock, return_value={"id": "bot-transcript"}) as mock_transcript,
        patch("modules.graph_outbox_worker.create_voice_bot", new_callable=AsyncMock) as mock_voice,
        patch("modules.graph_outbox_worker.create_gemini_live_bot", new_callable=AsyncMock) as mock_gemini,
        patch("modules.graph_outbox_worker.format_bot_name", return_value="Alice's AI Assistant"),
    ):
        from modules.graph_outbox_worker import _process_schedule_meeting_bot

        result = await _process_schedule_meeting_bot(job)

    assert result is True
    mock_transcript.assert_awaited_once()
    mock_voice.assert_not_called()
    mock_gemini.assert_not_called()
    update_payload = meetings_chain.update.call_args.args[0]
    assert update_payload["recall_bot_id"] == "bot-transcript"


@pytest.mark.asyncio
async def test_schedule_bot_flag_on_uses_gemini_live(monkeypatch):
    monkeypatch.setenv("MEETING_GEMINI_LIVE_ENABLED", "true")
    job = {
        "id": "job-2",
        "tenant_id": "tenant-1",
        "payload": {
            "twin_id": "twin-1",
            "tenant_id": "tenant-1",
            "booking_id": "booking-1",
            "meet_link": "https://meet.google.com/abc",
            "visitor_name": "Alice",
            "proposed_start": "2026-04-15T14:00:00Z",
        },
    }
    mock_sb, _, meetings_chain = _build_supabase(
        twin_data={"name": "Alice", "settings": {"gemini_voice": "Aoede"}}
    )

    with (
        patch("modules.graph_outbox_worker.supabase", mock_sb),
        patch("modules.graph_outbox_worker.issue_meeting_token", return_value="meeting-token") as mock_issue_token,
        patch("modules.graph_outbox_worker.create_gemini_live_bot", new_callable=AsyncMock, return_value={"id": "bot-gemini"}) as mock_gemini,
        patch("modules.graph_outbox_worker.create_voice_bot", new_callable=AsyncMock) as mock_voice,
        patch("modules.graph_outbox_worker.create_bot", new_callable=AsyncMock) as mock_transcript,
        patch("modules.graph_outbox_worker.format_bot_name", return_value="Alice's AI Assistant"),
    ):
        from modules.graph_outbox_worker import _process_schedule_meeting_bot

        result = await _process_schedule_meeting_bot(job)

    assert result is True
    mock_issue_token.assert_called_once_with("twin-1", "mtg-1")
    mock_gemini.assert_awaited_once()
    kwargs = mock_gemini.await_args.kwargs
    assert kwargs["voice_name"] == "Aoede"
    assert kwargs["api_key_token"] == "meeting-token"
    mock_voice.assert_not_called()
    mock_transcript.assert_not_called()
    update_payload = meetings_chain.update.call_args.args[0]
    assert update_payload["recall_bot_id"] == "bot-gemini"


@pytest.mark.asyncio
async def test_schedule_bot_fallback_order_is_gemini_then_voice_then_transcript(monkeypatch):
    monkeypatch.setenv("MEETING_GEMINI_LIVE_ENABLED", "true")
    job = {
        "id": "job-3",
        "tenant_id": "tenant-1",
        "payload": {
            "twin_id": "twin-1",
            "tenant_id": "tenant-1",
            "booking_id": "booking-1",
            "meet_link": "https://zoom.us/j/123",
            "visitor_name": "Bob",
            "proposed_start": "2026-04-15T14:00:00Z",
        },
    }
    mock_sb, _, meetings_chain = _build_supabase()

    with (
        patch("modules.graph_outbox_worker.supabase", mock_sb),
        patch("modules.graph_outbox_worker.issue_meeting_token", return_value="meeting-token"),
        patch("modules.graph_outbox_worker.create_gemini_live_bot", new_callable=AsyncMock, side_effect=Exception("gemini down")) as mock_gemini,
        patch("modules.graph_outbox_worker.create_voice_bot", new_callable=AsyncMock, side_effect=Exception("voice down")) as mock_voice,
        patch("modules.graph_outbox_worker.create_bot", new_callable=AsyncMock, return_value={"id": "bot-transcript"}) as mock_transcript,
        patch("modules.graph_outbox_worker.format_bot_name", return_value="Bob's AI Assistant"),
    ):
        from modules.graph_outbox_worker import _process_schedule_meeting_bot

        result = await _process_schedule_meeting_bot(job)

    assert result is True
    mock_gemini.assert_awaited_once()
    mock_voice.assert_awaited_once()
    mock_transcript.assert_awaited_once()
    update_payload = meetings_chain.update.call_args.args[0]
    assert update_payload["recall_bot_id"] == "bot-transcript"


@pytest.mark.asyncio
async def test_schedule_bot_no_meet_link_skips():
    job = {
        "id": "job-4",
        "payload": {"twin_id": "twin-1", "meet_link": "", "tenant_id": "t-1"},
    }

    from modules.graph_outbox_worker import _process_schedule_meeting_bot

    result = await _process_schedule_meeting_bot(job)
    assert result is True


@pytest.mark.asyncio
async def test_schedule_bot_api_failure_returns_false(monkeypatch):
    """When flags are unset (transcript-only short-circuit) and create_bot fails,
    the handler must return False to trigger a retry."""
    monkeypatch.delenv("MEETING_GEMINI_LIVE_ENABLED", raising=False)
    monkeypatch.delenv("MEETING_NATIVE_AUDIO_ENABLED", raising=False)
    job = {
        "id": "job-5",
        "payload": {
            "twin_id": "twin-1",
            "tenant_id": "tenant-1",
            "meet_link": "https://zoom.us/j/123",
            "visitor_name": "Bob",
        },
    }
    mock_sb, _, _ = _build_supabase(twin_data={"name": "Bob", "settings": {}})

    with (
        patch("modules.graph_outbox_worker.supabase", mock_sb),
        patch("modules.graph_outbox_worker.create_voice_bot", new_callable=AsyncMock),
        patch("modules.graph_outbox_worker.create_bot", new_callable=AsyncMock, side_effect=Exception("transcript down")),
        patch("modules.graph_outbox_worker.format_bot_name", return_value="Bob's AI Assistant"),
    ):
        from modules.graph_outbox_worker import _process_schedule_meeting_bot

        result = await _process_schedule_meeting_bot(job)

    assert result is False


@pytest.mark.asyncio
async def test_schedule_bot_uses_tenant_scoped_twin_query(monkeypatch):
    """Verify the twin lookup still applies the tenant scope under the
    transcript-only default path."""
    monkeypatch.delenv("MEETING_GEMINI_LIVE_ENABLED", raising=False)
    monkeypatch.delenv("MEETING_NATIVE_AUDIO_ENABLED", raising=False)
    job = {
        "id": "job-6",
        "payload": {
            "twin_id": "twin-1",
            "tenant_id": "tenant-99",
            "meet_link": "https://meet.google.com/xyz",
            "visitor_name": "Carol",
        },
    }
    mock_sb, twin_chain, _ = _build_supabase(
        twin_data={"name": "Carol", "settings": {}}
    )

    with (
        patch("modules.graph_outbox_worker.supabase", mock_sb),
        patch("modules.graph_outbox_worker.create_bot", new_callable=AsyncMock, return_value={"id": "bot-1"}),
        patch("modules.graph_outbox_worker.format_bot_name", return_value="Carol's AI Assistant"),
    ):
        from modules.graph_outbox_worker import _process_schedule_meeting_bot

        await _process_schedule_meeting_bot(job)

    assert twin_chain.eq.call_args_list[0].args == ("id", "twin-1")
    assert twin_chain.eq.call_args_list[1].args == ("tenant_id", "tenant-99")


@pytest.mark.asyncio
async def test_process_transcript_stores_text():
    job = {
        "id": "job-7",
        "payload": {"bot_id": "bot-abc", "meeting_id": "mtg-1"},
    }
    transcript = [
        {"participant": {"name": "Alice"}, "words": [{"text": "Hello"}, {"text": "there"}]},
        {"participant": {"name": "Bob"}, "words": [{"text": "Hi"}]},
    ]
    with (
        patch("modules.graph_outbox_worker.supabase") as mock_sb,
        patch("modules.graph_outbox_worker.get_graph_outbox") as mock_outbox,
        patch("services.recall_service.get_bot_transcript", new_callable=AsyncMock, return_value=transcript),
    ):
        # Handler first reads the meeting row (tenant_id/twin_id; no transcript yet)
        # so the later UPDATE can be dual-scoped by (id, tenant_id).
        mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = (
            SimpleNamespace(data={"tenant_id": "tenant-1", "twin_id": "twin-1", "transcript_text": None})
        )
        mock_sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock()
        from modules.graph_outbox_worker import _process_meeting_transcript

        result = await _process_meeting_transcript(job)

    assert result is True
    update_data = mock_sb.table.return_value.update.call_args.args[0]
    assert "Alice: Hello there" in update_data["transcript_text"]
    assert "Bob: Hi" in update_data["transcript_text"]
    assert update_data["status"] == "completed"
    assert update_data["transcript_raw"] == transcript
    # Summary + enrich jobs are enqueued (mocked outbox — no real DB write).
    assert mock_outbox.return_value.submit.call_count == 2


@pytest.mark.asyncio
async def test_process_transcript_missing_bot_id_skips():
    job = {"id": "job-8", "payload": {"bot_id": "", "meeting_id": "mtg-1"}}

    from modules.graph_outbox_worker import _process_meeting_transcript

    result = await _process_meeting_transcript(job)
    assert result is True


@pytest.mark.asyncio
async def test_process_transcript_api_failure_returns_false():
    job = {"id": "job-9", "payload": {"bot_id": "bot-1", "meeting_id": "mtg-1"}}

    with patch("services.recall_service.get_bot_transcript", new_callable=AsyncMock, side_effect=Exception("network error")):
        from modules.graph_outbox_worker import _process_meeting_transcript

        result = await _process_meeting_transcript(job)

    assert result is False


# ---------------------------------------------------------------------------
# Booking ↔ calendar dedup: the booking path must resolve-or-create by ical_uid
# so a booking and its calendar-synced twin converge on ONE meetings row.
# ---------------------------------------------------------------------------

def _build_supabase_lookup(*, lookup_rows: list, twin_data: dict | None = None, meeting_id: str = "mtg-1"):
    """Supabase mock that supports the ical_uid lookup (select→eq→limit→execute)
    followed by either an attach-update or an insert, then the recall_bot_id update.
    `meetings.execute` returns, in order: [lookup, insert-or-attach, final-update]."""
    twin_chain = MagicMock()
    twin_chain.select.return_value = twin_chain
    twin_chain.eq.return_value = twin_chain
    twin_chain.single.return_value = twin_chain
    twin_chain.execute.return_value = SimpleNamespace(data=twin_data or {"name": "Alice", "settings": {}})

    meetings_chain = MagicMock()
    for method in ("select", "insert", "update", "eq", "limit"):
        getattr(meetings_chain, method).return_value = meetings_chain
    meetings_chain.execute.side_effect = [
        SimpleNamespace(data=lookup_rows),            # ical_uid lookup
        SimpleNamespace(data=[{"id": meeting_id}]),   # insert OR attach-update
        SimpleNamespace(data=[{"id": meeting_id}]),   # final recall_bot_id update
    ]

    sb = MagicMock()

    def _table(name: str) -> MagicMock:
        if name == "twins":
            return twin_chain
        if name == "meetings":
            return meetings_chain
        raise AssertionError(f"Unexpected table lookup: {name}")

    sb.table.side_effect = _table
    return sb, meetings_chain


def _booking_bot_patches():
    # NB: the worker imports these names at module top (graph_outbox_worker.py:37),
    # so they must be patched on the worker module, not on services.recall_service —
    # otherwise the patch is a no-op and create_bot makes a real (403) network call.
    return (
        patch("modules.graph_outbox_worker.create_bot", new_callable=AsyncMock, return_value={"id": "bot-x"}),
        patch("modules.graph_outbox_worker.create_voice_bot", new_callable=AsyncMock),
        patch("modules.graph_outbox_worker.create_gemini_live_bot", new_callable=AsyncMock),
        patch("modules.graph_outbox_worker.format_bot_name", return_value="nikhil's AI"),
    )


@pytest.mark.asyncio
async def test_schedule_bot_with_ical_uid_existing_row_updates_not_inserts(monkeypatch):
    """A booking whose Google event already synced (same ical_uid) must ATTACH the bot
    to the existing row — never INSERT a second row (the duplicate-meeting bug)."""
    monkeypatch.delenv("MEETING_GEMINI_LIVE_ENABLED", raising=False)
    monkeypatch.delenv("MEETING_NATIVE_AUDIO_ENABLED", raising=False)
    job = {
        "id": "job-dedup-1",
        "tenant_id": "tenant-1",
        "payload": {
            "twin_id": "twin-1", "tenant_id": "tenant-1", "booking_id": "booking-1",
            "meet_link": "https://meet.google.com/abc", "visitor_name": "nikhil",
            "proposed_start": "2026-06-08T13:30:00Z",
            "ical_uid": "4knrlc2cjmu330jjfgsfd04p5g@google.com", "provider_event_id": "evt-1",
        },
    }
    mock_sb, meetings_chain = _build_supabase_lookup(lookup_rows=[{"id": "cal-mtg"}])
    create_bot, voice_bot, gemini_bot, bot_name = _booking_bot_patches()
    with patch("modules.graph_outbox_worker.supabase", mock_sb), create_bot, voice_bot, gemini_bot, bot_name:
        from modules.graph_outbox_worker import _process_schedule_meeting_bot
        result = await _process_schedule_meeting_bot(job)

    assert result is True
    meetings_chain.insert.assert_not_called()  # converged onto the existing calendar row
    update_payloads = [c.args[0] for c in meetings_chain.update.call_args_list]
    assert any(p.get("twin_attends") is True for p in update_payloads)


@pytest.mark.asyncio
async def test_schedule_bot_with_ical_uid_no_row_inserts_with_ical_uid(monkeypatch):
    """A booking with no pre-existing calendar row must INSERT the row WITH ical_uid, so a
    LATER calendar sync of the same event reconciles to it instead of duplicating."""
    monkeypatch.delenv("MEETING_GEMINI_LIVE_ENABLED", raising=False)
    monkeypatch.delenv("MEETING_NATIVE_AUDIO_ENABLED", raising=False)
    job = {
        "id": "job-dedup-2",
        "tenant_id": "tenant-1",
        "payload": {
            "twin_id": "twin-1", "tenant_id": "tenant-1", "booking_id": "booking-2",
            "meet_link": "https://meet.google.com/xyz", "visitor_name": "nikhil",
            "proposed_start": "2026-06-08T13:30:00Z",
            "ical_uid": "newevent@google.com", "provider_event_id": "evt-2",
        },
    }
    mock_sb, meetings_chain = _build_supabase_lookup(lookup_rows=[], meeting_id="new-mtg")
    create_bot, voice_bot, gemini_bot, bot_name = _booking_bot_patches()
    with patch("modules.graph_outbox_worker.supabase", mock_sb), create_bot, voice_bot, gemini_bot, bot_name:
        from modules.graph_outbox_worker import _process_schedule_meeting_bot
        result = await _process_schedule_meeting_bot(job)

    assert result is True
    insert_payload = meetings_chain.insert.call_args.args[0]
    assert insert_payload["ical_uid"] == "newevent@google.com"
    assert insert_payload["provider_event_id"] == "evt-2"
    assert insert_payload["twin_attends"] is True
