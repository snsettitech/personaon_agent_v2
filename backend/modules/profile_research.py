"""Research-based profile projection builders for public profiles."""
from __future__ import annotations

import re
from typing import Any

from modules.profile_utils import (
    _clean_text,
    _clean_unique_strings,
    _coerce_year,
    _first_sentence,
    _iso_now,
    _safe_dict,
    _safe_list,
    _social_key_from_url,
    generate_contextual_questions,
    normalize_social_links,
    _build_public_profile_meta,
)
from modules.profile_image import _resolve_profile_image


# ---------------------------------------------------------------------------
# Deduplication helper (also used by core module)
# ---------------------------------------------------------------------------

def _dedupe_object_rows(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            # Defensive: settings.public_profile.{work_experience,education} is
            # unvalidated Dict[str, Any] from PATCH /twins/{id} (routers/twins.py),
            # so a malformed row (e.g. a bare string) must not crash callers like
            # normalize_public_profile / build_public_profile_pack.
            continue
        normalized = {
            key: _clean_text(row.get(key)) if isinstance(row.get(key), str) else row.get(key)
            for key in row
        }
        dedupe_key = tuple(str(normalized.get(key) or "").lower() for key in keys)
        if not any(dedupe_key):
            continue
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(normalized)
    return deduped[:6]


# ---------------------------------------------------------------------------
# Work & education entry builders
# ---------------------------------------------------------------------------

def _build_work_entries(
    claims: list[dict[str, Any]],
    timeline_events: list[dict[str, Any]],
    seeded: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = list(seeded or [])

    for event in timeline_events:
        event_type = _clean_text(event.get("event_type")).lower()
        if event_type and not event_type.startswith("job") and event_type not in {"founded_company", "board_role", "investment"}:
            continue
        company = _clean_text(event.get("organization"))
        role = _clean_text(event.get("role_title")) or _clean_text(event.get("title"))
        description = _clean_text(event.get("description"))
        if not company and not role:
            continue
        entries.append(
            {
                "company": company,
                "role": role,
                "description": description,
                "start_year": _coerce_year(event.get("start_date")),
                "end_year": _coerce_year(event.get("end_date")),
            }
        )

    for claim in claims:
        if claim.get("claim_type") != "work_experience":
            continue
        meta = _claim_meta(claim)
        claim_text = _clean_text(claim.get("claim_text"))
        role = _clean_text(meta.get("role") or meta.get("role_title"))
        company = _clean_text(meta.get("company") or meta.get("organization"))
        if not role or not company:
            match = re.search(r"(?:a|an)\s+([^,.]+?)\s+(?:at|with)\s+([^,.]+)", claim_text, re.IGNORECASE)
            if match:
                role = role or _clean_text(match.group(1))
                company = company or _clean_text(match.group(2))
        if not role and not company:
            continue
        entries.append(
            {
                "company": company,
                "role": role,
                "description": claim_text,
                "start_year": _coerce_year(meta.get("start_year")) or _coerce_year(claim.get("claim_time_start")),
                "end_year": _coerce_year(meta.get("end_year")) or _coerce_year(claim.get("claim_time_end")),
            }
        )

    return _dedupe_object_rows(entries, ("company", "role"))


def _build_education_entries(
    claims: list[dict[str, Any]],
    timeline_events: list[dict[str, Any]],
    seeded: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = list(seeded or [])

    for event in timeline_events:
        event_type = _clean_text(event.get("event_type")).lower()
        if not event_type.startswith("education"):
            continue
        institution = _clean_text(event.get("organization"))
        degree = _clean_text(event.get("title"))
        if not institution and not degree:
            continue
        entries.append(
            {
                "institution": institution,
                "degree": degree,
                "field": "",
                "start_year": _coerce_year(event.get("start_date")),
                "end_year": _coerce_year(event.get("end_date")),
            }
        )

    for claim in claims:
        if claim.get("claim_type") != "education":
            continue
        meta = _claim_meta(claim)
        institution = _clean_text(meta.get("institution") or meta.get("school"))
        degree = _clean_text(meta.get("degree"))
        field = _clean_text(meta.get("field") or meta.get("major") or meta.get("subject"))
        if not institution:
            claim_text = _clean_text(claim.get("claim_text"))
            match = re.search(r"(?:from|at)\s+([^,.]+)", claim_text, re.IGNORECASE)
            if match:
                institution = _clean_text(match.group(1))
        if not institution and not degree and not field:
            continue
        entries.append(
            {
                "institution": institution,
                "degree": degree,
                "field": field,
                "start_year": _coerce_year(meta.get("start_year")) or _coerce_year(claim.get("claim_time_start")),
                "end_year": _coerce_year(meta.get("end_year")) or _coerce_year(claim.get("claim_time_end")),
            }
        )

    return _dedupe_object_rows(entries, ("institution", "degree", "field"))


# ---------------------------------------------------------------------------
# Claim metadata helper
# ---------------------------------------------------------------------------

def _claim_meta(row: dict[str, Any]) -> dict[str, Any]:
    return _safe_dict(row.get("metadata_json"))


# ---------------------------------------------------------------------------
# Research key achievements & contributions
# ---------------------------------------------------------------------------

def _build_research_key_achievements(
    result: dict[str, Any],
    existing_values: list[str] | None = None,
) -> list[str]:
    seeded = list(existing_values or [])
    claims = [
        _first_sentence(_safe_dict(claim).get("text"))
        for claim in _safe_list(result.get("claims"))
        if _clean_text(_safe_dict(claim).get("claim_type")).lower() in {"credential", "role"}
        and _clean_text(_safe_dict(claim).get("status")).lower() not in {"disputed", "unverified"}
    ]
    return _clean_unique_strings([*seeded, *claims], limit=6)


def _build_research_contributions(
    result: dict[str, Any],
    existing_values: list[str] | None = None,
) -> list[str]:
    seeded = list(existing_values or [])
    claims = [
        _first_sentence(_safe_dict(claim).get("text"))
        for claim in _safe_list(result.get("claims"))
        if _clean_text(_safe_dict(claim).get("claim_type")).lower() in {"project", "experience", "opinion"}
        and _clean_text(_safe_dict(claim).get("status")).lower() not in {"disputed"}
    ]
    timeline = [_first_sentence(_safe_dict(item).get("event")) for item in _safe_list(result.get("timeline"))]
    return _clean_unique_strings([*seeded, *claims, *timeline], limit=6)


# ---------------------------------------------------------------------------
# Birth/death/nationality inference
# ---------------------------------------------------------------------------

def _infer_birth_death_nationality(
    result: dict[str, Any],
    existing_profile: dict[str, Any],
) -> tuple[int | None, int | None, str]:
    birth_year = _coerce_year(existing_profile.get("birth_year"))
    death_year = _coerce_year(existing_profile.get("death_year"))
    nationality = _clean_text(existing_profile.get("nationality"))

    texts = [
        _safe_dict(result.get("bio")).get("short"),
        _safe_dict(result.get("bio")).get("medium"),
        *[_safe_dict(claim).get("text") for claim in _safe_list(result.get("claims"))],
    ]
    for raw_text in texts:
        text = _clean_text(raw_text)
        if not text:
            continue
        if birth_year is None:
            born_match = re.search(r"\bborn\b[^0-9]{0,24}((?:18|19|20)\d{2})", text, re.IGNORECASE)
            if born_match:
                birth_year = int(born_match.group(1))
        if death_year is None:
            died_match = re.search(r"\bdied\b[^0-9]{0,24}((?:18|19|20)\d{2})", text, re.IGNORECASE)
            if died_match:
                death_year = int(died_match.group(1))
        if not nationality:
            nationality_match = re.search(
                r"\b(?:an?|the)\s+([A-Z][a-z]+)\s+(?:politician|businessman|businesswoman|leader|entrepreneur|executive|actor|author|economist|scientist|citizen|national)\b",
                text,
            )
            if nationality_match:
                nationality = nationality_match.group(1)
    return birth_year, death_year, nationality


# ---------------------------------------------------------------------------
# Research education & work history (from research result format)
# ---------------------------------------------------------------------------

def _extract_research_expertise(profile_summary: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for item in _safe_list(profile_summary.get("expertise_topics")):
        if isinstance(item, dict):
            values.append(item.get("topic"))
        else:
            values.append(item)
    return _clean_unique_strings(values, limit=6)


def _extract_research_years(text: Any) -> tuple[int | None, int | None]:
    normalized = _clean_text(text)
    years = re.findall(r"\b(?:18|19|20)\d{2}\b", normalized)
    if not years:
        return None, None
    start_year = int(years[0])
    end_year = int(years[1]) if len(years) > 1 else None
    return start_year, end_year


def _extract_social_links_from_research(
    result: dict[str, Any],
    *,
    existing_links: Any = None,
) -> dict[str, str]:
    links = normalize_social_links(existing_links)

    input_data = _safe_dict(result.get("input"))
    hints = _safe_dict(input_data.get("hints"))
    website_hint = _clean_text(hints.get("website"))
    if website_hint:
        links.setdefault(_social_key_from_url(website_hint), website_hint)

    sources = sorted(
        _safe_list(result.get("sources")),
        key=lambda row: (
            not bool(_safe_dict(row).get("used_in_final")),
            -float(_safe_dict(row).get("identity_match_confidence") or 0.0),
        ),
    )
    for raw_source in sources:
        source = _safe_dict(raw_source)
        url = _clean_text(source.get("url"))
        if not url:
            continue
        source_type = _clean_text(source.get("source_type")).lower()
        key = _social_key_from_url(url)
        if key == "website" and source_type not in {"website", "profile"}:
            continue
        links.setdefault(key, url)
        if len(links) >= 6:
            break
    return links


def _parse_education_entry_from_text(text: Any) -> dict[str, Any] | None:
    normalized = _clean_text(text)
    if not normalized:
        return None

    degree_match = re.search(
        r"\b(BA|B\.A\.|BS|B\.S\.|BSc|Bachelor(?: of [^,.]+)?|MA|M\.A\.|MS|M\.S\.|MSc|MBA|Master(?: of [^,.]+)?|PhD|Ph\.D\.|Doctorate|JD)\b[^,.]*",
        normalized,
        re.IGNORECASE,
    )
    institution_match = re.search(
        r"(?:from|at)\s+([^,.]*(?:University|College|School|Institute|Academy)[^,.]*)",
        normalized,
        re.IGNORECASE,
    )
    field_match = re.search(r"\bin\s+([^,.]{3,80})", normalized, re.IGNORECASE)

    institution = _clean_text(institution_match.group(1)) if institution_match else ""
    degree = _clean_text(degree_match.group(0)) if degree_match else ""
    field = _clean_text(field_match.group(1)) if field_match else ""
    if degree:
        degree = re.split(r"\s+from\s+", degree, maxsplit=1, flags=re.IGNORECASE)[0]
        degree = re.sub(r"\s+in\s+(?:18|19|20)\d{2}\b.*$", "", degree, flags=re.IGNORECASE)
    if field:
        field = re.split(r"\s+from\s+|\s+at\s+", field, maxsplit=1, flags=re.IGNORECASE)[0]
    if institution:
        institution = re.sub(r"\s+in\s+(?:18|19|20)\d{2}\b.*$", "", institution, flags=re.IGNORECASE)
    start_year, end_year = _extract_research_years(normalized)

    if not institution and not degree and not field:
        return None

    return {
        "institution": institution,
        "degree": degree,
        "field": field,
        "start_year": start_year,
        "end_year": end_year,
    }


def _parse_work_entry_from_text(text: Any) -> dict[str, Any] | None:
    normalized = _clean_text(text)
    if not normalized:
        return None

    role = ""
    company = ""
    for pattern in (
        r"(?:served as|worked as|joined as|appointed as|elected as|became)\s+([^,.]+?)\s+(?:at|with|for|of)\s+([^,.]+)",
        r"(?:a|an)\s+([^,.]+?)\s+(?:at|with)\s+([^,.]+)",
        r"([^,.]+?)\s+(?:at|with|for|of)\s+([^,.]+)",
    ):
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            role = _clean_text(match.group(1))
            company = _clean_text(match.group(2))
            break
    if company:
        company = re.sub(r"\s+(?:from|since)\s+(?:18|19|20)\d{2}\b.*$", "", company, flags=re.IGNORECASE)

    start_year, end_year = _extract_research_years(normalized)
    if not role and not company and len(normalized) < 18:
        return None

    return {
        "company": company,
        "role": role,
        "description": normalized,
        "start_year": start_year,
        "end_year": end_year,
    }


def _looks_like_work_event(text: Any) -> bool:
    normalized = _clean_text(text).lower()
    if not normalized:
        return False
    if _parse_education_entry_from_text(normalized):
        return False
    return any(
        token in normalized
        for token in (
            " at ",
            " with ",
            " for ",
            " served as ",
            " worked as ",
            " joined ",
            " appointed ",
            " elected ",
            " became ",
            " minister",
            " ceo",
            " founder",
            " director",
            " president",
            " engineer",
        )
    )


def _build_research_education(result: dict[str, Any], existing_rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = list(existing_rows or [])
    for claim in _safe_list(result.get("claims")):
        claim_dict = _safe_dict(claim)
        if _clean_text(claim_dict.get("claim_type")).lower() != "credential":
            continue
        parsed = _parse_education_entry_from_text(claim_dict.get("text"))
        if parsed:
            entries.append(parsed)

    for item in _safe_list(result.get("timeline")):
        parsed = _parse_education_entry_from_text(_safe_dict(item).get("event"))
        if parsed:
            if parsed.get("start_year") is None:
                parsed["start_year"] = _coerce_year(_safe_dict(item).get("date_or_range"))
            if parsed.get("end_year") is None:
                parsed["end_year"] = _coerce_year(_safe_dict(item).get("date_or_range"))
            entries.append(parsed)

    return _dedupe_object_rows(entries, ("institution", "degree", "field"))


def _build_research_work_history(result: dict[str, Any], existing_rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = list(existing_rows or [])
    for claim in _safe_list(result.get("claims")):
        claim_dict = _safe_dict(claim)
        claim_type = _clean_text(claim_dict.get("claim_type")).lower()
        if claim_type not in {"experience", "role", "project"}:
            continue
        parsed = _parse_work_entry_from_text(claim_dict.get("text"))
        if parsed:
            entries.append(parsed)

    for item in _safe_list(result.get("timeline")):
        event_text = _safe_dict(item).get("event")
        if not _looks_like_work_event(event_text):
            continue
        parsed = _parse_work_entry_from_text(event_text)
        if parsed:
            if parsed.get("start_year") is None:
                parsed["start_year"] = _coerce_year(_safe_dict(item).get("date_or_range"))
            if parsed.get("end_year") is None:
                parsed["end_year"] = _coerce_year(_safe_dict(item).get("date_or_range"))
            entries.append(parsed)

    return _dedupe_object_rows(entries, ("company", "role", "description"))


# ---------------------------------------------------------------------------
# Headline builder from research
# ---------------------------------------------------------------------------

def _build_headline_from_research(
    role: str,
    organization: str,
    what_they_do: list[str],
    bio_text: str,
) -> str:
    if what_they_do:
        return _first_sentence(what_they_do[0]) or _clean_text(what_they_do[0])
    if role and organization:
        return f"{role} at {organization}"
    if role:
        return role
    return _first_sentence(bio_text)


# ---------------------------------------------------------------------------
# Main research projection builder
# ---------------------------------------------------------------------------

def build_research_profile_projection(
    twin: dict[str, Any],
    result: dict[str, Any],
    *,
    source_flow: str = "generated",
) -> dict[str, Any]:
    from modules.profile_marketplace import _build_occupation, _build_conversation_profile

    settings = _safe_dict(twin.get("settings"))
    existing_public_profile = _safe_dict(settings.get("public_profile"))
    existing_identity_pack = _safe_dict(settings.get("persona_identity_pack"))
    existing_meta = _safe_dict(settings.get("public_profile_meta"))
    claimed_identity = _safe_dict(result.get("claimed_identity"))
    profile_summary = _safe_dict(result.get("profile_summary"))
    bio = _safe_dict(result.get("bio"))

    display_name = (
        _clean_text(claimed_identity.get("canonical_name"))
        or _clean_text(existing_public_profile.get("display_name"))
        or _clean_text(twin.get("name"))
        or "Persona"
    )
    role = (
        _clean_text(existing_public_profile.get("role"))
        or _clean_text((_safe_list(profile_summary.get("public_roles")) or [""])[0])
    )
    organization = (
        _clean_text(existing_public_profile.get("organization"))
        or _clean_text((_safe_list(profile_summary.get("organizations")) or [""])[0])
    )
    bio_text = (
        _clean_text(existing_public_profile.get("bio"))
        or _clean_text(bio.get("medium"))
        or _clean_text(bio.get("short"))
        or _clean_text(twin.get("description"))
    )
    expertise = _clean_unique_strings(
        [
            *(_safe_list(existing_public_profile.get("areas_of_expertise")) or []),
            *_extract_research_expertise(profile_summary),
        ],
        limit=6,
    )
    what_they_do = _clean_unique_strings(profile_summary.get("what_they_do") or [], limit=4)
    headline = (
        _clean_text(existing_public_profile.get("headline"))
        or _build_headline_from_research(role, organization, what_they_do, bio_text)
    )
    occupation = _build_occupation(
        {
            "occupation": existing_public_profile.get("occupation"),
            "role": role,
            "organization": organization,
            "headline": headline,
        },
        expertise,
    )
    short_description = (
        _clean_text(existing_public_profile.get("short_description"))
        or _first_sentence(_clean_text(bio.get("short")))
        or _first_sentence(bio_text)
        or bio_text
    )
    fallback_questions = generate_contextual_questions(
        {
            "occupation": occupation,
            "organization": organization,
            "headline": headline,
            "work_experience": _build_research_work_history(result, _safe_list(existing_public_profile.get("work_experience"))),
            "key_achievements": _build_research_key_achievements(
                result,
                _safe_list(existing_public_profile.get("key_achievements")),
            ),
            "personality_traits": _clean_unique_strings(existing_public_profile.get("personality_traits") or [], limit=6),
            "areas_of_expertise": expertise,
        },
        limit=4,
    )
    pinned_questions = _clean_unique_strings(
        [
            *(_safe_list(existing_public_profile.get("pinned_questions")) or []),
            *(_safe_list(result.get("suggested_followup_questions")) or []),
            *[
                _safe_dict(item).get("question")
                for item in _safe_list(result.get("prepared_question_answers"))
            ],
            *fallback_questions,
        ],
        limit=4,
    )
    social_links = _extract_social_links_from_research(
        result,
        existing_links=existing_public_profile.get("social_links") or existing_identity_pack.get("social_links"),
    )
    education = _build_research_education(result, _safe_list(existing_public_profile.get("education")))
    work_experience = _build_research_work_history(result, _safe_list(existing_public_profile.get("work_experience")))
    key_achievements = _build_research_key_achievements(
        result,
        _safe_list(existing_public_profile.get("key_achievements")),
    )
    contributions = _build_research_contributions(
        result,
        _safe_list(existing_public_profile.get("contributions")),
    )
    birth_year, death_year, nationality = _infer_birth_death_nationality(result, existing_public_profile)
    materialized_at = (
        _clean_text(_safe_dict(result.get("crawl_stats")).get("run_completed_at"))
        or _clean_text(existing_meta.get("materialized_at"))
        or _iso_now()
    )
    image_resolution = _resolve_profile_image(result, existing_public_profile, existing_meta)

    # Import here to avoid circular dependency (this function is in profile_research
    # but _build_public_response_seeds stays in the core module)
    from modules.public_profile_pack import _build_public_response_seeds

    public_response_seeds = _build_public_response_seeds(
        result,
        display_name=display_name,
        public_profile={
            **existing_public_profile,
            "role": role,
            "organization": organization,
            "bio": bio_text,
            "contributions": contributions,
            "work_experience": work_experience,
        },
        existing_seeds=existing_public_profile.get("public_response_seeds"),
    )
    conversation_profile = _build_conversation_profile(
        display_name=display_name,
        occupation=occupation,
        short_description=short_description or bio_text,
        expertise=expertise,
        speaking_style=_clean_text(existing_public_profile.get("speaking_style")),
        existing_profile=existing_public_profile.get("conversation_profile"),
    )

    public_profile = {
        **existing_public_profile,
        "display_name": display_name,
        "role": role,
        "organization": organization,
        "occupation": occupation,
        "headline": headline,
        "bio": bio_text,
        "short_description": short_description,
        "avatar_url": (
            _clean_text(existing_public_profile.get("avatar_url"))
            or _clean_text(image_resolution.get("image_url"))
        ),
        "image_url": (
            _clean_text(image_resolution.get("image_url"))
            or _clean_text(existing_public_profile.get("image_url"))
            or _clean_text(existing_public_profile.get("avatar_url"))
        ),
        "pinned_questions": pinned_questions,
        "social_links": social_links,
        "areas_of_expertise": expertise,
        "key_achievements": key_achievements,
        "contributions": contributions,
        "personality_traits": _clean_unique_strings(existing_public_profile.get("personality_traits") or [], limit=6),
        "speaking_style": _clean_text(existing_public_profile.get("speaking_style")),
        "conversation_profile": conversation_profile,
        "public_response_seeds": public_response_seeds,
        "education": education,
        "work_experience": work_experience,
        "birth_year": birth_year,
        "death_year": death_year,
        "nationality": nationality,
        "verified_profile": bool(existing_public_profile.get("verified_profile")),
    }
    public_profile_meta = _build_public_profile_meta(
        source_flow=source_flow,
        materialized_at=materialized_at,
        public_profile=public_profile,
        image_resolution=image_resolution,
        existing_meta=existing_meta,
    )

    identity_pack = {
        **existing_identity_pack,
        "display_name": display_name,
        "preferred_name": display_name,
        "role": role,
        "current_role": role,
        "organization": organization,
        "current_company": organization,
        "headline": headline,
        "summary": short_description or bio_text,
        "biography": bio_text,
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
        "tagline": headline,
        "public_intro": short_description or bio_text,
        "description": short_description or bio_text,
        "specialization": expertise[0] if expertise else role,
    }
