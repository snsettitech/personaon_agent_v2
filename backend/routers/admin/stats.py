"""Admin: platform overview + user / twin / research listings."""
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query

from modules.auth_guard import require_admin

from ._common import _safe_count, _safe_query, _supabase

router = APIRouter()


@router.get("/stats/overview")
def get_overview_stats(user: dict = Depends(require_admin)) -> dict[str, Any]:
    """High-level platform stats: users, twins, conversations, messages."""
    sb = _supabase()
    users_result = sb.table("users").select("id", count="exact").limit(0).execute()
    total_users = users_result.count or 0
    twins_active = _safe_count("twins", {"is_active": True})
    twins_total = _safe_count("twins")
    convos_total = _safe_count("adk_conversations")
    msgs_total = _safe_count("adk_messages")
    research_total = _safe_count("name_deep_research_runs")
    return {
        "total_users": total_users,
        "total_twins": twins_total,
        "active_twins": twins_active,
        "total_conversations": convos_total,
        "total_messages": msgs_total,
        "total_research_runs": research_total,
    }


@router.get("/users/recent")
def get_recent_users(
    limit: int = Query(default=50, le=200),
    user: dict = Depends(require_admin),
) -> list:
    """Recent user signups with their twin count and last activity."""
    sb = _supabase()
    return _safe_query(
        sb.table("users")
        .select("id, email, full_name, role, created_at, last_active_at")
        .order("created_at", desc=True)
        .limit(limit)
    )


@router.get("/users/active")
def get_active_users(
    days: int = Query(default=7, le=90),
    limit: int = Query(default=50, le=200),
    user: dict = Depends(require_admin),
) -> list:
    """Users active in the last N days, sorted by most recent activity."""
    sb = _supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return _safe_query(
        sb.table("users")
        .select("id, email, full_name, role, last_active_at, created_at")
        .gte("last_active_at", cutoff)
        .order("last_active_at", desc=True)
        .limit(limit)
    )


@router.get("/twins/list")
def get_twins_list(
    limit: int = Query(default=50, le=200),
    status_filter: str | None = Query(default=None, alias="status"),
    user: dict = Depends(require_admin),
) -> list:
    """All twins with owner info, status, and activity metrics."""
    sb = _supabase()
    query = (
        sb.table("twins")
        .select("id, tenant_id, name, status, creation_mode, is_active, created_at, updated_at")
        .order("created_at", desc=True)
        .limit(limit)
    )
    if status_filter:
        query = query.eq("status", status_filter)
    return _safe_query(query)


@router.get("/research/runs")
def get_research_runs(
    limit: int = Query(default=50, le=200),
    user: dict = Depends(require_admin),
) -> list:
    """All research runs with status and timing."""
    sb = _supabase()
    return _safe_query(
        sb.table("name_deep_research_runs")
        .select("id, tenant_id, user_id, subject_name, status, twin_id, created_at, updated_at")
        .order("created_at", desc=True)
        .limit(limit)
    )
