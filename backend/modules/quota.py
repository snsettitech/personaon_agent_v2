"""Quota enforcement + metering for billable actions.

Check-and-increment via read-then-write. The race window is milliseconds;
at our scale this is acceptable — worst case is double-counting a single
message. Upgrade to Postgres RPC for atomicity at 10K+ MAU.

Overage on paid tiers enqueues a Stripe meter event via graph_outbox
(async, non-blocking hot path).
"""
from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any

logger = logging.getLogger(__name__)

# Tier caps.
# Pro (v2 launch tier $14.99/mo): 5K msg + 30 min voice — sized so worst-case
# COGS ~$8 against $14.99 price (~47% gross). Top ~10% of users hit cap and
# pay overage at $5/1K msg, $0.20/min voice.
# Believer LTD: hidden upsell, kept generous since pre-paid lifetime.
_QUOTA_CAPS: dict[str, dict[str, int]] = {
    "free":     {"messages": 500,    "voice_minutes": 0,   "bot_minutes": 0},
    "pro":      {"messages": 5_000,  "voice_minutes": 30,  "bot_minutes": 0},
    "believer": {"messages": 20_000, "voice_minutes": 60,  "bot_minutes": 180},
    "business": {"messages": 50_000, "voice_minutes": 300, "bot_minutes": 300},
}


def _get_supabase():
    from modules.observability import get_supabase_client
    return get_supabase_client()


def get_quota(user_id: str) -> dict[str, Any]:
    """Return quota snapshot for a user. Safe default (free) on DB error or missing row.

    Also enforces no-card trial expiry: if user is on a no_card trial and
    trial_ends_at has passed, downgrade to free here (lazy revert on read).
    This is the canonical enforcement point — every quota-checked operation
    (chat, voice, interview) flows through here.
    """
    try:
        sb = _get_supabase()
        row = sb.table("users").select(
            "plan, messages_this_period, voice_minutes_this_period, period_started_at, "
            "trial_kind, trial_ends_at"
        ).eq("id", user_id).maybe_single().execute()
    except Exception as exc:
        logger.warning("[quota] get_quota DB error user_id=%s error=%r", user_id, exc)
        return {
            "tier": "free",
            "messages_used": 0, "messages_cap": _QUOTA_CAPS["free"]["messages"],
            "voice_used": 0, "voice_cap": _QUOTA_CAPS["free"]["voice_minutes"],
            "bot_cap": _QUOTA_CAPS["free"]["bot_minutes"],
            "period_started_at": None,
        }
    data = (row.data if row is not None else None) or {}
    tier = data.get("plan") or "free"

    # Lazy-downgrade for expired no-card trials. Stripe-managed trials handle
    # their own state via the webhook; only the DB-only no_card path needs this.
    if data.get("trial_kind") == "no_card" and data.get("trial_ends_at") and tier != "free":
        from datetime import datetime, timezone
        try:
            ends = datetime.fromisoformat(str(data["trial_ends_at"]).replace("Z", "+00:00"))
            if ends < datetime.now(timezone.utc):
                sb.table("users").update({
                    "plan": "free",
                    "trial_kind": None,
                    "trial_ends_at": None,
                }).eq("id", user_id).execute()
                logger.info("[quota] no-card trial expired downgraded user_id=%s", user_id)
                tier = "free"
        except (ValueError, TypeError) as exc:
            logger.warning("[quota] bad trial_ends_at user_id=%s value=%r error=%r",
                           user_id, data.get("trial_ends_at"), exc)

    caps = _QUOTA_CAPS.get(tier, _QUOTA_CAPS["free"])
    return {
        "tier": tier,
        "messages_used": data.get("messages_this_period", 0) or 0,
        "messages_cap": caps["messages"],
        "voice_used": data.get("voice_minutes_this_period", 0) or 0,
        "voice_cap": caps["voice_minutes"],
        "bot_cap": caps["bot_minutes"],
        "period_started_at": data.get("period_started_at"),
    }


def _atomic_increment_messages(user_id: str, delta: int = 1) -> int:
    """Read-then-update increment. Race window ~ms, acceptable at current scale."""
    sb = _get_supabase()
    row = sb.table("users").select("messages_this_period").eq("id", user_id).maybe_single().execute()
    if row is None or row.data is None:
        logger.warning(
            "[quota] users row missing for user_id=%s — increment skipped, returning delta",
            user_id,
        )
        return delta
    current = (row.data.get("messages_this_period") or 0)
    new_value = current + delta
    sb.table("users").update({"messages_this_period": new_value}).eq("id", user_id).execute()
    return new_value


def _atomic_increment_voice(user_id: str, minutes: int) -> int:
    """Read-then-update increment for voice minutes."""
    sb = _get_supabase()
    row = sb.table("users").select("voice_minutes_this_period").eq("id", user_id).maybe_single().execute()
    if row is None or row.data is None:
        logger.warning(
            "[quota] users row missing for user_id=%s — voice increment skipped, returning minutes",
            user_id,
        )
        return minutes
    current = (row.data.get("voice_minutes_this_period") or 0)
    new_value = current + minutes
    sb.table("users").update({"voice_minutes_this_period": new_value}).eq("id", user_id).execute()
    return new_value


def _enqueue_meter_event(
    *,
    event_name: str,
    user_id: str,
    value: int,
    period_start: str | None,
) -> None:
    """Enqueue a Stripe meter event via graph_outbox for async reporting.

    Identifier combines user_id + period_start + value_snapshot + short uuid
    for idempotency within a single retry burst while remaining unique across calls.
    """
    identifier = f"{user_id}:{period_start or 'unknown'}:{value}:{_uuid.uuid4().hex[:8]}"
    payload = {
        "event_name": event_name,
        "user_id": user_id,
        "value": value,
        "identifier": identifier,
    }
    try:
        sb = _get_supabase()
        sb.table("graph_outbox").insert({
            "operation": "stripe_meter_event",
            "payload": payload,
            "status": "pending",
        }).execute()
    except Exception as exc:
        logger.warning(
            "[quota] failed to enqueue meter event user_id=%s error=%r", user_id, exc
        )


def check_and_increment_messages(user_id: str, delta: int = 1) -> tuple[bool, int, int]:
    """Check quota + increment. Returns (allowed, used_after, cap).

    Free tier: blocks at cap. Paid tiers: always allowed, overage -> Stripe meter.
    """
    q = get_quota(user_id)
    tier = q["tier"]
    used = q["messages_used"]
    cap = q["messages_cap"]

    if tier == "free" and used >= cap:
        return False, used, cap

    new_used = _atomic_increment_messages(user_id, delta)
    if tier != "free" and new_used > cap:
        overage = min(delta, new_used - cap)
        _enqueue_meter_event(
            event_name="personaon_messages",
            user_id=user_id,
            value=overage,
            period_start=q.get("period_started_at"),
        )
    return True, new_used, cap


def check_and_increment_voice(user_id: str, seconds: int) -> tuple[bool, int, int]:
    """Check voice quota + increment. Blocks tiers with cap=0. Reports overage."""
    minutes = max(1, seconds // 60)  # always bill at least 1 minute
    q = get_quota(user_id)
    tier = q["tier"]
    used = q["voice_used"]
    cap = q["voice_cap"]

    if cap == 0:
        return False, used, cap

    new_used = _atomic_increment_voice(user_id, minutes)
    if new_used > cap:
        overage = min(minutes, new_used - cap)
        _enqueue_meter_event(
            event_name="personaon_voice_minutes",
            user_id=user_id,
            value=overage,
            period_start=q.get("period_started_at"),
        )
    return True, new_used, cap


def reset_period_counters(user_id: str, period_started_at: str) -> None:
    """Called by webhook on subscription.updated when current_period_start changed."""
    sb = _get_supabase()
    sb.table("users").update({
        "messages_this_period": 0,
        "voice_minutes_this_period": 0,
        "period_started_at": period_started_at,
    }).eq("id", user_id).execute()
    sb.table("subscriptions").update({
        "messages_this_period": 0,
        "voice_minutes_this_period": 0,
        "bot_minutes_this_period": 0,
        "period_started_at": period_started_at,
    }).eq("user_id", user_id).execute()
    logger.info("[quota] period reset user_id=%s period=%s", user_id, period_started_at)
