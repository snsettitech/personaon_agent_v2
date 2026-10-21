"""Persona Readiness endpoint — outcome-based replacement for persona_score.

See docs/superpowers/specs/2026-05-30-persona-readiness-algorithm-design.md.

Unlike the volume-based /score, readiness measures whether the persona can
actually answer the questions people ask, grounded in diverse + fresh sources:

    identity (20) + coverage (40) + answerability (30) + freshness (10)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends

from modules.auth_guard import require_tenant, verify_twin_ownership
from modules.observability import get_supabase_client
from routers.sources import _infer_source_type

logger = logging.getLogger(__name__)

router = APIRouter(tags=["persona-readiness"])

# Cosine-similarity floor for "this question is answerable". Tune from data.
_ANSWERABLE_TAU = 0.35
# Cap the question set so page-load retrieval stays cheap.
_MAX_QUESTIONS = 6

_LABELS = [
    (0, 25, "Needs setup"),
    (25, 45, "Getting useful"),
    (45, 65, "Reliable"),
    (65, 85, "Sharp"),
    (85, 101, "Expert"),
]


def _label_for(score: int) -> str:
    for low, high, label in _LABELS:
        if low <= score < high:
            return label
    return "Needs setup"


def _coerce_profile(settings: dict) -> dict:
    profile = settings.get("persona_profile") or {}
    if isinstance(profile, str):
        try:
            profile = json.loads(profile)
        except (ValueError, TypeError):
            profile = {}
    return profile if isinstance(profile, dict) else {}


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


# ── 1. Identity (20) ─────────────────────────────────────────────────

def _score_identity(settings: dict) -> dict[str, Any]:
    profile = _coerce_profile(settings)
    bio = str(profile.get("bio") or "").strip()
    headline = profile.get("short_description") or profile.get("headline")
    expertise = profile.get("areas_of_expertise") or []

    weighted = {
        "name": (3, bool(profile.get("name"))),
        "occupation": (4, bool(profile.get("occupation"))),
        "headline": (4, bool(headline)),
        "areas_of_expertise": (5, isinstance(expertise, list) and len(expertise) > 0),
        "bio": (4, len(bio) >= 80),
    }
    points = sum(pts for pts, ok in weighted.values() if ok)
    fields = {key: ok for key, (_, ok) in weighted.items()}
    missing = [key.replace("_", " ") for key, ok in fields.items() if not ok]

    if points >= 20:
        status, hint, cta = "complete", None, None
    elif points == 0:
        status = "empty"
        hint = "Run persona enrichment to populate your identity"
        cta = "Re-run enrichment"
    else:
        status = "partial"
        hint = f"Missing: {', '.join(missing)}"
        cta = "Add a bio" if not fields["bio"] else "Re-run enrichment"

    return {"score": points, "max": 20, "status": status, "hint": hint, "cta": cta, "fields": fields}


# ── 2. Knowledge coverage (40) ───────────────────────────────────────

def _distinct_source_types(twin_id: str) -> list[str]:
    """Live, non-deleted source types (excludes the always-present profile)."""
    sb = get_supabase_client()
    try:
        resp = (
            sb.table("sources")
            .select("filename, citation_url, status")
            .eq("twin_id", twin_id)
            .neq("status", "deleted")
            .execute()
        )
    except Exception as exc:
        logger.warning("[Readiness] source listing failed twin=%s: %s", twin_id, exc)
        return []
    types: set[str] = set()
    for row in resp.data or []:
        types.add(_infer_source_type(row))
    # Meetings live in desktop_recordings, not sources.
    if _has_completed_meeting(twin_id):
        types.add("meeting")
    types.discard("profile")
    return sorted(types)


def _has_completed_meeting(twin_id: str) -> bool:
    sb = get_supabase_client()
    try:
        resp = (
            sb.table("desktop_recordings")
            .select("id")
            .eq("twin_id", twin_id)
            .eq("status", "completed")
            .limit(1)
            .execute()
        )
        return bool(resp.data)
    except Exception:
        return False


async def _score_coverage(twin_id: str) -> dict[str, Any]:
    try:
        from adk_core.services.vector_store import namespace_stats
        stats = await namespace_stats(twin_id)
        chunk_count = int(stats.get("vector_count", 0) or 0)
    except Exception as exc:
        logger.warning("[Readiness] namespace_stats failed twin=%s: %s", twin_id, exc)
        chunk_count = 0

    source_types = await asyncio.to_thread(_distinct_source_types, twin_id)
    breadth = 8 * min(len(source_types), 3)
    depth = min(16, round(4 * math.log2(1 + chunk_count))) if chunk_count > 0 else 0
    points = min(40, breadth + depth)

    if chunk_count == 0:
        status, hint = "empty", "Upload a resource or connect an integration to start"
    elif len(source_types) <= 1:
        status, hint = "growing", "Add a different kind of source to broaden coverage"
    elif points < 30:
        status, hint = "good", "Keep adding sources for deeper coverage"
    else:
        status, hint = "strong", None

    return {
        "score": points,
        "max": 40,
        "status": status,
        "hint": hint,
        "cta": "Add a resource or connect an integration" if status != "strong" else None,
        "source_types": source_types,
        "chunk_count": chunk_count,
    }


# ── 3. Answerability (30) ────────────────────────────────────────────

def _question_set(twin_id: str, settings: dict) -> list[str]:
    profile = _coerce_profile(settings)
    questions: list[str] = []
    seen: set[str] = set()

    def _add(raw: Any) -> None:
        text = str(raw or "").strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            questions.append(text)

    for q in profile.get("pinned_questions") or []:
        _add(q)

    sb = get_supabase_client()
    try:
        resp = (
            sb.table("queued_questions")
            .select("question")
            .eq("twin_id", twin_id)
            .order("ask_count", desc=True)
            .order("created_at", desc=True)
            .limit(_MAX_QUESTIONS)
            .execute()
        )
        for row in resp.data or []:
            _add(row.get("question"))
    except Exception as exc:
        logger.warning("[Readiness] queued_questions failed twin=%s: %s", twin_id, exc)

    return questions[:_MAX_QUESTIONS]


async def _score_answerability(twin_id: str, settings: dict, chunk_count: int) -> dict[str, Any]:
    questions = await asyncio.to_thread(_question_set, twin_id, settings)

    if not questions:
        # No real questions yet — can't claim an outcome. Cap the proxy at half.
        proxy = min(15, round(30 * min(1.0, chunk_count / 12)))
        return {
            "score": proxy,
            "max": 30,
            "status": "unmeasured" if chunk_count else "empty",
            "hint": "Pin a question on your /p page so we can measure answerability",
            "cta": "Pin a question",
            "asked": 0,
            "answerable": 0,
            "sampled_questions": [],
        }

    from adk_core.services.vector_store import search

    async def _probe(q: str) -> dict[str, Any]:
        try:
            hits = await search(q, twin_id, top_k=1)
            score = float(hits[0]["score"]) if hits else 0.0
        except Exception as exc:
            logger.warning("[Readiness] retrieval failed q=%r twin=%s: %s", q[:60], twin_id, exc)
            score = 0.0
        return {"question": q, "score": round(score, 3), "answerable": score >= _ANSWERABLE_TAU}

    sampled = await asyncio.gather(*[_probe(q) for q in questions])
    answerable = sum(1 for s in sampled if s["answerable"])
    asked = len(sampled)
    points = round(30 * (answerable / asked)) if asked else 0

    if answerable == asked:
        status, hint, cta = "strong", None, None
    elif answerable == 0:
        status = "empty"
        hint = "Your persona can't answer its own pinned questions yet"
        cta = "Add knowledge that answers these"
    else:
        gap = asked - answerable
        status = "partial"
        hint = f"{gap} of {asked} common question{'s' if gap != 1 else ''} have no good answer yet"
        cta = "Add knowledge that answers these"

    return {
        "score": points,
        "max": 30,
        "status": status,
        "hint": hint,
        "cta": cta,
        "asked": asked,
        "answerable": answerable,
        "sampled_questions": sampled,
    }


# ── 4. Freshness (10) ────────────────────────────────────────────────

def _newest_source_at(twin_id: str) -> datetime | None:
    sb = get_supabase_client()
    newest: datetime | None = None
    for table, status_filter in (("sources", "live"), ("desktop_recordings", "completed")):
        try:
            resp = (
                sb.table(table)
                .select("created_at")
                .eq("twin_id", twin_id)
                .eq("status", status_filter)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if resp.data:
                ts = _parse_ts(resp.data[0].get("created_at"))
                if ts and (newest is None or ts > newest):
                    newest = ts
        except Exception:
            continue
    return newest


def _score_freshness(twin_id: str, chunk_count: int) -> dict[str, Any]:
    newest = _newest_source_at(twin_id)
    if newest is None:
        points = 0 if chunk_count == 0 else 1
        age_days = None
    else:
        age_days = (datetime.now(timezone.utc) - newest).days
        if age_days <= 30:
            points = 10
        elif age_days <= 90:
            points = 6
        elif age_days <= 180:
            points = 3
        else:
            points = 1

    if points >= 10:
        status, hint, cta = "fresh", None, None
    elif points == 0:
        status, hint, cta = "empty", "No knowledge yet", "Add a resource"
    else:
        status = "stale"
        hint = "Your newest knowledge is getting old"
        cta = "Record a meeting or add a recent source"

    return {
        "score": points,
        "max": 10,
        "status": status,
        "hint": hint,
        "cta": cta,
        "newest_source_at": newest.isoformat() if newest else None,
        "age_days": age_days,
    }


# ── Endpoint ─────────────────────────────────────────────────────────

@router.get("/v2/twins/{twin_id}/readiness")
async def get_persona_readiness(
    twin_id: str,
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """Outcome-based persona readiness with per-dimension next-best-actions."""
    verify_twin_ownership(twin_id, user)

    sb = get_supabase_client()
    # maybe_single (not single): a missing twin returns data=None -> clean default,
    # rather than PGRST116 raising into a 500.
    resp = (
        sb.table("twins")
        .select("id, settings")
        .eq("id", twin_id)
        .maybe_single()
        .execute()
    )
    settings = (resp.data or {}).get("settings") if resp else None
    settings = settings or {}

    identity = _score_identity(settings)
    coverage = await _score_coverage(twin_id)
    chunk_count = coverage["chunk_count"]
    answerability = await _score_answerability(twin_id, settings, chunk_count)
    freshness = await asyncio.to_thread(_score_freshness, twin_id, chunk_count)

    total = identity["score"] + coverage["score"] + answerability["score"] + freshness["score"]

    return {
        "score": total,
        "max": 100,
        "label": _label_for(total),
        "version": "readiness_v1",
        "dimensions": {
            "identity": identity,
            "coverage": coverage,
            "answerability": answerability,
            "freshness": freshness,
        },
    }
