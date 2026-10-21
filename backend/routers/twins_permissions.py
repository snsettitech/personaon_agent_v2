"""Content permission endpoints for twins."""

import logging
from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)
from modules.auth_guard import get_current_user
from modules.schemas import ContentPermissionRequest
from modules.access_groups import (
    add_content_permission, remove_content_permission, get_group_permissions,
)
from routers.twins_helpers import ensure_twin_owner_or_403, _require_authenticated_user


router = APIRouter(tags=["twins"])


# ============================================================================
# Content Permission Endpoints
# ============================================================================


@router.post("/twins/{twin_id}/content/{content_id}/permissions")
async def add_content_permissions(
    twin_id: str,
    content_id: str,
    request: ContentPermissionRequest,
    user=Depends(get_current_user)
):
    """Add content permission for a group."""
    user = _require_authenticated_user(user)
    ensure_twin_owner_or_403(twin_id, user)

    try:
        permission = await add_content_permission(
            content_id=content_id,
            group_id=request.group_id,
            permission_type=request.permission_type,
            config=request.config
        )
        return permission
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TWINS] ERROR adding content permission: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/twins/{twin_id}/content/{content_id}/permissions")
async def get_content_permissions(twin_id: str, content_id: str, user=Depends(get_current_user)):
    """Get permissions for a content item."""
    user = _require_authenticated_user(user)
    ensure_twin_owner_or_403(twin_id, user)

    try:
        permissions = await get_group_permissions(content_id)
        return {"permissions": permissions}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TWINS] ERROR getting content permissions: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/twins/{twin_id}/content/{content_id}/permissions/{permission_id}")
async def remove_content_perm(
    twin_id: str,
    content_id: str,
    permission_id: str,
    user=Depends(get_current_user)
):
    """Remove a content permission."""
    user = _require_authenticated_user(user)
    ensure_twin_owner_or_403(twin_id, user)

    try:
        success = await remove_content_permission(permission_id)
        if not success:
            raise HTTPException(status_code=404, detail="Permission not found")
        return {"status": "removed", "permission_id": permission_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TWINS] ERROR removing content permission: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
