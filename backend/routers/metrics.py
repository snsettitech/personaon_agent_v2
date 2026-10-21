"""Per-twin analytics metrics endpoints.

Provides conversation volume, daily breakdown, and top questions
from the adk_conversations and adk_messages tables.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query

from modules.auth_guard import require_tenant, verify_twin_ownership

logger = logging.getLogger(__name__)
router = APIRouter(tags=["metrics"])


def _get_supabase():
    from modules.observability import get_supabase_client
    return get_supabase_client()


# ---------------------------------------------------------------------------
# GET /metrics/dashboard/{twin_id}
# ---------------------------------------------------------------------------

@router.get("/metrics/dashboard/{twin_id}")
async def get_dashboard_metrics(
    twin_id: str,
    days: int = Query(default=30, le=365),
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """Aggregate metrics for a twin over the given time window."""
    verify_twin_ownership(twin_id, user)
    sb = _get_supabase()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Conversations count
    convos_resp = (
        sb.table("adk_conversations")
        .select("id", count="exact")
        .eq("twin_id", twin_id)
        .gte("created_at", cutoff)
        .execute()
    )
    conversations = convos_resp.count or 0

    # Messages breakdown
    msgs_resp = (
        sb.table("adk_messages")
        .select("role")
        .eq("twin_id", twin_id)
        .gte("created_at", cutoff)
        .execute()
    )
    msgs = msgs_resp.data or []
    total_messages = len(msgs)
    user_messages = sum(1 for m in msgs if m.get("role") == "user")
    assistant_messages = sum(1 for m in msgs if m.get("role") == "assistant")

    # Response rate (assistant messages / user messages)
    response_rate = (assistant_messages / user_messages * 100) if user_messages > 0 else 0

    return {
        "conversations": conversations,
        "messages": total_messages,
        "user_messages": user_messages,
        "assistant_messages": assistant_messages,
        "response_rate": round(response_rate, 1),
        "review_rate": 0,
        "citation_rate": 0,
        "unsupported_rate": 0,
        "answer_mix": {"direct": assistant_messages, "derivable": 0, "insufficient": 0},
    }


# ---------------------------------------------------------------------------
# GET /metrics/daily/{twin_id}
# ---------------------------------------------------------------------------

@router.get("/metrics/daily/{twin_id}")
async def get_daily_metrics(
    twin_id: str,
    days: int = Query(default=30, le=90),
    user: dict = Depends(require_tenant),
) -> list[dict[str, Any]]:
    """Daily conversation and message counts for chart display."""
    verify_twin_ownership(twin_id, user)
    sb = _get_supabase()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Fetch conversations with dates
    convos_resp = (
        sb.table("adk_conversations")
        .select("created_at")
        .eq("twin_id", twin_id)
        .gte("created_at", cutoff)
        .execute()
    )

    # Fetch messages with dates
    msgs_resp = (
        sb.table("adk_messages")
        .select("created_at")
        .eq("twin_id", twin_id)
        .gte("created_at", cutoff)
        .execute()
    )

    # Aggregate by date
    convo_by_day: dict[str, int] = defaultdict(int)
    msg_by_day: dict[str, int] = defaultdict(int)

    for c in (convos_resp.data or []):
        day = c["created_at"][:10]  # YYYY-MM-DD
        convo_by_day[day] += 1

    for m in (msgs_resp.data or []):
        day = m["created_at"][:10]
        msg_by_day[day] += 1

    # Build contiguous day list
    result = []
    today = datetime.now(timezone.utc).date()
    for i in range(days):
        day = (today - timedelta(days=days - 1 - i)).isoformat()
        result.append({
            "date": day,
            "conversations": convo_by_day.get(day, 0),
            "messages": msg_by_day.get(day, 0),
        })

    return result


# ---------------------------------------------------------------------------
# GET /metrics/top-questions/{twin_id}
# ---------------------------------------------------------------------------

@router.get("/metrics/top-questions/{twin_id}")
async def get_top_questions(
    twin_id: str,
    limit: int = Query(default=10, le=30),
    user: dict = Depends(require_tenant),
) -> list[dict[str, Any]]:
    """Most common question themes from visitors.

    Groups similar questions by normalizing text and clustering
    by shared keywords rather than requiring exact matches.
    """
    verify_twin_ownership(twin_id, user)
    sb = _get_supabase()

    # Fetch recent user messages
    msgs_resp = (
        sb.table("adk_messages")
        .select("content, created_at, conversation_id")
        .eq("twin_id", twin_id)
        .eq("role", "user")
        .order("created_at", desc=True)
        .limit(1000)
        .execute()
    )

    messages = msgs_resp.data or []
    if not messages:
        return []

    # Normalize and cluster similar questions
    clusters: dict[str, dict[str, Any]] = {}
    unique_convos: dict[str, set[str]] = defaultdict(set)

    for m in messages:
        raw = (m.get("content") or "").strip()
        if len(raw) < 6:
            continue

        # Normalize: lowercase, strip punctuation, collapse whitespace
        normalized = raw.lower().strip("?!.,;: \n\t")
        # Remove common filler words for clustering key
        filler = {"a", "an", "the", "is", "are", "do", "does", "can", "could",
                  "would", "will", "your", "you", "me", "my", "i", "what",
                  "how", "tell", "about", "please", "hi", "hey", "hello"}
        words = [w for w in normalized.split() if w not in filler and len(w) > 1]
        cluster_key = " ".join(sorted(words[:5]))  # First 5 non-filler words, sorted

        if not cluster_key:
            continue

        convo_id = m.get("conversation_id", "")

        if cluster_key not in clusters:
            clusters[cluster_key] = {
                "representative": raw,  # Keep first (most recent) as display text
                "count": 0,
                "unique_visitors": 0,
                "last_asked": m.get("created_at", ""),
            }
        clusters[cluster_key]["count"] += 1
        if convo_id:
            unique_convos[cluster_key].add(convo_id)

    # Build result sorted by count
    result = []
    for key, data in sorted(clusters.items(), key=lambda x: x[1]["count"], reverse=True)[:limit]:
        result.append({
            "question": data["representative"],
            "count": data["count"],
            "unique_visitors": len(unique_convos.get(key, set())),
            "last_asked": data["last_asked"],
        })

    return result
