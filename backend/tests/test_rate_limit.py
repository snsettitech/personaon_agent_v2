import asyncio
import pytest
from modules.rate_limit import TenantRateLimiter, RateLimitExceeded


@pytest.mark.asyncio
async def test_limiter_passes_under_cap():
    limiter = TenantRateLimiter(per_minute=10)
    for _ in range(10):
        await limiter.consume("t1")


@pytest.mark.asyncio
async def test_limiter_raises_over_cap():
    limiter = TenantRateLimiter(per_minute=2)
    await limiter.consume("t1")
    await limiter.consume("t1")
    with pytest.raises(RateLimitExceeded):
        await limiter.consume("t1")


@pytest.mark.asyncio
async def test_limiter_is_per_tenant():
    limiter = TenantRateLimiter(per_minute=1)
    await limiter.consume("t1")
    await limiter.consume("t2")  # different tenant, fine
