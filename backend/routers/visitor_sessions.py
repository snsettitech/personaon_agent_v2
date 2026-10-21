"""
Phase G.3 — Visitor sessions router (owner-only).

Aggregated view of anonymous chats with the owner's twin across surfaces
(widget / public / widget_lead). Pure read endpoints; populated by chat.py
via the visitor_session_recorder service.

Sanitization (CR-6): response Pydantic models are the whitelist. tenant_id,
raw IP addresses, and internal ADK conversation_id are never returned.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from modules.auth_guard import verify_owner, verify_twin_ownership
from modules.observability import supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2/twins", tags=["visitor-sessions"])


# ---------------------------------------------------------------------------
# Response models — explicit whitelist (CR-6 sanitization)
# ---------------------------------------------------------------------------

class VisitorSessionSummary(BaseModel):
    id: str
    visitor_id: str
    surface: str
    contact_id: str | None = None
    message_count: int = 0
    first_message_at: str | None = None
    last_message_at: str | None = None
    visitor_name: str | None = None
    visitor_email: str | None = None
    source_domain: str | None = None


class VisitorMessage(BaseModel):
    id: str
    role: str
    content: str
    created_at: str | None = None


# Only these columns are fetched from Supabase — no tenant_id in SELECT.
_LIST_FIELDS = (
    "id, visitor_id, surface, contact_id, message_count, "
    "first_message_at, last_message_at, visitor_name, visitor_email, source_domain"
)


def _resolve_tenant(user: dict[str, Any]) -> str:
    return str(user.get("tenant_id") or user.get("user_id") or "")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/{twin_id}/visitors")
async def list_visitor_sessions(
    twin_id: str,
    surface: str | None = Query(
        default=None,
        pattern=r"^(widget|public|widget_lead)$",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    """
    List visitor sessions for a twin, newest-first.

    Optional ?surface= filter to narrow to a specific chat surface.
    """
    verify_twin_ownership(twin_id, user)
    tenant_id = _resolve_tenant(user)

    query = (
        supabase.table("visitor_sessions")
        .select(_LIST_FIELDS)
        .eq("twin_id", twin_id)
        .eq("tenant_id", tenant_id)
        .order("last_message_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if surface:
        query = query.eq("surface", surface)

    try:
        resp = query.execute()
    except Exception as exc:
        logger.info("[visitors] list failed twin=%s err=%s", twin_id, type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not load visitors") from exc

    rows = getattr(resp, "data", None) or []
    return {
        "status": "ok",
        "data": {
            "sessions": [VisitorSessionSummary(**r).model_dump() for r in rows],
            "count": len(rows),
        },
    }


@router.get("/{twin_id}/visitors/{session_id}/messages")
async def list_visitor_messages(
    twin_id: str,
    session_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    """
    Fetch chat messages for a visitor session.

    Resolution strategy: the visitor_sessions row holds visitor_id (= session_id
    / conversation_id used during chat). We find all adk_conversations where
    user_id contains visitor_id AND surface matches, then return the messages
    from those conversations. This is a best-effort match — it covers the
    common cases where session_id is used as visitor_id (Phase G.2 wire-in).
    """
    verify_twin_ownership(twin_id, user)
    tenant_id = _resolve_tenant(user)

    # Resolve session → visitor_id + surface (tenant-scoped to prevent cross-tenant reads)
    try:
        sess_resp = (
            supabase.table("visitor_sessions")
            .select("visitor_id, surface")
            .eq("id", session_id)
            .eq("twin_id", twin_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
    except Exception as exc:
        logger.info(
            "[visitors] session fetch failed id=%s err=%s", session_id, type(exc).__name__
        )
        raise HTTPException(status_code=404, detail="Visitor session not found") from exc

    sess = getattr(sess_resp, "data", None)
    if not sess:
        raise HTTPException(status_code=404, detail="Visitor session not found")

    visitor_id = sess["visitor_id"]
    surface = sess["surface"]

    # Best-effort: find adk_conversations where user_id contains the visitor_id
    # and surface matches. This is loose — exact mapping depends on chat.py
    # conventions — but covers the common cases (session_id used as visitor_id,
    # widget:{twin_id}:{visitor_id}, public:{twin_id}:{visitor_id}, etc.).
    try:
        conv_resp = (
            supabase.table("adk_conversations")
            .select("id, user_id, surface")
            .eq("surface", surface)
            .ilike("user_id", f"%{visitor_id}%")
            .limit(20)
            .execute()
        )
        conversation_ids = [r["id"] for r in (getattr(conv_resp, "data", None) or [])]
    except Exception:
        conversation_ids = []

    if not conversation_ids:
        return {"status": "ok", "data": {"messages": [], "count": 0}}

    try:
        msg_resp = (
            supabase.table("adk_messages")
            .select("id, role, content, created_at")
            .in_("conversation_id", conversation_ids)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        rows = getattr(msg_resp, "data", None) or []
    except Exception as exc:
        logger.info(
            "[visitors] messages fetch failed sess=%s err=%s", session_id, type(exc).__name__
        )
        raise HTTPException(status_code=500, detail="Could not load messages") from exc

    return {
        "status": "ok",
        "data": {
            "messages": [VisitorMessage(**r).model_dump() for r in rows],
            "count": len(rows),
        },
    }
