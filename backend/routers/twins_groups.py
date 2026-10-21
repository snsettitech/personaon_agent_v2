"""Access group endpoints for twins."""

import logging
from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)
from modules.auth_guard import get_current_user
from modules.schemas import (
    GroupCreateRequest, GroupUpdateRequest,
    AssignUserRequest,
    GroupLimitSchema, GroupOverrideSchema,
)
from modules.access_groups import (
    create_group, assign_user_to_group,
    list_groups, get_group, update_group, delete_group,
    get_group_members, set_group_limit, get_group_limits,
    set_group_override, get_group_overrides,
)
from routers.twins_helpers import ensure_twin_owner_or_403, _require_authenticated_user


router = APIRouter(tags=["twins"])


# ============================================================================
# Access Group Endpoints
# ============================================================================


@router.post("/twins/{twin_id}/groups")
async def create_twin_group(
    twin_id: str,
    request: GroupCreateRequest,
    user=Depends(get_current_user)
):
    """Create a new access group for a twin."""
    user = _require_authenticated_user(user)
    ensure_twin_owner_or_403(twin_id, user)

    try:
        group = await create_group(
            twin_id=twin_id,
            name=request.name,
            description=request.description,
            is_default=request.is_default
        )
        return group
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TWINS] ERROR creating group: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/twins/{twin_id}/groups")
async def list_twin_groups(twin_id: str, user=Depends(get_current_user)):
    """List all access groups for a twin."""
    user = _require_authenticated_user(user)
    ensure_twin_owner_or_403(twin_id, user)

    try:
        groups = await list_groups(twin_id)
        return {"groups": groups}
    except Exception as e:
        logger.error("[TWINS] ERROR listing groups: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/twins/{twin_id}/groups/{group_id}")
async def get_twin_group(twin_id: str, group_id: str, user=Depends(get_current_user)):
    """Get a specific access group."""
    user = _require_authenticated_user(user)
    ensure_twin_owner_or_403(twin_id, user)

    try:
        group = await get_group(group_id)
        if not group or group.get("twin_id") != twin_id:
            raise HTTPException(status_code=404, detail="Group not found")
        return group
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TWINS] ERROR getting group: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/twins/{twin_id}/groups/{group_id}")
async def update_twin_group(
    twin_id: str,
    group_id: str,
    request: GroupUpdateRequest,
    user=Depends(get_current_user)
):
    """Update an access group."""
    user = _require_authenticated_user(user)
    ensure_twin_owner_or_403(twin_id, user)

    try:
        # Verify group belongs to this twin
        group = await get_group(group_id)
        if not group or group.get("twin_id") != twin_id:
            raise HTTPException(status_code=404, detail="Group not found")

        updated = await update_group(
            group_id=group_id,
            name=request.name,
            description=request.description,
            is_default=request.is_default
        )
        return updated
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TWINS] ERROR updating group: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/twins/{twin_id}/groups/{group_id}")
async def delete_twin_group(twin_id: str, group_id: str, user=Depends(get_current_user)):
    """Delete an access group."""
    user = _require_authenticated_user(user)
    ensure_twin_owner_or_403(twin_id, user)

    try:
        # Verify group belongs to this twin
        group = await get_group(group_id)
        if not group or group.get("twin_id") != twin_id:
            raise HTTPException(status_code=404, detail="Group not found")

        success = await delete_group(group_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete group")

        return {"status": "deleted", "group_id": group_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TWINS] ERROR deleting group: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/twins/{twin_id}/groups/{group_id}/assign")
async def assign_user_to_twin_group(
    twin_id: str,
    group_id: str,
    request: AssignUserRequest,
    user=Depends(get_current_user)
):
    """Assign a user to an access group."""
    user = _require_authenticated_user(user)
    ensure_twin_owner_or_403(twin_id, user)

    try:
        # Verify group belongs to this twin
        group = await get_group(group_id)
        if not group or group.get("twin_id") != twin_id:
            raise HTTPException(status_code=404, detail="Group not found")

        membership = await assign_user_to_group(
            group_id=group_id,
            user_id=request.user_id,
            role=request.role,
            permissions=request.permissions
        )
        return membership
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TWINS] ERROR assigning user to group: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/twins/{twin_id}/groups/{group_id}/members")
async def get_group_members_list(twin_id: str, group_id: str, user=Depends(get_current_user)):
    """Get members of an access group."""
    user = _require_authenticated_user(user)
    ensure_twin_owner_or_403(twin_id, user)

    try:
        # Verify group belongs to this twin
        group = await get_group(group_id)
        if not group or group.get("twin_id") != twin_id:
            raise HTTPException(status_code=404, detail="Group not found")

        members = await get_group_members(group_id)
        return {"members": members}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TWINS] ERROR getting group members: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Group Limits Endpoints
# ============================================================================


@router.post("/twins/{twin_id}/groups/{group_id}/limits")
async def set_group_limit_endpoint(
    twin_id: str,
    group_id: str,
    request: GroupLimitSchema,
    user=Depends(get_current_user)
):
    """Set rate and token limits for a group."""
    user = _require_authenticated_user(user)
    ensure_twin_owner_or_403(twin_id, user)

    try:
        # Verify group belongs to this twin
        group = await get_group(group_id)
        if not group or group.get("twin_id") != twin_id:
            raise HTTPException(status_code=404, detail="Group not found")

        limit = await set_group_limit(
            group_id=group_id,
            rate_limit=request.rate_limit,
            token_limit=request.token_limit,
            reset_period=request.reset_period
        )
        return limit
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TWINS] ERROR setting group limit: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/twins/{twin_id}/groups/{group_id}/limits")
async def get_group_limit_endpoint(twin_id: str, group_id: str, user=Depends(get_current_user)):
    """Get rate and token limits for a group."""
    user = _require_authenticated_user(user)
    ensure_twin_owner_or_403(twin_id, user)

    try:
        # Verify group belongs to this twin
        group = await get_group(group_id)
        if not group or group.get("twin_id") != twin_id:
            raise HTTPException(status_code=404, detail="Group not found")

        limits = await get_group_limits(group_id)
        return {"limits": limits}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TWINS] ERROR getting group limits: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/twins/{twin_id}/groups/{group_id}/overrides")
async def set_group_override_endpoint(
    twin_id: str,
    group_id: str,
    request: GroupOverrideSchema,
    user=Depends(get_current_user)
):
    """Set model override for a group."""
    user = _require_authenticated_user(user)
    ensure_twin_owner_or_403(twin_id, user)

    try:
        # Verify group belongs to this twin
        group = await get_group(group_id)
        if not group or group.get("twin_id") != twin_id:
            raise HTTPException(status_code=404, detail="Group not found")

        override = await set_group_override(
            group_id=group_id,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens
        )
        return override
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TWINS] ERROR setting group override: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/twins/{twin_id}/groups/{group_id}/overrides")
async def get_group_override_endpoint(twin_id: str, group_id: str, user=Depends(get_current_user)):
    """Get model override for a group."""
    user = _require_authenticated_user(user)
    ensure_twin_owner_or_403(twin_id, user)

    try:
        # Verify group belongs to this twin
        group = await get_group(group_id)
        if not group or group.get("twin_id") != twin_id:
            raise HTTPException(status_code=404, detail="Group not found")

        overrides = await get_group_overrides(group_id)
        return {"overrides": overrides}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TWINS] ERROR getting group overrides: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
