"""Admin: business cockpit — headline KPIs, time-series, engagement.

``/cockpit/summary`` is one call that powers the dashboard home: Supabase
operational counts + plan distribution + Stripe-derived revenue + PostHog
engagement (DAU/MAU, null when the PostHog personal key is absent).
``/cockpit/engagement`` adds the PostHog funnel + weekly-active series.
"""
from typing import Any

from fastapi import APIRouter, Depends, Query

from modules import cockpit_metrics, posthog_query, revenue_metrics
from modules.auth_guard import require_admin

router = APIRouter()

# Ordered acquisition funnel (event name, display label). Events come from the
# captured taxonomy in frontend/lib/analytics/events.ts + backend captures.
FUNNEL_STEPS: list[tuple[str, str]] = [
    ("user_signup", "Signed up"),
    ("onboarding_started", "Started onboarding"),
    ("onboarding_published", "Published persona"),
    ("chat_message_sent", "First chat"),
]


@router.get("/cockpit/summary")
def cockpit_summary(user: dict = Depends(require_admin)) -> dict[str, Any]:
    """Everything the cockpit home needs in a single request."""
    return {
        "ops": cockpit_metrics.get_summary(),
        "plans": cockpit_metrics.get_plan_distribution(),
        "revenue": revenue_metrics.get_revenue_summary(),
        "engagement": {
            "dau": posthog_query.get_dau(),
            "mau": posthog_query.get_mau(),
        },
    }


@router.get("/cockpit/timeseries")
def cockpit_timeseries(
    metric: str = Query(..., description="signups | twins | conversations | leads"),
    days: int = Query(default=30, ge=1, le=90),
    user: dict = Depends(require_admin),
) -> list[dict[str, Any]]:
    """Daily counts for a metric over the trailing window (zero-filled)."""
    return cockpit_metrics.get_timeseries(metric, days)


@router.get("/cockpit/engagement")
def cockpit_engagement(
    days: int = Query(default=30, ge=1, le=90),
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """PostHog acquisition funnel + weekly-active series (null without the key)."""
    counts = posthog_query.get_event_counts([ev for ev, _ in FUNNEL_STEPS], days)
    funnel = None
    if counts is not None:
        funnel = [{"step": label, "event": ev, "count": counts.get(ev, 0)} for ev, label in FUNNEL_STEPS]
    return {"funnel": funnel, "weekly_active": posthog_query.get_weekly_active(8)}
