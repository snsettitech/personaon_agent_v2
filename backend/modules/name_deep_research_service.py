"""ADK-backed deep research service."""

from __future__ import annotations

import asyncio
import logging
import os
from functools import lru_cache
from typing import Any

from adk_core.app import get_research_repository
from adk_core.schemas.artifacts import ResearchArtifact

logger = logging.getLogger(__name__)


def is_name_only_deep_research_enabled() -> bool:
    return os.getenv("NAME_ONLY_DEEP_RESEARCH_ENABLED", "true").lower() == "true"


class NameDeepResearchService:
    """Creates and executes research runs against the new ADK runtime."""

    def __init__(self) -> None:
        self._repository = get_research_repository()

    def parse_artifact(self, payload: dict[str, Any]) -> ResearchArtifact:
        return ResearchArtifact.model_validate(payload)

    async def create_run(
        self,
        *,
        tenant_id: str,
        user_id: str,
        name: str,
        hints: dict[str, Any] | None = None,
        seed_urls: list[str] | None = None,
        idempotency_key: str | None = None,
        twin_id: str | None = None,
    ) -> dict[str, Any]:
        run_hints = {**(hints or {})}
        if seed_urls:
            run_hints["seed_urls"] = seed_urls
        row = self._repository.create_run(
            tenant_id=tenant_id,
            user_id=user_id,
            subject_name=name,
            twin_id=twin_id,
            hints=run_hints,
            idempotency_key=idempotency_key,
        )
        run_id = row["id"]
        # Enqueue to graph_outbox so the worker picks it up on its 3600s budget.
        # The frontend polls /v2/research/runs/{run_id} for status.
        try:
            from modules.graph_outbox import GraphOperationType, GraphOutbox
            outbox = GraphOutbox()
            await asyncio.to_thread(
                outbox.submit,
                tenant_id,
                twin_id or tenant_id,
                GraphOperationType.PERSONA_RESEARCH,
                run_id,  # idempotency_key — run_id is already unique
                {"run_id": run_id, "tenant_id": tenant_id, "user_id": user_id},
                5,  # priority — higher than default graph ops
            )
        except Exception as exc:
            logger.warning("[NameDeepResearch] Failed to enqueue research job for run %s: %s", run_id, exc)
        return row

    async def execute_run(self, *, run_id: str, tenant_id: str, user_id: str) -> dict[str, Any]:
        """Execute a queued research run inline.

        Called from a dedicated endpoint so each execution gets its own
        HTTP request budget (300s on Cloud Run).  Returns the updated run row.
        """
        row = self._repository.get_run(run_id=run_id, tenant_id=tenant_id)
        if not row:
            return {"error": "Run not found"}
        if row.get("status") not in {"queued", "running"}:
            return row  # already completed/failed/compiled

        await self._execute_run(
            run_id=run_id,
            tenant_id=tenant_id,
            user_id=user_id,
            subject_name=row.get("subject_name", ""),
            twin_id=row.get("twin_id"),
            hints=row.get("hints") or {},
            seed_urls=(row.get("hints") or {}).get("seed_urls") or [],
        )
        updated = self._repository.get_run(run_id=run_id, tenant_id=tenant_id)
        return updated or row

    async def _execute_run(
        self,
        *,
        run_id: str,
        tenant_id: str,
        user_id: str,
        subject_name: str,
        twin_id: str | None,
        hints: dict[str, Any],
        seed_urls: list[str],
    ) -> None:
        try:
            raise NotImplementedError(
                "Research pipeline has been removed. Use the enrichment flow instead."
            )
        except Exception as exc:
            logger.exception("ADK research run failed: %s", exc)
            self._repository.update_run(
                run_id,
                status="failed",
                error_message=f"Research pipeline error: {exc}",
            )

    async def _auto_compile(
        self,
        *,
        run_id: str,
        tenant_id: str,
        user_id: str,
        twin_id: str,
    ) -> None:
        """Best-effort compile after research succeeds. Failures are logged, not raised."""
        try:
            raise NotImplementedError(
                "Compiler pipeline has been removed. Use the enrichment flow instead."
            )
        except Exception as exc:
            logger.exception("Auto-compile failed for run %s: %s", run_id, exc)
            # Don't update status — leave as "completed" so frontend can still
            # trigger manual compile via the /compile endpoint.

    async def get_run(self, *, run_id: str, tenant_id: str) -> dict[str, Any] | None:
        return self._repository.get_run(run_id=run_id, tenant_id=tenant_id)

    async def get_result(self, *, run_id: str, tenant_id: str) -> dict[str, Any] | None:
        row = self._repository.get_artifact(run_id=run_id, tenant_id=tenant_id)
        if not row:
            return None
        return row.get("artifact_json")

    def _build_graph_memory_text(self, artifact: dict[str, Any]) -> str:
        parsed = self.parse_artifact(artifact)
        lines = [parsed.synthesis_summary]
        for claim in parsed.extracted_claims[:20]:
            lines.append(f"Claim: {claim.text}")
        for item in parsed.timeline[:12]:
            lines.append(f"Timeline: {item.date_or_range} - {item.event}")
        for quote in parsed.verified_quote_candidates[:8]:
            lines.append(f"Quote: {quote.quote}")
        return "\n".join(line for line in lines if line).strip()


@lru_cache(maxsize=1)
def get_name_deep_research_service() -> NameDeepResearchService:
    return NameDeepResearchService()
