"""Operational business metrics for the admin cockpit.

Counts and distributions sourced from Supabase via the service-role client
(bypasses RLS — correct for a platform-wide owner view). Engagement metrics
(DAU/MAU) come from PostHog (modules/posthog_query.py); revenue from
modules/revenue_metrics.py. This module owns the Supabase operational counts.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from modules.observability import get_supabase_client

logger = logging.getLogger(__name__)

# metric name -> (table, timestamp column) for the time-series endpoint.
_TIMESERIES_SOURCES: dict[str, tuple[str, str]] = {
    "signups": ("users", "created_at"),
    "twins": ("twins", "created_at"),
    "conversations": ("adk_conversations", "created_at"),
    "leads": ("widget_leads", "created_at"),
}


def _count(sb, table: str, *, gte_col: str | None = None, since_iso: str | None = None,
           eq: tuple[str, Any] | None = None) -> int:
    """Exact row count with optional time-window and equality filter."""
    try:
        q = sb.table(table).select("id", count="exact")
        if eq is not None:
            q = q.eq(eq[0], eq[1])
        if gte_col and since_iso:
            q = q.gte(gte_col, since_iso)
        resp = q.limit(0).execute()
        return resp.count or 0
    except Exception as exc:
        logger.warning("[cockpit] count failed table=%s err=%r", table, exc)
        return 0


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def get_summary() -> dict[str, Any]:
    """Headline operational counts for the cockpit (no PostHog/Stripe here)."""
    sb = get_supabase_client()
    today = _iso_days_ago(1)
    week = _iso_days_ago(7)
    return {
        "users": {
            "total": _count(sb, "users"),
            "new_24h": _count(sb, "users", gte_col="created_at", since_iso=today),
            "new_7d": _count(sb, "users", gte_col="created_at", since_iso=week),
        },
        "twins": {
            "total": _count(sb, "twins"),
            "active": _count(sb, "twins", eq=("is_active", True)),
        },
        "conversations": {
            "total": _count(sb, "adk_conversations"),
            "new_7d": _count(sb, "adk_conversations", gte_col="created_at", since_iso=week),
        },
        "leads": {
            "total": _count(sb, "widget_leads"),
            "new_7d": _count(sb, "widget_leads", gte_col="created_at", since_iso=week),
        },
    }


def get_plan_distribution() -> dict[str, int]:
    """Count of users per plan tier."""
    sb = get_supabase_client()
    return {tier: _count(sb, "users", eq=("plan", tier)) for tier in ("free", "pro", "business", "believer")}


def get_timeseries(metric: str, days: int = 30) -> list[dict[str, Any]]:
    """Daily counts for a metric over the trailing ``days`` (bucketed in Python).

    Returns a continuous series (zero-filled) of ``{date, count}`` for the range.
    Returns [] for an unknown metric.
    """
    source = _TIMESERIES_SOURCES.get(metric)
    if source is None:
        return []
    table, col = source
    days = max(1, min(int(days), 90))
    since = _iso_days_ago(days)
    sb = get_supabase_client()
    try:
        resp = sb.table(table).select(col).gte(col, since).limit(50000).execute()
        rows = resp.data or []
    except Exception as exc:
        logger.warning("[cockpit] timeseries fetch failed metric=%s err=%r", metric, exc)
        rows = []

    buckets: dict[str, int] = {}
    for row in rows:
        ts = row.get(col)
        if not ts:
            continue
        day = str(ts)[:10]  # YYYY-MM-DD
        buckets[day] = buckets.get(day, 0) + 1

    start = datetime.now(timezone.utc).date() - timedelta(days=days - 1)
    return [
        {"date": (start + timedelta(days=i)).isoformat(), "count": buckets.get((start + timedelta(days=i)).isoformat(), 0)}
        for i in range(days)
    ]
