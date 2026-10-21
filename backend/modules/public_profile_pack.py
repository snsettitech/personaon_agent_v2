"""Public profile pack — orchestrator module.

Delegates to extracted sub-modules and keeps only:
  - Data fetching (Supabase queries)
  - normalize_public_profile / build_public_profile_pack
  - build_existing_profile_projection
  - merge helpers
  - _build_public_response_seeds (referenced by profile_research via lazy import)
"""
from __future__ import annotations

import os
import re
from typing import Any

from modules.observability import supabase
from modules.text_quality import is_meaningful_text
from modules.profile_image import (  # noqa: F401
    OWNER_LOCKED_IMAGE_SOURCE_TYPES,
    _build_image_candidate,
    _candidate_priority,
    _clean_host,
    _extract_meta_image,
    _fetch_remote_json,
    _fetch_remote_text,
    _fetch_wikipedia_thumbnail,
    _host_matches,
    _image_source_tier,
    _is_official_source,
    _looks_like_image_url,
    _looks_like_logo_url,
    _official_host_candidates,
    _request_url,
    _resolve_profile_image,
    _wikipedia_summary_api_url,
)
from modules.profile_marketplace import (  # noqa: F401
    _build_conversation_profile,
    _build_expertise,
    _build_occupation,
    _build_personality_traits,
    build_marketplace_persona_payload,
)
from modules.profile_research import (  # noqa: F401
    _build_education_entries,
    _build_headline_from_research,
    _build_research_contributions,
    _build_research_education,
    _build_research_key_achievements,
    _build_research_work_history,
    _build_work_entries,
    _claim_meta,
    _dedupe_object_rows,
    _extract_research_expertise,
    _extract_research_years,
    _extract_social_links_from_research,
    _infer_birth_death_nationality,
    _looks_like_work_event,
    _parse_education_entry_from_text,
    _parse_work_entry_from_text,
    build_research_profile_projection,
)

# ---------------------------------------------------------------------------
# Re-exports from extracted modules (preserve `from modules.public_profile_pack import X`)
# ---------------------------------------------------------------------------
from modules.profile_utils import (  # noqa: F401
    PUBLIC_PROFILE_META_VERSION,
    _build_public_profile_meta,
    _calculate_completeness_score,
    _clean_text,
    _clean_unique_strings,
    _coerce_ratio,
    _coerce_score_percent,
    _coerce_year,
    _first_sentence,
    _is_populated,
    _iso_now,
    _safe_dict,
    _safe_list,
    _social_key_from_url,
    normalize_social_links,
)


def _build_voice_capabilities(twin_settings: dict[str, Any]) -> dict[str, Any]:
    has_voice = bool(twin_settings.get("voice_id"))
    voice_name = _clean_text(twin_settings.get("voice_name"))
    provider = (os.getenv("VOICE_CALL_PROVIDER", "deepgram") or "deepgram").strip().lower()
    shared_webhook_secret = bool(os.getenv("ELEVENLABS_WEBHOOK_SECRET"))
    live_call = (
        has_voice
        and provider == "deepgram"
        and bool(os.getenv("DEEPGRAM_API_KEY"))
        and bool(os.getenv("ELEVENLABS_API_KEY"))
        and (bool(os.getenv("VOICE_CALL_SESSION_SECRET")) or shared_webhook_secret)
        and (bool(os.getenv("VOICE_LLM_WEBHOOK_SECRET")) or shared_webhook_secret)
    )
    capabilities = {
        "tts": has_voice,
        "live_call": live_call,
        "provider": "deepgram" if live_call else "none",
    }
    if has_voice and voice_name:
        capabilities["voice_name"] = voice_name
    return capabilities

# ---------------------------------------------------------------------------
# Inline citation / response-seed helpers (kept here; profile_research
# imports _build_public_response_seeds lazily from this module)
# ---------------------------------------------------------------------------

def _strip_inline_source_refs(text: Any) -> str:
    cleaned = re.sub(r"\[[0-9a-fA-F\-\s;,]+\]", "", str(text or ""))
    return re.sub(r"\s+", " ", cleaned).strip(" .")


def _sanitize_public_faq(entries: Any) -> list[dict[str, str]]:
    """Whitelist owner-approved FAQ down to the public ``{question, answer}`` shape.

    Leak-safe by construction:
      - ONLY the ``question`` and ``answer`` strings survive; any other keys an
        owner row might carry (ids, source refs, internal flags) are dropped.
      - Inline citation / source refs (e.g. ``[<uuid>]``) are stripped from the
        answer via :func:`_strip_inline_source_refs`, matching the response-seed
        path, so a pasted-in citation never reaches an anonymous visitor.
      - Rows with a blank question or a blank answer (after cleaning) are dropped.

    SAFETY: this NEVER derives FAQ from ``public_response_seeds`` /
    ``response_seeds`` or any redacted source. The owner populates
    ``settings.public_profile.public_faq`` explicitly; it defaults to ``[]`` when
    absent, so nothing existing gets un-redacted.
    """
    faq: list[dict[str, str]] = []
    for entry in _safe_list(entries):
        if not isinstance(entry, dict):
            continue
        question = _clean_text(entry.get("question"))
        answer = _strip_inline_source_refs(entry.get("answer"))
        if not question or not answer:
            continue
        faq.append({"question": question, "answer": answer})
    return faq


def _extract_inline_citation_ids(text: Any) -> list[str]:
    out: list[str] = []
    seen = set()
    for block in re.findall(r"\[([^\]]+)\]", str(text or "")):
        for token in re.split(r"[;,\s]+", block):
            candidate = token.strip()
            if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", candidate):
                lowered = candidate.lower()
                if lowered not in seen:
                    seen.add(lowered)
                    out.append(candidate)
    return out


def _build_public_response_seeds(
    result: dict[str, Any],
    *,
    display_name: str,
    public_profile: dict[str, Any],
    existing_seeds: Any = None,
) -> list[dict[str, Any]]:
    seeds: list[dict[str, Any]] = []
    seen = set()

    def _add(question: str, answer: str, citations: list[str], title: str, confidence: Any = None) -> None:
        clean_question = _clean_text(question)
        clean_answer = _strip_inline_source_refs(answer)
        if not clean_answer:
            return
        key = (clean_question.lower(), clean_answer.lower())
        if key in seen:
            return
        seen.add(key)
        payload: dict[str, Any] = {
            "question": clean_question,
            "answer": clean_answer if clean_answer.endswith((".", "!", "?")) else f"{clean_answer}.",
            "citations": [c for c in citations if _clean_text(c)],
            "title": title,
        }
        if isinstance(confidence, (int, float)):
            payload["confidence"] = round(float(confidence), 3)
        seeds.append(payload)

    for item in _safe_list(existing_seeds):
        if not isinstance(item, dict):
            continue
        _add(
            str(item.get("question") or "").strip(),
            str(item.get("answer") or item.get("text") or "").strip(),
            [str(c) for c in _safe_list(item.get("citations")) if str(c)],
            str(item.get("title") or "Prepared public answer").strip() or "Prepared public answer",
            item.get("confidence"),
        )

    for item in _safe_list(result.get("prepared_question_answers")):
        if not isinstance(item, dict):
            continue
        _add(
            str(item.get("question") or "").strip(),
            str(item.get("answer") or "").strip(),
            [str(c) for c in _safe_list(item.get("citations")) if str(c)],
            "Prepared public answer",
            item.get("confidence"),
        )

    bio = _safe_dict(result.get("bio"))
    bio_medium = _clean_text(bio.get("medium"))
    bio_short = _clean_text(bio.get("short"))
    bio_citations = _extract_inline_citation_ids(bio_medium or bio_short or public_profile.get("bio"))
    if bio_medium or bio_short:
        _add(
            f"Who is {display_name}?",
            bio_short or bio_medium,
            bio_citations,
            "Canonical biography",
            0.82,
        )

    role = _clean_text(public_profile.get("role"))
    organization = _clean_text(public_profile.get("organization"))
    if role or organization:
        answer = f"{display_name} is the {role} at {organization}." if role and organization else f"{display_name} is associated with {role or organization}."
        _add(
            f"What public role is {display_name} associated with?",
            answer,
            bio_citations,
            "Canonical role",
            0.9,
        )

    contributions = _clean_unique_strings(public_profile.get("contributions") or [], limit=6)
    if contributions:
        _add(
            f"How did {display_name} build their public career?",
            " ".join(contributions[:4]),
            [],
            "Career milestones",
            0.68,
        )
        _add(
            f"How did {display_name} get into public life or politics?",
            " ".join(contributions[:4]),
            [],
            "Career milestones",
            0.68,
        )

    work_experience = _safe_list(public_profile.get("work_experience"))
    if work_experience:
        work_lines: list[str] = []
        for job in work_experience[:4]:
            if not isinstance(job, dict):
                continue
            role_value = _clean_text(job.get("role") or job.get("title"))
            company = _clean_text(job.get("company") or job.get("organization"))
            description = _clean_text(job.get("description"))
            start_year = _clean_text(job.get("start_year"))
            end_year = _clean_text(job.get("end_year"))
            years = ""
            if start_year and end_year:
                years = f" ({start_year}-{end_year})"
            elif start_year:
                years = f" (since {start_year})"
            if description:
                work_lines.append(description)
            elif role_value and company:
                work_lines.append(f"{role_value} at {company}{years}")
        if work_lines:
            _add(
                f"What career path is documented for {display_name}?",
                " ".join(work_lines),
                [],
                "Work history",
                0.7,
            )
            _add(
                f"What is {display_name}'s background?",
                " ".join(work_lines[:2]),
                [],
                "Work history",
                0.69,
            )
            _add(
                f"What experience led {display_name} to this role?",
                " ".join(work_lines[:3]),
                [],
                "Work history",
                0.7,
            )

    return seeds[:10]


# ---------------------------------------------------------------------------
# Supabase data-fetching helpers
# ---------------------------------------------------------------------------

def _check_calendar_connected(twin_id: str) -> bool:
    """Check whether Google Calendar is connected AND active for the twin.

    Bug 4 fix: previously this returned True for any row regardless of
    ``is_active``, but ``services.calendar_service.get_calendar_credentials``
    only accepts active rows. The mismatch meant a revoked / errored connector
    could still light up the "Book" chip on /p/{handle} while every actual
    booking flow returned 404. Both gates now require ``is_active=True``.

    Returns False on any error so we never block the public profile response.
    """
    if not _clean_text(twin_id):
        return False
    try:
        resp = (
            supabase.table("tool_connectors")
            .select("id, is_active")
            .eq("twin_id", twin_id)
            .eq("connector_type", "google_calendar")
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return bool(rows)
    except Exception:
        return False


def _fetch_existing_source_candidates(twin_id: str, *, limit: int = 24) -> list[dict[str, Any]]:
    if not _clean_text(twin_id):
        return []
    select_variants = (
        "id, citation_url, filename, source_type",
        "id, citation_url, filename",
    )
    for select_clause in select_variants:
        try:
            response = (
                supabase.table("sources")
                .select(select_clause)
                .eq("twin_id", twin_id)
                .limit(limit)
                .execute()
            )
            rows = response.data or []
            if isinstance(rows, list):
                return [_safe_dict(row) for row in rows]
        except Exception:
            continue
    return []


def _fetch_answerability_score(twin_id: str) -> float:
    try:
        result = (
            supabase.table("person_answerability_scores")
            .select("answerability_score")
            .eq("twin_id", twin_id)
            .eq("scope_type", "global")
            .eq("scope_key", "global")
            .single()
            .execute()
        )
        if result.data:
            return _coerce_score_percent(result.data.get("answerability_score"))
    except Exception:
        pass
    return 0.0


def _fetch_verified_claim_count(twin_id: str) -> int:
    try:
        result = (
            supabase.table("person_claims")
            .select("id", count="exact")
            .eq("twin_id", twin_id)
            .eq("verification_status", "verified")
            .eq("public_visibility", "public")
            .eq("is_active", True)
            .execute()
        )
        return int(result.count or 0)
    except Exception:
        return 0


def _fetch_public_topics(twin_id: str, *, limit: int = 6) -> list[dict[str, Any]]:
    topic_select_variants = [
        ("topic_slug, topic_name, answerability_score", "topic_slug", "topic_name"),
        ("topic_slug, name, answerability_score", "topic_slug", "name"),
        ("slug, name, answerability_score", "slug", "name"),
    ]

    for select_clause, slug_key, name_key in topic_select_variants:
        try:
            result = (
                supabase.table("person_topic_profiles")
                .select(select_clause)
                .eq("twin_id", twin_id)
                .order("answerability_score", desc=True)
                .limit(limit * 2)
                .execute()
            )
            topics: list[dict[str, Any]] = []
            for row in result.data or []:
                score = _coerce_score_percent(row.get("answerability_score"))
                if score < 45:
                    continue
                slug = _clean_text(row.get(slug_key) or row.get("topic_slug") or row.get("slug")).lower()
                name = _clean_text(row.get(name_key) or row.get("topic_name") or row.get("name") or slug)
                if not slug and not name:
                    continue
                topics.append(
                    {
                        "slug": slug or name.lower().replace(" ", "-"),
                        "name": name,
                        "answerability_score": score,
                    }
                )
            if topics:
                deduped = []
                seen = set()
                for topic in topics:
                    key = str(topic.get("slug") or topic.get("name")).lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    deduped.append(topic)
                    if len(deduped) >= limit:
                        break
                return deduped
        except Exception:
            continue
    return []


def _fetch_public_claims(twin_id: str) -> list[dict[str, Any]]:
    try:
        result = (
            supabase.table("person_claims")
            .select(
                "id, claim_text, claim_type, claim_time_start, claim_time_end, verification_status, "
                "public_visibility, extraction_confidence, metadata_json, is_active"
            )
            .eq("twin_id", twin_id)
            .eq("is_active", True)
            .neq("verification_status", "rejected")
            .neq("public_visibility", "private")
            .order("verification_status", desc=True)
            .order("extraction_confidence", desc=True)
            .limit(100)
            .execute()
        )
        return result.data or []
    except Exception:
        return []


def _fetch_timeline_events(twin_id: str) -> list[dict[str, Any]]:
    try:
        result = (
            supabase.table("person_timeline_events")
            .select(
                "event_type, title, description, start_date, end_date, organization, role_title, "
                "confidence, is_active"
            )
            .eq("twin_id", twin_id)
            .eq("is_active", True)
            .order("start_date", desc=True)
            .limit(24)
            .execute()
        )
        return result.data or []
    except Exception:
        return []


def _fetch_style_profile(twin_id: str) -> dict[str, Any]:
    try:
        result = (
            supabase.table("person_style_profile")
            .select("tone_descriptors, sentence_length_profile, common_phrases")
            .eq("twin_id", twin_id)
            .eq("is_active_version", True)
            .order("version", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            return _safe_dict(result.data[0])
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# Claim-based identity stats (DB-claims path, distinct from research path)
# ---------------------------------------------------------------------------

def _identity_stat_from_claims(claims: list[dict[str, Any]]) -> tuple[int | None, int | None, str]:
    birth_year: int | None = None
    death_year: int | None = None
    nationality = ""

    for claim in claims:
        if claim.get("claim_type") not in {"identity", "bio_fact"}:
            continue
        meta = _claim_meta(claim)
        if birth_year is None:
            birth_year = _coerce_year(meta.get("birth_year")) or _coerce_year(claim.get("claim_time_start"))
        if death_year is None:
            death_year = _coerce_year(meta.get("death_year")) or _coerce_year(claim.get("claim_time_end"))
        if not nationality:
            nationality = _clean_text(meta.get("nationality"))
            if not nationality:
                text = _clean_text(claim.get("claim_text"))
                match = re.search(r"\b([A-Z][a-z]+)\s+(?:national|citizen|American|Canadian|Indian|British)\b", text)
                if match:
                    nationality = match.group(1)

    return birth_year, death_year, nationality


# ---------------------------------------------------------------------------
# Speaking style / key achievements / contributions (DB-claims path)
# ---------------------------------------------------------------------------

def _build_speaking_style(
    profile: dict[str, Any],
    identity_pack: dict[str, Any],
    style_profile: dict[str, Any],
) -> str:
    explicit = _clean_text(profile.get("speaking_style"))
    if explicit:
        return explicit

    tone_descriptors = _clean_unique_strings(
        [
            *_safe_list(identity_pack.get("tone_tags")),
            *_safe_list(style_profile.get("tone_descriptors")),
        ],
        limit=3,
    )
    sentence_profile = _safe_dict(style_profile.get("sentence_length_profile"))
    average_length = sentence_profile.get("average_length")

    parts: list[str] = []
    if tone_descriptors:
        parts.append(", ".join(tone_descriptors))
    if isinstance(average_length, (int, float)):
        if average_length <= 10:
            parts.append("generally concise")
        elif average_length >= 24:
            parts.append("detail-oriented")
        else:
            parts.append("balanced in detail")
    if not parts:
        return ""
    return f"{parts[0].capitalize()}" + (f", {parts[1]}." if len(parts) > 1 else ".")


def _build_key_achievements(profile: dict[str, Any], claims: list[dict[str, Any]], timeline_events: list[dict[str, Any]]) -> list[str]:
    seeded = _safe_list(profile.get("key_achievements"))
    claim_values = [
        claim.get("claim_text")
        for claim in claims
        if claim.get("claim_type") in {"achievement", "credential", "media_appearance"}
    ]
    timeline_values = [
        event.get("title")
        for event in timeline_events
        if _clean_text(event.get("event_type")).lower() in {"award", "publication", "founded_company", "milestone"}
    ]
    return _clean_unique_strings([*seeded, *claim_values, *timeline_values], limit=6)


def _build_contributions(profile: dict[str, Any], claims: list[dict[str, Any]], timeline_events: list[dict[str, Any]]) -> list[str]:
    seeded = _safe_list(profile.get("contributions"))
    claim_values = [
        claim.get("claim_text")
        for claim in claims
        if claim.get("claim_type") in {"project", "expertise", "media_appearance"}
    ]
    timeline_values = [event.get("description") or event.get("title") for event in timeline_events[:6]]
    return _clean_unique_strings([*seeded, *claim_values, *timeline_values], limit=6)


# ---------------------------------------------------------------------------
# normalize_public_profile
# ---------------------------------------------------------------------------

def _first_meaningful_candidate(*candidates: str) -> str:
    """Return the first candidate that passes the shared meaningfulness bar
    (modules.text_quality.is_meaningful_text), falling back to the first
    non-empty candidate if none qualify.

    Execution-board 0.1 (PRD R1): a plain `x or y or z` chain always takes
    the first truthy value regardless of quality, which is how an
    owner-typed "nill" bio permanently beat genuine enrichment content that
    arrived later. This helper fixes the *ordering* — it does not itself
    decide public reachability; the publish/marketplace gate re-checks
    meaningfulness explicitly on whatever comes out of this function.
    """
    fallback = ""
    for candidate in candidates:
        if not candidate:
            continue
        if not fallback:
            fallback = candidate
        if is_meaningful_text(candidate):
            return candidate
    return fallback


def normalize_public_profile(twin: dict[str, Any]) -> dict[str, Any]:
    settings = _safe_dict(twin.get("settings"))
    public_profile = _safe_dict(settings.get("public_profile"))
    public_profile_meta = _safe_dict(settings.get("public_profile_meta"))

    # Fall back to persona_profile (Firecrawl agent output) when public_profile is empty
    pp = _safe_dict(settings.get("persona_profile"))
    if isinstance(pp, str):
        import json as _json
        try:
            pp = _json.loads(pp)
        except (ValueError, TypeError):
            pp = {}

    def _pget(field: str, *alt_fields: str) -> str:
        """Get first non-empty value from public_profile, then persona_profile."""
        val = _clean_text(public_profile.get(field))
        if val:
            return val
        for alt in alt_fields:
            val = _clean_text(pp.get(alt))
            if val:
                return val
        return _clean_text(pp.get(field)) or ""

    def _plist(field: str) -> list:
        """Get list from public_profile, fall back to persona_profile."""
        val = public_profile.get(field)
        if isinstance(val, list) and val:
            return val
        val = pp.get(field)
        return val if isinstance(val, list) else []

    display_name = (
        _pget("display_name", "name")
        or _clean_text(twin.get("name"))
        or "Persona"
    )
    organization = _pget("organization") or _clean_text(settings.get("organization"))
    role = _pget("role", "occupation") or _clean_text(settings.get("role"))
    headline = (
        _pget("headline")
        or _clean_text(settings.get("headline"))
        or _clean_text(settings.get("tagline"))
        or _pget("short_description")
    )
    # Execution-board 0.1 fix (PRD R1 root cause): this used to be a plain
    # `or` chain, which always took the *first* non-empty candidate — an
    # owner-typed bio like "nill" permanently won over anything enrichment
    # found later, because "or" only cares about truthiness, never quality.
    # `_first_meaningful_candidate` prefers the first candidate that passes
    # the same meaningfulness bar used at write time (modules.text_quality,
    # execution-board 0.2), so genuine enrichment content can win even when
    # the owner-typed value came first in the chain. It still falls back to
    # the first non-empty candidate if none qualify (never silently discards
    # data) — the publish/marketplace gate is what decides reachability by
    # re-checking meaningfulness explicitly, not this fallback.
    bio = _first_meaningful_candidate(
        _pget("bio"),
        _clean_text(settings.get("public_intro")),
        _clean_text(twin.get("description")),
        _clean_text(settings.get("description")),
        _pget("short_description"),
        headline,
    )
    avatar_url = _pget("avatar_url", "image_url")
    pinned_questions = _clean_unique_strings(public_profile.get("pinned_questions") or [], limit=4)

    return {
        "display_name": display_name,
        "organization": organization,
        "role": role,
        "occupation": _pget("occupation") or _clean_text(settings.get("occupation")),
        "headline": headline,
        "bio": bio,
        "short_description": _pget("short_description"),
        "avatar_url": avatar_url,
        "image_url": _pget("image_url") or avatar_url,
        "mind_label": _pget("mind_label"),
        "handle": _clean_text(settings.get("handle")),
        "pinned_questions": pinned_questions,
        "social_links": normalize_social_links(public_profile.get("social_links") or pp.get("social_links")),
        "featured_content": _safe_list(public_profile.get("featured_content")),
        "conversation_profile": _safe_dict(public_profile.get("conversation_profile")),
        "personality_traits": _clean_unique_strings(_plist("personality_traits"), limit=6),
        "key_achievements": _clean_unique_strings(_plist("key_achievements"), limit=6),
        "areas_of_expertise": _clean_unique_strings(_plist("areas_of_expertise"), limit=6),
        "contributions": _clean_unique_strings(_plist("contributions"), limit=6),
        "speaking_style": _pget("speaking_style"),
        "verified_profile": bool(public_profile.get("verified_profile")),
        "birth_year": _coerce_year(public_profile.get("birth_year") or pp.get("birth_year")),
        "death_year": _coerce_year(public_profile.get("death_year") or pp.get("death_year")),
        "nationality": _pget("nationality"),
        "education": _dedupe_object_rows(
            _safe_list(public_profile.get("education") or pp.get("education")),
            ("institution", "degree", "field"),
        ),
        "work_experience": _dedupe_object_rows(
            _safe_list(public_profile.get("work_experience") or pp.get("work_experience")),
            ("company", "role", "description"),
        ),
        "public_profile_meta": public_profile_meta,
        "settings": settings,
        "public_profile": public_profile,
    }


# ---------------------------------------------------------------------------
# Merge helpers
# ---------------------------------------------------------------------------

def merge_materialized_profile_settings(
    current_settings: dict[str, Any],
    projection: dict[str, Any],
) -> dict[str, Any]:
    merged_settings = {**_safe_dict(current_settings)}
    if projection.get("public_profile"):
        merged_settings["public_profile"] = projection["public_profile"]
    if projection.get("persona_identity_pack"):
        merged_settings["persona_identity_pack"] = projection["persona_identity_pack"]
    if projection.get("public_profile_meta"):
        merged_settings["public_profile_meta"] = projection["public_profile_meta"]
    if projection.get("tagline"):
        merged_settings["tagline"] = projection["tagline"]
    if projection.get("public_intro"):
        merged_settings["public_intro"] = projection["public_intro"]
    return merged_settings


def merge_profile_fields_partial(
    existing_profile: dict[str, Any],
    new_fields: dict[str, Any],
    source_confidence: float,
) -> dict[str, Any]:
    """
    Merge extracted profile fields into an existing public_profile dict.

    Rules:
    - Simple text fields: only fill if EMPTY in existing, or if new confidence is higher.
    - Array fields (areas_of_expertise, key_achievements): extend and deduplicate.
    - Structured arrays (work_experience, education): append and deduplicate by key fields.
    - Tracks per-field confidence in _field_confidences (internal metadata key).

    Args:
        existing_profile:  Current twins.settings.public_profile dict.
        new_fields:        Output from extract_profile_fields() or linkedin_export_parser.
        source_confidence: Float 0.0-1.0 representing source reliability.

    Returns:
        Updated profile dict (new object, never mutates existing).
    """
    field_confidences: dict[str, float] = dict(
        _safe_dict(existing_profile.get("_field_confidences"))
    )
    merged: dict[str, Any] = {**existing_profile}

    # --- Simple scalar fields ---
    SCALAR_FIELDS = [
        "display_name", "headline", "bio", "short_description",
        "role", "organization", "nationality",
    ]
    for field in SCALAR_FIELDS:
        new_val = _clean_text(new_fields.get(field))
        if not new_val:
            continue
        existing_val = _clean_text(merged.get(field))
        existing_conf = field_confidences.get(field, 0.0)
        if not existing_val or source_confidence > existing_conf:
            merged[field] = new_val
            field_confidences[field] = source_confidence

    # birth_year
    new_year = new_fields.get("birth_year")
    if new_year and isinstance(new_year, int):
        existing_year = merged.get("birth_year")
        existing_conf = field_confidences.get("birth_year", 0.0)
        if not existing_year or source_confidence > existing_conf:
            merged["birth_year"] = new_year
            field_confidences["birth_year"] = source_confidence

    # --- Append-only array fields ---
    for field in ("areas_of_expertise", "key_achievements"):
        new_items = _safe_list(new_fields.get(field))
        if new_items:
            existing_items = _safe_list(merged.get(field))
            merged[field] = _clean_unique_strings(existing_items + new_items, limit=6)

    # --- Structured arrays: append + deduplicate ---
    if new_fields.get("work_experience"):
        existing_work = _safe_list(merged.get("work_experience"))
        merged["work_experience"] = _dedupe_object_rows(
            existing_work + _safe_list(new_fields["work_experience"]),
            ("company", "role"),
        )

    if new_fields.get("education"):
        existing_edu = _safe_list(merged.get("education"))
        merged["education"] = _dedupe_object_rows(
            existing_edu + _safe_list(new_fields["education"]),
            ("institution", "degree", "field"),
        )

    # Persist confidence metadata (internal, stripped before display)
    merged["_field_confidences"] = field_confidences

    return merged


# ---------------------------------------------------------------------------
# build_existing_profile_projection
# ---------------------------------------------------------------------------

def build_existing_profile_projection(
    twin: dict[str, Any],
    *,
    source_flow: str = "backfill",
) -> dict[str, Any]:
    normalized = normalize_public_profile(twin)
    settings = _safe_dict(normalized.get("settings"))
    existing_public_profile = _safe_dict(settings.get("public_profile"))
    existing_identity_pack = _safe_dict(settings.get("persona_identity_pack"))
    existing_meta = _safe_dict(settings.get("public_profile_meta"))
    source_rows = _fetch_existing_source_candidates(str(twin.get("id") or ""))
    source_urls = [
        _clean_text(row.get("citation_url"))
        for row in source_rows
        if _clean_text(row.get("citation_url"))
    ]

    display_name = normalized["display_name"]
    role = (
        normalized["role"]
        or _clean_text(existing_public_profile.get("role"))
        or _clean_text(existing_identity_pack.get("role"))
        or _clean_text(settings.get("headline"))
    )
    organization = (
        normalized["organization"]
        or _clean_text(existing_public_profile.get("organization"))
        or _clean_text(existing_identity_pack.get("organization"))
    )
    expertise = _clean_unique_strings(
        [
            *normalized.get("areas_of_expertise", []),
            *_safe_list(existing_identity_pack.get("expertise_areas")),
            _clean_text(settings.get("specialization")),
            _clean_text(settings.get("headline")),
        ],
        limit=6,
    )
    fallback_social_links = normalize_social_links(source_urls)
    social_links = normalized["social_links"] or fallback_social_links
    image_resolution = _resolve_profile_image(
        {
            "input": {
                "hints": {
                    "website": social_links.get("website") or social_links.get("wikipedia") or "",
                }
            },
            "sources": [
                {
                    "source_id": row.get("id"),
                    "url": _clean_text(row.get("citation_url")),
                    "title": _clean_text(row.get("filename")),
                    "source_type": (
                        _clean_text(row.get("source_type"))
                        or ("profile" if "wikipedia.org" in _clean_host(row.get("citation_url")) else "website")
                    ),
                    "used_in_final": True,
                    "identity_match_confidence": 0.82,
                }
                for row in source_rows
                if _clean_text(row.get("citation_url"))
            ],
        },
        existing_public_profile,
        existing_meta,
    )
    image_url = _clean_text(
        image_resolution.get("image_url")
        or normalized.get("image_url")
        or normalized.get("avatar_url")
    )
    public_response_seeds = _build_public_response_seeds(
        {},
        display_name=display_name,
        public_profile={
            **existing_public_profile,
            "role": role,
            "organization": organization,
            "bio": normalized["bio"],
            "contributions": normalized["contributions"],
            "work_experience": normalized["work_experience"],
        },
        existing_seeds=existing_public_profile.get("public_response_seeds"),
    )
    conversation_profile = _build_conversation_profile(
        display_name=display_name,
        occupation=_build_occupation(
            {
                "occupation": existing_public_profile.get("occupation") or settings.get("occupation"),
                "role": role,
                "organization": organization,
                "headline": normalized["headline"] or settings.get("headline"),
            },
            expertise,
        ),
        short_description=normalized["short_description"] or _first_sentence(normalized["bio"]) or normalized["bio"],
        expertise=expertise,
        speaking_style=normalized["speaking_style"],
        existing_profile=existing_public_profile.get("conversation_profile"),
    )

    public_profile = {
        **existing_public_profile,
        "display_name": display_name,
        "role": role,
        "organization": organization,
        "occupation": _build_occupation(
            {
                "occupation": existing_public_profile.get("occupation") or settings.get("occupation"),
                "role": role,
                "organization": organization,
                "headline": normalized["headline"] or settings.get("headline"),
            },
            expertise,
        ),
        "headline": normalized["headline"],
        "bio": normalized["bio"],
        "short_description": normalized["short_description"] or _first_sentence(normalized["bio"]) or normalized["bio"],
        "avatar_url": _clean_text(normalized.get("avatar_url")) or image_url,
        "image_url": image_url,
        "pinned_questions": normalized["pinned_questions"],
        "social_links": social_links,
        "areas_of_expertise": expertise,
        "key_achievements": normalized["key_achievements"],
        "contributions": normalized["contributions"],
        "personality_traits": normalized["personality_traits"],
        "speaking_style": normalized["speaking_style"],
        "conversation_profile": conversation_profile,
        "public_response_seeds": public_response_seeds,
        "education": normalized["education"],
        "work_experience": normalized["work_experience"],
        "birth_year": normalized["birth_year"],
        "death_year": normalized["death_year"],
        "nationality": normalized["nationality"],
        "verified_profile": bool(normalized.get("verified_profile")),
    }
    public_profile_meta = _build_public_profile_meta(
        source_flow=source_flow,
        materialized_at=_clean_text(existing_meta.get("materialized_at")) or _iso_now(),
        public_profile=public_profile,
        image_resolution=image_resolution,
        existing_meta=existing_meta,
    )
    identity_pack = {
        **existing_identity_pack,
        "display_name": display_name,
        "preferred_name": _clean_text(existing_identity_pack.get("preferred_name")) or display_name,
        "role": role or _clean_text(existing_identity_pack.get("role")),
        "current_role": role or _clean_text(existing_identity_pack.get("current_role")),
        "organization": organization or _clean_text(existing_identity_pack.get("organization")),
        "current_company": organization or _clean_text(existing_identity_pack.get("current_company")),
        "headline": normalized["headline"] or _clean_text(existing_identity_pack.get("headline")),
        "summary": normalized["short_description"] or normalized["bio"] or _clean_text(existing_identity_pack.get("summary")),
        "biography": normalized["bio"] or _clean_text(existing_identity_pack.get("biography")),
        "expertise_areas": expertise,
        "social_links": social_links,
        "preferred_contact_channel": (
            _clean_text(existing_identity_pack.get("preferred_contact_channel"))
            or next(iter(social_links.keys()), "")
        ),
    }
    return {
        "public_profile": public_profile,
        "persona_identity_pack": identity_pack,
        "public_profile_meta": public_profile_meta,
        "tagline": normalized["headline"],
        "public_intro": normalized["short_description"] or normalized["bio"],
        "description": normalized["short_description"] or normalized["bio"],
        "specialization": expertise[0] if expertise else role,
    }


# Security (C1): raw dossier / PII fields that must NEVER appear in an anonymous
# public response. The redactor starts from the full pack, so anything not
# explicitly emptied passes through — these are stripped unconditionally. The
# public profile needs name/headline/bio/avatar/expertise/pinned_questions/
# social_links, not the scraped life dossier or auto-generated answer seeds.
_PUBLIC_PII_DENYLIST = frozenset({
    "birth_year",
    "death_year",
    "nationality",
    "date_of_birth",
    "dob",
    # NOTE: work_experience / education are NOT denylisted — they are the
    # core of the portfolio page. They are emitted as curated, sub-field
    # whitelisted entries gated by section_visibility (see
    # _PUBLIC_STRUCTURED_SECTIONS below). employment_history remains denied:
    # it is the raw dossier alias, never the curated projection.
    "employment_history",
    "speaking_style",
    "conversation_profile",
    "public_response_seeds",
    "response_seeds",
    "persona_profile",
    "persona",
    "raw_persona",
    # Owner-only profile-extraction review flags. This is internal metadata
    # used by the owner-confirm review card; it must NEVER reach an
    # unauthenticated public/shared profile response. Default-deny.
    "extraction_review",
    "email",
    "phone",
    "phone_number",
})

# Structured portfolio sections exposed publicly: only these sub-fields
# survive redaction, so a malformed or over-enriched entry can never leak
# extra keys into the anonymous response.
_PUBLIC_STRUCTURED_SECTIONS: dict[str, tuple[str, ...]] = {
    "work_experience": ("company", "role", "description", "start_year", "end_year", "period"),
    "education": ("institution", "degree", "field", "start_year", "end_year", "period"),
}

# Allowed public-page layout themes. SINGLE SOURCE OF TRUTH: routers/profile.py
# builds its write-validator regex from this set, and the redactor below only
# emits a theme_id that is in this set (default-deny). Add new ids here when
# shipping a new layout (see the persona-themes package).
ALLOWED_THEME_IDS: frozenset[str] = frozenset(
    {"classic", "founder-site", "conversion-warm", "editorial", "split", "site"}
)
# Curated public-page accent swatches (default-deny, like theme_id). The
# frontend maps these ids to AA-safe hex via ACCENT_HEX.
ALLOWED_ACCENTS: frozenset[str] = frozenset(
    {"blue", "orange", "forest", "violet", "slate", "crimson"}
)


def redact_public_profile_pack_for_public_response(
    profile_pack: dict[str, Any],
    twin_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the anonymous/public-safe view of a profile pack."""
    sanitized = dict(_safe_dict(profile_pack))
    settings = _safe_dict(twin_settings)
    profile_settings = _safe_dict(sanitized.get("settings"))
    section_visibility = _safe_dict(settings.get("section_visibility") or profile_settings.get("section_visibility"))
    stored_public_profile = _safe_dict(settings.get("public_profile"))
    social_link_visibility = _safe_dict(
        stored_public_profile.get("social_link_visibility")
        or sanitized.get("social_link_visibility")
    )

    def _section_visible(section_name: str) -> bool:
        return section_visibility.get(section_name) is not False

    for section_name in (
        "areas_of_expertise",
        "key_achievements",
        "personality_traits",
        "contributions",
        "pinned_questions",
    ):
        sanitized[section_name] = list(_safe_list(sanitized.get(section_name))) if _section_visible(section_name) else []

    # Structured portfolio sections (work_experience, education): visibility-
    # gated like the lists above, and each entry is reduced to the public
    # sub-field whitelist so nothing beyond the curated projection leaks.
    for section_name, allowed_keys in _PUBLIC_STRUCTURED_SECTIONS.items():
        if not _section_visible(section_name):
            sanitized[section_name] = []
            continue
        sanitized[section_name] = [
            {key: entry[key] for key in allowed_keys if key in entry}
            for entry in _safe_list(sanitized.get(section_name))
            if isinstance(entry, dict)
        ]

    if _section_visible("featured_content"):
        sanitized["featured_content"] = [
            dict(item)
            for item in _safe_list(sanitized.get("featured_content"))
            if isinstance(item, dict) and item.get("hidden") is not True
        ]
    else:
        sanitized["featured_content"] = []

    # Owner-approved AEO FAQ. NEW leak-safe field: defaults to [] and is NEVER
    # seeded from response_seeds. Honor section_visibility['faq'] like the other
    # sections, and re-run the {question, answer} whitelist so a row stored raw
    # (or over-enriched) can never leak extra keys or inline source refs into the
    # anonymous response.
    if _section_visible("faq"):
        sanitized["public_faq"] = _sanitize_public_faq(sanitized.get("public_faq"))
    else:
        sanitized["public_faq"] = []

    if _section_visible("social_links"):
        social_links = _safe_dict(sanitized.get("social_links"))
        visible_social_links = {
            platform: url
            for platform, url in social_links.items()
            if social_link_visibility.get(platform) is not False
        }
        sanitized["social_links"] = visible_social_links
        sanitized["social_link_visibility"] = {
            platform: visible
            for platform, visible in social_link_visibility.items()
            if platform in visible_social_links and visible is not False
        }
    else:
        sanitized["social_links"] = {}
        sanitized["social_link_visibility"] = {}

    sanitized.pop("voice_id", None)
    sanitized["voice_capabilities"] = _safe_dict(
        sanitized.get("voice_capabilities")
    ) or _build_voice_capabilities(settings)
    _raw_theme_id = stored_public_profile.get("theme_id")
    _raw_accent = stored_public_profile.get("accent")
    sanitized["settings"] = {
        "subscription_tier": profile_settings.get("subscription_tier", settings.get("subscription_tier", "free")),
        "section_visibility": section_visibility,
        "show_branding": profile_settings.get("show_branding", settings.get("show_branding")),
        "theme_id": _raw_theme_id if _raw_theme_id in ALLOWED_THEME_IDS else None,
        "accent": _raw_accent if _raw_accent in ALLOWED_ACCENTS else None,
    }

    # Security (C1): unconditionally strip raw dossier / PII fields. Default-deny —
    # never rely on section_visibility (which defaults to visible) for these.
    for _field in _PUBLIC_PII_DENYLIST:
        sanitized.pop(_field, None)
    return sanitized


# ---------------------------------------------------------------------------
# build_public_profile_pack (main public API)
# ---------------------------------------------------------------------------

def build_public_profile_pack(twin: dict[str, Any]) -> dict[str, Any]:
    profile = normalize_public_profile(twin)
    settings = _safe_dict(profile.get("settings"))
    identity_pack = _safe_dict(settings.get("persona_identity_pack"))
    profile_meta = _safe_dict(profile.get("public_profile_meta"))
    twin_id = str(twin.get("id") or "")

    answerability_score = _fetch_answerability_score(twin_id)
    verified_claims_count = _fetch_verified_claim_count(twin_id)
    public_topics = _fetch_public_topics(twin_id)
    claims = _fetch_public_claims(twin_id)
    timeline_events = _fetch_timeline_events(twin_id)
    style_profile = _fetch_style_profile(twin_id)

    birth_year, death_year, nationality = _identity_stat_from_claims(claims)
    birth_year = birth_year or profile.get("birth_year")
    death_year = death_year or profile.get("death_year")
    nationality = nationality or profile.get("nationality")
    expertise = _build_expertise(profile, identity_pack, public_topics)

    # Extract subscription_tier from twin settings for frontend tier-aware rendering
    twin_settings = _safe_dict(twin.get("settings"))
    subscription_tier = twin_settings.get("subscription_tier", "free") or "free"
    section_visibility = _safe_dict(twin_settings.get("section_visibility"))

    # Extract pre-compiled public_response_seeds from stored settings (read-only, no recomputation)
    stored_public_profile = _safe_dict(settings.get("public_profile"))
    public_response_seeds = _safe_list(stored_public_profile.get("public_response_seeds"))

    # Bug 8 fix: only check calendar connection when the owner has actually
    # opted in to showing the booking button on their public profile. Saves
    # one supabase query per public profile fetch for the 99%+ of profiles
    # that don't use booking.
    booking_enabled = bool(stored_public_profile.get("show_booking_button"))
    booking_connected = _check_calendar_connected(twin_id) if booking_enabled else False

    return {
        "id": twin_id,
        "name": profile["display_name"],
        "occupation": _build_occupation(profile, expertise),
        "headline": profile["headline"],
        "bio": profile["bio"],
        "short_description": profile["short_description"] or _first_sentence(profile["bio"]) or profile["bio"],
        "avatar_url": profile["image_url"] or profile["avatar_url"],
        "image_url": profile["image_url"] or profile["avatar_url"],
        "birth_year": birth_year,
        "death_year": death_year,
        "nationality": nationality,
        "verified_profile": bool(profile.get("verified_profile")),
        "answerability_score": answerability_score,
        "verified_claims_count": verified_claims_count,
        "public_topics": public_topics,
        "areas_of_expertise": expertise,
        "personality_traits": _build_personality_traits(profile, identity_pack, style_profile),
        "key_achievements": _build_key_achievements(profile, claims, timeline_events),
        "contributions": _build_contributions(profile, claims, timeline_events),
        "speaking_style": _build_speaking_style(profile, identity_pack, style_profile),
        "social_links": profile["social_links"],
        "education": _build_education_entries(claims, timeline_events, profile.get("education")),
        "work_experience": _build_work_entries(claims, timeline_events, profile.get("work_experience")),
        "pinned_questions": profile["pinned_questions"],
        # Owner-approved AEO FAQ. Read ONLY from the explicit owner field
        # settings.public_profile.public_faq (default []); NEVER seeded from
        # public_response_seeds / response_seeds. The redactor re-whitelists this
        # at the public boundary (section_visibility['faq'] + {question, answer}).
        "public_faq": _sanitize_public_faq(stored_public_profile.get("public_faq")),
        "public_response_seeds": public_response_seeds[:5],  # Limit to 5 for detail page display
        "featured_content": _safe_list(profile.get("featured_content")),
        "conversation_profile": _safe_dict(profile.get("conversation_profile")),
        "mind_label": profile["mind_label"],
        "profile_meta": profile_meta,
        "completeness_score": profile_meta.get("completeness_score"),
        "subscription_tier": subscription_tier,
        "has_voice": bool(twin_settings.get("voice_id")),
        "voice_capabilities": _build_voice_capabilities(twin_settings),
        "booking": {
            "enabled": booking_enabled,
            "connected": booking_connected,
        },
        "settings": {
            "subscription_tier": subscription_tier,
            "section_visibility": section_visibility,
            "show_branding": twin_settings.get("show_branding"),
            "voice_id": twin_settings.get("voice_id"),
        },
        "social_link_visibility": _safe_dict(stored_public_profile.get("social_link_visibility")),
        "extra": {},
        "created_at": twin.get("created_at"),
        "updated_at": twin.get("updated_at"),
    }
