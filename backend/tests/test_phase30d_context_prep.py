"""Phase 30-D tests: PREP_MEETING_CONTEXT worker + bot.joining_call webhook dispatch.

Covers:
  - prep_meeting_context() stores context_prep in meetings table
  - format_context_for_instruction() returns expected snippet / empty string
  - bot.joining_call webhook submits PREP_MEETING_CONTEXT job
  - bot.joining_call webhook still updates status even if meeting lookup fails
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Shared webhook helpers (same as test_meetings_webhook.py)
# ---------------------------------------------------------------------------

TEST_SECRET = "whsec_" + base64.b64encode(b"test-secret-32-bytes-long-padding").decode()


def _make_signature(secret: str, webhook_id: str, timestamp: str, body: bytes) -> str:
    raw = secret[6:] if secret.startswith("whsec_") else secret
    key = base64.b64decode(raw)
    msg = f"{webhook_id}.{timestamp}.{body.decode()}"
    sig = base64.b64encode(hmac.new(key, msg.encode(), hashlib.sha256).digest()).decode()
    return f"v1,{sig}"


def _post_webhook(client, body: dict):
    body_bytes = json.dumps(body).encode()
    wid, ts = "msg-30d", str(int(time.time()))  # webhook enforces a 5-min timestamp tolerance
    headers = {
        "webhook-id": wid,
        "webhook-timestamp": ts,
        "webhook-signature": _make_signature(TEST_SECRET, wid, ts, body_bytes),
        "content-type": "application/json",
    }
    return client.post("/v2/meetings/webhook/recall", content=body_bytes, headers=headers)


@pytest.fixture
def client():
    with patch("services.recall_auth.RECALL_WEBHOOK_SECRET", TEST_SECRET):
        from main import app
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# format_context_for_instruction
# ---------------------------------------------------------------------------

def test_format_context_none_returns_empty():
    from services.meeting_context_prep import format_context_for_instruction
    assert format_context_for_instruction(None) == ""


def test_format_context_empty_chunks_returns_empty():
    from services.meeting_context_prep import format_context_for_instruction
    assert format_context_for_instruction({"chunks": []}) == ""


def test_format_context_returns_snippet():
    from services.meeting_context_prep import format_context_for_instruction
    prep = {
        "chunks": [
            {"text": "John is a senior engineer.", "score": 0.9, "source_id": "s1", "filename": "bio.pdf"},
            {"text": "He specializes in distributed systems.", "score": 0.8, "source_id": "s2", "filename": "resume.pdf"},
        ]
    }
    result = format_context_for_instruction(prep)
    assert "John is a senior engineer." in result
    assert "He specializes in distributed systems." in result
    assert "Pre-fetched knowledge base context" in result


# ---------------------------------------------------------------------------
# prep_meeting_context service
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prep_meeting_context_stores_chunks():
    """Happy path: KB returns 2 high-score chunks; they are stored in meetings.context_prep."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.side_effect = [
        MagicMock(data={"id": "mtg-1", "title": "Q1 Planning", "twin_id": "twin-1"}),
        MagicMock(data={"name": "Alice", "settings": {"persona_profile": {"expertise": "AI, ML"}}}),
    ]
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    mock_chunks = [
        {"text": "Alice leads the AI team.", "score": 0.88, "source_id": "s1", "filename": "bio.pdf"},
        {"text": "She focuses on ML infrastructure.", "score": 0.75, "source_id": "s2", "filename": "work.pdf"},
    ]

    with patch("services.meeting_context_prep.get_supabase_client", return_value=mock_sb), \
         patch("services.meeting_context_prep.kb_search", new=AsyncMock(return_value=mock_chunks)):
        from services.meeting_context_prep import prep_meeting_context
        result = await prep_meeting_context("mtg-1", "twin-1")

    assert result is True

    # Verify context_prep was written to DB
    update_call = mock_sb.table.return_value.update.call_args
    stored = update_call[0][0]["context_prep"]
    assert stored["chunk_count"] == 2
    assert len(stored["chunks"]) == 2
    assert stored["chunks"][0]["text"] == "Alice leads the AI team."
    assert "prepped_at" in stored
    assert "queries_used" in stored


@pytest.mark.asyncio
async def test_prep_meeting_context_filters_low_score():
    """Chunks below 0.50 threshold are not stored."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.side_effect = [
        MagicMock(data={"id": "mtg-2", "title": "Demo Day", "twin_id": "twin-2"}),
        MagicMock(data={"name": "Bob", "settings": {}}),
    ]
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    low_score_chunks = [
        {"text": "Unrelated content.", "score": 0.3, "source_id": "s99", "filename": "misc.txt"},
    ]

    with patch("services.meeting_context_prep.get_supabase_client", return_value=mock_sb), \
         patch("services.meeting_context_prep.kb_search", new=AsyncMock(return_value=low_score_chunks)):
        from services.meeting_context_prep import prep_meeting_context
        result = await prep_meeting_context("mtg-2", "twin-2")

    assert result is True
    stored = mock_sb.table.return_value.update.call_args[0][0]["context_prep"]
    assert stored["chunk_count"] == 0
    assert stored["chunks"] == []


@pytest.mark.asyncio
async def test_prep_meeting_context_db_load_failure_returns_false():
    """DB load failure returns False without crashing."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.side_effect = Exception("DB down")

    with patch("services.meeting_context_prep.get_supabase_client", return_value=mock_sb):
        from services.meeting_context_prep import prep_meeting_context
        result = await prep_meeting_context("mtg-fail", "twin-fail")

    assert result is False


@pytest.mark.asyncio
async def test_prep_meeting_context_deduplicates_by_source_id():
    """Two queries returning the same source_id → only highest-score entry kept."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.side_effect = [
        MagicMock(data={"id": "mtg-3", "title": "Board Meeting", "twin_id": "twin-3"}),
        MagicMock(data={"name": "Carol", "settings": {"persona_profile": {"expertise": "Finance"}}}),
    ]
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    # Same source_id returned by both queries with different scores
    chunks_q1 = [{"text": "Carol manages the portfolio.", "score": 0.70, "source_id": "s-dup", "filename": "bio.pdf"}]
    chunks_q2 = [{"text": "Carol manages the portfolio.", "score": 0.85, "source_id": "s-dup", "filename": "bio.pdf"}]

    with patch("services.meeting_context_prep.get_supabase_client", return_value=mock_sb), \
         patch("services.meeting_context_prep.kb_search", new=AsyncMock(side_effect=[chunks_q1, chunks_q2])):
        from services.meeting_context_prep import prep_meeting_context
        result = await prep_meeting_context("mtg-3", "twin-3")

    assert result is True
    stored = mock_sb.table.return_value.update.call_args[0][0]["context_prep"]
    assert stored["chunk_count"] == 1  # deduplicated
    assert stored["chunks"][0]["score"] == 0.85  # kept the higher score


# ---------------------------------------------------------------------------
# bot.joining_call webhook → PREP_MEETING_CONTEXT job
# ---------------------------------------------------------------------------

def test_joining_call_submits_prep_context_job(client):
    """bot.joining_call must submit a PREP_MEETING_CONTEXT outbox job."""
    meeting_row = {"id": "mtg-a", "twin_id": "twin-a", "tenant_id": "tenant-a"}
    mock_outbox = MagicMock()

    with patch("routers.meetings.supabase") as mock_sb, \
         patch("routers.meetings.get_graph_outbox", return_value=mock_outbox):
        # First call: status update (update chain)
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        # Second call: meeting lookup for context prep (select chain)
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [meeting_row]

        resp = _post_webhook(client, {"event": "bot.joining_call", "data": {"bot": {"id": "bot-30d"}}})

    assert resp.status_code == 200
    mock_outbox.submit.assert_called_once()
    kwargs = mock_outbox.submit.call_args.kwargs
    assert kwargs["operation"].value == "prep_meeting_context"
    assert kwargs["payload"]["meeting_id"] == "mtg-a"
    assert kwargs["payload"]["twin_id"] == "twin-a"
    assert kwargs["idempotency_key"] == "prep_meeting_context:bot-30d"
    assert kwargs["priority"] == 8


def test_joining_call_no_meeting_still_returns_200(client):
    """bot.joining_call with unknown bot_id must not crash — just update status and skip job."""
    mock_outbox = MagicMock()

    with patch("routers.meetings.supabase") as mock_sb, \
         patch("routers.meetings.get_graph_outbox", return_value=mock_outbox):
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

        resp = _post_webhook(client, {"event": "bot.joining_call", "data": {"bot": {"id": "unknown-bot"}}})

    assert resp.status_code == 200
    mock_outbox.submit.assert_not_called()


def test_joining_call_status_still_updated_alongside_prep_job(client):
    """Status update and context prep job must both fire on bot.joining_call."""
    meeting_row = {"id": "mtg-b", "twin_id": "twin-b", "tenant_id": "tenant-b"}
    mock_outbox = MagicMock()

    with patch("routers.meetings.supabase") as mock_sb, \
         patch("routers.meetings.get_graph_outbox", return_value=mock_outbox):
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [meeting_row]

        resp = _post_webhook(client, {"event": "bot.joining_call", "data": {"bot": {"id": "bot-dual"}}})

    assert resp.status_code == 200
    mock_sb.table.return_value.update.assert_called_with({"status": "bot_joining"})
    mock_outbox.submit.assert_called_once()
