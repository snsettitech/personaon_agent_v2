"""
User Management Module

Handles user listing, invitations, role management, and user deletion.
"""
import logging
import uuid
from typing import Any
from datetime import datetime, timedelta
from modules.observability import supabase

logger = logging.getLogger(__name__)


def _is_missing_users_column_error(error: Exception, column_name: str) -> bool:
    text = str(error or "")
    lowered = text.lower()
    return "pgrst204" in lowered and column_name.lower() in lowered and "users" in lowered


def _safe_users_update_by_id(user_id: str, payload: dict[str, Any]) -> None:
    try:
        supabase.table("users").update(payload).eq("id", user_id).execute()
    except Exception as exc:
        if payload.get("full_name") and _is_missing_users_column_error(exc, "full_name"):
            fallback_payload = dict(payload)
            fallback_payload.pop("full_name", None)
            supabase.table("users").update(fallback_payload).eq("id", user_id).execute()
            return
        raise


def _safe_users_insert(payload: dict[str, Any]):
    try:
        return supabase.table("users").insert(payload).execute()
    except Exception as exc:
        if payload.get("full_name") and _is_missing_users_column_error(exc, "full_name"):
            fallback_payload = dict(payload)
            fallback_payload.pop("full_name", None)
            return supabase.table("users").insert(fallback_payload).execute()
        raise


def list_users(tenant_id: str) -> list[dict[str, Any]]:
    """
    List all users for a tenant with their roles and basic info.
    """
    try:
        response = supabase.table("users").select("*").eq("tenant_id", tenant_id).order("created_at", desc=True).execute()

        if not response.data:
            return []

        users = []
        for user in response.data:
            users.append({
                "id": user["id"],
                "tenant_id": user["tenant_id"],
                "email": user["email"],
                "role": user["role"],
                "invited_at": user.get("invited_at"),
                "created_at": user.get("created_at"),
                "last_active_at": user.get("last_active_at")
            })

        return users
    except Exception as e:
        logger.warning("Error listing users: %s", e)
        return []


def invite_user(tenant_id: str, email: str, role: str, invited_by: str) -> dict[str, Any]:
    """
    Generate invitation token and create invitation record.
    Returns invitation details including token.
    """
    # Check if user already exists
    existing_user_response = supabase.table("users").select("id").eq("email", email).execute()
    if existing_user_response.data:
        raise ValueError(f"User with email {email} already exists")

    # Check for existing pending invitation
    existing_invitation_response = supabase.table("user_invitations").select("*").eq(
        "tenant_id", tenant_id
    ).eq("email", email).eq("status", "pending").execute()

    invitation_token = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(days=7)

    if existing_invitation_response.data and len(existing_invitation_response.data) > 0:
        # Update existing invitation
        invitation_id = existing_invitation_response.data[0]["id"]
        supabase.table("user_invitations").update({
            "invitation_token": invitation_token,
            "role": role,
            "invited_by": invited_by,
            "expires_at": expires_at.isoformat(),
            "status": "pending"
        }).eq("id", invitation_id).execute()
    else:
        # Create new invitation
        invitation_data = {
            "tenant_id": tenant_id,
            "email": email,
            "invitation_token": invitation_token,
            "invited_by": invited_by,
            "role": role,
            "status": "pending",
            "expires_at": expires_at.isoformat()
        }

        response = supabase.table("user_invitations").insert(invitation_data).execute()

        if not response.data:
            raise ValueError("Failed to create invitation")

        invitation_id = response.data[0]["id"]

    # Generate invitation URL
    import os
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    invitation_url = f"{frontend_url}/auth/accept-invitation/{invitation_token}"

    return {
        "id": invitation_id,
        "email": email,
        "invitation_token": invitation_token,
        "invitation_url": invitation_url,
        "role": role,
        "expires_at": expires_at.isoformat()
    }


def validate_invitation_token(token: str) -> dict[str, Any] | None:
    """
    Verify invitation token is valid and not expired.
    Returns invitation details if valid, None otherwise.
    """
    try:
        response = supabase.table("user_invitations").select("*").eq("invitation_token", token).single().execute()

        if not response.data:
            return None

        invitation = response.data

        # Check status
        if invitation["status"] != "pending":
            return None  # Already accepted or expired

        # Check expiration
        expires_at_str = invitation.get("expires_at")
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
            if datetime.now(expires_at.tzinfo) > expires_at:
                # Mark as expired
                supabase.table("user_invitations").update({"status": "expired"}).eq("id", invitation["id"]).execute()
                return None

        return {
            "id": invitation["id"],
            "tenant_id": invitation["tenant_id"],
            "email": invitation["email"],
            "role": invitation["role"],
            "invited_by": invitation["invited_by"],
            "expires_at": invitation.get("expires_at")
        }
    except Exception as e:
        logger.warning("Error validating invitation token: %s", e)
        return None


def accept_invitation(
    token: str,
    user_data: dict[str, Any],
    auth_user_id: str | None = None,
) -> dict[str, Any]:
    """
    Create user account from invitation and mark invitation as accepted.
    user_data should contain: email, password_hash (if using password auth), name (optional)
    Returns created user dict.
    """
    # Validate token first
    invitation = validate_invitation_token(token)
    if not invitation:
        raise ValueError("Invalid or expired invitation token")

    invited_email = invitation["email"]
    now_iso = datetime.utcnow().isoformat()
    full_name = (user_data or {}).get("name")

    existing_response = (
        supabase.table("users")
        .select("id, tenant_id, email, role, created_at")
        .eq("email", invited_email)
        .limit(1)
        .execute()
    )
    existing_user = (existing_response.data or [None])[0]

    user_row: dict[str, Any]
    if existing_user:
        existing_id = existing_user.get("id")
        target_id = auth_user_id or existing_id

        update_payload: dict[str, Any] = {
            "tenant_id": invitation["tenant_id"],
            "role": invitation["role"],
            "invited_at": now_iso,
            "invitation_id": invitation["id"],
        }
        if full_name:
            update_payload["full_name"] = full_name

        if target_id and existing_id and target_id != existing_id:
            try:
                supabase.table("users").update({"id": target_id}).eq("id", existing_id).execute()
            except Exception:
                # Non-fatal: keep existing primary key if PK migration is blocked by constraints.
                target_id = existing_id

        if target_id:
            _safe_users_update_by_id(target_id, update_payload)
            user_lookup = supabase.table("users").select("*").eq("id", target_id).limit(1).execute()
            user_row = (user_lookup.data or [None])[0]
        else:
            supabase.table("users").update(update_payload).eq("email", invited_email).execute()
            user_lookup = supabase.table("users").select("*").eq("email", invited_email).limit(1).execute()
            user_row = (user_lookup.data or [None])[0]
    else:
        user_create_data: dict[str, Any] = {
            "tenant_id": invitation["tenant_id"],
            "email": invited_email,
            "role": invitation["role"],
            "invited_at": now_iso,
            "invitation_id": invitation["id"],
        }
        if auth_user_id:
            user_create_data["id"] = auth_user_id
        if full_name:
            user_create_data["full_name"] = full_name

        user_response = _safe_users_insert(user_create_data)
        if not user_response.data:
            raise ValueError("Failed to create user")
        user_row = user_response.data[0]

    if not user_row:
        raise ValueError("Failed to create or update invited user")

    # Mark invitation as accepted
    supabase.table("user_invitations").update({
        "status": "accepted",
        "accepted_at": datetime.utcnow().isoformat()
    }).eq("id", invitation["id"]).execute()

    return {
        "id": user_row["id"],
        "tenant_id": user_row.get("tenant_id"),
        "email": user_row.get("email"),
        "role": user_row.get("role"),
        "created_at": user_row.get("created_at")
    }


def update_user_role(user_id: str, new_role: str, updated_by: str) -> bool:
    """
    Update user role (owners only).
    """
    if new_role not in ["owner", "viewer"]:
        raise ValueError(f"Invalid role: {new_role}")

    try:
        response = supabase.table("users").update({"role": new_role}).eq("id", user_id).execute()
        return bool(response.data)
    except Exception as e:
        logger.warning("Error updating user role: %s", e)
        return False


def delete_user(user_id: str, deleted_by: str) -> bool:
    """
    Delete a user (cascading deletes will handle group memberships).
    """
    try:
        # Also mark related invitations as expired if any
        supabase.table("user_invitations").update({"status": "expired"}).eq(
            "invited_by", user_id
        ).eq("status", "pending").execute()

        # Delete user (cascading will handle group_memberships)
        response = supabase.table("users").delete().eq("id", user_id).execute()
        return bool(response.data)
    except Exception as e:
        logger.warning("Error deleting user: %s", e)
        return False


def get_user_details(user_id: str) -> dict[str, Any] | None:
    """
    Get user details including group memberships across all twins.
    """
    try:
        # Get user
        user_response = supabase.table("users").select("*").eq("id", user_id).single().execute()

        if not user_response.data:
            return None

        user = user_response.data

        # Get group memberships
        memberships_response = supabase.table("group_memberships").select(
            "*, access_groups(id, name, twin_id, is_default, is_public)"
        ).eq("user_id", user_id).eq("is_active", True).execute()

        group_memberships = []
        if memberships_response.data:
            for membership in memberships_response.data:
                group_memberships.append({
                    "membership_id": membership["id"],
                    "group_id": membership["group_id"],
                    "twin_id": membership["twin_id"],
                    "group_name": membership.get("access_groups", {}).get("name"),
                    "is_default": membership.get("access_groups", {}).get("is_default"),
                    "is_public": membership.get("access_groups", {}).get("is_public")
                })

        return {
            "id": user["id"],
            "tenant_id": user["tenant_id"],
            "email": user["email"],
            "role": user["role"],
            "invited_at": user.get("invited_at"),
            "created_at": user.get("created_at"),
            "group_memberships": group_memberships
        }
    except Exception as e:
        logger.warning("Error getting user details: %s", e)
        return None
