"""
Dashboard composition endpoints.

Aggregates per-tenant pending counts for the workspace Today screen. Pure
composition — no new schema. The 'to_review' proxy uses recap_edits with
store_routing IS NULL until memory_candidates ships in Phase B.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends

from modules.auth_guard import verify_owner
from modules.observability import supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2/dashboard", tags=["dashboard"])


def _resolve_tenant(user: dict[str, Any]) -> str:
    return str(user.get("tenant_id") or user.get("user_id") or "")


@router.get("/pending")
async def get_pending_counts(
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    """
    Compose pending counts for the workspace Today screen.

    Returns:
      to_review        — recap_edits with store_routing IS NULL (proxy for
                         "memory candidates pending" until Phase B lands).
      follow_ups       — meetings.action_items with due_at set + completed=false
                         (best-effort count from the JSONB array).
      visitor_questions — queued_questions where status='pending'.

    All counts are tenant-scoped (CR-3 invariant).
    """
    tenant_id = _resolve_tenant(user)
    if not tenant_id:
        # No tenant resolved — return zeroed counts rather than failing.
        return {
            "status": "ok",
            "data": {"to_review": 0, "follow_ups": 0, "visitor_questions": 0},
        }

    to_review_count = 0
    follow_ups_count = 0
    visitor_questions_count = 0

    # 1. to_review: recap_edits awaiting classification (store_routing IS NULL)
    try:
        resp = (
            supabase.table("recap_edits")
            .select("id", count="exact")
            .eq("tenant_id", tenant_id)
            .is_("store_routing", "null")
            .limit(1)
            .execute()
        )
        to_review_count = getattr(resp, "count", 0) or 0
    except Exception as exc:
        logger.info("[dashboard/pending] recap_edits count failed: %s", type(exc).__name__)

    # 2. visitor_questions: queued_questions pending
    try:
        resp = (
            supabase.table("queued_questions")
            .select("id", count="exact")
            .eq("tenant_id", tenant_id)
            .eq("status", "pending")
            .limit(1)
            .execute()
        )
        visitor_questions_count = getattr(resp, "count", 0) or 0
    except Exception as exc:
        logger.info(
            "[dashboard/pending] queued_questions count failed: %s", type(exc).__name__
        )

    # 3. follow_ups: action items in meetings with due_at + not completed.
    # Best-effort walk — fetch meetings for the tenant (last 30 days) and walk
    # action_items JSONB in Python. Cheap because meetings is small per-tenant
    # and this endpoint is hit on Today-page load only.
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        resp = (
            supabase.table("meetings")
            .select("action_items")
            .eq("tenant_id", tenant_id)
            .neq("status", "deleted")
            .gte("created_at", since)
            .limit(100)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        for row in rows:
            items = row.get("action_items") or []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                due_at = item.get("due_at")
                completed = item.get("completed")
                if due_at and completed is not True:
                    follow_ups_count += 1
    except Exception as exc:
        logger.info("[dashboard/pending] follow_ups walk failed: %s", type(exc).__name__)

    return {
        "status": "ok",
        "data": {
            "to_review": to_review_count,
            "follow_ups": follow_ups_count,
            "visitor_questions": visitor_questions_count,
        },
    }
