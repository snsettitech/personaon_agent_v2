"""Notification-agent memory helpers.

Small, explicit functions keep the Phase II loop easy to operate:
measure outcomes, remember the lesson, retrieve similar lessons next time.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

AGENT_SLUG = "notification_agent"
OUTCOME_KIND = "outcome"
EMBEDDING_DIMENSION = 768
DEFAULT_SNIPPET_CHARS = 480
EmbeddingFn = Callable[[str], list[float]]


class NotificationOutcomeMemory(BaseModel):
    tenant_id: str
    flow_run_id: str
    lifecycle_event_id: str | None = None
    event_type: str
    email_type: str
    category: str
    audience_label: str = "unknown"
    subject: str = ""
    cta_label: str = ""
    audience_count: int = 0
    open_count: int = 0
    click_count: int = 0
    conversion_count: int = 0
    open_rate: float = 0.0
    click_rate: float = 0.0
    conversion_rate: float = 0.0
    measured_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RetrievedMemory(BaseModel):
    id: str
    content: str
    meta: dict[str, Any] = Field(default_factory=dict)
    similarity: float | None = None

    def snippet(self, max_chars: int = DEFAULT_SNIPPET_CHARS) -> str:
        return make_snippet(self.content, max_chars=max_chars)


def _embedding_default(text: str) -> list[float]:
    from modules.embeddings import get_embedding

    return get_embedding(text)


def _ensure_768(vector: list[float]) -> list[float]:
    if len(vector) != EMBEDDING_DIMENSION:
        raise ValueError(f"notification memory embeddings must be {EMBEDDING_DIMENSION} dimensions")
    return [float(value) for value in vector]


def compose_outcome_memory(outcome: NotificationOutcomeMemory) -> str:
    return (
        f"{outcome.event_type} notification | email_type={outcome.email_type} | "
        f"audience={outcome.audience_label} | subject={outcome.subject or 'unknown'} | "
        f"cta={outcome.cta_label or 'unknown'} | "
        f"open_rate={outcome.open_rate:.2%} | click_rate={outcome.click_rate:.2%} | "
        f"conversion_rate={outcome.conversion_rate:.2%} | "
        f"counts={outcome.open_count}/{outcome.click_count}/{outcome.conversion_count} "
        f"of {outcome.audience_count}"
    )


def make_snippet(content: str, *, max_chars: int = DEFAULT_SNIPPET_CHARS) -> str:
    text = " ".join(content.split())
    if max_chars < 1 or len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    cut = text[: max_chars - 3].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0].rstrip()
    return f"{cut}..."


def remember_notification_outcome(
    sb: Any,
    outcome: NotificationOutcomeMemory,
    *,
    embed: EmbeddingFn | None = None,
) -> dict[str, Any]:
    """Store or update the single outcome memory row for a measured run."""
    content = compose_outcome_memory(outcome)
    embedding = _ensure_768((embed or _embedding_default)(content))
    meta = outcome.model_dump(mode="json")
    existing_resp = (
        sb.table("agent_memory")
        .select("id")
        .eq("agent_slug", AGENT_SLUG)
        .eq("kind", OUTCOME_KIND)
        .eq("source_run_id", outcome.flow_run_id)
        .limit(1)
        .execute()
    )
    existing = (existing_resp.data or [None])[0]
    row = {
        "tenant_id": outcome.tenant_id,
        "agent_slug": AGENT_SLUG,
        "kind": OUTCOME_KIND,
        "content": content,
        "embedding": embedding,
        "meta": meta,
        "source_run_id": outcome.flow_run_id,
        "source_event_id": outcome.lifecycle_event_id,
    }
    if existing:
        resp = (
            sb.table("agent_memory")
            .update(row)
            .eq("id", existing["id"])
            .execute()
        )
    else:
        resp = sb.table("agent_memory").insert(row).execute()
    rows = resp.data or []
    if not rows:
        logger.warning(
            "[notification_memory] agent_memory write returned no rows — data likely written; treating as success run_id=%s",
            outcome.flow_run_id,
        )
        return {"agent_slug": AGENT_SLUG, "source_run_id": outcome.flow_run_id}
    return dict(rows[0])


def build_memory_query(
    *,
    event_type: str,
    audience_label: str,
    category: str,
) -> str:
    return f"{event_type} notification for {audience_label} audience in {category}"


def retrieve_prior_outcomes(
    sb: Any,
    *,
    tenant_id: str,
    event_type: str,
    audience_label: str,
    category: str,
    limit: int = 5,
    embed: EmbeddingFn | None = None,
) -> list[RetrievedMemory]:
    query_text = build_memory_query(
        event_type=event_type,
        audience_label=audience_label,
        category=category,
    )
    embedding = _ensure_768((embed or _embedding_default)(query_text))
    try:
        resp = sb.rpc(
            "match_agent_memory",
            {
                "query_embedding": embedding,
                "match_agent_slug": AGENT_SLUG,
                "match_kind": OUTCOME_KIND,
                "match_count": max(1, min(int(limit), 10)),
                "match_tenant_id": tenant_id,
            },
        ).execute()
    except Exception as exc:
        logger.warning("[notification_memory] retrieval unavailable event_type=%s err=%r", event_type, exc)
        return []
    memories: list[RetrievedMemory] = []
    for row in resp.data or []:
        try:
            memories.append(RetrievedMemory.model_validate(row))
        except Exception:
            logger.debug("[notification_memory] skipping invalid memory row=%s", row)
    return memories


def retrieve_prior_outcome_snippets(
    sb: Any,
    *,
    tenant_id: str,
    event_type: str,
    audience_label: str,
    category: str,
    limit: int = 5,
    max_chars: int = DEFAULT_SNIPPET_CHARS,
    embed: EmbeddingFn | None = None,
) -> list[str]:
    """Return compact prior-outcome snippets for notification generation context."""
    memories = retrieve_prior_outcomes(
        sb,
        tenant_id=tenant_id,
        event_type=event_type,
        audience_label=audience_label,
        category=category,
        limit=limit,
        embed=embed,
    )
    return [memory.snippet(max_chars=max_chars) for memory in memories]
