"""
Tests for Graph Context Soft Budget Enforcement (Phase 2)

Verifies that:
1. Chat does not block beyond soft budget when graph is slow
2. Context is included only if available within budget
3. Fallback behavior works when graph unavailable
"""

import pytest
import asyncio
import time
from unittest.mock import AsyncMock, patch, MagicMock

from modules.graph_context_builder import (
    GraphContextBuilder,
    GraphContextResult,
    get_graph_context_for_chat
)


class TestSoftBudgetEnforcement:
    """Test soft budget (300-600ms) enforcement for chat context."""

    @pytest.mark.asyncio
    async def test_returns_context_within_budget(self):
        """Context should be returned if available within soft budget."""
        with patch('modules.graph_context_builder.get_graph_memory_config') as mock_config:
            mock_config.return_value = MagicMock()
            mock_config.return_value.is_read_allowed.return_value = True
            mock_config.return_value.chat_soft_budget_ms = 500
            mock_config.return_value.neo4j_uri = "bolt://localhost:7687"
            mock_config.return_value.neo4j_user = "neo4j"
            mock_config.return_value.neo4j_password = "password"

            with patch('modules.graph_memory_core._get_pooled_driver') as mock_driver:
                mock_driver.return_value = MagicMock()

                builder = GraphContextBuilder(
                    tenant_id="test-tenant",
                    twin_id="test-twin",
                    correlation_id="test"
                )

                # Mock the internal _fetch_and_format_context
                builder._fetch_and_format_context = AsyncMock(return_value={
                    'episodes': [{"name": "Episode 1", "content": "Graph content"}],
                    'claim_count': 0
                })

                start = time.time()
                result = await builder.build_context("test query", soft_budget_ms=500)
                elapsed = (time.time() - start) * 1000

                assert result.context is not None
                assert result.source == "graph"
                assert result.episode_count == 1
                assert elapsed < 600  # Should complete within soft budget + buffer

    @pytest.mark.asyncio
    async def test_timeout_when_graph_slow(self):
        """Chat should not block beyond soft budget when graph is slow."""
        with patch('modules.graph_context_builder.get_graph_memory_config') as mock_config:
            mock_config.return_value = MagicMock()
            mock_config.return_value.is_read_allowed.return_value = True
            mock_config.return_value.chat_soft_budget_ms = 200
            mock_config.return_value.neo4j_uri = "bolt://localhost:7687"
            mock_config.return_value.neo4j_user = "neo4j"
            mock_config.return_value.neo4j_password = "password"

            builder = GraphContextBuilder(
                tenant_id="test-tenant",
                twin_id="test-twin"
            )

            # Mock slow fetch that exceeds budget
            async def slow_fetch(*args, **kwargs):
                await asyncio.sleep(1.0)  # 1 second delay
                return {'episodes': [], 'claim_count': 0}

            builder._fetch_and_format_context = slow_fetch

            start = time.time()
            result = await builder.build_context("test query", soft_budget_ms=200)
            elapsed = (time.time() - start) * 1000

            assert result.context is None
            assert result.source == "timeout"
            assert elapsed < 400  # Should timeout quickly (200ms + buffer)

    @pytest.mark.asyncio
    async def test_fallback_when_graph_disabled(self):
        """Should gracefully fallback when graph memory disabled."""
        with patch('modules.graph_context_builder.get_graph_memory_config') as mock_config:
            mock_config.return_value = MagicMock()
            mock_config.return_value.is_read_allowed.return_value = False

            builder = GraphContextBuilder(
                tenant_id="test-tenant",
                twin_id="test-twin"
            )

            start = time.time()
            result = await builder.build_context("test query")
            elapsed = (time.time() - start) * 1000

            assert result.context is None
            assert result.source == "disabled"
            assert elapsed < 50  # Should return immediately

    @pytest.mark.asyncio
    async def test_fallback_when_graph_unavailable(self):
        """Should gracefully fallback when Neo4j unavailable."""
        with patch('modules.graph_context_builder.get_graph_memory_config') as mock_config:
            mock_config.return_value = MagicMock()
            mock_config.return_value.is_read_allowed.return_value = True
            mock_config.return_value.chat_soft_budget_ms = 500
            mock_config.return_value.neo4j_uri = None  # Not configured
            mock_config.return_value.neo4j_user = None
            mock_config.return_value.neo4j_password = None

            builder = GraphContextBuilder(
                tenant_id="test-tenant",
                twin_id="test-twin"
            )

            # Mock fetch that raises exception
            async def failing_fetch(*args, **kwargs):
                raise Exception("Neo4j connection failed")

            builder._fetch_and_format_context = failing_fetch

            result = await builder.build_context("test query")

            assert result.context is None
            assert result.source == "unavailable"

    @pytest.mark.asyncio
    async def test_parallel_retrieval_doesnt_block_chat(self):
        """Graph retrieval in parallel should not block chat response."""
        with patch('modules.graph_context_builder.GraphMemoryCore') as mock_core:
            # Mock moderately slow response (300ms)
            async def medium_search(*args, **kwargs):
                await asyncio.sleep(0.3)
                return [{"name": "Episode", "content": "Content"}]

            mock_client = MagicMock()
            mock_client.search = medium_search
            mock_client.config = MagicMock()
            mock_client.config.is_read_allowed.return_value = True
            mock_client.config.chat_soft_budget_ms = 500
            mock_client.config.neo4j_uri = "bolt://localhost:7687"
            mock_client.config.neo4j_user = "neo4j"
            mock_client.config.neo4j_password = "password"
            mock_core.return_value = mock_client

            builder = GraphContextBuilder(
                tenant_id="test-tenant",
                twin_id="test-twin"
            )

            # Simulate parallel retrieval with timeout
            async def parallel_retrieval():
                return await builder.build_context("test query", soft_budget_ms=500)

            start = time.time()
            result = await parallel_retrieval()
            elapsed = (time.time() - start) * 1000

            # Should complete within soft budget even if context returned
            assert elapsed < 600


class TestDebugHeaders:
    """Test debug header generation gated by GRAPH_MEMORY_DEBUG_HEADERS."""

    @pytest.mark.asyncio
    async def test_debug_headers_when_enabled(self):
        """Debug headers should be returned when feature flag enabled."""
        with patch('modules.graph_context_builder.get_graph_memory_config') as mock_config:
            mock_config.return_value = MagicMock()
            mock_config.return_value.debug_headers = True

            builder = GraphContextBuilder(
                tenant_id="test-tenant",
                twin_id="test-twin"
            )

            result = GraphContextResult(
                context="Test context",
                latency_ms=150.5,
                source="graph",
                episode_count=3,
                claim_count=5
            )

            headers = builder.get_debug_headers(result)

            assert "X-Graph-Context-Source" in headers
            assert headers["X-Graph-Context-Source"] == "graph"
            assert "X-Graph-Context-Latency-Ms" in headers
            assert headers["X-Graph-Context-Latency-Ms"] == "150"
            assert "X-Graph-Context-Episodes" in headers
            assert headers["X-Graph-Context-Episodes"] == "3"

    @pytest.mark.asyncio
    async def test_no_debug_headers_when_disabled(self):
        """Debug headers should be empty when feature flag disabled."""
        with patch('modules.graph_context_builder.get_graph_memory_config') as mock_config:
            mock_config.return_value = MagicMock()
            mock_config.return_value.debug_headers = False

            builder = GraphContextBuilder(
                tenant_id="test-tenant",
                twin_id="test-twin"
            )

            result = GraphContextResult(
                context="Test context",
                latency_ms=150.5,
                source="graph",
                episode_count=3,
                claim_count=5
            )

            headers = builder.get_debug_headers(result)

            assert headers == {}


class TestConvenienceFunction:
    """Test the get_graph_context_for_chat convenience function."""

    @pytest.mark.asyncio
    async def test_convenience_function_works(self):
        """Convenience function should work with minimal parameters."""
        with patch('modules.graph_context_builder.GraphMemoryCore') as mock_core:
            mock_client = MagicMock()
            mock_client.search = AsyncMock(return_value=[])
            mock_client.config = MagicMock()
            mock_client.config.is_read_allowed.return_value = True
            mock_client.config.chat_soft_budget_ms = 500
            mock_client.config.neo4j_uri = "bolt://localhost:7687"
            mock_client.config.neo4j_user = "neo4j"
            mock_client.config.neo4j_password = "password"
            mock_core.return_value = mock_client

            result = await get_graph_context_for_chat(
                tenant_id="tenant-1",
                twin_id="twin-1",
                query="What is the answer?"
            )

            assert isinstance(result, GraphContextResult)
            assert result.source in ['graph', 'timeout', 'unavailable', 'disabled']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
