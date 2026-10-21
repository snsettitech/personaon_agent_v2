# backend/routers/billing.py
"""Stripe billing endpoints — checkout, portal, subscription status, webhooks."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from modules.auth_guard import require_tenant
from modules.plan_guard import invalidate_plan_cache

logger = logging.getLogger(__name__)
router = APIRouter(tags=["billing"], prefix="/billing")

_FRONTEND_URL = os.getenv("NEXT_PUBLIC_FRONTEND_URL", "https://personaon.com")

_LOOKUP_KEY_TO_TIER: dict[str, str] = {
    "pro_monthly_v2": "pro",   # $14.99/mo — current launch tier
    "pro_annual_v2": "pro",    # $149/yr (~17% off)
    "pro_monthly": "pro",      # legacy $29/mo — kept for backward compat
    "pro_annual": "pro",       # legacy $264/yr
    "business_monthly": "business",
    "business_annual": "business",
    "believer_ltd": "believer",
}

# Lookup keys eligible for the 14-day Stripe trial. Annual plans don't get trials
# (already discounted). One-time payments (Believer LTD) can't trial.
_TRIAL_ELIGIBLE_LOOKUP_KEYS: set[str] = {"pro_monthly_v2"}
_TRIAL_PERIOD_DAYS = 14


def _get_stripe() -> Any:
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "").strip()
    return stripe


def _get_supabase():
    from modules.observability import get_supabase_client
    return get_supabase_client()


class CheckoutRequest(BaseModel):
    lookup_key: str


class CheckoutResponse(BaseModel):
    client_secret: str


class PortalResponse(BaseModel):
    url: str


class CurrentPlanResponse(BaseModel):
    tier: str
    status: str
    current_period_end: str | None
    cancel_at_period_end: bool
    trial_kind: str | None = None       # "no_card" | "card_required" | None
    trial_ends_at: str | None = None    # ISO string for no_card trials


class UsageResponse(BaseModel):
    tier: str
    messages_used: int
    messages_cap: int
    voice_used: int
    voice_cap: int
    period_started_at: str | None


def _get_or_create_customer(st: Any, user: dict) -> str:
    sb = _get_supabase()
    user_id: str = user.get("user_id") or user.get("id") or ""
    row = sb.table("users").select("stripe_customer_id, email").eq("id", user_id).single().execute()
    data = row.data or {}
    existing_cid = data.get("stripe_customer_id")
    if existing_cid:
        return existing_cid
    customer = st.Customer.create(
        email=data.get("email", ""),
        metadata={"user_id": user_id},
    )
    sb.table("users").update({"stripe_customer_id": customer.id}).eq("id", user_id).execute()
    return customer.id


def _tier_from_session(st: Any, session: dict) -> str:
    if session.get("mode") == "payment":
        return "believer"
    sub_id = session.get("subscription")
    if not sub_id:
        return "free"
    sub = st.Subscription.retrieve(sub_id, expand=["items.data.price"])
    for item in sub["items"]["data"]:
        lk = item["price"].get("lookup_key") or ""
        if lk in _LOOKUP_KEY_TO_TIER:
            return _LOOKUP_KEY_TO_TIER[lk]
    return "free"


def _ts_to_iso(unix_ts: int | None) -> str | None:
    if not unix_ts:
        return None
    from datetime import datetime, timezone
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).isoformat()


@router.get("/believer-seats")
def get_believer_seats() -> dict:
    """Public — no auth. Used to display seat count on billing/pricing pages."""
    sb = _get_supabase()
    try:
        row = sb.table("believer_seats").select("seats_sold, seats_cap").eq("id", 1).single().execute()
        data = row.data or {"seats_sold": 0, "seats_cap": 50}
    except Exception:
        data = {"seats_sold": 0, "seats_cap": 50}
    return {
        "status": "ok",
        "data": {
            "sold": data["seats_sold"],
            "cap": data["seats_cap"],
            "available": data["seats_cap"] - data["seats_sold"],
        },
    }


_NO_CARD_TRIAL_DAYS = 7
_ACTIVE_STRIPE_SUBSCRIPTION_STATUSES = {"active", "trialing", "past_due"}


def _parse_billing_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_no_card_trial_for_current_plan(
    sb: Any,
    user_id: str,
    user_data: dict[str, Any],
    subscription_status: str,
) -> dict[str, Any]:
    """Clear or expire stale DB-only trial state before /billing/current responds."""
    normalized = dict(user_data)
    if normalized.get("trial_kind") != "no_card" or not normalized.get("trial_ends_at"):
        return normalized

    trial_ends = _parse_billing_datetime(normalized.get("trial_ends_at"))
    if trial_ends is None:
        logger.warning(
            "[billing] bad no-card trial_ends_at user_id=%s value=%r",
            user_id, normalized.get("trial_ends_at"),
        )
        return normalized

    if trial_ends > datetime.now(timezone.utc):
        return normalized

    if subscription_status in _ACTIVE_STRIPE_SUBSCRIPTION_STATUSES:
        payload = {"trial_kind": None, "trial_ends_at": None}
        sb.table("users").update(payload).eq("id", user_id).execute()
        invalidate_plan_cache(user_id)
        normalized.update(payload)
        logger.info("[billing] cleared stale no-card trial fields for paid user_id=%s", user_id)
        return normalized

    payload = {"plan": "free", "trial_kind": None, "trial_ends_at": None}
    sb.table("users").update(payload).eq("id", user_id).execute()
    invalidate_plan_cache(user_id)
    normalized.update(payload)
    logger.info("[billing] expired no-card trial downgraded user_id=%s", user_id)
    return normalized


@router.post("/start-trial-no-card")
def start_no_card_trial(user: dict = Depends(require_tenant)) -> dict:
    """Start a 7-day no-card trial. DB-only — no Stripe involvement.

    User must already exist (require_tenant). One trial per user lifetime —
    enforced via users.no_card_trial_used_at, which is a PERSISTENT marker that
    is never cleared (unlike trial_kind / trial_ends_at, which the lazy-downgrade
    paths in quota.py + plan_guard.py clear when the trial expires).
    """
    user_id: str = user.get("user_id") or user.get("id") or ""
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found in token")

    sb = _get_supabase()
    row = (
        sb.table("users")
        .select("plan, trial_kind, trial_ends_at, no_card_trial_used_at")
        .eq("id", user_id)
        .single()
        .execute()
    )
    data = row.data or {}
    if data.get("plan") != "free":
        raise HTTPException(status_code=400, detail="Trial is only available for users on the Free plan.")
    if data.get("no_card_trial_used_at") or data.get("trial_kind") == "no_card":
        raise HTTPException(status_code=400, detail="Trial already used. Start a paid plan to continue.")

    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    trial_ends_at = (now + timedelta(days=_NO_CARD_TRIAL_DAYS)).isoformat()
    sb.table("users").update({
        "plan": "pro",
        "trial_kind": "no_card",
        "trial_ends_at": trial_ends_at,
        "no_card_trial_used_at": now.isoformat(),
    }).eq("id", user_id).execute()

    invalidate_plan_cache(user_id)
    logger.info("[billing] no-card trial started user_id=%s ends=%s", user_id, trial_ends_at)
    return {
        "status": "ok",
        "data": {"trial_kind": "no_card", "trial_ends_at": trial_ends_at, "tier": "pro"},
    }


@router.post("/checkout", response_model=CheckoutResponse)
def create_checkout_session(
    body: CheckoutRequest,
    user: dict = Depends(require_tenant),
) -> CheckoutResponse:
    st = _get_stripe()
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    if body.lookup_key not in _LOOKUP_KEY_TO_TIER:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.lookup_key}")

    if body.lookup_key == "believer_ltd":
        sb_check = _get_supabase()
        try:
            seats_row = sb_check.table("believer_seats").select("seats_sold, seats_cap").eq("id", 1).single().execute()
            seats = seats_row.data or {"seats_sold": 0, "seats_cap": 50}
            if seats["seats_sold"] >= seats["seats_cap"]:
                raise HTTPException(
                    status_code=410,
                    detail=f"All {seats['seats_cap']} Believer seats have been claimed. Thank you for your interest!"
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("[billing] believer seat check failed: %r — proceeding", exc)

    try:
        prices = st.Price.list(lookup_keys=[body.lookup_key], limit=1)
    except Exception as exc:
        logger.error(
            "[billing] Stripe Price.list failed lookup_key=%s cause=%r context=%r",
            body.lookup_key, exc.__cause__, exc.__context__,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Stripe connection failed: {type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__}",
        )
    if not prices.data:
        raise HTTPException(status_code=500, detail=f"Price not found for {body.lookup_key}")
    price = prices.data[0]

    customer_id = _get_or_create_customer(st, user)
    user_id: str = user.get("user_id") or user.get("id") or ""
    is_one_time = body.lookup_key == "believer_ltd"

    session_kwargs: dict[str, Any] = {
        "customer": customer_id,
        "mode": "payment" if is_one_time else "subscription",
        "line_items": [{"price": price.id, "quantity": 1}],
        "ui_mode": "embedded_page",
        "return_url": f"{_FRONTEND_URL}/dashboard/billing?session_id={{CHECKOUT_SESSION_ID}}",
        "metadata": {"user_id": user_id, "lookup_key": body.lookup_key},
    }
    # Attach 14-day trial only on monthly subscription tier. Annual = no trial
    # (already 17% discounted). Believer = one-time payment, can't trial.
    if body.lookup_key in _TRIAL_ELIGIBLE_LOOKUP_KEYS:
        session_kwargs["subscription_data"] = {"trial_period_days": _TRIAL_PERIOD_DAYS}

    # Idempotency: if the same user POSTs the same lookup_key within a 1-hour window
    # (double-click, page refresh, React re-render), Stripe returns the SAME session
    # instead of creating a duplicate subscription. Bucket by hour so a real retry
    # after >1h gets a fresh session.
    import time
    hour_bucket = int(time.time() // 3600)
    idempotency_key = f"checkout:{user_id}:{body.lookup_key}:{hour_bucket}"

    session = st.checkout.Session.create(**session_kwargs, idempotency_key=idempotency_key)
    logger.info("[billing] checkout session created user_id=%s lookup_key=%s session_id=%s", user_id, body.lookup_key, session.id)
    return CheckoutResponse(client_secret=session.client_secret)


@router.get("/portal", response_model=PortalResponse)
def create_portal_session(user: dict = Depends(require_tenant)) -> PortalResponse:
    st = _get_stripe()
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    user_id: str = user.get("user_id") or user.get("id") or ""
    sb = _get_supabase()
    row = sb.table("users").select("stripe_customer_id").eq("id", user_id).single().execute()
    customer_id = (row.data or {}).get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(status_code=400, detail="No billing account found. Subscribe first.")
    portal = st.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{_FRONTEND_URL}/dashboard/billing",
    )
    return PortalResponse(url=portal.url)


@router.get("/current", response_model=CurrentPlanResponse)
def get_current_plan(user: dict = Depends(require_tenant)) -> CurrentPlanResponse:
    sb = _get_supabase()
    user_id: str = user.get("user_id") or user.get("id") or ""
    user_row = (
        sb.table("users")
        .select("plan, trial_kind, trial_ends_at")
        .eq("id", user_id)
        .single()
        .execute()
    )
    user_data = user_row.data or {}
    sub_row = (
        sb.table("subscriptions")
        .select("status, current_period_end, cancel_at_period_end")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    sub = (sub_row.data or [None])[0] or {}
    # Status precedence:
    # 1. Stripe subscription status (trialing/active/past_due/canceled)
    # 2. DB no-card trial flag → "trialing" (mirrors Stripe semantics for the UI)
    status = sub.get("status", "inactive")
    user_data = _normalize_no_card_trial_for_current_plan(sb, user_id, user_data, status)
    tier = user_data.get("plan", "free")
    if status == "inactive" and user_data.get("trial_kind") == "no_card":
        status = "trialing"
    return CurrentPlanResponse(
        tier=tier,
        status=status,
        current_period_end=sub.get("current_period_end"),
        cancel_at_period_end=sub.get("cancel_at_period_end", False),
        trial_kind=user_data.get("trial_kind"),
        trial_ends_at=user_data.get("trial_ends_at"),
    )


@router.get("/usage", response_model=UsageResponse)
def get_usage(user: dict = Depends(require_tenant)) -> UsageResponse:
    """Return the authenticated user's current period quota consumption."""
    from modules.quota import get_quota
    user_id: str = user.get("user_id") or user.get("id") or ""
    q = get_quota(user_id)
    return UsageResponse(
        tier=q["tier"],
        messages_used=q["messages_used"],
        messages_cap=q["messages_cap"],
        voice_used=q["voice_used"],
        voice_cap=q["voice_cap"],
        period_started_at=q.get("period_started_at"),
    )


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(..., alias="stripe-signature"),
) -> dict:
    st = _get_stripe()
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    if not webhook_secret or not os.getenv("STRIPE_SECRET_KEY"):
        logger.error("[billing] webhook received but Stripe secrets not configured")
        raise HTTPException(status_code=503, detail="Billing not configured")
    raw_body = await request.body()

    try:
        st.Webhook.construct_event(raw_body, stripe_signature, webhook_secret)
    except stripe.error.SignatureVerificationError as exc:
        logger.warning("[billing] webhook signature invalid: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid signature")

    # stripe-python v10+ returns StripeObjects (no .get()); re-parse raw body
    # as plain Python dicts so all downstream handlers work without changes.
    import json as _json
    event = _json.loads(raw_body)

    event_id: str = event["id"]
    event_type: str = event["type"]
    sb = _get_supabase()

    # INSERT — rely on PRIMARY KEY constraint to reject duplicates atomically
    try:
        sb.table("stripe_webhook_events").insert(
            {"stripe_event_id": event_id, "event_type": event_type}
        ).execute()
    except Exception:
        # Primary key violation = duplicate delivery
        logger.info("[billing] duplicate webhook (constraint) event_id=%s", event_id)
        return {"status": "ok", "data": {"duplicate": True}}

    try:
        _handle_event(st, sb, event)
    except Exception as exc:
        logger.exception("[billing] webhook handler error event_id=%s error=%r", event_id, exc)

    return {"status": "ok", "data": {"event_type": event_type}}


def _handle_event(st: Any, sb: Any, event: dict) -> None:
    event_type: str = event["type"]
    obj = event["data"]["object"]
    if event_type == "checkout.session.completed":
        _on_checkout_completed(st, sb, obj)
    elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
        _on_subscription_updated(sb, obj)
    elif event_type == "customer.subscription.deleted":
        _on_subscription_deleted(sb, obj)
    elif event_type == "invoice.payment_failed":
        customer_id = obj.get("customer", "")
        logger.warning("[billing] payment failed customer=%s", customer_id)
        if customer_id:
            try:
                user_row = sb.table("users").select("id").eq("stripe_customer_id", customer_id).execute()
                for row in (user_row.data or []):
                    sb.table("subscriptions").update({"status": "past_due"}).eq("user_id", row["id"]).execute()
                    logger.info("[billing] marked subscription past_due for user=%s", row["id"])
            except Exception as exc:
                logger.exception("[billing] failed to update past_due status: %s", exc)
    else:
        logger.info("[billing] unhandled event type=%s", event_type)


def _on_checkout_completed(st: Any, sb: Any, session: dict) -> None:
    user_id: str = (session.get("metadata") or {}).get("user_id", "")
    customer_id: str = session.get("customer", "")
    if not user_id:
        logger.warning("[billing] checkout.completed missing user_id metadata")
        return
    tier = _tier_from_session(st, session)
    sub_id: str = session.get("subscription", "") or ""
    # Clear any leftover no-card trial state — user is now on a paid Stripe sub.
    # Without this clear, plan_guard's lazy-downgrade on read would later flip
    # this paying user back to free when trial_ends_at passes.
    sb.table("users").update({
        "plan": tier,
        "stripe_customer_id": customer_id,
        "trial_kind": None,
        "trial_ends_at": None,
    }).eq("id", user_id).execute()
    if sub_id:
        sub_data = st.Subscription.retrieve(sub_id)
        # Stripe leaves `current_period_end` NULL while the sub is in `trialing`
        # (the billing period only starts after the trial converts). Fall back to
        # `trial_end` so the UI can display "X days left" during the trial.
        period_end = sub_data.get("current_period_end") or sub_data.get("trial_end")
        sb.table("subscriptions").upsert({
            "user_id": user_id,
            "stripe_customer_id": customer_id,
            "stripe_subscription_id": sub_id,
            "tier": tier,
            "status": sub_data["status"],
            "current_period_end": _ts_to_iso(period_end),
            "cancel_at_period_end": sub_data.get("cancel_at_period_end", False),
        }, on_conflict="stripe_subscription_id").execute()
    else:
        sb.table("subscriptions").insert({
            "user_id": user_id,
            "stripe_customer_id": customer_id,
            "tier": tier,
            "status": "active",
        }).execute()
    if tier == "believer":
        try:
            sb.rpc("increment_believer_seats").execute()
            logger.info("[billing] believer seat claimed user=%s", user_id)
        except Exception as exc:
            logger.exception("[billing] believer seat increment failed user=%s: %s", user_id, exc)
            # Don't abort — user's plan is already set. Seat count mismatch is recoverable manually.
    invalidate_plan_cache(user_id)
    logger.info("[billing] checkout completed user_id=%s tier=%s", user_id, tier)


def _on_subscription_updated(sb: Any, sub: dict) -> None:
    sub_id: str = sub["id"]
    customer_id: str = sub.get("customer", "")
    status: str = sub.get("status", "")
    cancel_at_period_end: bool = sub.get("cancel_at_period_end", False)
    # During trialing, Stripe sets current_period_end=NULL but trial_end is set.
    # Fall back to trial_end so the UI can render "X days left" / charge date.
    period_end = _ts_to_iso(sub.get("current_period_end") or sub.get("trial_end"))
    new_period_start_unix = sub.get("current_period_start")
    new_period_start_iso = _ts_to_iso(new_period_start_unix)

    # Resolve tier from subscription items
    tier = "free"
    items = (sub.get("items") or {}).get("data", [])
    for item in items:
        lk = (item.get("price") or {}).get("lookup_key") or ""
        if lk in _LOOKUP_KEY_TO_TIER:
            tier = _LOOKUP_KEY_TO_TIER[lk]
            break
    if tier == "free":
        logger.warning(
            "[billing] subscription_updated no matching lookup_key sub_id=%s items=%d — skipping",
            sub_id, len(items),
        )
        return

    # Resolve user_id from customer_id BEFORE upsert (subscriptions.user_id is NOT NULL)
    user_row = (
        sb.table("users")
        .select("id, period_started_at")
        .eq("stripe_customer_id", customer_id)
        .execute()
    )
    users = user_row.data or []
    if not users:
        logger.warning(
            "[billing] subscription_updated no user for customer=%s sub_id=%s — skipping",
            customer_id, sub_id,
        )
        return

    user_id: str = users[0]["id"]
    old_period_iso: str | None = users[0].get("period_started_at")

    # Period rollover: reset quota counters when billing period changes
    if new_period_start_iso and new_period_start_iso != old_period_iso:
        from modules.quota import reset_period_counters
        try:
            reset_period_counters(user_id, new_period_start_iso)
            logger.info(
                "[billing] period rolled over user=%s old=%s new=%s",
                user_id, old_period_iso, new_period_start_iso,
            )
        except Exception as exc:
            logger.exception("[billing] period reset failed user=%s: %s", user_id, exc)
            # Don't return — continue updating plan/subscription regardless

    sb.table("subscriptions").upsert({
        "user_id": user_id,
        "stripe_subscription_id": sub_id,
        "stripe_customer_id": customer_id,
        "tier": tier,
        "status": status,
        "current_period_end": period_end,
        "cancel_at_period_end": cancel_at_period_end,
    }, on_conflict="stripe_subscription_id").execute()

    for row in users:
        # Clear no-card trial state alongside plan upgrade to prevent
        # plan_guard's lazy-downgrade from later flipping a paid user to free
        # when the orphaned trial_ends_at passes.
        sb.table("users").update({
            "plan": tier,
            "trial_kind": None,
            "trial_ends_at": None,
        }).eq("id", row["id"]).execute()
        invalidate_plan_cache(row["id"])
    logger.info("[billing] subscription updated sub_id=%s tier=%s status=%s", sub_id, tier, status)


def _on_subscription_deleted(sb: Any, sub: dict) -> None:
    sub_id: str = sub["id"]
    customer_id: str = sub.get("customer", "")

    # Resolve user first to satisfy subscriptions.user_id NOT NULL
    user_row = sb.table("users").select("id").eq("stripe_customer_id", customer_id).execute()
    users = user_row.data or []
    if not users:
        logger.warning(
            "[billing] subscription_deleted no user for customer=%s sub_id=%s",
            customer_id, sub_id,
        )
        return

    user_id: str = users[0]["id"]

    sb.table("subscriptions").upsert({
        "user_id": user_id,
        "stripe_subscription_id": sub_id,
        "stripe_customer_id": customer_id,
        "status": "canceled",
        "tier": "free",
    }, on_conflict="stripe_subscription_id").execute()

    # Only downgrade users.plan if the user has NO other active/trialing
    # subscription on this customer. This prevents canceling an orphan duplicate
    # subscription from cascading into a downgrade of the canonical paid sub.
    # _ACTIVE_STRIPE_SUBSCRIPTION_STATUSES covers active, trialing, past_due.
    for row in users:
        try:
            others = (
                sb.table("subscriptions")
                .select("stripe_subscription_id, status, tier")
                .eq("user_id", row["id"])
                .neq("stripe_subscription_id", sub_id)
                .in_("status", list(_ACTIVE_STRIPE_SUBSCRIPTION_STATUSES))
                .execute()
            )
            other_subs = others.data or []
        except Exception as exc:
            logger.warning(
                "[billing] subscription_deleted other-sub lookup failed user=%s err=%r — failing closed (no plan change)",
                row["id"], exc,
            )
            continue

        if other_subs:
            # Pick the highest tier among surviving subs, in case the user has
            # a mix (e.g., business + believer). Falls back to first row's tier.
            tier_rank = {"free": 0, "pro": 1, "believer": 1, "business": 2}
            best_tier = max(
                (s.get("tier", "free") for s in other_subs),
                key=lambda t: tier_rank.get(t, 0),
            )
            sb.table("users").update({"plan": best_tier}).eq("id", row["id"]).execute()
            invalidate_plan_cache(row["id"])
            logger.info(
                "[billing] subscription canceled sub_id=%s but user=%s has %d other active sub(s); kept plan=%s",
                sub_id, row["id"], len(other_subs), best_tier,
            )
        else:
            sb.table("users").update({"plan": "free"}).eq("id", row["id"]).execute()
            invalidate_plan_cache(row["id"])
            logger.info("[billing] subscription canceled sub_id=%s user=%s downgraded to free (no other active subs)", sub_id, row["id"])
