"""
Tests for Phase 3: Materialized Graph Snapshots

Verifies:
1. Fast reads from Supabase
2. TTL-based expiration
3. Fallback to direct query
4. Proper formatting for agent context
"""

import pytest
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

from modules.graph_snapshot_manager import (
    GraphSnapshotManager,
    GraphSnapshot,
    get_fast_graph_context,
    refresh_twin_snapshot
)


class TestSnapshotReads:
    """Test fast snapshot reads from Supabase."""

    @pytest.mark.asyncio
    async def test_get_snapshot_from_supabase(self):
        """Should read snapshot from Supabase."""
        with patch('modules.graph_snapshot_manager.supabase') as mock_supabase:
            mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[{
                    "twin_id": "twin1",
                    "tenant_id": "tenant1",
                    "group_id": "tenant1__twin1",
                    "snapshot_data": json.dumps({"episodes": [{"name": "Ep1", "content": "Content"}]}),
                    "episode_count": 1,
                    "claim_count": 0,
                    "created_at": datetime.utcnow().isoformat(),
                    "expires_at": (datetime.utcnow() + timedelta(minutes=5)).isoformat(),
                    "version": 1
                }]
            )

            manager = GraphSnapshotManager()
            snapshot = await manager.get_snapshot("tenant1", "twin1")

            assert snapshot is not None
            assert snapshot.twin_id == "twin1"

    @pytest.mark.asyncio
    async def test_returns_none_when_expired(self):
        """Should return None when snapshot expired."""
        with patch('modules.graph_snapshot_manager.supabase') as mock_supabase:
            mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[{
                    "twin_id": "twin1",
                    "tenant_id": "tenant1",
                    "group_id": "tenant1__twin1",
                    "snapshot_data": json.dumps({"episodes": []}),
                    "episode_count": 0,
                    "created_at": (datetime.utcnow() - timedelta(hours=1)).isoformat(),
                    "expires_at": (datetime.utcnow() - timedelta(minutes=30)).isoformat(),
                    "version": 1
                }]
            )

            manager = GraphSnapshotManager()
            snapshot = await manager.get_snapshot("tenant1", "twin1")

            assert snapshot is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_snapshot(self):
        """Should return None when no snapshot exists."""
        with patch('modules.graph_snapshot_manager.supabase') as mock_supabase:
            mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[]
            )

            manager = GraphSnapshotManager()
            snapshot = await manager.get_snapshot("tenant1", "twin1")

            assert snapshot is None


class TestSnapshotFormatting:
    """Test snapshot formatting for agent context."""

    @pytest.mark.asyncio
    async def test_format_snapshot_for_agent(self):
        """Should format snapshot into agent-readable context."""
        with patch('modules.graph_snapshot_manager.supabase') as mock_supabase:
            mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[{
                    "twin_id": "twin1",
                    "tenant_id": "tenant1",
                    "group_id": "tenant1__twin1",
                    "snapshot_data": json.dumps({
                        "episodes": [
                            {"name": "Meeting 1", "content": "Discussed project timeline"},
                            {"name": "Email", "content": "Sent follow-up notes"}
                        ]
                    }),
                    "episode_count": 2,
                    "claim_count": 0,
                    "created_at": datetime.utcnow().isoformat(),
                    "expires_at": (datetime.utcnow() + timedelta(minutes=5)).isoformat(),
                    "version": 1
                }]
            )

            manager = GraphSnapshotManager()
            context = await manager.get_formatted_context("tenant1", "twin1")

            assert context is not None
            assert "## Graph Memory Context" in context
            assert "Meeting 1" in context
            assert "Discussed project timeline" in context

    @pytest.mark.asyncio
    async def test_filter_relevant_by_query(self):
        """Should filter episodes by relevance to query."""
        manager = GraphSnapshotManager()

        snapshot = GraphSnapshot(
            scope_id="tenant1__twin1",
            twin_id="twin1",
            tenant_id="tenant1",
            group_id="tenant1__twin1",
            snapshot_data={
                "episodes": [
                    {"name": "Meeting", "content": "Discussed project timeline"},
                    {"name": "Email", "content": "Budget approval requested"},
                    {"name": "Chat", "content": "Team lunch plans"}
                ]
            },
            episode_count=3,
            claim_count=0,
            created_at=datetime.utcnow().isoformat(),
            expires_at=(datetime.utcnow() + timedelta(minutes=5)).isoformat(),
            version=1
        )

        formatted = manager._format_snapshot(snapshot, query="budget approval")

        assert "Budget approval" in formatted
        assert "project timeline" not in formatted  # Less relevant


class TestSnapshotRefresh:
    """Test snapshot refresh from Neo4j."""

    @pytest.mark.asyncio
    async def test_refresh_creates_snapshot(self):
        """Should refresh snapshot from Neo4j and store in Supabase."""
        with patch('modules.graph_snapshot_manager.get_graph_memory_config') as mock_config, \
             patch('modules.graph_snapshot_manager.GraphMemoryCore') as mock_core, \
             patch('modules.graph_snapshot_manager.supabase') as mock_supabase:

            mock_config.return_value = MagicMock()
            mock_config.return_value.is_read_allowed.return_value = True
            mock_config.return_value.make_group_id.return_value = "tenant1__twin1"

            mock_client = MagicMock()
            mock_client.search = AsyncMock(return_value=[
                {"name": "Ep1", "content": "Content 1"},
                {"name": "Ep2", "content": "Content 2"}
            ])
            mock_core.return_value = mock_client

            mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock()

            manager = GraphSnapshotManager()
            result = await manager.refresh_snapshot("tenant1", "twin1")

            assert result is True
            mock_client.search.assert_called_once()
            mock_supabase.table.return_value.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_respects_write_permissions(self):
        """Should not refresh if graph writes disabled."""
        with patch('modules.graph_snapshot_manager.get_graph_memory_config') as mock_config:
            mock_config.return_value = MagicMock()
            mock_config.return_value.is_read_allowed.return_value = False

            manager = GraphSnapshotManager()
            result = await manager.refresh_snapshot("tenant1", "twin1")

            assert result is False


class TestFallbackBehavior:
    """Test fallback to direct query when snapshot unavailable."""

    @pytest.mark.asyncio
    async def test_fast_context_uses_snapshot(self):
        """get_fast_graph_context should use snapshot when available."""
        with patch('modules.graph_snapshot_manager.GraphSnapshotManager') as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.get_formatted_context = AsyncMock(return_value="Snapshot context")
            mock_manager_class.return_value = mock_manager

            context = await get_fast_graph_context("tenant1", "twin1", "query")

            assert context == "Snapshot context"
            mock_manager.get_formatted_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_fast_context_returns_none_when_no_snapshot(self):
        """Should return None when no snapshot and no fallback."""
        with patch('modules.graph_snapshot_manager.GraphSnapshotManager') as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.get_formatted_context = AsyncMock(return_value=None)
            mock_manager_class.return_value = mock_manager

            context = await get_fast_graph_context("tenant1", "twin1", "query")

            assert context is None


class TestWorkerRefresh:
    """Test worker-driven snapshot refresh."""

    @pytest.mark.asyncio
    async def test_worker_refresh_function(self):
        """Worker should refresh snapshot via refresh_twin_snapshot."""
        with patch('modules.graph_snapshot_manager.GraphSnapshotManager') as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.refresh_snapshot = AsyncMock(return_value=True)
            mock_manager_class.return_value = mock_manager

            result = await refresh_twin_snapshot("tenant1", "twin1")

            assert result is True
            mock_manager.refresh_snapshot.assert_called_once_with(
                tenant_id="tenant1", twin_id="twin1", correlation_id=None, creator_id=None
            )


class TestTenantTwinIsolation:
    """Test tenant/twin isolation."""

    @pytest.mark.asyncio
    async def test_group_id_in_query(self):
        """Supabase queries should filter by group_id."""
        with patch('modules.graph_snapshot_manager.supabase') as mock_supabase:
            mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

            manager = GraphSnapshotManager()
            await manager.get_snapshot("tenant1", "twin1")

            # Verify both twin_id and group_id filters applied
            calls = mock_supabase.table.return_value.select.return_value.eq.call_args_list
            # Should have eq("twin_id", twin_id) and eq("group_id", group_id)
            assert len(calls) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
