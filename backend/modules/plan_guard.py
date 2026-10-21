# backend/modules/plan_guard.py
"""Tier-based plan enforcement for FastAPI endpoints.

Usage:
    @router.post("/widget/keys/{twin_id}")
    async def create_key(twin_id: str, user: dict = Depends(require_plan("pro"))):
        ...
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import Depends, HTTPException

from modules.auth_guard import require_tenant

logger = logging.getLogger(__name__)

# Tier order — higher index = higher access level.
# believer == pro-equivalent for access purposes.
_TIER_ORDER: dict[str, int] = {
    "free": 0,
    "pro": 1,
    "believer": 1,
    "business": 2,
}

# In-process LRU cache: user_id -> (tier, cached_at_unix)
_plan_cache: dict[str, tuple[str, float]] = {}
# NOTE: in-process dict. Safe on Cloud Run (single process per instance).
# Replace with Redis if multi-process workers are ever introduced.
_CACHE_TTL_SECONDS = 300  # 5 minutes

_BILLING_PATH = "/dashboard/billing"


def _fetch_tier(user_id: str) -> str:
    """Fetch tier from DB, honoring no-card trial expiry. Returns 'free' on any error.

    If user is on a no-card trial and trial_ends_at < now(), auto-downgrades to
    free in DB (lazy revert on first read after expiry — no cron needed).
    """
    from modules.observability import get_supabase_client
    try:
        sb = get_supabase_client()
        resp = (
            sb.table("users")
            .select("plan, trial_kind, trial_ends_at")
            .eq("id", user_id)
            .single()
            .execute()
        )
        data = resp.data or {}
        plan = data.get("plan") or "free"
        trial_kind = data.get("trial_kind")
        trial_ends_at_iso = data.get("trial_ends_at")

        if trial_kind == "no_card" and trial_ends_at_iso and plan != "free":
            from datetime import datetime, timezone
            try:
                ends = datetime.fromisoformat(trial_ends_at_iso.replace("Z", "+00:00"))
                if ends < datetime.now(timezone.utc):
                    # Clear trial state alongside plan downgrade so a future paid
                    # upgrade via Stripe webhook can't be re-downgraded by this
                    # same path.
                    sb.table("users").update({
                        "plan": "free",
                        "trial_kind": None,
                        "trial_ends_at": None,
                    }).eq("id", user_id).execute()
                    logger.info("[plan_guard] no-card trial expired downgraded user_id=%s", user_id)
                    return "free"
            except ValueError:
                logger.warning("[plan_guard] bad trial_ends_at format user_id=%s value=%r", user_id, trial_ends_at_iso)
        return plan
    except Exception as exc:
        logger.warning("[plan_guard] tier fetch failed user_id=%s error=%r", user_id, exc)
        return "free"


def get_user_tier(user_id: str) -> str:
    """Return the user's current plan tier, using cache when fresh."""
    entry = _plan_cache.get(user_id)
    if entry is not None:
        tier, cached_at = entry
        if time.time() - cached_at < _CACHE_TTL_SECONDS:
            return tier
    tier = _fetch_tier(user_id)
    _plan_cache[user_id] = (tier, time.time())
    # Evict stale entries when cache grows large (prevents unbounded growth)
    if len(_plan_cache) > 50_000:
        cutoff = time.time() - _CACHE_TTL_SECONDS
        stale_keys = [k for k, (_, ts) in list(_plan_cache.items()) if ts < cutoff]
        for k in stale_keys:
            _plan_cache.pop(k, None)
    return tier


def invalidate_plan_cache(user_id: str) -> None:
    """Remove a user's cached tier — call this from the webhook handler."""
    _plan_cache.pop(user_id, None)
    logger.info("[plan_guard] cache invalidated user_id=%s", user_id)


def require_plan(min_tier: str):
    """FastAPI dependency factory. Raises HTTP 402 if user's tier is below min_tier.

    Example:
        @router.post("/endpoint")
        async def handler(user: dict = Depends(require_plan("pro"))):
            ...
    """
    if min_tier not in _TIER_ORDER:
        raise ValueError(
            f"[plan_guard] Unknown min_tier: {min_tier!r}. Valid: {list(_TIER_ORDER)}"
        )

    def _dependency(user: dict[str, Any] = Depends(require_tenant)) -> dict[str, Any]:
        user_id: str = user.get("user_id") or user.get("id") or ""
        if not user_id:
            raise HTTPException(status_code=401, detail="User ID not found in token")
        tier = get_user_tier(user_id)
        if _TIER_ORDER.get(tier, 0) < _TIER_ORDER.get(min_tier, 0):
            raise HTTPException(
                status_code=402,
                detail=f"This feature requires the {min_tier} plan. Current: {tier}. "
                       f"Upgrade at {_BILLING_PATH}",
            )
        return user
    return _dependency
