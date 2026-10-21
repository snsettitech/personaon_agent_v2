"""Admin: audit log viewer (reads admin_audit_log)."""
from fastapi import APIRouter, Depends, Query

from modules.auth_guard import require_admin

from ._common import _safe_query, _supabase

router = APIRouter()


@router.get("/audit")
def list_audit(
    action: str | None = Query(default=None),
    actor: str | None = Query(default=None, description="actor_id"),
    limit: int = Query(default=100, le=500),
    user: dict = Depends(require_admin),
) -> list:
    """Recent admin actions, newest first; optional action/actor filters."""
    sb = _supabase()
    query = (
        sb.table("admin_audit_log")
        .select(
            "id, actor_id, actor_email, action, target_type, target_id, "
            "target_email, before, after, created_at"
        )
        .order("created_at", desc=True)
        .limit(limit)
    )
    if action:
        query = query.eq("action", action)
    if actor:
        query = query.eq("actor_id", actor)
    return _safe_query(query)
