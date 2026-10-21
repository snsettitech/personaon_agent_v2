"""Admin: conversation inspection."""
from fastapi import APIRouter, Depends, Query

from modules.auth_guard import require_admin

from ._common import _safe_query, _supabase

router = APIRouter()


@router.get("/conversations/recent")
def get_recent_conversations(
    limit: int = Query(default=50, le=200),
    twin_id: str | None = Query(default=None),
    user: dict = Depends(require_admin),
) -> list:
    """Recent conversations with twin and surface info."""
    sb = _supabase()
    query = (
        sb.table("adk_conversations")
        .select("id, twin_id, user_id, surface, share_token, metadata, created_at, updated_at")
        .order("created_at", desc=True)
        .limit(limit)
    )
    if twin_id:
        query = query.eq("twin_id", twin_id)
    return _safe_query(query)


@router.get("/conversations/{conversation_id}/messages")
def get_conversation_messages(
    conversation_id: str,
    limit: int = Query(default=100, le=500),
    user: dict = Depends(require_admin),
) -> list:
    """All messages in a conversation, chronological order."""
    sb = _supabase()
    rows = _safe_query(
        sb.table("adk_messages")
        .select("id, role, content, citations, created_at")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=True)
        .limit(limit)
    )
    rows.reverse()
    return rows
