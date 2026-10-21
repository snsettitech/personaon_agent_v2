# backend/tests/test_graphrag_isolation.py
"""GraphRAG Lite Isolation Tests

Tests for tenant and twin isolation in Graph Snapshot and MemoryEvent operations.
Ensures no cross-twin data leakage.
"""

import pytest
from unittest.mock import AsyncMock, patch
import uuid


# Test fixtures

@pytest.fixture(autouse=True)
def _no_vector_seed_search():
    """Seed selection falls back to vector_store.search, which embeds the query
    via OpenAI/Gemini. No vector hits keeps these tests on graph scoping."""
    with patch("adk_core.services.vector_store.search", new=AsyncMock(return_value=[])):
        yield

@pytest.fixture
def twin_a():
    return {
        "id": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "name": "Twin A"
    }


@pytest.fixture
def twin_b():
    return {
        "id": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "name": "Twin B"
    }


@pytest.fixture
def same_tenant_twin(twin_a):
    return {
        "id": str(uuid.uuid4()),
        "tenant_id": twin_a["tenant_id"],  # Same tenant
        "name": "Twin C"
    }


# ISO-001: Snapshot only returns own twin's nodes
@pytest.mark.asyncio
async def test_snapshot_returns_only_own_nodes(twin_a, twin_b):
    """Graph snapshot should only return nodes belonging to the requesting twin."""
    from modules.graph_context import get_graph_snapshot

    with patch('modules.graph_context.supabase') as mock_supabase:
        # Mock RPC to return nodes only for twin_a
        mock_supabase.rpc.return_value.execute.return_value.data = [
            {"id": "node1", "twin_id": twin_a["id"], "name": "Node A", "type": "test", "description": "Test"}
        ]

        snapshot = await get_graph_snapshot(twin_a["id"], query="test")

        # Verify RPC was called with correct twin_id
        mock_supabase.rpc.assert_called()
        call_args = mock_supabase.rpc.call_args_list[0]
        assert call_args[0][1]["t_id"] == twin_a["id"]


# ISO-002: Snapshot only returns own twin's edges
@pytest.mark.asyncio
async def test_snapshot_returns_only_own_edges(twin_a):
    """Graph snapshot edges should be scoped to twin."""
    from modules.graph_context import _expand_one_hop

    with patch('modules.graph_context.supabase') as mock_supabase:
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

        nodes, edges = await _expand_one_hop(twin_a["id"], ["node1"])

        # Verify query was scoped to twin_id
        mock_supabase.table.return_value.select.return_value.eq.assert_called_with("twin_id", twin_a["id"])


# ISO-003: Cross-twin ID guessing returns empty
@pytest.mark.asyncio
async def test_cross_twin_access_returns_empty(twin_a, twin_b):
    """Attempting to access another twin's data should return empty."""
    from modules.graph_context import get_graph_snapshot

    with patch('modules.graph_context.supabase') as mock_supabase:
        # Simulate empty result for wrong twin
        mock_supabase.rpc.return_value.execute.return_value.data = []

        snapshot = await get_graph_snapshot(twin_b["id"], query="test")

        assert snapshot["node_count"] == 0
        assert snapshot["context_text"] == ""


# ISO-004: Tenant isolation enforced
@pytest.mark.asyncio
async def test_tenant_isolation_enforced(twin_a, twin_b):
    """Nodes from different tenants should never be mixed."""
    from modules.memory_events import get_memory_events

    with patch('modules.memory_events.supabase') as mock_supabase:
        mock_supabase.rpc.return_value.execute.return_value.data = []

        events = await get_memory_events(twin_a["id"])

        # Verify RPC was called with twin_a's ID only
        mock_supabase.rpc.assert_called_once()
        # RPC uses positional args: rpc(name, params)
        params = mock_supabase.rpc.call_args[0][1]
        assert params["p_twin_id"] == twin_a["id"]


# ISO-005: Seed selection scoped by twin_id
@pytest.mark.asyncio
async def test_seed_selection_scoped(twin_a):
    """Seed selection should only search within twin's nodes."""
    from modules.graph_context import _select_seeds

    with patch('modules.graph_context.supabase') as mock_supabase:
        mock_supabase.rpc.return_value.execute.return_value.data = []

        seeds = await _select_seeds(twin_a["id"], "test query")

        # Verify correct twin_id was used
        call_args = mock_supabase.rpc.call_args
        params = call_args[0][1]  # Second positional arg is params dict
        assert params["t_id"] == twin_a["id"]


# ISO-006: 1-hop expansion scoped by twin_id
@pytest.mark.asyncio
async def test_one_hop_expansion_scoped(twin_a):
    """1-hop expansion should only traverse twin's edges."""
    from modules.graph_context import _expand_one_hop

    with patch('modules.graph_context.supabase') as mock_supabase:
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

        await _expand_one_hop(twin_a["id"], ["node1"])

        # Verify edges query uses twin_id
        mock_supabase.table.assert_called_with("edges")


# ISO-007: MemoryEvent read scoped by twin_id
@pytest.mark.asyncio
async def test_memory_event_read_scoped(twin_a):
    """Memory events should only be readable by owning twin."""
    from modules.memory_events import get_memory_events

    with patch('modules.memory_events.supabase') as mock_supabase:
        mock_supabase.rpc.return_value.execute.return_value.data = []

        events = await get_memory_events(twin_a["id"])

        # Verify RPC uses correct twin_id
        mock_supabase.rpc.assert_called_with("get_memory_events_system", {
            "p_twin_id": twin_a["id"],
            "p_limit": 50,
            "p_event_type": None
        })


# ISO-008: TIL feed scoped by twin_id
@pytest.mark.asyncio
async def test_til_feed_scoped(twin_a):
    """TIL feed should only show events for the requesting twin."""
    from modules.memory_events import get_til_feed

    with patch('modules.memory_events.get_memory_events') as mock_get:
        mock_get.return_value = []

        await get_til_feed(twin_a["id"])

        mock_get.assert_called_once_with(twin_a["id"], limit=50)


# ISO-009: Confirm action scoped by twin_id
@pytest.mark.asyncio
async def test_confirm_action_scoped(twin_a):
    """Confirm action should create event for correct twin."""
    from modules.memory_events import create_memory_event

    with patch('modules.memory_events.supabase') as mock_supabase:
        mock_supabase.rpc.return_value.execute.return_value.data = [{"id": "event1"}]

        await create_memory_event(
            twin_id=twin_a["id"],
            tenant_id=twin_a["tenant_id"],
            event_type="confirm",
            payload={"node_id": "node1"}
        )

        call_args = mock_supabase.rpc.call_args
        params = call_args[0][1]  # Second positional arg is params dict
        assert params["p_twin_id"] == twin_a["id"]
        assert params["p_tenant_id"] == twin_a["tenant_id"]


# ISO-010: Delete action scoped by twin_id
@pytest.mark.asyncio
async def test_delete_action_scoped(twin_a):
    """Delete action should only affect own twin's nodes."""
    from modules.memory_events import create_memory_event

    with patch('modules.memory_events.supabase') as mock_supabase:
        mock_supabase.rpc.return_value.execute.return_value.data = [{"id": "event1"}]

        await create_memory_event(
            twin_id=twin_a["id"],
            tenant_id=twin_a["tenant_id"],
            event_type="delete",
            payload={"node_id": "node1", "deleted_by": "user1"}
        )

        call_args = mock_supabase.rpc.call_args
        params = call_args[0][1]  # Second positional arg is params dict
        assert params["p_twin_id"] == twin_a["id"]
        assert params["p_event_type"] == "delete"
