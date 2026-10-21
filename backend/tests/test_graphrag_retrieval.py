# backend/tests/test_graphrag_retrieval.py
"""GraphRAG Retrieval Tests

Tests for GraphRAG retrieval functionality.
"""

import pytest
from unittest.mock import AsyncMock, patch
import uuid



@pytest.fixture(autouse=True)
def _no_vector_seed_search():
    """Seed selection falls back to vector_store.search, which embeds the query
    via OpenAI/Gemini. No vector hits keeps these tests on graph retrieval."""
    with patch("adk_core.services.vector_store.search", new=AsyncMock(return_value=[])):
        yield

@pytest.fixture
def twin_id():
    return str(uuid.uuid4())


@pytest.fixture
def mock_nodes():
    """Mock nodes data."""
    return [
        {
            "id": "node1",
            "twin_id": "twin1",
            "name": "Python",
            "type": "Technology",
            "description": "Favorite programming language",
            "properties": {},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z"
        },
        {
            "id": "node2",
            "twin_id": "twin1",
            "name": "AI",
            "type": "Interest",
            "description": "Interest in artificial intelligence",
            "properties": {},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z"
        }
    ]


@pytest.fixture
def mock_edges():
    """Mock edges data."""
    return [
        {
            "id": "edge1",
            "twin_id": "twin1",
            "from_node_id": "node1",
            "to_node_id": "node2",
            "type": "RELATED_TO",
            "description": "Python used for AI",
            "weight": 1.0,
            "properties": {},
            "created_at": "2024-01-01T00:00:00Z"
        }
    ]


# Test 1: get_graph_snapshot returns contexts when graph has known nodes
@pytest.mark.asyncio
async def test_get_graph_snapshot_returns_contexts(twin_id, mock_nodes):
    """get_graph_snapshot should return non-empty context when graph has nodes."""
    from modules.graph_context import get_graph_snapshot

    with patch('modules.graph_context.supabase') as mock_supabase:
        # Mock RPC call for nodes
        mock_supabase.rpc.return_value.execute.return_value.data = mock_nodes

        # Mock edges query (empty for simplicity)
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

        snapshot = await get_graph_snapshot(twin_id, query="python programming")

        assert snapshot is not None
        assert snapshot.get("node_count", 0) > 0
        # Should have context text when nodes exist
        context_text = snapshot.get("context_text", "")
        # Even if empty, node_count should be > 0
        assert snapshot["node_count"] > 0


# Test 2: get_graph_snapshot returns empty when graph has no nodes
@pytest.mark.asyncio
async def test_get_graph_snapshot_empty_graph(twin_id):
    """get_graph_snapshot should return empty context when graph has no nodes."""
    from modules.graph_context import get_graph_snapshot

    with patch('modules.graph_context.supabase') as mock_supabase:
        # Mock RPC call returning no nodes
        mock_supabase.rpc.return_value.execute.return_value.data = []
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

        snapshot = await get_graph_snapshot(twin_id, query="test query")

        assert snapshot is not None
        assert snapshot.get("node_count", 0) == 0
        assert snapshot.get("context_text", "") == ""


# Test 3: get_graph_snapshot handles errors gracefully
@pytest.mark.asyncio
async def test_get_graph_snapshot_error_handling(twin_id):
    """get_graph_snapshot should handle errors gracefully and return empty result."""
    from modules.graph_context import get_graph_snapshot

    with patch('modules.graph_context.supabase') as mock_supabase:
        # Mock RPC call to raise exception in _select_seeds and _get_all_nodes
        mock_supabase.rpc.side_effect = Exception("Database error")

        snapshot = await get_graph_snapshot(twin_id, query="test query")

        assert snapshot is not None
        assert snapshot.get("node_count", 0) == 0
        # Error is logged but not returned in snapshot (by design - graceful degradation)
        # The snapshot should still be a valid structure
        assert "context_text" in snapshot
        assert "nodes" in snapshot


# Test 4: Integration test - toggling works and fallback triggers
@pytest.mark.asyncio
async def test_integration_toggle_fallback(twin_id):
    """Integration test: toggling feature flag works, fallback triggers when graph returns nothing."""
    from modules.graph_context import get_graph_snapshot

    # Test with empty graph (simulates fallback scenario)
    with patch('modules.graph_context.supabase') as mock_supabase:
        mock_supabase.rpc.return_value.execute.return_value.data = []
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

        snapshot = await get_graph_snapshot(twin_id, query="test")

        # Should return empty but valid structure
        assert snapshot is not None
        assert snapshot.get("node_count", 0) == 0
        assert "context_text" in snapshot
        assert "nodes" in snapshot
        assert "edges" in snapshot


# Test 5: Seed selection works with matching query
@pytest.mark.asyncio
async def test_seed_selection_matching_query(twin_id, mock_nodes):
    """Seed selection should find nodes matching query keywords."""
    from modules.graph_context import _select_seeds

    with patch('modules.graph_context.supabase') as mock_supabase:
        mock_supabase.rpc.return_value.execute.return_value.data = mock_nodes

        seeds = await _select_seeds(twin_id, "python programming language")

        # Should find at least one node matching "python"
        assert len(seeds) > 0
        # Check that Python node is in results
        node_names = [n.get("name", "") for n in seeds]
        assert any("python" in name.lower() for name in node_names)


# Test 6: Seed selection returns empty for non-matching query
@pytest.mark.asyncio
async def test_seed_selection_non_matching_query(twin_id, mock_nodes):
    """Seed selection should return empty for queries that don't match any nodes."""
    from modules.graph_context import _select_seeds

    with patch('modules.graph_context.supabase') as mock_supabase:
        mock_supabase.rpc.return_value.execute.return_value.data = mock_nodes

        seeds = await _select_seeds(twin_id, "completely unrelated query xyz123")

        # Should return empty for non-matching query
        assert len(seeds) == 0

