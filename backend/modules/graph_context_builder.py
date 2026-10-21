"""Best-effort graph context retrieval with a chat soft budget."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Literal

from pydantic import BaseModel

from modules.graph_memory_config import get_graph_memory_config
from modules.graph_memory_core import GraphMemoryCore

logger = logging.getLogger(__name__)


class GraphContextResult(BaseModel):
    context: str | None = None
    latency_ms: float = 0.0
    source: Literal["graph", "timeout", "unavailable", "disabled"]
    episode_count: int = 0
    claim_count: int = 0


class GraphContextBuilder:
    def __init__(
        self,
        *,
        tenant_id: str,
        twin_id: str,
        correlation_id: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.twin_id = twin_id
        self.correlation_id = correlation_id

    async def build_context(self, query: str, soft_budget_ms: int | None = None) -> GraphContextResult:
        config = get_graph_memory_config()
        start = time.perf_counter()

        if not config.is_read_allowed():
            return GraphContextResult(source="disabled", latency_ms=self._elapsed_ms(start))
        if not config.neo4j_uri or not config.neo4j_user or not config.neo4j_password:
            return GraphContextResult(source="unavailable", latency_ms=self._elapsed_ms(start))

        budget_ms = soft_budget_ms if soft_budget_ms is not None else int(config.chat_soft_budget_ms)
        try:
            fetched = await asyncio.wait_for(
                self._fetch_and_format_context(query),
                timeout=max(budget_ms, 1) / 1000,
            )
        except asyncio.TimeoutError:
            return GraphContextResult(source="timeout", latency_ms=self._elapsed_ms(start))
        except Exception as exc:
            logger.warning("[graph_context] unavailable twin_id=%s: %s", self.twin_id, exc)
            return GraphContextResult(source="unavailable", latency_ms=self._elapsed_ms(start))

        raw_episodes = fetched.get("episodes")
        episodes: list[Any] = raw_episodes if isinstance(raw_episodes, list) else []
        claim_count = int(fetched.get("claim_count") or 0)
        context = self._format_episodes(episodes)
        return GraphContextResult(
            context=context,
            source="graph",
            latency_ms=self._elapsed_ms(start),
            episode_count=len(episodes),
            claim_count=claim_count,
        )

    async def _fetch_and_format_context(self, query: str) -> dict[str, Any]:
        client = GraphMemoryCore(
            tenant_id=self.tenant_id,
            twin_id=self.twin_id,
            correlation_id=self.correlation_id,
        )
        episodes = await client.search(query=query, limit=5)
        return {"episodes": episodes or [], "claim_count": 0}

    def get_debug_headers(self, result: GraphContextResult) -> dict[str, str]:
        if not get_graph_memory_config().debug_headers:
            return {}
        return {
            "X-Graph-Context-Source": result.source,
            "X-Graph-Context-Latency-Ms": str(int(result.latency_ms)),
            "X-Graph-Context-Episodes": str(result.episode_count),
            "X-Graph-Context-Claims": str(result.claim_count),
        }

    @staticmethod
    def _elapsed_ms(start: float) -> float:
        return (time.perf_counter() - start) * 1000

    @staticmethod
    def _format_episodes(episodes: list[Any]) -> str | None:
        lines: list[str] = []
        for episode in episodes:
            if not isinstance(episode, dict):
                continue
            name = str(episode.get("name") or "Episode").strip()
            content = str(episode.get("content") or episode.get("body") or "").strip()
            lines.append(f"{name}: {content}" if content else name)
        return "\n".join(lines) if lines else None


async def get_graph_context_for_chat(
    *,
    tenant_id: str,
    twin_id: str,
    query: str,
    correlation_id: str | None = None,
) -> GraphContextResult:
    builder = GraphContextBuilder(
        tenant_id=tenant_id,
        twin_id=twin_id,
        correlation_id=correlation_id,
    )
    return await builder.build_context(query)
