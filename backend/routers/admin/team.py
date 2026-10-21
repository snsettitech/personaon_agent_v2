"""Admin: team & roles — staff list, role changes, staff invites.

Role is a platform-wide attribute on ``users.role``. ``require_admin_write``
(owner/admin) is required to mutate; granting the ``owner`` role requires the
actor to be an owner, and you cannot change your own role (avoids self-lockout).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from modules import admin_audit
from modules.auth_guard import require_admin, require_admin_write

from ._common import ROLES, _safe_query, _supabase

logger = logging.getLogger(__name__)
router = APIRouter()

# Roles considered "staff" (have admin-area access).
STAFF_ROLES = ("owner", "admin", "support")


class RoleUpdate(BaseModel):
    role: str


class StaffInvite(BaseModel):
    email: str
    role: str = "support"


@router.get("/team")
def list_team(user: dict = Depends(require_admin)) -> dict[str, Any]:
    """List staff members (owner/admin/support)."""
    sb = _supabase()
    staff = _safe_query(
        sb.table("users")
        .select("id, email, full_name, role, created_at, last_active_at")
        .in_("role", list(STAFF_ROLES))
        .order("created_at", desc=True)
        .limit(200)
    )
    return {"staff": staff}


@router.put("/users/{user_id}/role")
def change_role(
    user_id: str,
    body: RoleUpdate,
    user: dict = Depends(require_admin_write),
) -> dict[str, Any]:
    """Change a user's platform role. Audited."""
    if body.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"invalid role: {body.role}")
    actor_id = user.get("user_id") or user.get("id")
    if user_id == actor_id:
        raise HTTPException(status_code=400, detail="cannot change your own role")
    if body.role == "owner" and user.get("actual_role") != "owner":
        raise HTTPException(status_code=403, detail="only an owner can grant the owner role")

    sb = _supabase()
    rows = _safe_query(sb.table("users").select("role, email").eq("id", user_id).limit(1))
    if not rows:
        raise HTTPException(status_code=404, detail="user not found")
    before_role = rows[0].get("role")
    sb.table("users").update({"role": body.role}).eq("id", user_id).execute()
    admin_audit.record_admin_action(
        actor=user, action=admin_audit.ACTION_ROLE_CHANGED, target_type="user",
        target_id=user_id, target_email=rows[0].get("email"),
        before={"role": before_role}, after={"role": body.role},
    )
    return {"status": "ok", "data": {"user_id": user_id, "role": body.role}}


@router.post("/team/invite")
def invite_staff(body: StaffInvite, user: dict = Depends(require_admin_write)) -> dict[str, Any]:
    """Invite a new teammate by email and pre-assign their role. Audited.

    Sends a Supabase invite email (creates the auth identity in invited state)
    and upserts a ``users`` row with the role so it's effective on first sign-in.
    For users who already exist, change their role in the staff table instead.
    """
    if body.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"invalid role: {body.role}")
    if body.role == "owner" and user.get("actual_role") != "owner":
        raise HTTPException(status_code=403, detail="only an owner can grant the owner role")

    sb = _supabase()
    try:
        resp = sb.auth.admin.invite_user_by_email(body.email)
        invited = getattr(resp, "user", None)
        new_id = getattr(invited, "id", None)
    except Exception as exc:
        logger.warning("[admin.team] invite failed email=%s err=%r", body.email, exc)
        raise HTTPException(
            status_code=409,
            detail="could not invite (user may already exist — change their role instead)",
        )
    if not new_id:
        raise HTTPException(status_code=500, detail="invite returned no user id")

    try:
        sb.table("users").upsert(
            {"id": new_id, "email": body.email, "role": body.role, "tenant_id": new_id}
        ).execute()
    except Exception as exc:
        logger.exception("[admin.team] users upsert failed id=%s err=%r", new_id, exc)
        raise HTTPException(status_code=500, detail="invite sent but role assignment failed")

    admin_audit.record_admin_action(
        actor=user, action=admin_audit.ACTION_STAFF_INVITED, target_type="user",
        target_id=new_id, target_email=body.email, after={"role": body.role},
    )
    return {"status": "ok", "data": {"user_id": new_id, "email": body.email, "role": body.role}}
