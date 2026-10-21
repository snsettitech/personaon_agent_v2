"""Admin Control Center router.

Platform-wide analytics + operator tools for PersonaOn admins, split into
sub-domain modules to stay under the 300-line router limit. Reads require
admin/owner/support role (``require_admin``); mutations require
``require_admin_write`` (owner/admin only).

Preserves the public ``router`` symbol so ``from routers.admin import router`` and
``admin.router`` (routers/__init__.py registration) keep working.

Sub-router include order matters: ``stats`` (static /users/recent, /users/active)
must precede ``users`` (which owns the /users/{user_id} catch-all).
"""
from fastapi import APIRouter

from . import (
    audit,
    cockpit,
    conversations,
    insights,
    moderation,
    notifications,
    ops,
    revenue,
    stats,
    team,
    users,
)

router = APIRouter(prefix="/admin", tags=["admin"])
router.include_router(stats.router)
router.include_router(cockpit.router)
router.include_router(revenue.router)
router.include_router(conversations.router)
router.include_router(insights.router)
router.include_router(users.router)
router.include_router(team.router)
router.include_router(moderation.router)
router.include_router(notifications.router)
router.include_router(audit.router)
router.include_router(ops.router)

__all__ = ["router"]
