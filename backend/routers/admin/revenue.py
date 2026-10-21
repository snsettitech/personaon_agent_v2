"""Admin: revenue & subscriptions."""
from typing import Any

from fastapi import APIRouter, Depends, Query

from modules import revenue_metrics
from modules.auth_guard import require_admin

from ._common import _safe_query, _supabase

router = APIRouter()


@router.get("/revenue/summary")
def revenue_summary(user: dict = Depends(require_admin)) -> dict[str, Any]:
    """MRR, active subscriptions, churn signal, and believer LTD seats."""
    return revenue_metrics.get_revenue_summary()


@router.get("/revenue/subscriptions")
def revenue_subscriptions(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, le=500),
    user: dict = Depends(require_admin),
) -> list:
    """Subscription rows (optionally filtered by status), newest first."""
    sb = _supabase()
    query = (
        sb.table("subscriptions")
        .select(
            "id, user_id, tier, status, price_lookup_key, current_period_end, "
            "cancel_at_period_end, created_at"
        )
        .order("created_at", desc=True)
        .limit(limit)
    )
    if status_filter:
        query = query.eq("status", status_filter)
    return _safe_query(query)
