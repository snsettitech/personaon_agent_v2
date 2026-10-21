"""Per-tenant API rate limiter (in-process). Similar shape to llm_budget."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)


class RateLimitExceeded(Exception):
    pass


class TenantRateLimiter:
    def __init__(self, per_minute: int):
        self.cap = per_minute
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def consume(self, tenant_id: str) -> None:
        async with self._lock:
            now = time.monotonic()
            b = self._buckets[tenant_id]
            while b and now - b[0] > 60.0:
                b.popleft()
            if len(b) >= self.cap:
                raise RateLimitExceeded(f"tenant={tenant_id} over {self.cap}/min")
            b.append(now)


_LIMITER: TenantRateLimiter | None = None


def _get() -> TenantRateLimiter:
    global _LIMITER
    if _LIMITER is None:
        _LIMITER = TenantRateLimiter(
            per_minute=int(os.getenv("API_RATE_LIMIT_PER_MIN", "300"))
        )
    return _LIMITER


async def rate_limit_middleware(request: Request, call_next):
    """FastAPI middleware: per-tenant 300 req/min cap (env: API_RATE_LIMIT_PER_MIN)."""
    auth = request.headers.get("authorization", "")
    # Use a hash of the full Authorization header as bucket key.
    # This is not auth — it's just a dedup key for rate-limiting.
    # Two different tenants with the same last-16 chars no longer share a bucket.
    raw_key = auth if auth else (request.client.host if request.client else "anon")
    tenant_key = hashlib.sha256(raw_key.encode()).hexdigest()[:32]
    try:
        await _get().consume(tenant_key)
    except RateLimitExceeded:
        raise HTTPException(status_code=429, detail="Too Many Requests")
    return await call_next(request)
