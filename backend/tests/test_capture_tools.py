"""Unit tests for capture_knowledge and queue_question tool factories."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# capture_knowledge tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capture_knowledge_upsert():
    """capture_knowledge calls upsert_text_chunks with captured_ prefix."""
    mock_invalidate = MagicMock()
    with patch("adk_core.tools.capture_tools.upsert_text_chunks") as mock_upsert, \
         patch("adk_core.services.agent_service.invalidate_agent", mock_invalidate):

        from adk_core.tools.capture_tools import _make_capture_tool

        tool = _make_capture_tool("twin-abc")
        # Call the underlying async function directly
        result = await tool.func(topic="AI ethics", content="I believe AI should be open.", is_boundary=False)

        assert result["status"] == "captured"
        assert result["topic"] == "AI ethics"

        mock_upsert.assert_called_once()

        # Use keyword argument lookup
        kwargs = mock_upsert.call_args[1] if mock_upsert.call_args[1] else {}
        args = mock_upsert.call_args[0] if mock_upsert.call_args[0] else []

        # Extract source (could be positional or keyword)
        if kwargs.get("source"):
            source = kwargs["source"]
        else:
            source = args[2] if len(args) > 2 else None

        assert source is not None, "source argument not found"
        assert source.startswith("captured_"), f"Expected 'captured_' prefix, got: {source}"

        # metadata should have topic
        metadata = kwargs.get("metadata") or (args[3] if len(args) > 3 else None)
        assert metadata == {"topic": "AI ethics"}


@pytest.mark.asyncio
async def test_capture_knowledge_boundary():
    """capture_knowledge with is_boundary=True stores [BOUNDARY] text."""
    with patch("adk_core.tools.capture_tools.upsert_text_chunks") as mock_upsert, \
         patch("adk_core.services.agent_service.invalidate_agent"):

        from adk_core.tools.capture_tools import _make_capture_tool

        tool = _make_capture_tool("twin-abc")
        await tool.func(topic="cooking", content="", is_boundary=True)

        mock_upsert.assert_called_once()
        call_kwargs = mock_upsert.call_args[1] if mock_upsert.call_args[1] else {}
        call_args = mock_upsert.call_args[0] if mock_upsert.call_args[0] else []

        # text should start with [BOUNDARY]
        text = call_kwargs.get("text") or (call_args[0] if call_args else None)
        assert text is not None, "text argument not found"
        assert text.startswith("[BOUNDARY]"), f"Expected '[BOUNDARY]' prefix, got: {text}"
        assert "cooking" in text


@pytest.mark.asyncio
async def test_capture_knowledge_unique_source():
    """Two calls with different topics produce different source strings."""
    import time

    mock_upsert = AsyncMock()

    with patch("adk_core.tools.capture_tools.upsert_text_chunks", mock_upsert), \
         patch("adk_core.services.agent_service.invalidate_agent"):

        from adk_core.tools.capture_tools import _make_capture_tool

        tool = _make_capture_tool("twin-abc")
        await tool.func(topic="topic alpha", content="content 1", is_boundary=False)
        # Small delay to ensure different timestamp in source
        time.sleep(0.01)
        await tool.func(topic="topic beta", content="content 2", is_boundary=False)

    assert mock_upsert.call_count == 2
    call1_kwargs = mock_upsert.call_args_list[0][1]
    call2_kwargs = mock_upsert.call_args_list[1][1]
    source1 = call1_kwargs.get("source", "")
    source2 = call2_kwargs.get("source", "")
    assert source1 != source2, f"Sources should differ for different topics: {source1!r} vs {source2!r}"


# ---------------------------------------------------------------------------
# queue_question tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_question_insert_new():
    """queue_question inserts a new row when no existing pending row."""
    mock_sb = MagicMock()
    # No existing rows
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.gte.return_value.execute.return_value.data = []
    mock_sb.table.return_value.insert.return_value.execute.return_value = MagicMock()

    with patch("adk_core.tools.capture_tools.get_supabase_client", return_value=mock_sb):
        from adk_core.tools.capture_tools import _make_queue_tool

        tool = _make_queue_tool(
            twin_id="twin-xyz",
            conversation_id="conv-1",
            visitor_user_id="user-1",
            tenant_id="tenant-1",
        )
        result = await tool.func(question="What about crypto?", topic="crypto")

    assert result["status"] == "queued"
    assert result["topic"] == "crypto"

    # Should have called insert (not update)
    mock_sb.table.return_value.insert.assert_called_once()
    insert_call_data = mock_sb.table.return_value.insert.call_args[0][0]
    assert insert_call_data["ask_count"] == 1
    assert insert_call_data["status"] == "pending"
    assert insert_call_data["twin_id"] == "twin-xyz"
    assert insert_call_data["topic"] == "crypto"


@pytest.mark.asyncio
async def test_queue_question_dedup():
    """queue_question increments ask_count when pending row exists."""
    mock_sb = MagicMock()
    # Existing row found
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.gte.return_value.execute.return_value.data = [
        {"id": "row-1", "ask_count": 2}
    ]
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    with patch("adk_core.tools.capture_tools.get_supabase_client", return_value=mock_sb):
        from adk_core.tools.capture_tools import _make_queue_tool

        tool = _make_queue_tool(
            twin_id="twin-xyz",
            conversation_id="conv-1",
            visitor_user_id="user-1",
        )
        result = await tool.func(question="Tell me about crypto?", topic="crypto")

    assert result["status"] == "queued"

    # Should have called update, not insert
    mock_sb.table.return_value.insert.assert_not_called()
    mock_sb.table.return_value.update.assert_called_once()
    update_data = mock_sb.table.return_value.update.call_args[0][0]
    assert update_data["ask_count"] == 3  # incremented from 2
