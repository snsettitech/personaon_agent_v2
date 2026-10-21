"""Token-bucket budget wrapper around Gemini generate_content calls.

Every Gemini call in services/ MUST go through run_with_budget(). The wrapper:
- Enforces a per-tenant requests-per-minute cap (env: LLM_BUDGET_TENANT_PER_MIN, default 60)
- Emits $ai_generation telemetry (latency, tokens, model, error) to PostHog when
  the underlying call actually executed.
- Emits persona.llm_budget_exceeded telemetry when the budget is exhausted (v2
  amendment) instead of polluting $ai_generation with a 0-token entry.
- Raises LlmBudgetExceeded when the bucket is empty (workers should return False
  to retry; request handlers should bubble up as 429).

The bucket is in-process — fine for a single Cloud Run instance. When we scale to
multiple instances we'll move state to Redis. The cap is conservative; the goal is
to detect runaway loops, not throttle normal traffic.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections import defaultdict, deque
from typing import Any, Callable

from adk_core.model_names import DEFAULT_GEMINI_MODEL
from modules.posthog_analytics import ph_ai_generation, ph_capture

logger = logging.getLogger(__name__)


class LlmBudgetExceeded(RuntimeError):
    """Raised when a tenant has consumed its per-minute LLM call budget."""


# tenant_id -> deque[float timestamps within the last 60s]
_BUCKETS: dict[str, deque[float]] = defaultdict(deque)
# Per-tenant locks — eliminates cross-tenant blocking from a single global lock.
_BUCKET_LOCKS: dict[str, asyncio.Lock] = {}


def _get_lock(tenant_id: str) -> asyncio.Lock:
    if tenant_id not in _BUCKET_LOCKS:
        _BUCKET_LOCKS[tenant_id] = asyncio.Lock()
    return _BUCKET_LOCKS[tenant_id]


def _cap() -> int:
    try:
        return max(1, int(os.getenv("LLM_BUDGET_TENANT_PER_MIN", "60")))
    except ValueError:
        return 60


async def _consume(tenant_id: str) -> None:
    async with _get_lock(tenant_id):
        now = time.monotonic()
        bucket = _BUCKETS[tenant_id]
        # drop timestamps older than 60s
        while bucket and now - bucket[0] > 60.0:
            bucket.popleft()
        if len(bucket) >= _cap():
            raise LlmBudgetExceeded(
                f"tenant={tenant_id} exceeded {_cap()} LLM calls/min"
            )
        bucket.append(now)


async def run_with_budget(
    *,
    tenant_id: str,
    operation: str,
    call: Callable[[], Any],
    user_id: str | None = None,
    model: str = DEFAULT_GEMINI_MODEL,
) -> Any:
    """Run `call` under the tenant budget.

    `call` is a zero-arg sync callable that invokes
    client.models.generate_content (or similar). The wrapper schedules it on
    asyncio.to_thread, times it, and emits $ai_generation telemetry on
    completion (success or error).

    Returns the raw response object. Raises LlmBudgetExceeded if over cap.
    When the budget is exhausted, emits `persona.llm_budget_exceeded` to
    PostHog with `{tenant_id, operation}` and does NOT emit $ai_generation
    (which would otherwise show a misleading 0-token entry).
    """
    # v2 amendment: emit budget-exceeded telemetry separately so $ai_generation
    # stays clean (only real calls).
    try:
        await _consume(tenant_id)
    except LlmBudgetExceeded:
        try:
            ph_capture(
                user_id=user_id or tenant_id,
                event="persona.llm_budget_exceeded",
                properties={"tenant_id": tenant_id, "operation": operation},
            )
        except Exception:  # telemetry must never break callers
            logger.exception("[LlmBudget] ph_capture for budget-exceeded failed")
        raise

    trace_id = str(uuid.uuid4())
    start = time.monotonic()
    err: str | None = None
    resp: Any = None
    try:
        resp = await asyncio.to_thread(call)
        return resp
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        latency = time.monotonic() - start
        usage = getattr(resp, "usage_metadata", None) if resp is not None else None
        in_tok = int(getattr(usage, "prompt_token_count", 0) or 0)
        out_tok = int(getattr(usage, "candidates_token_count", 0) or 0)
        try:
            ph_ai_generation(
                user_id=user_id or tenant_id,
                trace_id=trace_id,
                model=model,
                provider="google",
                input_tokens=in_tok,
                output_tokens=out_tok,
                latency_seconds=latency,
                error=err,
                extra={"operation": operation, "tenant_id": tenant_id},
            )
        except Exception:  # telemetry must never break callers
            logger.exception("[LlmBudget] ph_ai_generation failed")
