"""Persona Score endpoint — measures persona completeness."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from modules.auth_guard import require_tenant, verify_twin_ownership
from modules.observability import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["persona-score"])

# ── Score thresholds ────────────────────────────────────────────────

_LABELS = [
    (0, 15, "Early"),
    (15, 35, "Growing"),
    (35, 55, "Developing"),
    (55, 75, "Strong"),
    (75, 90, "Highly Trained"),
    (90, 101, "Expert"),
]


def _label_for(score: int) -> str:
    for low, high, label in _LABELS:
        if low <= score < high:
            return label
    return "Unknown"


# ── Profile completeness ────────────────────────────────────────────

def _score_profile(settings: dict) -> dict[str, Any]:
    """Score profile field completeness (max 25 points)."""
    profile = settings.get("persona_profile") or {}
    if isinstance(profile, str):
        import json
        try:
            profile = json.loads(profile)
        except (ValueError, TypeError):
            profile = {}

    checks = {
        "name": bool(profile.get("name")),
        "occupation": bool(profile.get("occupation")),
        "education": bool(profile.get("education")),
        "work_experience": bool(profile.get("work_experience")),
        "achievements": bool(profile.get("achievements")),
    }
    points = sum(5 for v in checks.values() if v)
    filled = sum(1 for v in checks.values() if v)
    total = len(checks)

    if filled == total:
        status = "complete"
        hint = None
    elif filled == 0:
        status = "empty"
        hint = "Run persona extraction to populate your profile"
    else:
        missing = [k.replace("_", " ") for k, v in checks.items() if not v]
        status = "partial"
        hint = f"Missing: {', '.join(missing)}"

    return {"score": points, "max": 25, "status": status, "hint": hint, "fields": checks}


# ── Knowledge depth ─────────────────────────────────────────────────

async def _score_knowledge(twin_id: str) -> dict[str, Any]:
    """Score knowledge base depth from pgvector vectors (max 35 points)."""
    try:
        from adk_core.services.vector_store import namespace_stats
        stats = await namespace_stats(twin_id)
        count = stats.get("vector_count", 0)
    except Exception as exc:
        logger.warning("Failed to get pgvector stats for %s: %s", twin_id, exc)
        count = 0

    points = 0
    if count > 0:
        points += 10
    if count > 10:
        points += 5
    if count > 25:
        points += 5
    if count > 50:
        points += 5
    # FAQ and document bonuses would need source-type filtering
    # For now, give partial credit based on total count
    if count > 5:
        points += 5  # likely has FAQ or doc entries
    if count > 15:
        points += 5

    if count == 0:
        status = "empty"
        hint = "Upload documents or do an interview to build knowledge"
    elif count < 20:
        status = "growing"
        hint = "Upload more documents to strengthen your persona"
    elif count < 50:
        status = "good"
        hint = "Keep adding knowledge for deeper expertise"
    else:
        status = "strong"
        hint = None

    return {"score": points, "max": 35, "status": status, "hint": hint, "vector_count": count}


# ── Interview coverage ──────────────────────────────────────────────

def _score_interview(twin_id: str) -> dict[str, Any]:
    """Score interview coverage from FAQ-type entries (max 25 points)."""
    # Count conversations with this twin to estimate interview coverage
    try:
        sb = get_supabase_client()
        resp = sb.table("adk_messages").select(
            "id", count="exact"
        ).eq("twin_id", twin_id).eq("role", "user").execute()
        msg_count = resp.count or 0
    except Exception:
        msg_count = 0

    points = 0
    if msg_count >= 1:
        points += 10
    if msg_count >= 5:
        points += 5
    if msg_count >= 10:
        points += 5
    if msg_count >= 20:
        points += 5

    if msg_count == 0:
        status = "not_started"
        hint = "Start an interview to teach your persona how you think"
    elif msg_count < 10:
        status = "started"
        hint = f"{msg_count} exchanges — answer more questions to improve"
    elif msg_count < 20:
        status = "growing"
        hint = f"{msg_count} exchanges — keep going for expert coverage"
    else:
        status = "strong"
        hint = None

    return {"score": points, "max": 25, "status": status, "hint": hint, "exchange_count": msg_count}


# ── Voice ───────────────────────────────────────────────────────────

def _score_voice(settings: dict) -> dict[str, Any]:
    """Score voice clone status (max 15 points)."""
    voice_id = settings.get("voice_id")
    if voice_id:
        return {"score": 15, "max": 15, "status": "cloned", "hint": None}
    return {"score": 0, "max": 15, "status": "missing", "hint": "Clone your voice in Studio"}


# ── Main endpoint ───────────────────────────────────────────────────

@router.get("/v2/twins/{twin_id}/score")
async def get_persona_score(
    twin_id: str,
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """Calculate persona completeness score with actionable breakdown."""
    verify_twin_ownership(twin_id, user)

    # Load twin settings
    sb = get_supabase_client()
    resp = sb.table("twins").select("id, name, settings").eq("id", twin_id).single().execute()
    if not resp.data:
        return {"score": 0, "label": "Unknown", "breakdown": {}}

    settings = resp.data.get("settings") or {}

    # Calculate each dimension
    profile = _score_profile(settings)
    knowledge = await _score_knowledge(twin_id)
    interview = _score_interview(twin_id)
    voice = _score_voice(settings)

    total = profile["score"] + knowledge["score"] + interview["score"] + voice["score"]
    label = _label_for(total)

    return {
        "score": total,
        "max": 100,
        "label": label,
        "breakdown": {
            "profile": profile,
            "knowledge": knowledge,
            "interview": interview,
            "voice": voice,
        },
    }
