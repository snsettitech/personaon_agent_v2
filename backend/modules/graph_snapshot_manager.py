"""
Graph Snapshot Manager (Phase 3)

Manages materialized graph-context snapshots per scope (single-profile).
Stored in Supabase for instant chat reads.
Refreshed asynchronously by worker.

Single-Profile Scope Migration:
- scope_id: "{tenant_id}__{creator_id}" (single-profile boundary)
- Queries use scope_id for isolation
- twin_id kept for backward compatibility during rollout
"""

import asyncio
import json
from typing import Any
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from modules.graph_memory_core import GraphMemoryCore
from modules.graph_memory_config import get_graph_memory_config, is_single_profile_enabled
from modules.observability import supabase


@dataclass
class GraphSnapshot:
    """Materialized snapshot of graph context for a scope."""
    scope_id: str
    tenant_id: str
    twin_id: str  # Kept for backward compat
    group_id: str  # Same as scope_id
    snapshot_data: dict[str, Any]
    episode_count: int
    claim_count: int
    created_at: str
    expires_at: str
    version: int


class GraphSnapshotManager:
    """
    Manages materialized graph-context snapshots.

    - Chat reads from Supabase (instant)
    - Worker refreshes from Neo4j (async)
    - TTL-based expiration (default 5 minutes)
    - Single-profile scope isolation

    Usage:
        manager = GraphSnapshotManager()

        # Chat path (fast read from Supabase) - Single-profile mode
        snapshot = await manager.get_snapshot_by_scope(scope_id)

        # Legacy mode (during rollout)
        snapshot = await manager.get_snapshot(tenant_id, twin_id)

        # Worker path (refresh from Neo4j)
        await manager.refresh_snapshot(tenant_id, twin_id, creator_id)
    """

    DEFAULT_TTL_SECONDS = 300  # 5 minutes

    def __init__(self):
        self.config = get_graph_memory_config()

    def _make_scope_id(self, tenant_id: str, creator_id: str) -> str:
        """Generate scope_id for single-profile isolation."""
        return self.config.make_scope_id(tenant_id, creator_id)

    def _make_group_id(self, tenant_id: str, twin_id: str) -> str:
        """Generate group_id for tenant/twin isolation (legacy)."""
        return self.config.make_group_id(tenant_id, twin_id)

    async def _run_db(self, callable_obj):
        """Run blocking Supabase calls off the event loop."""
        return await asyncio.to_thread(callable_obj)

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except Exception:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _parse_snapshot_data(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return {}
        return {}

    async def get_snapshot_by_scope(
        self,
        scope_id: str,
        max_age_seconds: int = 300
    ) -> GraphSnapshot | None:
        """
        Get snapshot from Supabase by scope_id (single-profile path - must be fast).

        Args:
            scope_id: Scope ID (format: "{tenant_id}__{creator_id}")
            max_age_seconds: Maximum acceptable age (default 5 min)

        Returns:
            GraphSnapshot or None if not found/expired
        """
        try:
            tenant_hint = scope_id.split("__", 1)[0] if "__" in scope_id else None

            def _query():
                query = supabase.table("graph_context_snapshots").select("*").eq(
                    "scope_id", scope_id
                )
                if tenant_hint:
                    query = query.eq("tenant_id", tenant_hint)
                return query.order("created_at", desc=True).limit(1).execute()

            result = await self._run_db(_query)

            if not result.data:
                return None

            row = result.data[0]

            # Check expiration
            created_at = self._parse_dt(row.get("created_at"))
            expires_at = self._parse_dt(row.get("expires_at"))
            now = datetime.now(timezone.utc)
            if not created_at or not expires_at:
                return None

            if now > expires_at:
                return None

            # Check max age
            age_seconds = (now - created_at).total_seconds()
            if age_seconds > max_age_seconds:
                return None

            return GraphSnapshot(
                scope_id=row.get('scope_id', row.get('group_id', '')),
                tenant_id=row['tenant_id'],
                twin_id=row.get('twin_id', ''),
                group_id=row.get('group_id', ''),
                snapshot_data=self._parse_snapshot_data(row.get("snapshot_data")),
                episode_count=int(row.get('episode_count') or 0),
                claim_count=int(row.get('claim_count') or 0),
                created_at=str(row.get('created_at') or ""),
                expires_at=str(row.get('expires_at') or ""),
                version=int(row.get('version') or 1)
            )

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"[GraphSnapshot] Failed to get snapshot by scope: {e}")
            return None

    async def get_snapshot(
        self,
        tenant_id: str,
        twin_id: str,
        max_age_seconds: int = 300,
        creator_id: str | None = None
    ) -> GraphSnapshot | None:
        """
        Get snapshot from Supabase (chat path - must be fast).

        Supports both single-profile and legacy modes.

        Args:
            tenant_id: Tenant ID
            twin_id: Twin ID (legacy)
            max_age_seconds: Maximum acceptable age (default 5 min)
            creator_id: Creator ID for single-profile mode (optional)

        Returns:
            GraphSnapshot or None if not found/expired
        """
        # Single-profile mode: prefer canonical scope_id.
        if is_single_profile_enabled() and creator_id:
            scope_id = self._make_scope_id(tenant_id, creator_id)
            scoped = await self.get_snapshot_by_scope(scope_id, max_age_seconds)
            if scoped:
                return scoped

        try:
            group_id = self._make_group_id(tenant_id, twin_id)

            # Dual-read strategy during rollout.
            if is_single_profile_enabled():
                from modules.twin_namespace import resolve_scope_from_twin

                resolved_scope = await asyncio.to_thread(resolve_scope_from_twin, twin_id)
                if resolved_scope:
                    scoped = await self.get_snapshot_by_scope(resolved_scope, max_age_seconds)
                    if scoped:
                        return scoped

            def _legacy_query():
                return (
                    supabase.table("graph_context_snapshots")
                    .select("*")
                    .eq("tenant_id", tenant_id)
                    .eq("twin_id", twin_id)
                    .eq("group_id", group_id)
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )

            result = await self._run_db(_legacy_query)
            if not result.data:
                return None

            row = result.data[0]
            created_at = self._parse_dt(row.get("created_at"))
            expires_at = self._parse_dt(row.get("expires_at"))
            now = datetime.now(timezone.utc)
            if not created_at or not expires_at:
                return None
            if now > expires_at:
                return None
            if (now - created_at).total_seconds() > max_age_seconds:
                return None

            return GraphSnapshot(
                scope_id=row.get("scope_id", group_id),
                tenant_id=row["tenant_id"],
                twin_id=row.get("twin_id", twin_id),
                group_id=row.get("group_id", group_id),
                snapshot_data=self._parse_snapshot_data(row.get("snapshot_data")),
                episode_count=int(row.get("episode_count") or 0),
                claim_count=int(row.get("claim_count") or 0),
                created_at=str(row.get("created_at") or ""),
                expires_at=str(row.get("expires_at") or ""),
                version=int(row.get("version") or 1),
            )

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"[GraphSnapshot] Failed to get snapshot: {e}")
            return None

    async def refresh_snapshot(
        self,
        tenant_id: str,
        twin_id: str,
        correlation_id: str | None = None,
        creator_id: str | None = None
    ) -> bool:
        """
        Refresh snapshot from Neo4j (worker path - can be slow).

        Args:
            tenant_id: Tenant ID
            twin_id: Twin ID (legacy, for backward compat)
            correlation_id: For tracing
            creator_id: Creator ID for single-profile mode

        Returns:
            True if successful
        """
        try:
            # Determine scope
            if creator_id:
                scope_id = self._make_scope_id(tenant_id, creator_id)
            else:
                scope_id = self._make_group_id(tenant_id, twin_id)

            # 1) Load recent claims from Supabase (fast and deterministic).
            def _load_claims():
                query = (
                    supabase.table("graph_claims")
                    .select("claim_id,claim_text,claim_type,confidence,source_type,source_ref,extracted_at,scope_id")
                    .eq("tenant_id", tenant_id)
                )
                if scope_id:
                    query = query.eq("scope_id", scope_id)
                else:
                    query = query.eq("twin_id", twin_id)
                return query.order("extracted_at", desc=True).limit(120).execute()

            claims_result = await self._run_db(_load_claims)
            claims_rows = claims_result.data or []

            # 2) Best-effort graph episode fetch. If unavailable, build from claims.
            episodes: list[dict[str, Any]] = []
            if self.config.is_read_allowed():
                try:
                    client = GraphMemoryCore(
                        tenant_id=tenant_id,
                        twin_id=twin_id,
                        correlation_id=correlation_id,
                        creator_id=creator_id,
                        scope_id=scope_id,
                    )
                    episodes = await client.search("*", num_results=50) or []
                except Exception:
                    episodes = []

            if not episodes and claims_rows:
                for row in claims_rows[:20]:
                    text = str(row.get("claim_text") or "").strip()
                    if not text:
                        continue
                    episodes.append(
                        {
                            "name": f"{row.get('claim_type', 'claim').title()} Claim",
                            "content": text,
                            "source_type": row.get("source_type"),
                            "source_ref": row.get("source_ref"),
                        }
                    )

            # 3) Build snapshot data and upsert.
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=self.DEFAULT_TTL_SECONDS)
            snapshot_data = {
                "episodes": episodes,
                "claims": [
                    {
                        "claim_id": row.get("claim_id"),
                        "text": row.get("claim_text"),
                        "claim_type": row.get("claim_type"),
                        "confidence": row.get("confidence"),
                        "source_type": row.get("source_type"),
                        "source_ref": row.get("source_ref"),
                    }
                    for row in claims_rows[:50]
                ],
                "summary": self._generate_summary(episodes),
                "topics": self._extract_topics(episodes),
                "last_updated": now.isoformat(),
                "scope_id": scope_id,
            }

            payload = {
                "twin_id": twin_id,
                "tenant_id": tenant_id,
                "scope_id": scope_id,
                "group_id": scope_id,
                "snapshot_data": snapshot_data,
                "episode_count": len(episodes),
                "claim_count": len(claims_rows),
                "created_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "version": 1,
                "correlation_id": correlation_id,
            }

            def _upsert_snapshot():
                return (
                    supabase.table("graph_context_snapshots")
                    .upsert(payload, on_conflict="twin_id,group_id")
                    .execute()
                )

            await self._run_db(_upsert_snapshot)
            return True

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"[GraphSnapshot] Failed to refresh snapshot: {e}")
            return False

    def _generate_summary(self, episodes: list[dict[str, Any]]) -> str:
        """Generate text summary of episodes."""
        if not episodes:
            return ""

        parts = []
        for ep in episodes[:10]:  # Top 10
            name = ep.get('name', 'Unnamed')
            content = ep.get('content', '')
            if content:
                parts.append(f"- {name}: {content[:200]}")

        return "\n".join(parts)

    def _extract_topics(self, episodes: list[dict[str, Any]]) -> list[str]:
        """Extract topics from episodes."""
        topics = set()

        for ep in episodes:
            name = ep.get('name', '').lower()
            content = ep.get('content', '').lower()

            words = (name + " " + content).split()
            for word in words:
                word = word.strip(".,!?;:")
                if len(word) > 4 and word.isalpha():
                    topics.add(word)

        return sorted(list(topics))[:20]

    async def get_formatted_context(
        self,
        tenant_id: str,
        twin_id: str,
        query: str | None = None,
        max_age_seconds: int = 300,
        creator_id: str | None = None
    ) -> str | None:
        """
        Get formatted context string for agent (chat integration).

        Args:
            tenant_id: Tenant ID
            twin_id: Twin ID (legacy)
            query: Optional query for relevance filtering
            max_age_seconds: Maximum acceptable age
            creator_id: Creator ID for single-profile mode

        Returns:
            Formatted context string or None
        """
        snapshot = await self.get_snapshot(
            tenant_id, twin_id, max_age_seconds, creator_id
        )

        if not snapshot:
            return None

        return self._format_snapshot(snapshot, query)

    def _format_snapshot(
        self,
        snapshot: GraphSnapshot,
        query: str | None = None
    ) -> str:
        """Format snapshot into context string for agent."""
        data = snapshot.snapshot_data
        episodes = data.get('episodes', [])

        if not episodes:
            return ""

        if query:
            episodes = self._filter_relevant(episodes, query)

        parts = ["## Graph Memory Context"]
        parts.append(f"*(Based on {len(episodes)} episodes)*\n")

        for i, ep in enumerate(episodes[:5], 1):
            name = ep.get('name', 'Unnamed')
            content = ep.get('content', '')
            if content:
                parts.append(f"### {i}. {name}")
                parts.append(content[:400])
                parts.append("")

        return "\n".join(parts)

    def _filter_relevant(
        self,
        episodes: list[dict[str, Any]],
        query: str
    ) -> list[dict[str, Any]]:
        """Filter episodes by relevance to query."""
        query_words = set(query.lower().split())

        scored = []
        for ep in episodes:
            content = (ep.get('name', '') + " " + ep.get('content', '')).lower()
            score = sum(1 for word in query_words if word in content)
            if score > 0:
                scored.append((score, ep))

        scored.sort(reverse=True, key=lambda x: x[0])
        return [ep for _, ep in scored]


# Convenience function for chat integration - Single-profile mode
async def get_fast_graph_context_by_scope(
    scope_id: str,
    query: str,
    max_age_seconds: int = 300
) -> str | None:
    """
    Get graph context instantly from materialized snapshot (single-profile).

    Usage:
        context = await get_fast_graph_context_by_scope(scope_id, query)
        if context:
            agent_state["graph_context"] = context
    """
    manager = GraphSnapshotManager()
    snapshot = await manager.get_snapshot_by_scope(scope_id, max_age_seconds)

    if not snapshot:
        return None

    return manager._format_snapshot(snapshot, query)


# Legacy convenience function (backward compatibility)
async def get_fast_graph_context(
    tenant_id: str,
    twin_id: str,
    query: str,
    max_age_seconds: int = 300,
    creator_id: str | None = None
) -> str | None:
    """
    Get graph context instantly from materialized snapshot.

    Usage:
        context = await get_fast_graph_context(tenant_id, twin_id, query)
        if context:
            agent_state["graph_context"] = context
    """
    manager = GraphSnapshotManager()
    return await manager.get_formatted_context(
        tenant_id=tenant_id,
        twin_id=twin_id,
        query=query,
        max_age_seconds=max_age_seconds,
        creator_id=creator_id
    )


# Worker function - Single-profile mode
async def refresh_scope_snapshot(
    scope_id: str,
    correlation_id: str | None = None
) -> bool:
    """
    Refresh snapshot for a scope (called by background worker).

    Usage:
        await refresh_scope_snapshot(scope_id)
    """
    manager = GraphSnapshotManager()

    # Parse scope_id to extract tenant and creator
    if "__" in scope_id:
        parts = scope_id.split("__", 1)
        tenant_id = parts[0]
        creator_id = parts[1] if len(parts) > 1 else None
    else:
        # Legacy scope format
        tenant_id = scope_id
        creator_id = None

    # Resolve a concrete twin_id for this scope (required by FK constraints).
    async def _resolve_twin_id() -> str | None:
        def _from_claims():
            return (
                supabase.table("graph_claims")
                .select("twin_id")
                .eq("tenant_id", tenant_id)
                .eq("scope_id", scope_id)
                .order("extracted_at", desc=True)
                .limit(1)
                .execute()
            )

        claims = await manager._run_db(_from_claims)
        if claims.data:
            return claims.data[0].get("twin_id")

        def _from_outbox():
            return (
                supabase.table("graph_outbox")
                .select("twin_id")
                .eq("tenant_id", tenant_id)
                .eq("scope_id", scope_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )

        outbox = await manager._run_db(_from_outbox)
        if outbox.data:
            return outbox.data[0].get("twin_id")
        return None

    twin_id = await _resolve_twin_id()
    if not twin_id:
        return False

    return await manager.refresh_snapshot(
        tenant_id=tenant_id,
        twin_id=twin_id,
        correlation_id=correlation_id,
        creator_id=creator_id
    )


# Legacy worker function (backward compatibility)
async def refresh_twin_snapshot(
    tenant_id: str,
    twin_id: str,
    correlation_id: str | None = None,
    creator_id: str | None = None
) -> bool:
    """
    Refresh snapshot for a twin (called by background worker).

    Usage:
        await refresh_twin_snapshot(tenant_id, twin_id)
    """
    manager = GraphSnapshotManager()
    return await manager.refresh_snapshot(
        tenant_id=tenant_id,
        twin_id=twin_id,
        correlation_id=correlation_id,
        creator_id=creator_id
    )
