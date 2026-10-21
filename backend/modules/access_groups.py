"""
Access Groups Module
Manages access groups, memberships, content permissions, limits, and overrides.
"""

from typing import Any
from modules.observability import supabase


async def get_user_group(user_id: str, twin_id: str) -> dict[str, Any] | None:
    """
    Get user's group for a twin.
    Returns the group object with membership info, or None if not found.
    """
    try:
        membership_response = supabase.table("group_memberships").select(
            "*, access_groups(*)"
        ).eq("user_id", user_id).eq("twin_id", twin_id).eq("is_active", True).single().execute()

        if membership_response.data:
            membership = membership_response.data
            group = membership.get("access_groups")
            if group:
                return group
        return None
    except Exception:
        # If no membership found, return None
        return None


async def get_default_group(twin_id: str) -> dict[str, Any]:
    """
    Get default group for a twin.
    Raises ValueError if no default group exists.
    """
    response = supabase.table("access_groups").select("*").eq(
        "twin_id", twin_id
    ).eq("is_default", True).single().execute()

    if not response.data:
        raise ValueError(f"No default group found for twin {twin_id}")

    return response.data


async def create_group(
    twin_id: str,
    name: str,
    description: str | None = None,
    is_public: bool = False,
    is_default: bool = False,
    settings: dict[str, Any] | None = None
) -> str:
    """
    Create a new access group.
    Returns the group ID.
    """
    group_data = {
        "twin_id": twin_id,
        "name": name,
        "description": description,
        "is_public": is_public,
        "is_default": is_default,
        "settings": settings or {}
    }

    response = supabase.table("access_groups").insert(group_data).execute()

    if not response.data:
        raise ValueError("Failed to create access group")

    return response.data[0]["id"]


async def assign_user_to_group(user_id: str, twin_id: str, group_id: str) -> bool:
    """
    Assign user to a group (replaces existing membership for that twin).
    Returns True if successful.
    """
    # First, verify the group belongs to the twin
    group_response = supabase.table("access_groups").select("id").eq(
        "id", group_id
    ).eq("twin_id", twin_id).single().execute()

    if not group_response.data:
        raise ValueError(f"Group {group_id} does not belong to twin {twin_id}")

    # Delete existing membership for this user-twin combination
    supabase.table("group_memberships").delete().eq(
        "user_id", user_id
    ).eq("twin_id", twin_id).execute()

    # Create new membership
    membership_data = {
        "group_id": group_id,
        "user_id": user_id,
        "twin_id": twin_id,
        "is_active": True
    }

    response = supabase.table("group_memberships").insert(membership_data).execute()

    return bool(response.data)


async def add_content_permission(group_id: str, content_type: str, content_id: str, twin_id: str) -> bool:
    """
    Grant group access to content.
    content_type must be 'source' or 'verified_qna'.
    Returns True if successful.
    """
    if content_type not in ["source", "verified_qna"]:
        raise ValueError(f"Invalid content_type: {content_type}. Must be 'source' or 'verified_qna'")

    permission_data = {
        "group_id": group_id,
        "twin_id": twin_id,
        "content_type": content_type,
        "content_id": content_id
    }

    try:
        response = supabase.table("content_permissions").insert(permission_data).execute()
        return bool(response.data)
    except Exception as e:
        # If unique constraint violation, permission already exists
        if "duplicate key" in str(e).lower() or "unique" in str(e).lower():
            return True  # Already exists, consider it success
        raise


async def remove_content_permission(group_id: str, content_type: str, content_id: str) -> bool:
    """
    Revoke group access to content.
    Returns True if successful.
    """
    _ = supabase.table("content_permissions").delete().eq(
        "group_id", group_id
    ).eq("content_type", content_type).eq("content_id", content_id).execute()

    return True


async def get_group_permissions(group_id: str) -> list[dict[str, Any]]:
    """
    Get all content accessible to a group.
    Returns list of permission objects with content_type and content_id.
    """
    response = supabase.table("content_permissions").select("*").eq(
        "group_id", group_id
    ).execute()

    return response.data or []


async def get_groups_for_content(content_type: str, content_id: str) -> list[str]:
    """
    Get all group IDs that have access to specific content.
    Returns list of group IDs.
    """
    response = supabase.table("content_permissions").select("group_id").eq(
        "content_type", content_type
    ).eq("content_id", content_id).execute()

    return [perm["group_id"] for perm in (response.data or [])]


async def check_content_access(group_id: str, content_type: str, content_id: str) -> bool:
    """
    Check if group can access specific content.
    Returns True if access exists.
    """
    response = supabase.table("content_permissions").select("id").eq(
        "group_id", group_id
    ).eq("content_type", content_type).eq("content_id", content_id).execute()

    return bool(response.data)


async def get_group_settings(group_id: str) -> dict[str, Any]:
    """
    Get group settings and overrides.
    Returns merged settings dict with overrides applied.
    """
    # Get group
    group_response = supabase.table("access_groups").select("settings").eq(
        "id", group_id
    ).single().execute()

    if not group_response.data:
        raise ValueError(f"Group {group_id} not found")

    settings = group_response.data.get("settings", {})

    # Get overrides
    overrides_response = supabase.table("group_overrides").select("*").eq(
        "group_id", group_id
    ).execute()

    overrides = {}
    if overrides_response.data:
        for override in overrides_response.data:
            override_type = override["override_type"]
            override_value = override["override_value"]
            overrides[override_type] = override_value

    # Merge: settings as base, overrides take precedence
    result = {**settings, **overrides}

    return result


async def list_groups(twin_id: str) -> list[dict[str, Any]]:
    """
    List all groups for a twin.
    """
    response = supabase.table("access_groups").select("*").eq(
        "twin_id", twin_id
    ).order("created_at").execute()

    return response.data or []


async def get_group(group_id: str) -> dict[str, Any] | None:
    """
    Get group by ID.
    """
    response = supabase.table("access_groups").select("*").eq(
        "id", group_id
    ).single().execute()

    return response.data if response.data else None


async def update_group(group_id: str, updates: dict[str, Any]) -> bool:
    """
    Update group fields.
    """
    # Add updated_at timestamp
    updates["updated_at"] = "now()"

    response = supabase.table("access_groups").update(updates).eq(
        "id", group_id
    ).execute()

    return bool(response.data)


async def delete_group(group_id: str) -> bool:
    """
    Delete a group (CASCADE will handle memberships and permissions).
    Cannot delete if it's the default group.
    """
    # Check if it's a default group
    group_response = supabase.table("access_groups").select("is_default").eq(
        "id", group_id
    ).single().execute()

    if group_response.data and group_response.data.get("is_default"):
        raise ValueError("Cannot delete default group")

    _ = supabase.table("access_groups").delete().eq("id", group_id).execute()

    return True


async def get_group_members(group_id: str) -> list[dict[str, Any]]:
    """
    Get all members of a group.
    Returns list of membership objects with user info.
    """
    response = supabase.table("group_memberships").select(
        "*, users(id, email, role)"
    ).eq("group_id", group_id).eq("is_active", True).execute()

    return response.data or []


async def set_group_limit(group_id: str, limit_type: str, limit_value: int) -> bool:
    """
    Set a limit for a group.
    limit_type: 'requests_per_hour', 'requests_per_day', 'tokens_per_request', 'tokens_per_day'
    """
    limit_data = {
        "group_id": group_id,
        "limit_type": limit_type,
        "limit_value": limit_value,
        "updated_at": "now()"
    }

    # Use upsert to update if exists, insert if not
    response = supabase.table("group_limits").upsert(
        limit_data,
        on_conflict="group_id,limit_type"
    ).execute()

    return bool(response.data)


async def get_group_limits(group_id: str) -> list[dict[str, Any]]:
    """
    Get all limits for a group.
    """
    response = supabase.table("group_limits").select("*").eq(
        "group_id", group_id
    ).execute()

    return response.data or []


async def set_group_override(group_id: str, override_type: str, override_value: Any) -> bool:
    """
    Set an override for a group.
    override_type: 'system_prompt', 'temperature', 'max_tokens', 'tool_access'
    override_value: JSON-serializable value
    """
    import json

    override_data = {
        "group_id": group_id,
        "override_type": override_type,
        "override_value": json.loads(json.dumps(override_value)) if not isinstance(override_value, (dict, list, str, int, float, bool)) else override_value,
        "updated_at": "now()"
    }

    # Use upsert to update if exists, insert if not
    response = supabase.table("group_overrides").upsert(
        override_data,
        on_conflict="group_id,override_type"
    ).execute()

    return bool(response.data)


async def get_group_overrides(group_id: str) -> list[dict[str, Any]]:
    """
    Get all overrides for a group.
    """
    response = supabase.table("group_overrides").select("*").eq(
        "group_id", group_id
    ).execute()

    return response.data or []
