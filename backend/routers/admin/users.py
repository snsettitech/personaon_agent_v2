"""Admin: user management — search, detail, entitlements, trial, suspend, delete, export.

Reads use ``require_admin``; every mutation uses ``require_admin_write`` (owner/
admin only) and writes an ``admin_audit_log`` row.

Feature flags live in Supabase ``user_metadata`` under ``flag_<name>`` and are
read by the app from the user's JWT — so flag changes here take effect on the
target user's NEXT sign-in / token refresh. Plan changes apply within ~5 min
(``invalidate_plan_cache`` clears the in-process tier cache immediately on this
instance).
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from modules import admin_audit
from modules.auth_guard import require_admin, require_admin_write
from modules.plan_guard import invalidate_plan_cache
from services.account_notification_service import enqueue_account_notification

from ._common import ALL_FLAGS, PLAN_TIERS, _safe_query, _supabase

logger = logging.getLogger(__name__)
router = APIRouter()

# Supabase Auth ban duration for an indefinite suspension (~100 years).
_BAN_FOREVER = "876000h"


class EntitlementsUpdate(BaseModel):
    plan: str | None = None
    flags: dict[str, bool] | None = None


class TrialGrant(BaseModel):
    plan: str = "pro"
    days: int = 14


def _user_metadata(sb, user_id: str) -> dict[str, Any]:
    """Read a user's Supabase Auth user_metadata (for flag_* keys)."""
    try:
        resp = sb.auth.admin.get_user_by_id(user_id)
        user_obj = getattr(resp, "user", None)
        meta = getattr(user_obj, "user_metadata", None)
        return dict(meta) if isinstance(meta, dict) else {}
    except Exception as exc:
        logger.warning("[admin.users] metadata fetch failed user_id=%s err=%r", user_id, exc)
        return {}


def _flags_view(metadata: dict[str, Any]) -> dict[str, Any]:
    """{flag_name: True/False/None} — None means 'not set' (uses default)."""
    return {name: metadata.get(f"flag_{name}") for name in ALL_FLAGS}


# ── Reads ───────────────────────────────────────────────────────────────────


@router.get("/users/search")
def search_users(
    q: str | None = Query(default=None, description="email substring"),
    plan: str | None = Query(default=None),
    role: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(require_admin),
) -> list:
    """Search users by email substring, optionally filtered by plan/role (paged)."""
    sb = _supabase()
    query = (
        sb.table("users")
        .select("id, email, full_name, role, plan, created_at, last_active_at")
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if q:
        query = query.ilike("email", f"%{q}%")
    if plan:
        query = query.eq("plan", plan)
    if role:
        query = query.eq("role", role)
    return _safe_query(query)


@router.get("/users/export")
def export_users(user: dict = Depends(require_admin)) -> Response:
    """Export users as CSV (up to 5000 rows)."""
    sb = _supabase()
    rows = _safe_query(
        sb.table("users")
        .select("id, email, full_name, role, plan, created_at, last_active_at")
        .order("created_at", desc=True)
        .limit(5000)
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "email", "full_name", "role", "plan", "created_at", "last_active_at"])
    for r in rows:
        writer.writerow([
            r.get("id"), r.get("email"), r.get("full_name"), r.get("role"),
            r.get("plan"), r.get("created_at"), r.get("last_active_at"),
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=personaon-users.csv"},
    )


@router.get("/users/{user_id}")
def get_user_detail(user_id: str, user: dict = Depends(require_admin)) -> dict[str, Any]:
    """Full picture of one user: profile, usage, subscription, twins, flags."""
    sb = _supabase()
    rows = _safe_query(
        sb.table("users")
        .select(
            "id, email, full_name, role, plan, stripe_customer_id, trial_kind, "
            "trial_ends_at, messages_this_period, voice_minutes_this_period, "
            "period_started_at, created_at, last_active_at"
        )
        .eq("id", user_id)
        .limit(1)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="user not found")
    twins = _safe_query(
        sb.table("twins")
        .select("id, name, status, is_active, created_at")
        .eq("tenant_id", user_id)
        .order("created_at", desc=True)
        .limit(50)
    )
    subs = _safe_query(
        sb.table("subscriptions")
        .select("tier, status, price_lookup_key, current_period_end, cancel_at_period_end")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(1)
    )
    return {
        "user": rows[0],
        "twins": twins,
        "subscription": subs[0] if subs else None,
        "flags": _flags_view(_user_metadata(sb, user_id)),
    }


@router.get("/users/{user_id}/entitlements")
def get_entitlements(user_id: str, user: dict = Depends(require_admin)) -> dict[str, Any]:
    """Current plan + per-user feature-flag overrides."""
    sb = _supabase()
    rows = _safe_query(sb.table("users").select("plan").eq("id", user_id).limit(1))
    if not rows:
        raise HTTPException(status_code=404, detail="user not found")
    return {"plan": rows[0].get("plan", "free"), "flags": _flags_view(_user_metadata(sb, user_id))}


# ── Mutations (require_admin_write) ──────────────────────────────────────────


@router.post("/users/{user_id}/entitlements")
def set_entitlements(
    user_id: str,
    body: EntitlementsUpdate,
    user: dict = Depends(require_admin_write),
) -> dict[str, Any]:
    """Set a user's plan and/or feature flags. Audited."""
    sb = _supabase()
    if body.plan is not None and body.plan not in PLAN_TIERS:
        raise HTTPException(status_code=400, detail=f"invalid plan: {body.plan}")
    if body.flags:
        unknown = [f for f in body.flags if f not in ALL_FLAGS]
        if unknown:
            raise HTTPException(status_code=400, detail=f"unknown flags: {unknown}")

    rows = _safe_query(sb.table("users").select("plan, email").eq("id", user_id).limit(1))
    if not rows:
        raise HTTPException(status_code=404, detail="user not found")
    before_plan = rows[0].get("plan")
    target_email = rows[0].get("email")

    if body.plan is not None and body.plan != before_plan:
        sb.table("users").update({"plan": body.plan}).eq("id", user_id).execute()
        invalidate_plan_cache(user_id)
        admin_audit.record_admin_action(
            actor=user, action=admin_audit.ACTION_PLAN_CHANGED, target_type="user",
            target_id=user_id, target_email=target_email,
            before={"plan": before_plan}, after={"plan": body.plan},
        )

    if body.flags:
        metadata = _user_metadata(sb, user_id)
        for name, value in body.flags.items():
            metadata[f"flag_{name}"] = bool(value)
        sb.auth.admin.update_user_by_id(user_id, {"user_metadata": metadata})
        admin_audit.record_admin_action(
            actor=user, action=admin_audit.ACTION_FLAGS_CHANGED, target_type="user",
            target_id=user_id, target_email=target_email, after={"flags": body.flags},
        )

    return {"status": "ok", "data": {"user_id": user_id, "plan": body.plan or before_plan}}


@router.post("/users/{user_id}/grant-all")
def grant_all_features(user_id: str, user: dict = Depends(require_admin_write)) -> dict[str, Any]:
    """Give an employee everything: top plan + all feature flags on."""
    body = EntitlementsUpdate(plan="business", flags={name: True for name in ALL_FLAGS})
    result = set_entitlements(user_id, body, user)
    enqueue_account_notification(
        _supabase(),
        user_id=user_id,
        flow_key="access_granted",
        idempotency_key=f"access-granted-{user_id}",
        actor_id=str(user.get("user_id") or user.get("id") or ""),
    )
    return result


@router.post("/users/{user_id}/trial")
def grant_trial(
    user_id: str,
    body: TrialGrant,
    user: dict = Depends(require_admin_write),
) -> dict[str, Any]:
    """Grant/extend a no-card trial on a given plan. Audited."""
    if body.plan not in PLAN_TIERS:
        raise HTTPException(status_code=400, detail=f"invalid plan: {body.plan}")
    sb = _supabase()
    ends = (datetime.now(timezone.utc) + timedelta(days=max(1, body.days))).isoformat()
    sb.table("users").update(
        {"plan": body.plan, "trial_kind": "no_card", "trial_ends_at": ends}
    ).eq("id", user_id).execute()
    invalidate_plan_cache(user_id)
    admin_audit.record_admin_action(
        actor=user, action=admin_audit.ACTION_TRIAL_GRANTED, target_type="user",
        target_id=user_id, after={"plan": body.plan, "trial_ends_at": ends, "days": body.days},
    )
    return {"status": "ok", "data": {"user_id": user_id, "plan": body.plan, "trial_ends_at": ends}}


@router.post("/users/{user_id}/suspend")
def suspend_user(user_id: str, user: dict = Depends(require_admin_write)) -> dict[str, Any]:
    """Suspend a user via Supabase Auth ban (blocks login). Audited."""
    sb = _supabase()
    try:
        sb.auth.admin.update_user_by_id(user_id, {"ban_duration": _BAN_FOREVER})
    except Exception as exc:
        logger.exception("[admin.users] suspend failed user_id=%s err=%r", user_id, exc)
        raise HTTPException(status_code=500, detail="suspend failed")
    admin_audit.record_admin_action(
        actor=user, action=admin_audit.ACTION_USER_SUSPENDED, target_type="user", target_id=user_id,
    )
    enqueue_account_notification(
        _supabase(),
        user_id=user_id,
        flow_key="account_suspended",
        idempotency_key=f"account-suspended-{user_id}",
        actor_id=str(user.get("user_id") or user.get("id") or ""),
    )
    return {"status": "ok", "data": {"user_id": user_id, "suspended": True}}


@router.post("/users/{user_id}/unsuspend")
def unsuspend_user(user_id: str, user: dict = Depends(require_admin_write)) -> dict[str, Any]:
    """Lift a suspension (ban_duration=none). Audited."""
    sb = _supabase()
    try:
        sb.auth.admin.update_user_by_id(user_id, {"ban_duration": "none"})
    except Exception as exc:
        logger.exception("[admin.users] unsuspend failed user_id=%s err=%r", user_id, exc)
        raise HTTPException(status_code=500, detail="unsuspend failed")
    admin_audit.record_admin_action(
        actor=user, action=admin_audit.ACTION_USER_UNSUSPENDED, target_type="user", target_id=user_id,
    )
    return {"status": "ok", "data": {"user_id": user_id, "suspended": False}}


@router.delete("/users/{user_id}")
def delete_user(user_id: str, user: dict = Depends(require_admin_write)) -> dict[str, Any]:
    """Delete a user from Auth and the public.users table. Audited.

    Cleans BOTH the Supabase Auth identity and the public.users row (a Supabase
    soft-delete otherwise leaves an orphaned public row).
    """
    sb = _supabase()
    rows = _safe_query(sb.table("users").select("email").eq("id", user_id).limit(1))
    target_email = rows[0].get("email") if rows else None

    try:
        sb.auth.admin.delete_user(user_id)
    except Exception as exc:
        logger.warning("[admin.users] auth delete failed/unsupported user_id=%s err=%r", user_id, exc)

    try:
        sb.table("users").delete().eq("id", user_id).execute()
    except Exception as exc:
        logger.exception("[admin.users] users row delete failed user_id=%s err=%r", user_id, exc)
        raise HTTPException(status_code=500, detail="user delete failed")

    admin_audit.record_admin_action(
        actor=user, action=admin_audit.ACTION_USER_DELETED, target_type="user",
        target_id=user_id, target_email=target_email,
    )
    return {"status": "ok", "data": {"user_id": user_id, "deleted": True}}
