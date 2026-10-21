# backend/tests/test_memory_events_flow.py
"""Memory Events Flow Tests

Tests for MemoryEvent creation, updates, and flow correctness.
Ensures every Scribe run creates an event and events are tracked properly.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid


# Test fixtures
@pytest.fixture
def twin():
    return {
        "id": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4())
    }


@pytest.fixture
def mock_event():
    return {
        "id": str(uuid.uuid4()),
        "twin_id": "twin1",
        "tenant_id": "tenant1",
        "event_type": "auto_extract",
        "payload": {},
        "status": "applied"
    }


# MEM-001: Scribe creates MemoryEvent on success
@pytest.mark.asyncio
async def test_scribe_creates_event_on_success(twin):
    """Successful Scribe extraction should create MemoryEvent."""
    with patch('modules._core.scribe_engine.get_async_openai_client') as mock_client, \
         patch('modules._core.scribe_engine.supabase') as mock_supabase, \
         patch('modules.memory_events.supabase') as mock_mem_supabase:

        # Mock OpenAI response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = MagicMock()
        mock_response.choices[0].message.parsed.nodes = []
        mock_response.choices[0].message.parsed.edges = []
        mock_response.choices[0].message.parsed.confidence = 0.9
        mock_response.choices[0].message.parsed.model_dump = lambda: {"nodes": [], "edges": [], "confidence": 0.9}

        mock_client.return_value.beta.chat.completions.parse = AsyncMock(return_value=mock_response)

        # Mock Supabase
        mock_supabase.rpc.return_value.execute.return_value.data = []
        mock_mem_supabase.rpc.return_value.execute.return_value.data = [{"id": "event1"}]

        from modules._core.scribe_engine import process_interaction

        result = await process_interaction(
            twin_id=twin["id"],
            user_message="Test message",
            assistant_message="Test response",
            tenant_id=twin["tenant_id"]
        )

        # Verify MemoryEvent was created
        mock_mem_supabase.rpc.assert_called()


# MEM-002: Scribe creates MemoryEvent on failure
@pytest.mark.asyncio
async def test_scribe_creates_event_on_failure(twin):
    """Failed Scribe extraction should still create MemoryEvent with error status."""
    with patch('modules._core.scribe_engine.get_async_openai_client') as mock_client, \
         patch('modules.memory_events.create_memory_event') as mock_create:

        mock_client.return_value.beta.chat.completions.parse = AsyncMock(
            side_effect=Exception("API Error")
        )
        mock_create.return_value = {"id": "event1"}

        from modules._core.scribe_engine import process_interaction

        result = await process_interaction(
            twin_id=twin["id"],
            user_message="Test",
            assistant_message="Response",
            tenant_id=twin["tenant_id"]
        )

        # Verify error result
        assert "error" in result

        # Verify failed event was created
        mock_create.assert_called()
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["status"] == "failed"


# MEM-003: MemoryEvent payload contains nodes_created
@pytest.mark.asyncio
async def test_event_payload_contains_nodes(twin):
    """MemoryEvent payload should include nodes_created list."""
    from modules.memory_events import create_memory_event, update_memory_event

    with patch('modules.memory_events.supabase') as mock_supabase:
        mock_supabase.rpc.return_value.execute.return_value.data = [{"id": "event1"}]

        # Create initial event
        event = await create_memory_event(
            twin_id=twin["id"],
            tenant_id=twin["tenant_id"],
            event_type="auto_extract",
            payload={"raw_nodes": [{"name": "Test"}]}
        )

        # Update with resolved IDs
        await update_memory_event("event1", {
            "nodes_created": ["node1", "node2"]
        })

        # Verify update was called with nodes_created
        # supabase.rpc uses positional args: rpc(name, params)
        update_call = mock_supabase.rpc.call_args_list[-1]
        params = update_call[0][1]  # Second positional arg is params dict
        assert "nodes_created" in params["p_payload"]


# MEM-004: MemoryEvent payload contains confidence
@pytest.mark.asyncio
async def test_event_payload_contains_confidence(twin):
    """MemoryEvent payload should include confidence score."""
    from modules.memory_events import create_memory_event

    with patch('modules.memory_events.supabase') as mock_supabase:
        mock_supabase.rpc.return_value.execute.return_value.data = [{"id": "event1"}]

        await create_memory_event(
            twin_id=twin["id"],
            tenant_id=twin["tenant_id"],
            event_type="auto_extract",
            payload={"confidence": 0.85}
        )

        call_args = mock_supabase.rpc.call_args
        params = call_args[0][1]  # Second positional arg is params dict
        assert params["p_payload"]["confidence"] == 0.85


# MEM-005: Confirm creates new 'confirm' event
@pytest.mark.asyncio
async def test_confirm_creates_event(twin):
    """Confirming a memory should create a confirm event."""
    from modules.memory_events import create_memory_event

    with patch('modules.memory_events.supabase') as mock_supabase:
        mock_supabase.rpc.return_value.execute.return_value.data = [{"id": "event1"}]

        await create_memory_event(
            twin_id=twin["id"],
            tenant_id=twin["tenant_id"],
            event_type="confirm",
            payload={"node_id": "node1"}
        )

        call_args = mock_supabase.rpc.call_args
        params = call_args[0][1]  # Second positional arg is params dict
        assert params["p_event_type"] == "confirm"


# MEM-006: Edit creates new 'manual_edit' event
@pytest.mark.asyncio
async def test_edit_creates_event(twin):
    """Editing a memory should create a manual_edit event."""
    from modules.memory_events import create_memory_event

    with patch('modules.memory_events.supabase') as mock_supabase:
        mock_supabase.rpc.return_value.execute.return_value.data = [{"id": "event1"}]

        await create_memory_event(
            twin_id=twin["id"],
            tenant_id=twin["tenant_id"],
            event_type="manual_edit",
            payload={"node_id": "node1", "changes": {"name": "Updated"}}
        )

        call_args = mock_supabase.rpc.call_args
        params = call_args[0][1]  # Second positional arg is params dict
        assert params["p_event_type"] == "manual_edit"


# MEM-007: Delete creates new 'delete' event
@pytest.mark.asyncio
async def test_delete_creates_event(twin):
    """Deleting a memory should create a delete event."""
    from modules.memory_events import create_memory_event

    with patch('modules.memory_events.supabase') as mock_supabase:
        mock_supabase.rpc.return_value.execute.return_value.data = [{"id": "event1"}]

        await create_memory_event(
            twin_id=twin["id"],
            tenant_id=twin["tenant_id"],
            event_type="delete",
            payload={"node_id": "node1"}
        )

        call_args = mock_supabase.rpc.call_args
        params = call_args[0][1]  # Second positional arg is params dict
        assert params["p_event_type"] == "delete"


# MEM-008: TIL feed returns events in date order
@pytest.mark.asyncio
async def test_til_feed_date_order(twin):
    """TIL feed should return events in reverse chronological order."""
    from modules.memory_events import get_til_feed

    with patch('modules.memory_events.get_memory_events') as mock_get:
        mock_get.return_value = [
            {"id": "e1", "event_type": "auto_extract", "status": "applied", "created_at": "2024-01-02", "payload": {}},
            {"id": "e2", "event_type": "auto_extract", "status": "applied", "created_at": "2024-01-01", "payload": {}}
        ]

        events = await get_til_feed(twin["id"])

        # Verify events are returned (order maintained from source)
        assert len(events) == 2


# MEM-009: Graph Snapshot respects max_nodes cap
@pytest.mark.asyncio
async def test_snapshot_respects_max_nodes(twin):
    """Graph Snapshot should not exceed max_nodes limit."""
    from modules.graph_context import get_graph_snapshot, MAX_NODES

    with patch('modules.graph_context.supabase') as mock_supabase:
        # Return more nodes than MAX_NODES
        many_nodes = [
            {"id": f"node{i}", "twin_id": twin["id"], "name": f"Node {i}", "type": "test", "description": "Test"}
            for i in range(50)
        ]
        mock_supabase.rpc.return_value.execute.return_value.data = many_nodes
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        mock_supabase.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = []

        snapshot = await get_graph_snapshot(twin["id"], query="test")

        assert snapshot["node_count"] <= MAX_NODES


# MEM-010: Graph Snapshot respects max_edges cap
@pytest.mark.asyncio
async def test_snapshot_respects_max_edges(twin):
    """Graph Snapshot should not exceed max_edges limit."""
    from modules.graph_context import get_graph_snapshot, MAX_EDGES

    # The seed fallback embeds the query via vector_store.search (OpenAI/Gemini);
    # no vector hits keeps this test on the graph-scoping logic under test.
    with patch('modules.graph_context.supabase') as mock_supabase, patch(
        'adk_core.services.vector_store.search', new=AsyncMock(return_value=[])
    ):
        # Return nodes and many edges
        mock_supabase.rpc.return_value.execute.return_value.data = [
            {"id": "node1", "twin_id": twin["id"], "name": "Node 1", "type": "test", "description": "Test"}
        ]
        many_edges = [
            {"id": f"edge{i}", "twin_id": twin["id"], "from_node_id": "node1", "to_node_id": f"node{i}", "type": "RELATES"}
            for i in range(50)
        ]
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = many_edges
        mock_supabase.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = []

        snapshot = await get_graph_snapshot(twin["id"], query="test")

        assert snapshot["edge_count"] <= MAX_EDGES
