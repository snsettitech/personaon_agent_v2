"""Revenue metrics for the admin control center.

Computes MRR / active subscriptions / churn from the Supabase ``subscriptions``
table, which the Stripe webhook (routers/billing.py) keeps current. This avoids
live Stripe polling on every dashboard load.

``compute_mrr`` is pure (price map injected) so it is trivially unit tested.
Business-tier prices are fetched LIVE from Stripe (cached 1h) per the chosen
design; they fall back to env ``BUSINESS_MONTHLY_USD`` / 0 when Stripe is
unavailable, and unpriced live subs are logged so MRR under-reporting is visible.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from modules.observability import get_supabase_client

logger = logging.getLogger(__name__)

# Subscriptions in these statuses are counted as "live" for MRR / active counts.
LIVE_STATUSES = ("active", "trialing", "past_due")

_BUSINESS_MONTHLY = float(os.getenv("BUSINESS_MONTHLY_USD", "0") or "0")
_BUSINESS_ANNUAL_MONTHLY = float(os.getenv("BUSINESS_ANNUAL_MONTHLY_USD", "0") or "0")

# Monthly USD per Stripe price lookup key. Annual plans normalized to monthly.
# ``believer_ltd`` is one-time → 0 MRR. business_* are overridden by live Stripe.
LOOKUP_KEY_MONTHLY_USD: dict[str, float] = {
    "pro_monthly_v2": 14.99,
    "pro_annual_v2": round(149.0 / 12, 2),
    "pro_monthly": 29.0,            # legacy
    "pro_annual": round(264.0 / 12, 2),  # legacy
    "business_monthly": _BUSINESS_MONTHLY,
    "business_annual": _BUSINESS_ANNUAL_MONTHLY,
    "believer_ltd": 0.0,
}

# ── Live Stripe business price (cached) ─────────────────────────────────────
_BUSINESS_LOOKUP_KEYS = ("business_monthly", "business_annual")
_price_cache: dict[str, Any] = {"map": {}, "fetched_at": 0.0}
_PRICE_TTL_SECONDS = 3600


def _live_business_prices() -> dict[str, float]:
    """Fetch business_* monthly-normalized prices from Stripe (cached 1h).

    Returns {} when Stripe is not configured or the call fails — callers then
    fall back to the static/env map.
    """
    if not os.getenv("STRIPE_SECRET_KEY", "").strip():
        return {}
    now = time.time()
    if _price_cache["map"] and (now - _price_cache["fetched_at"]) < _PRICE_TTL_SECONDS:
        return _price_cache["map"]
    out: dict[str, float] = {}
    try:
        import stripe

        stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "").strip()
        prices = stripe.Price.list(lookup_keys=list(_BUSINESS_LOOKUP_KEYS), active=True)
        for price in prices.get("data", []):
            lk = price.get("lookup_key")
            unit = price.get("unit_amount")  # cents
            interval = (price.get("recurring") or {}).get("interval")
            if not lk or unit is None:
                continue
            monthly = unit / 100.0
            if interval == "year":
                monthly = round(monthly / 12, 2)
            out[lk] = monthly
        _price_cache["map"] = out
        _price_cache["fetched_at"] = now
    except Exception as exc:
        logger.warning("[revenue] live Stripe business price fetch failed err=%r", exc)
        return _price_cache["map"] or {}
    return out


def effective_price_map() -> dict[str, float]:
    """Static price map merged with live Stripe business prices."""
    merged = dict(LOOKUP_KEY_MONTHLY_USD)
    merged.update(_live_business_prices())
    return merged


def monthly_value(row: dict[str, Any], price_map: dict[str, float] | None = None) -> float:
    """Monthly USD a single subscription row contributes to MRR."""
    price_map = price_map or LOOKUP_KEY_MONTHLY_USD
    key = row.get("price_lookup_key")
    if key and price_map.get(key):  # present and non-zero
        return price_map[key]
    tier = (row.get("tier") or "free").lower()
    tier_fallback = {
        "free": 0.0,
        "pro": price_map.get("pro_monthly_v2", 14.99),
        "business": price_map.get("business_monthly", _BUSINESS_MONTHLY),
        "believer": 0.0,
    }
    val = tier_fallback.get(tier, 0.0)
    if val == 0.0 and tier not in ("free", "believer"):
        logger.warning(
            "[revenue] unpriced live subscription tier=%s lookup_key=%r — MRR under-reported",
            tier, key,
        )
    return val


def compute_mrr(rows: list[dict[str, Any]], price_map: dict[str, float] | None = None) -> dict[str, Any]:
    """Pure: aggregate live subscription rows into MRR + breakdowns."""
    mrr = 0.0
    by_tier: dict[str, dict[str, float]] = {}
    live = 0
    for row in rows:
        status = (row.get("status") or "").lower()
        if status not in LIVE_STATUSES:
            continue
        live += 1
        tier = (row.get("tier") or "free").lower()
        value = monthly_value(row, price_map)
        mrr += value
        bucket = by_tier.setdefault(tier, {"count": 0, "mrr": 0.0})
        bucket["count"] += 1
        bucket["mrr"] = round(bucket["mrr"] + value, 2)
    return {
        "mrr": round(mrr, 2),
        "active_subscriptions": live,
        "by_tier": by_tier,
    }


def get_revenue_summary() -> dict[str, Any]:
    """Fetch live subscriptions + believer seats and compute the revenue summary."""
    sb = get_supabase_client()
    price_map = effective_price_map()
    try:
        resp = (
            sb.table("subscriptions")
            .select("user_id, tier, status, price_lookup_key, cancel_at_period_end")
            .in_("status", list(LIVE_STATUSES))
            .execute()
        )
        rows = resp.data or []
    except Exception as exc:
        logger.exception("[revenue] subscriptions fetch failed err=%r", exc)
        rows = []

    summary = compute_mrr(rows, price_map)
    summary["scheduled_cancellations"] = sum(1 for r in rows if r.get("cancel_at_period_end"))

    try:
        seats_resp = (
            sb.table("believer_seats").select("seats_sold, seats_cap").eq("id", 1).limit(1).execute()
        )
        seats = (seats_resp.data or [{}])[0]
        summary["believer_seats"] = {
            "sold": seats.get("seats_sold", 0),
            "cap": seats.get("seats_cap", 0),
        }
    except Exception as exc:
        logger.warning("[revenue] believer_seats fetch failed err=%r", exc)
        summary["believer_seats"] = {"sold": 0, "cap": 0}

    return summary
