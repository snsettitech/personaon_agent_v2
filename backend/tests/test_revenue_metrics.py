"""Tests for modules/revenue_metrics.py — MRR math + summary assembly."""
from __future__ import annotations

from unittest.mock import MagicMock

import modules.revenue_metrics as rm
from tests._supabase_mock import fluent


def test_compute_mrr_counts_only_live_statuses() -> None:
    rows = [
        {"tier": "pro", "status": "active", "price_lookup_key": "pro_monthly_v2"},
        {"tier": "pro", "status": "trialing", "price_lookup_key": "pro_monthly_v2"},
        {"tier": "pro", "status": "canceled", "price_lookup_key": "pro_monthly_v2"},  # excluded
    ]
    out = rm.compute_mrr(rows)
    assert out["active_subscriptions"] == 2
    assert out["mrr"] == round(14.99 * 2, 2)
    assert out["by_tier"]["pro"]["count"] == 2


def test_monthly_value_prefers_lookup_key_then_tier() -> None:
    assert rm.monthly_value({"price_lookup_key": "pro_annual_v2", "tier": "pro"}) == round(149 / 12, 2)
    # unknown lookup key falls back to tier price
    assert rm.monthly_value({"price_lookup_key": "mystery", "tier": "pro"}) == 14.99
    # believer LTD contributes nothing
    assert rm.monthly_value({"price_lookup_key": "believer_ltd", "tier": "believer"}) == 0.0


def test_get_revenue_summary_assembles_seats(monkeypatch) -> None:
    # Avoid any live Stripe call in tests.
    monkeypatch.setattr(rm, "_live_business_prices", lambda: {})
    subs = fluent([
        {"tier": "pro", "status": "active", "price_lookup_key": "pro_monthly_v2", "cancel_at_period_end": True},
    ])
    seats = fluent([{"seats_sold": 7, "seats_cap": 50}])
    sb = MagicMock()
    sb.table.side_effect = [subs, seats]
    monkeypatch.setattr(rm, "get_supabase_client", lambda: sb)

    out = rm.get_revenue_summary()
    assert out["active_subscriptions"] == 1
    assert out["scheduled_cancellations"] == 1
    assert out["believer_seats"] == {"sold": 7, "cap": 50}
