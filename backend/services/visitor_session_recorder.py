"""
Phase G.2 — Visitor session recorder.

Upserts a visitor_sessions row for every non-owner chat turn. Idempotent:
unique on (twin_id, visitor_id, surface) — repeated calls with the same key
increment message_count + bump last_message_at.

Called inline from chat.py:_persist_chat_turn AFTER the chat turn is logged to
adk_messages. Failures must NOT 500 the chat surface — wrap in try/except.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from modules.observability import supabase

logger = logging.getLogger(__name__)

# Non-owner surfaces that warrant inbox tracking.
_TRACKED_SURFACES = {"widget", "public", "widget_lead"}


def _resolve_tenant_from_twin(twin_id: str) -> str | None:
    """
    Best-effort lookup of tenant_id from the twins table.

    Used when the calling context (widget/public chat) has no authenticated
    tenant_id. Returns None on any failure — callers must handle gracefully.
    """
    try:
        resp = (
            supabase.table("twins")
            .select("tenant_id")
            .eq("id", twin_id)
            .single()
            .execute()
        )
        row = getattr(resp, "data", None)
        if row:
            return str(row.get("tenant_id") or "")
        return None
    except Exception as exc:
        logger.debug(
            "[visitor_session_recorder] tenant lookup failed twin=%s err=%s",
            twin_id, type(exc).__name__
        )
        return None


def record_visitor_turn(
    *,
    tenant_id: str | None,
    twin_id: str,
    visitor_id: str,
    surface: str,
    visitor_name: str | None = None,
    visitor_email: str | None = None,
    source_domain: str | None = None,
) -> None:
    """
    Upsert one visitor_sessions row for the current chat turn.

    If tenant_id is not provided (e.g. widget/public surface), it is resolved
    from the twins table. This adds one extra DB round-trip but is acceptable
    since this function is called after the chat response is already streamed.

    Never raises — callers (chat.py) treat this as best-effort observability.
    """
    if surface not in _TRACKED_SURFACES:
        return
    if not (twin_id and visitor_id):
        return

    # Resolve tenant_id if not provided (widget / public have no auth context)
    resolved_tenant_id = tenant_id
    if not resolved_tenant_id:
        resolved_tenant_id = _resolve_tenant_from_twin(twin_id)
    if not resolved_tenant_id:
        logger.debug(
            "[visitor_session_recorder] skipping — could not resolve tenant twin=%s",
            twin_id,
        )
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        # Try to find existing row first; if found, update; else insert.
        existing_resp = (
            supabase.table("visitor_sessions")
            .select("id, message_count")
            .eq("twin_id", twin_id)
            .eq("visitor_id", visitor_id)
            .eq("surface", surface)
            .eq("tenant_id", resolved_tenant_id)
            .limit(1)
            .execute()
        )
        existing = (getattr(existing_resp, "data", None) or [None])[0]
        if existing:
            new_count = (existing.get("message_count") or 0) + 1
            update_data: dict[str, Any] = {
                "last_message_at": now_iso,
                "message_count": new_count,
            }
            # Late-arrival visitor metadata: only set if not currently set
            if visitor_name:
                update_data["visitor_name"] = visitor_name
            if visitor_email:
                update_data["visitor_email"] = visitor_email.lower()
            if source_domain:
                update_data["source_domain"] = source_domain
            supabase.table("visitor_sessions").update(update_data).eq(
                "id", existing["id"]
            ).eq("tenant_id", resolved_tenant_id).execute()
        else:
            supabase.table("visitor_sessions").insert({
                "tenant_id": resolved_tenant_id,
                "twin_id": twin_id,
                "visitor_id": visitor_id,
                "surface": surface,
                "first_message_at": now_iso,
                "last_message_at": now_iso,
                "message_count": 1,
                "visitor_name": visitor_name,
                "visitor_email": visitor_email.lower() if visitor_email else None,
                "source_domain": source_domain,
            }).execute()
    except Exception as exc:
        # Best-effort: log and swallow. Chat surface must never 500 over this.
        logger.warning(
            "[visitor_session_recorder] upsert failed twin=%s visitor=%s surface=%s err=%s",
            twin_id, visitor_id, surface, type(exc).__name__
        )
