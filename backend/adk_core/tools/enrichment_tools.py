"""Post-compile enrichment tools — deterministic DB population from PersonaArtifact.

These tools run after the compiler pipeline to populate the marketplace-visible
database tables (person_claims, person_topic_profiles, person_answerability_scores)
that the /public/marketplace endpoint reads for ranking, filtering, and display.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from typing import Any

from adk_core.repositories.base import utc_now_iso
from adk_core.schemas.artifacts import PersonaArtifact, ResearchArtifact
from adk_core.text_utils import clamp_int, slugify, tokenize

logger = logging.getLogger(__name__)

# ── Claim type mapping ────────────────────────────────────────────────────────
# Maps research claim_type values to the person_claims CHECK constraint enum.
_CLAIM_TYPE_MAP: dict[str, str] = {
    "achievement": "achievement",
    "fact": "bio_fact",
    "role": "work_experience",
    "education": "education",
    "credential": "credential",
    "project": "project",
    "preference": "preference",
    "belief": "belief",
    "goal": "goal",
    "skill": "skill",
    "expertise": "expertise",
    "media_appearance": "media_appearance",
    "timeline_event": "timeline_event",
    "identity": "identity",
    "work_experience": "work_experience",
    "bio_fact": "bio_fact",
}
_DEFAULT_CLAIM_TYPE = "uncertain"

# ── Claim-type display names for fallback topic grouping ──────────────────────
_TYPE_DISPLAY_NAMES: dict[str, str] = {
    "achievement": "Achievements",
    "fact": "Key Facts",
    "role": "Career",
    "education": "Education",
    "credential": "Credentials",
    "project": "Projects",
    "skill": "Skills",
    "expertise": "Expertise",
    "other": "General",
}

# ── Batch insert size for claims ──────────────────────────────────────────────
_CLAIM_INSERT_CHUNK_SIZE = 200


class _TopicEntry:
    """Topic keyword entry for claim clustering."""
    __slots__ = ("name", "tokens")

    def __init__(self, name: str, tokens: set[str]) -> None:
        self.name = name
        self.tokens = tokens


def _get_supabase():
    """Lazy import matching the pattern in persona_repository.py."""
    from modules.observability import supabase
    return supabase


def _claim_fingerprint(text: str) -> str:
    """Deterministic fingerprint for claim dedup.

    Fingerprints the truncated form (max 2000 chars) so the stored claim_text
    and its fingerprint are always consistent.
    """
    normalized = text[:2000].lower().strip()
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    return utc_now_iso()


def _slugify(text: str) -> str:
    return slugify(text)


def _tokenize(text: str) -> list[str]:
    return tokenize(text)


def _clamp_int(value: float, lo: int = 0, hi: int = 100) -> int:
    return clamp_int(value, lo, hi)


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 1: Persist Claims
# ═══════════════════════════════════════════════════════════════════════════════

def persist_claims(
    *,
    twin_id: str,
    artifact: PersonaArtifact,
) -> dict[str, Any]:
    """Persist PersonaArtifact claims into the person_claims table.

    Verification status is derived from extraction confidence:
      >= 0.8 -> verified (public)
      >= 0.5 -> unverified (restricted)
      <  0.5 -> pending_review (restricted)

    Claims are inserted in chunks of _CLAIM_INSERT_CHUNK_SIZE to avoid
    oversized HTTP requests. Fingerprint is computed from the truncated
    claim text (max 2000 chars) for consistency with the stored value.
    """
    claims = artifact.claims
    if not claims:
        return {"status": "success", "claims_persisted": 0}

    try:
        supabase = _get_supabase()
    except Exception as exc:
        logger.warning("persist_claims: cannot connect to Supabase: %s", exc)
        return {"status": "error", "error": str(exc), "claims_persisted": 0}

    now = _utc_now_iso()

    # Soft-delete prior rule-extracted claims for this twin (recompile safety)
    try:
        supabase.table("person_claims").update(
            {"is_active": False}
        ).eq("twin_id", twin_id).eq("extraction_method", "rule").execute()
    except Exception as exc:
        logger.warning("persist_claims: soft-delete failed (continuing): %s", exc)

    rows: list[dict[str, Any]] = []
    for claim in claims:
        confidence = float(claim.confidence or 0.0)
        if confidence >= 0.8:
            verification_status = "verified"
            public_visibility = "public"
        elif confidence >= 0.5:
            verification_status = "unverified"
            public_visibility = "restricted"
        else:
            verification_status = "pending_review"
            public_visibility = "restricted"

        truncated_text = claim.text[:2000]
        mapped_type = _CLAIM_TYPE_MAP.get(claim.claim_type, _DEFAULT_CLAIM_TYPE)

        rows.append({
            "twin_id": twin_id,
            "claim_text": truncated_text,
            "claim_type": mapped_type,
            "extraction_confidence": round(confidence, 4),
            "extraction_method": "rule",
            "extraction_source_ids": claim.source_ids,
            "verification_status": verification_status,
            "public_visibility": public_visibility,
            "claim_fingerprint": _claim_fingerprint(claim.text),
            "is_active": True,
            "first_seen_at": now,
            "last_seen_at": now,
        })

    # Chunked insert to avoid oversized HTTP requests
    persisted = 0
    for i in range(0, len(rows), _CLAIM_INSERT_CHUNK_SIZE):
        chunk = rows[i:i + _CLAIM_INSERT_CHUNK_SIZE]
        try:
            supabase.table("person_claims").insert(chunk).execute()
            persisted += len(chunk)
        except Exception as exc:
            logger.warning("persist_claims: insert failed for chunk %d: %s", i // _CLAIM_INSERT_CHUNK_SIZE, exc)

    return {"status": "success", "claims_persisted": persisted}


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 2: Extract Topics
# ═══════════════════════════════════════════════════════════════════════════════

def extract_topics(
    *,
    twin_id: str,
    artifact: PersonaArtifact,
) -> dict[str, Any]:
    """Cluster claims into topics and upsert into person_topic_profiles.

    Primary topics come from identity_frame.expertise_topics.
    Claims are associated by keyword overlap.
    Unmatched claims fall back to claim_type grouping.
    """
    claims = artifact.claims
    expertise_topics: list[str] = (
        artifact.identity_frame.get("expertise_topics", [])
        if isinstance(artifact.identity_frame, dict)
        else []
    )

    if not claims and not expertise_topics:
        return {"status": "success", "topics_extracted": 0}

    # Build topic -> keyword tokens mapping from expertise topics
    topic_keywords: dict[str, _TopicEntry] = {}
    for topic_name in expertise_topics:
        if not isinstance(topic_name, str) or not topic_name.strip():
            continue
        slug = _slugify(topic_name)
        if slug:
            topic_keywords[slug] = _TopicEntry(
                name=topic_name.strip(),
                tokens=set(_tokenize(topic_name)),
            )

    # Associate each claim with topics by keyword overlap
    topic_claims: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unmatched_claims: list[dict[str, Any]] = []

    for claim in claims:
        claim_tokens = set(_tokenize(claim.text))
        matched = False
        for slug, entry in topic_keywords.items():
            if claim_tokens & entry.tokens:
                topic_claims[slug].append({"confidence": claim.confidence})
                matched = True
        if not matched:
            unmatched_claims.append({
                "claim_type": claim.claim_type,
                "confidence": claim.confidence,
            })

    # Fallback: group unmatched claims by claim_type
    type_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for uc in unmatched_claims:
        type_groups[uc["claim_type"]].append(uc)

    for ct, ct_claims in type_groups.items():
        if len(ct_claims) < 2:
            continue
        display_name = _TYPE_DISPLAY_NAMES.get(ct, ct.replace("_", " ").title())
        slug = _slugify(display_name)
        if slug and slug not in topic_claims:
            topic_claims[slug] = ct_claims
            topic_keywords[slug] = _TopicEntry(name=display_name, tokens=set())

    if not topic_claims and expertise_topics:
        for topic_name in expertise_topics:
            slug = _slugify(topic_name)
            if slug:
                topic_claims[slug] = []

    if not topic_claims:
        return {"status": "success", "topics_extracted": 0}

    try:
        supabase = _get_supabase()
    except Exception as exc:
        logger.warning("extract_topics: cannot connect to Supabase: %s", exc)
        return {"status": "error", "error": str(exc), "topics_extracted": 0}

    now = _utc_now_iso()
    upserted = 0

    for slug, claims_list in topic_claims.items():
        entry = topic_keywords.get(slug)
        topic_name = entry.name if entry else slug.replace("-", " ").title()
        evidence_count = len(claims_list)
        # Schema: coverage_score is FLOAT 0.0-1.0 (CHECK constraint)
        coverage_score = min(1.0, evidence_count / 10.0)
        verified_count = sum(1 for c in claims_list if c.get("confidence", 0) >= 0.8)
        verified_ratio = (verified_count / evidence_count) if evidence_count > 0 else 0.0
        # Schema: answerability_score is FLOAT 0.0-1.0
        topic_answerability = round(coverage_score * 0.6 + verified_ratio * 0.4, 4)

        row_data = {
            "twin_id": twin_id,
            "topic_slug": slug,
            "topic_name": topic_name[:200],
            "evidence_count": evidence_count,
            "coverage_score": round(coverage_score, 4),
            "verification_score": round(verified_ratio, 4),
            "answerability_score": min(1.0, topic_answerability),
            "last_computed_at": now,
            "updated_at": now,
        }

        try:
            # Atomic upsert — avoids TOCTOU race on concurrent compiles
            supabase.table("person_topic_profiles").upsert(
                {**row_data, "created_at": now},
                on_conflict="twin_id,topic_slug",
            ).execute()
            upserted += 1
        except Exception as exc:
            logger.warning("extract_topics: upsert failed for %s: %s", slug, exc)

    return {"status": "success", "topics_extracted": upserted}


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 3: Compute Answerability
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_global_scores(
    artifact: PersonaArtifact,
    research_artifact: ResearchArtifact,
) -> dict[str, int]:
    """Compute component scores and weighted composite (all INTEGER 0-100)."""
    source_count = len(research_artifact.source_registry)
    claim_count = len(artifact.claims)
    verified_count = sum(1 for c in artifact.claims if c.confidence >= 0.8)

    coverage = min(100.0, source_count * 10 + claim_count * 2)
    verification = (verified_count / claim_count * 100) if claim_count > 0 else 0.0
    recency = 75.0  # Fresh compile is reasonably recent
    consistency = 90.0  # Fresh compile has no known contradictions
    style_fidelity = 70.0  # Placeholder — voice match requires runtime evaluation

    composite = (
        coverage * 0.25
        + verification * 0.25
        + recency * 0.20
        + consistency * 0.20
        + style_fidelity * 0.10
    )

    return {
        "coverage_score": _clamp_int(coverage),
        "verification_score": _clamp_int(verification),
        "recency_score": _clamp_int(recency),
        "consistency_score": _clamp_int(consistency),
        "style_fidelity_score": _clamp_int(style_fidelity),
        "answerability_score": _clamp_int(composite),
    }


def compute_answerability(
    *,
    twin_id: str,
    artifact: PersonaArtifact,
    research_artifact: ResearchArtifact,
) -> dict[str, Any]:
    """Compute and persist global + per-topic answerability scores.

    Weights match the existing answerability_scorer.py formula:
      coverage=0.25, verification=0.25, recency=0.20, consistency=0.20, style=0.10
    """
    scores = _compute_global_scores(artifact, research_artifact)

    try:
        supabase = _get_supabase()
    except Exception as exc:
        logger.warning("compute_answerability: cannot connect to Supabase: %s", exc)
        return {"status": "error", "error": str(exc), "global_score": 0}

    now = _utc_now_iso()

    # Atomic upsert for global score — avoids TOCTOU race
    global_row = {
        "twin_id": twin_id,
        "scope_type": "global",
        "scope_key": "global",
        **scores,
        "last_computed_at": now,
        "updated_at": now,
        "created_at": now,
    }
    topic_scores_computed = 0

    try:
        supabase.table("person_answerability_scores").upsert(
            global_row,
            on_conflict="twin_id,scope_type,scope_key",
        ).execute()
    except Exception as exc:
        logger.warning("compute_answerability: global upsert failed: %s", exc)
        return {"status": "error", "error": str(exc), "global_score": scores["answerability_score"]}

    # Per-topic scores from just-written topic profiles
    try:
        topic_rows = (
            supabase.table("person_topic_profiles")
            .select("topic_slug, coverage_score, verification_score, answerability_score")
            .eq("twin_id", twin_id)
            .execute()
        )
        for topic in (topic_rows.data or []):
            topic_slug = topic.get("topic_slug")
            if not topic_slug:
                continue
            # Topic profile stores 0.0-1.0; answerability_scores needs INTEGER 0-100
            # Schema CHECK guarantees 0.0-1.0 — always multiply unconditionally
            topic_score_row = {
                "twin_id": twin_id,
                "scope_type": "topic",
                "scope_key": topic_slug,
                "coverage_score": _clamp_int(float(topic.get("coverage_score") or 0) * 100),
                "verification_score": _clamp_int(float(topic.get("verification_score") or 0) * 100),
                "recency_score": scores["recency_score"],
                "consistency_score": scores["consistency_score"],
                "style_fidelity_score": scores["style_fidelity_score"],
                "answerability_score": _clamp_int(float(topic.get("answerability_score") or 0) * 100),
                "last_computed_at": now,
                "updated_at": now,
                "created_at": now,
            }
            try:
                supabase.table("person_answerability_scores").upsert(
                    topic_score_row,
                    on_conflict="twin_id,scope_type,scope_key",
                ).execute()
                topic_scores_computed += 1
            except Exception as exc:
                logger.warning("compute_answerability: topic upsert failed for %s: %s", topic_slug, exc)
    except Exception as exc:
        logger.warning("compute_answerability: topic fetch failed: %s", exc)

    return {
        "status": "success",
        "global_score": scores["answerability_score"],
        "topic_scores_computed": topic_scores_computed,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

async def post_compile_enrichment(
    *,
    twin_id: str,
    artifact: PersonaArtifact,
    research_artifact: ResearchArtifact,
) -> dict[str, Any]:
    """Run all enrichment tools sequentially after compile.

    Each step is independent — failure in one does not block the others.
    Order matters: claims -> topics -> answerability (data dependencies).

    Note: Inner tools are synchronous (supabase-py sync client). The async
    wrapper is for compatibility with the calling async context in runtime.py.
    """
    results: dict[str, Any] = {}

    try:
        results["claims"] = persist_claims(twin_id=twin_id, artifact=artifact)
    except Exception as exc:
        logger.warning("post_compile_enrichment: persist_claims failed: %s", exc)
        results["claims"] = {"status": "error", "error": str(exc)}

    try:
        results["topics"] = extract_topics(twin_id=twin_id, artifact=artifact)
    except Exception as exc:
        logger.warning("post_compile_enrichment: extract_topics failed: %s", exc)
        results["topics"] = {"status": "error", "error": str(exc)}

    try:
        results["answerability"] = compute_answerability(
            twin_id=twin_id,
            artifact=artifact,
            research_artifact=research_artifact,
        )
    except Exception as exc:
        logger.warning("post_compile_enrichment: compute_answerability failed: %s", exc)
        results["answerability"] = {"status": "error", "error": str(exc)}

    return results
