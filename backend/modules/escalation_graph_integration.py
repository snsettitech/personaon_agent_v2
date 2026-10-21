"""Escalation to graph-memory outbox integration."""

from __future__ import annotations

import logging
from typing import Any

from modules.graph_memory_core import GraphMemoryCore
from modules.graph_outbox import GraphOperationType

logger = logging.getLogger(__name__)


async def enqueue_escalation_graph_jobs(
    *,
    tenant_id: str,
    twin_id: str,
    escalation_id: str,
    question: str,
    answer: str,
    owner_id: str,
) -> dict[str, Any]:
    """Enqueue best-effort graph jobs after an escalation is resolved."""
    client = GraphMemoryCore()
    outbox = client.outbox
    result: dict[str, Any] = {
        "escalation_episode_job": None,
        "claim_extraction_job": None,
        "contradiction_eval_job": None,
        "errors": [],
    }

    episode_payload = {
        "name": "Escalation resolved",
        "body": f"Question: {question}\n\nAnswer: {answer}",
        "source_type": "escalation_resolution",
        "source_ref": escalation_id,
        "metadata": {
            "tenant_id": tenant_id,
            "twin_id": twin_id,
            "owner_id": owner_id,
            "escalation_id": escalation_id,
        },
    }
    jobs = [
        (
            "escalation_episode_job",
            "episode_job_failed",
            GraphOperationType.CREATE_EPISODE,
            f"escalation_episode:{escalation_id}",
            episode_payload,
        ),
        (
            "claim_extraction_job",
            "claim_extraction_job_failed",
            GraphOperationType.EXTRACT_CLAIMS,
            f"claim_extract:{escalation_id}",
            {"source_ref": escalation_id, "text": answer, "twin_id": twin_id},
        ),
        (
            "contradiction_eval_job",
            "contradiction_eval_job_failed",
            GraphOperationType.EVALUATE_CONTRADICTIONS,
            f"contradiction_eval:{escalation_id}",
            {"source_ref": escalation_id, "twin_id": twin_id},
        ),
    ]

    for result_key, error_key, operation, idempotency_key, payload in jobs:
        try:
            result[result_key] = outbox.submit(
                tenant_id=tenant_id,
                twin_id=twin_id,
                operation=operation,
                idempotency_key=idempotency_key,
                payload=payload,
                scope_id=twin_id,
                creator_id=owner_id,
            )
        except Exception as exc:
            logger.warning("[escalation_graph] %s escalation_id=%s: %s", error_key, escalation_id, exc)
            result["errors"].append({error_key: str(exc)})

    return result


def check_escalation_graph_status(*, tenant_id: str, twin_id: str, escalation_id: str) -> dict[str, Any]:
    """Return outbox status counters for escalation graph processing."""
    stats = GraphMemoryCore().outbox.get_stats()
    return {
        "tenant_id": tenant_id,
        "twin_id": twin_id,
        "escalation_id": escalation_id,
        "outbox_pending": stats.get("pending", 0),
        "outbox_processing": stats.get("processing", 0),
        "outbox_completed": stats.get("completed", 0),
        "outbox_failed": stats.get("failed", 0),
    }
