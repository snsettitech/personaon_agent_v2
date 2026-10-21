"""
Public Profile Router

Public-safe profile data for share pages and the public marketplace.
Never returns private claims, unverified claims, or sensitive data.
"""

from collections import Counter, defaultdict
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from typing import Any
import logging

from modules.observability import supabase
from modules.public_profile_pack import (
    build_marketplace_persona_payload,
    build_public_profile_pack,
    redact_public_profile_pack_for_public_response,
)
from modules.share_links import (
    build_public_share_path,
    is_marketplace_public_twin_record,
    is_publicly_accessible_twin_record,
    validate_share_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["profile-public"])


def _missing_column_error(exc: Exception, column_name: str) -> bool:
    message = str(exc).lower()
    return column_name in message and (
        "does not exist" in message
        or "could not find" in message
        or "pgrst204" in message
    )


def _fetch_public_twin(twin_id: str) -> dict[str, Any] | None:
    result = (
        supabase.table("twins")
        .select("id, name, settings, status")
        .eq("id", twin_id)
        .single()
        .execute()
    )
    return result.data or None


def _fetch_marketplace_twin_rows() -> list[dict[str, Any]]:
    result = (
        supabase.table("twins")
        .select("id, name, settings, status, created_at")
        .execute()
    )
    return result.data or []


def _normalize_public_profile(twin: dict[str, Any]) -> dict[str, Any]:
    settings = twin.get("settings") or {}
    if not isinstance(settings, dict):
        settings = {}
    public_profile = settings.get("public_profile") or {}
    if not isinstance(public_profile, dict):
        public_profile = {}

    # Fall back to persona_profile (Firecrawl agent output) for fields not in public_profile
    persona_profile = settings.get("persona_profile") or {}
    if isinstance(persona_profile, str):
        import json as _json
        try:
            persona_profile = _json.loads(persona_profile)
        except (ValueError, TypeError):
            persona_profile = {}

    def _get(field: str, *alt_fields: str) -> str:
        """Get first non-empty value from public_profile, then persona_profile."""
        val = str(public_profile.get(field) or "").strip()
        if val:
            return val
        for alt in alt_fields:
            val = str(persona_profile.get(alt) or "").strip()
            if val:
                return val
        val = str(persona_profile.get(field) or "").strip()
        return val

    tagline = settings.get("tagline") if isinstance(settings.get("tagline"), str) else ""
    public_intro = settings.get("public_intro") if isinstance(settings.get("public_intro"), str) else ""
    display_name = (
        _get("display_name", "name")
        or str(twin.get("name") or "").strip()
        or "Persona"
    )
    organization = _get("organization")
    role = _get("role", "occupation")
    headline = _get("headline") or tagline or _get("short_description")
    bio = _get("bio") or public_intro or _get("short_description")
    avatar_url = _get("avatar_url", "image_url")
    mind_label = _get("mind_label")
    pinned = public_profile.get("pinned_questions") if isinstance(public_profile.get("pinned_questions"), list) else []
    pinned_questions = [
        str(item).strip()
        for item in pinned
        if isinstance(item, str) and str(item).strip()
    ][:3]

    return {
        "display_name": display_name,
        "organization": organization,
        "role": role,
        "headline": headline,
        "bio": bio,
        "avatar_url": avatar_url,
        "mind_label": mind_label,
        "pinned_questions": pinned_questions,
        "handle": str(settings.get("handle") or "").strip(),
        "settings": settings,
        "persona_profile": persona_profile,
    }


def _coerce_score(value: Any) -> float:
    try:
        score = float(value or 0)
        if score <= 1.0:
            score *= 100.0
        return max(0.0, min(score, 100.0))
    except Exception:
        return 0.0


def _marketplace_search_blob(item: dict[str, Any]) -> str:
    topic_names = " ".join(
        f"{topic.get('name', '')} {topic.get('slug', '')}".strip()
        for topic in item.get("public_topics", [])
    )
    expertise = " ".join(str(value or "") for value in item.get("areas_of_expertise", []))
    return " ".join(
        [
            str(item.get("display_name") or ""),
            str(item.get("occupation") or ""),
            str(item.get("headline") or ""),
            str(item.get("bio") or ""),
            str(item.get("short_description") or ""),
            str(item.get("organization") or ""),
            str(item.get("role") or ""),
            str(item.get("handle") or ""),
            expertise,
            topic_names,
        ]
    ).lower()


def _get_score_rows(twin_ids: list[str]) -> dict[str, float]:
    if not twin_ids:
        return {}
    try:
        result = (
            supabase.table("person_answerability_scores")
            .select("twin_id, answerability_score")
            .in_("twin_id", twin_ids)
            .eq("scope_type", "global")
            .eq("scope_key", "global")
            .execute()
        )
        return {
            row.get("twin_id"): _coerce_score(row.get("answerability_score"))
            for row in (result.data or [])
            if row.get("twin_id")
        }
    except Exception as exc:
        logger.warning("Error fetching marketplace answerability scores: %s", exc)
        return {}


def _get_public_topics(twin_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not twin_ids:
        return {}
    result = None
    slug_key = "slug"
    name_key = "name"
    topic_select_variants = [
        ("twin_id, slug, name, answerability_score", "slug", "name"),
        ("twin_id, topic_slug, name, answerability_score", "topic_slug", "name"),
        ("twin_id, topic_slug, topic_name, answerability_score", "topic_slug", "topic_name"),
    ]

    last_exc: Exception | None = None
    for select_clause, slug_key, name_key in topic_select_variants:
        try:
            result = (
                supabase.table("person_topic_profiles")
                .select(select_clause)
                .in_("twin_id", twin_ids)
                .gte("answerability_score", 60)
                .order("answerability_score", desc=True)
                .execute()
            )
            break
        except Exception as exc:
            last_exc = exc
            if not any(
                _missing_column_error(exc, column_name)
                for column_name in ("slug", "topic_slug", "name", "topic_name")
            ):
                logger.warning("Error fetching marketplace public topics: %s", exc)
                return {}

    if result is None:
        if last_exc:
            logger.warning("Error fetching marketplace public topics: %s", last_exc)
        return {}

    topics: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in result.data or []:
        twin_id = row.get("twin_id")
        if not twin_id:
            continue
        topics[twin_id].append(
            {
                "slug": row.get(slug_key) or row.get("slug") or row.get("topic_slug"),
                "name": row.get(name_key) or row.get("name") or row.get("topic_name") or row.get(slug_key),
                "answerability_score": _coerce_score(row.get("answerability_score")),
            }
        )
    return topics


def _get_verified_claim_counts(twin_ids: list[str]) -> dict[str, int]:
    if not twin_ids:
        return {}
    try:
        result = (
            supabase.table("person_claims")
            .select("twin_id")
            .in_("twin_id", twin_ids)
            .eq("verification_status", "verified")
            .eq("public_visibility", "public")
            .execute()
        )
    except Exception as exc:
        logger.warning("Error fetching marketplace verified claim counts: %s", exc)
        return {}

    counts: dict[str, int] = Counter()
    for row in result.data or []:
        twin_id = row.get("twin_id")
        if twin_id:
            counts[twin_id] += 1
    return dict(counts)


@router.get("/public/marketplace")
async def get_public_marketplace(
    q: str = Query("", max_length=200),
    topic: str | None = Query(None, max_length=120),
    cursor: str | None = Query(None),
    limit: int = Query(24, ge=1, le=60),
):
    """
    Public marketplace listing of eligible personas across all tenants.

    V1 treats every non-archived active/persona_built twin as publicly
    discoverable, regardless of the legacy direct-share toggle.
    """
    twin_rows = [row for row in _fetch_marketplace_twin_rows() if is_marketplace_public_twin_record(row)]
    twin_ids = [row.get("id") for row in twin_rows if row.get("id")]

    score_map = _get_score_rows(twin_ids)
    topics_map = _get_public_topics(twin_ids)
    claims_map = _get_verified_claim_counts(twin_ids)

    items: list[dict[str, Any]] = []
    normalized_query = q.strip().lower()
    normalized_topic = topic.strip().lower() if isinstance(topic, str) and topic.strip() else None

    for twin in twin_rows:
        twin_id = twin.get("id")
        if not twin_id:
            continue

        public_topics = topics_map.get(twin_id, [])[:6]
        item = build_marketplace_persona_payload(
            twin,
            public_topics=public_topics,
            answerability_score=score_map.get(twin_id, 0.0),
            verified_claims_count=claims_map.get(twin_id, 0),
        )
        item["updated_at"] = twin.get("updated_at") or twin.get("created_at") or ""
        item["settings"] = _normalize_public_profile(twin)["settings"]

        if normalized_topic:
            topic_slugs = {str(entry.get("slug") or "").lower() for entry in public_topics}
            if normalized_topic not in topic_slugs:
                continue

        if normalized_query and normalized_query not in _marketplace_search_blob(item):
            continue

        items.append(item)

    items.sort(
        key=lambda row: (
            float(row.get("answerability_score") or 0.0),
            int(row.get("verified_claims_count") or 0),
            str(row.get("updated_at") or ""),
        ),
        reverse=True,
    )

    topic_counter: Counter = Counter()
    topic_labels: dict[str, str] = {}
    for item in items:
        for topic_entry in item.get("public_topics", []):
            slug = str(topic_entry.get("slug") or "").strip().lower()
            name = str(topic_entry.get("name") or "").strip() or slug
            if not slug:
                continue
            topic_counter[slug] += 1
            topic_labels[slug] = name

    try:
        offset = max(int(cursor or "0"), 0)
    except ValueError:
        offset = 0

    page_items = items[offset : offset + limit]
    next_cursor = str(offset + limit) if offset + limit < len(items) else None

    for item in page_items:
        public_url = build_public_share_path(
            item["twin_id"],
            item.get("settings"),
            ensure_token_if_missing=True,
            enable_public_share=False,
        )
        item["public_url"] = public_url
        item.pop("settings", None)
        item.pop("updated_at", None)

    return {
        "items": page_items,
        "facets": {
            "topics": [
                {"slug": slug, "name": topic_labels.get(slug, slug), "count": count}
                for slug, count in topic_counter.most_common(12)
            ]
        },
        "next_cursor": next_cursor,
    }


# ---------------------------------------------------------------------------
# "Ask the Marketplace" — semantic cross-twin search
# ---------------------------------------------------------------------------


class MarketplaceAskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)
    limit: int = Field(10, ge=1, le=30)


class _AskResultPersona(BaseModel):
    twin_id: str
    display_name: str
    occupation: str
    headline: str
    avatar_url: str
    verified_profile: bool
    public_url: str | None = None


class _AskResultItem(BaseModel):
    persona: _AskResultPersona
    snippet: str
    relevance: float


class MarketplaceAskResponse(BaseModel):
    results: list[_AskResultItem]
    query: str


def _truncate_snippet(text: str, max_sentences: int = 2) -> str:
    """Extract the first N sentences from a chunk for a clean preview."""
    if not text:
        return ""
    # Strip markdown artifacts
    cleaned = text.replace("**", "").replace("##", "").strip()
    sentences: list[str] = []
    for part in cleaned.replace("? ", "?|").replace(". ", ".|").replace("! ", "!|").split("|"):
        stripped = part.strip()
        if stripped:
            sentences.append(stripped)
        if len(sentences) >= max_sentences:
            break
    return " ".join(sentences)[:300]


@router.post("/public/marketplace/ask")
async def ask_marketplace(body: MarketplaceAskRequest):
    """
    Semantic search across all public personas' knowledge.

    Takes a natural-language question, embeds it, searches all public twins'
    vector chunks via pgvector LATERAL join, groups by twin, enriches with
    persona metadata, and returns ranked results with answer preview snippets.
    """
    from adk_core.services.vector_store import search_global

    # Step 1: Get eligible public twins (same filter as browse marketplace)
    twin_rows = [
        row for row in _fetch_marketplace_twin_rows()
        if is_marketplace_public_twin_record(row)
    ]
    twin_map: dict[str, dict[str, Any]] = {}
    for row in twin_rows:
        tid = row.get("id")
        if tid:
            twin_map[tid] = row

    if not twin_map:
        return MarketplaceAskResponse(results=[], query=body.question)

    twin_ids = list(twin_map.keys())

    # Step 2: Cross-twin semantic search
    try:
        raw_results = await search_global(
            query=body.question,
            twin_ids=twin_ids,
            per_twin_limit=3,
            global_limit=body.limit * 3,  # over-fetch to allow grouping
        )
    except Exception as exc:
        logger.exception("[MarketplaceAsk] vector search failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Search temporarily unavailable",
        )

    # Step 3: Group by twin_id — keep the best (highest score) snippet per twin
    best_per_twin: dict[str, dict[str, Any]] = {}
    for result in raw_results:
        tid = result["twin_id"]
        if tid not in twin_map:
            continue
        if tid not in best_per_twin or result["score"] > best_per_twin[tid]["score"]:
            best_per_twin[tid] = result

    # Step 4: Enrich with persona metadata and build response
    score_map = _get_score_rows(list(best_per_twin.keys()))
    topics_map = _get_public_topics(list(best_per_twin.keys()))

    items: list[_AskResultItem] = []
    for tid, match in sorted(
        best_per_twin.items(),
        key=lambda kv: kv[1]["score"],
        reverse=True,
    ):
        twin = twin_map[tid]
        public_topics = topics_map.get(tid, [])[:6]
        payload = build_marketplace_persona_payload(
            twin,
            public_topics=public_topics,
            answerability_score=score_map.get(tid, 0.0),
        )

        public_url = build_public_share_path(
            tid,
            _normalize_public_profile(twin)["settings"],
            ensure_token_if_missing=True,
            enable_public_share=False,
        )

        items.append(_AskResultItem(
            persona=_AskResultPersona(
                twin_id=tid,
                display_name=payload.get("display_name", ""),
                occupation=payload.get("occupation", ""),
                headline=payload.get("headline", ""),
                avatar_url=payload.get("avatar_url", ""),
                verified_profile=payload.get("verified_profile", False),
                public_url=public_url,
            ),
            snippet=_truncate_snippet(match["text"]),
            relevance=round(match["score"] * 100, 1),
        ))

    return MarketplaceAskResponse(
        results=items[:body.limit],
        query=body.question,
    )


@router.get("/share/{twin_id}/{token}/profile")
async def get_public_profile(twin_id: str, token: str):
    """
    Get public-safe profile data for a shared profile.
    Validates token and respects public visibility settings.
    """
    twin = _fetch_public_twin(twin_id)
    if not twin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Profile not found", "code": "PROFILE_NOT_FOUND"}
        )

    if not is_publicly_accessible_twin_record(twin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Profile not published",
                "code": "PROFILE_NOT_PUBLISHED",
                "message": "This profile is not yet ready for public sharing."
            }
        )

    is_valid = validate_share_token(token, twin_id)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Invalid share token",
                "code": "TOKEN_INVALID",
                "message": "This share link is invalid or has expired."
            }
        )

    policies = {
        "require_citation": True,
        "confidence_threshold": 0.5,
    }
    try:
        policy_result = (
            supabase.table("person_runtime_policies")
            .select("*")
            .eq("twin_id", twin_id)
            .eq("is_active", True)
            .or_("audience.eq.public,audience.is.null")
            .order("priority", desc=True)
            .limit(1)
            .execute()
        )
        if policy_result.data:
            policy = policy_result.data[0]
            policies["require_citation"] = policy.get("require_citation", True)
            policies["confidence_threshold"] = policy.get("confidence_threshold_answer", 0.5)
    except Exception:
        pass

    settings_obj = twin.get("settings") if isinstance(twin, dict) else {}
    if not isinstance(settings_obj, dict):
        settings_obj = {}

    profile_pack = redact_public_profile_pack_for_public_response(
        build_public_profile_pack(twin),
        settings_obj,
    )
    profile_pack["citations_enabled"] = policies["require_citation"]
    profile_pack["confidence_threshold"] = policies["confidence_threshold"]
    profile_pack["share_config"] = {
        "allow_chat": True,
        "show_topics": len(profile_pack.get("public_topics") or []) > 0,
    }
    # Public URL slug — lets the legacy /share page redirect to the canonical /p/{handle}.
    profile_pack["handle"] = str(settings_obj.get("handle") or "").strip()

    return profile_pack
