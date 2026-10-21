"""Marketplace persona payload and conversation profile builders."""
from __future__ import annotations

from typing import Any

from modules.profile_utils import (
    _clean_text,
    _clean_unique_strings,
    _coerce_score_percent,
    _first_sentence,
    _safe_dict,
    _safe_list,
)


def _build_occupation(profile: dict[str, Any], expertise: list[str] | None = None) -> str:
    explicit_occupation = _clean_text(profile.get("occupation"))
    if explicit_occupation:
        return explicit_occupation
    role = _clean_text(profile.get("role"))
    organization = _clean_text(profile.get("organization"))
    headline = _clean_text(profile.get("headline"))
    if role and organization:
        return f"{role} at {organization}"
    if role:
        return role
    if headline:
        return headline
    if expertise:
        return ", ".join(expertise[:3])
    return "Public persona"


def _build_conversation_profile(
    *,
    display_name: str,
    occupation: str,
    short_description: str,
    expertise: list[str],
    speaking_style: str,
    existing_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing = _safe_dict(existing_profile)
    help_areas = _clean_unique_strings(
        existing.get("help_areas") or existing.get("areas") or expertise,
        limit=6,
    )
    if help_areas:
        if len(help_areas) == 1:
            capability_intro = f"I can help with {help_areas[0]}."
        elif len(help_areas) == 2:
            capability_intro = f"I can help with {help_areas[0]} and {help_areas[1]}."
        else:
            capability_intro = (
                f"I can help with {help_areas[0]}, {help_areas[1]}, {help_areas[2]}, and more."
            )
    elif occupation:
        capability_intro = f"I can help from my perspective as {occupation}."
    else:
        capability_intro = "I can help you think through the topics I am known for."

    greeting = (
        _clean_text(existing.get("greeting"))
        or f"Hi, it's {display_name}'s AI. {capability_intro} What would you like to dig into?"
    )
    authenticity_disclosure = (
        _clean_text(existing.get("authenticity_disclosure"))
        or (
            f"I'm a digital mind based on public information about {display_name}. "
            "I can share the perspective captured here, but I am not the real person."
        )
    )

    return {
        "greeting": greeting,
        "help_areas": help_areas,
        "capability_intro": _clean_text(existing.get("capability_intro")) or capability_intro,
        "authenticity_disclosure": authenticity_disclosure,
        "tone": _clean_text(existing.get("tone")) or speaking_style or "direct and conversational",
        "summary": _clean_text(existing.get("summary")) or short_description,
    }


def build_marketplace_persona_payload(
    twin: dict[str, Any],
    *,
    public_topics: list[dict[str, Any]] | None = None,
    answerability_score: float = 0.0,
    verified_claims_count: int = 0,
) -> dict[str, Any]:
    from modules.public_profile_pack import normalize_public_profile

    profile = normalize_public_profile(twin)
    identity_pack = _safe_dict(profile.get("settings", {}).get("persona_identity_pack"))
    profile_meta = _safe_dict(profile.get("public_profile_meta"))
    topics = public_topics or []
    expertise = _build_expertise(profile, identity_pack, topics)
    short_description = _first_sentence(profile.get("bio")) or _clean_text(profile.get("bio"))

    return {
        "twin_id": twin.get("id"),
        "display_name": profile["display_name"],
        "occupation": _build_occupation(profile, expertise),
        "headline": profile["headline"],
        "bio": profile["bio"],
        "short_description": profile["short_description"] or short_description,
        "avatar_url": profile["image_url"] or profile["avatar_url"],
        "organization": profile["organization"],
        "role": profile["role"],
        "mind_label": profile["mind_label"],
        "answerability_score": _coerce_score_percent(answerability_score),
        "verified_claims_count": int(verified_claims_count or 0),
        "public_topics": topics,
        "areas_of_expertise": expertise,
        "personality_traits": _build_personality_traits(profile, identity_pack, {}),
        "pinned_questions": profile["pinned_questions"],
        "handle": profile["handle"],
        "verified_profile": bool(profile.get("verified_profile")),
        "nationality": _clean_text(profile.get("nationality")) or "",
        "profile_meta": profile_meta,
        "completeness_score": profile_meta.get("completeness_score"),
    }


# ---------------------------------------------------------------------------
# Helpers also used by the core build_public_profile_pack
# ---------------------------------------------------------------------------

def _build_expertise(profile: dict[str, Any], identity_pack: dict[str, Any], public_topics: list[dict[str, Any]]) -> list[str]:
    seeded = _safe_list(profile.get("areas_of_expertise"))
    identity = _safe_list(identity_pack.get("expertise_areas"))
    topic_names = [topic.get("name") for topic in public_topics]
    return _clean_unique_strings([*seeded, *identity, *topic_names], limit=6)


def _build_personality_traits(profile: dict[str, Any], identity_pack: dict[str, Any], style_profile: dict[str, Any]) -> list[str]:
    seeded = _safe_list(profile.get("personality_traits"))
    tone_tags = _safe_list(identity_pack.get("tone_tags"))
    style_tags = _safe_list(style_profile.get("tone_descriptors"))
    return _clean_unique_strings([*seeded, *tone_tags, *style_tags], limit=6)
