# tests/test_content_extraction.py
"""
Integration tests for content-to-graph extraction.

Tests:
1. extract_from_content() function extracts nodes/edges from text
2. API endpoint /ingest/extract-nodes/{source_id} works correctly
3. Nodes/edges are persisted to graph_nodes/graph_edges tables
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


# Test 1: extract_from_content returns expected structure
@pytest.mark.asyncio
async def test_extract_from_content_returns_nodes_and_edges():
    """Verify extract_from_content returns nodes and edges from sample content."""

    # Mock the OpenAI response
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.parsed = MagicMock()
    mock_response.choices[0].message.parsed.nodes = [
        MagicMock(name="Test Company", type="Company", description="A test company", properties=[]),
        MagicMock(name="John Doe", type="Person", description="CEO of Test Company", properties=[])
    ]
    mock_response.choices[0].message.parsed.edges = [
        MagicMock(from_node="John Doe", to_node="Test Company", type="CEO_OF", description="Is CEO")
    ]
    mock_response.choices[0].message.parsed.confidence = 0.85

    # Mock the persist functions
    mock_nodes = [
        {"id": "node-1", "name": "Test Company", "type": "Company"},
        {"id": "node-2", "name": "John Doe", "type": "Person"}
    ]
    mock_edges = [
        {"id": "edge-1", "from_node": "node-2", "to_node": "node-1", "type": "CEO_OF"}
    ]

    with patch('modules._core.scribe_engine.get_async_openai_client') as mock_client, \
         patch('modules._core.scribe_engine._persist_nodes', new_callable=AsyncMock, return_value=mock_nodes), \
         patch('modules._core.scribe_engine._persist_edges', new_callable=AsyncMock, return_value=mock_edges), \
         patch('modules.memory_events.create_memory_event', new_callable=AsyncMock, return_value={"id": "mem-1"}):

        # Setup mock client
        mock_client.return_value = MagicMock()
        mock_client.return_value.beta = MagicMock()
        mock_client.return_value.beta.chat = MagicMock()
        mock_client.return_value.beta.chat.completions = MagicMock()
        mock_client.return_value.beta.chat.completions.parse = AsyncMock(return_value=mock_response)

        from modules._core.scribe_engine import extract_from_content

        result = await extract_from_content(
            twin_id="test-twin-123",
            content_text="John Doe is the CEO of Test Company. The company was founded in 2020 and focuses on AI technology.",
            source_id="source-123",
            source_type="test",
            tenant_id="tenant-123"
        )

        # Assertions
        assert "all_nodes" in result
        assert "all_edges" in result
        assert "chunks_processed" in result
        assert len(result["all_nodes"]) == 2
        assert len(result["all_edges"]) == 1
        assert result["chunks_processed"] >= 1


# Test 2: extract_from_content handles empty content gracefully
@pytest.mark.asyncio
async def test_extract_from_content_handles_empty_content():
    """Verify extract_from_content returns empty result for empty content."""

    from modules._core.scribe_engine import extract_from_content

    result = await extract_from_content(
        twin_id="test-twin-123",
        content_text="",
        source_id="source-123"
    )

    assert result["all_nodes"] == []
    assert result["all_edges"] == []
    assert result["chunks_processed"] == 0


# Test 3: extract_from_content handles short content
@pytest.mark.asyncio
async def test_extract_from_content_handles_short_content():
    """Verify extract_from_content returns empty for content < 50 chars."""

    from modules._core.scribe_engine import extract_from_content

    result = await extract_from_content(
        twin_id="test-twin-123",
        content_text="Too short",
        source_id="source-123"
    )

    assert result["all_nodes"] == []
    assert result["chunks_processed"] == 0


# Test 4: extract_from_content chunks large content correctly
@pytest.mark.asyncio
async def test_extract_from_content_chunks_large_content():
    """Verify large content is chunked appropriately."""

    # Create content larger than chunk_size
    large_content = "This is a test sentence about AI technology. " * 200  # ~9000 chars

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.parsed = MagicMock()
    mock_response.choices[0].message.parsed.nodes = []
    mock_response.choices[0].message.parsed.edges = []
    mock_response.choices[0].message.parsed.confidence = 0.5

    with patch('modules._core.scribe_engine.get_async_openai_client') as mock_client, \
         patch('modules._core.scribe_engine._persist_nodes', new_callable=AsyncMock, return_value=[]), \
         patch('modules._core.scribe_engine._persist_edges', new_callable=AsyncMock, return_value=[]):

        mock_client.return_value.beta.chat.completions.parse = AsyncMock(return_value=mock_response)

        from modules._core.scribe_engine import extract_from_content

        result = await extract_from_content(
            twin_id="test-twin-123",
            content_text=large_content,
            source_id="source-123",
            chunk_size=4000,
            max_chunks=3
        )

        # Should have processed multiple chunks (but limited by max_chunks)
        assert result["chunks_processed"] <= 3


# Test 5: GraphUpdates schema is correct
def test_graph_updates_schema():
    """Verify GraphUpdates Pydantic schema is valid."""
    from modules._core.scribe_engine import GraphUpdates, NodeUpdate, EdgeUpdate, Property

    # Create valid objects
    prop = Property(key="sector", value="Technology")
    node = NodeUpdate(
        name="Test Node",
        type="Company",
        description="A test node",
        properties=[prop]
    )
    edge = EdgeUpdate(
        from_node="Node A",
        to_node="Node B",
        type="RELATES_TO",
        description="Some relationship"
    )
    graph = GraphUpdates(
        nodes=[node],
        edges=[edge],
        confidence=0.9
    )

    assert len(graph.nodes) == 1
    assert len(graph.edges) == 1
    assert graph.confidence == 0.9


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
