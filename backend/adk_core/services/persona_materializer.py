"""Deterministic persona artifact materialization."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from adk_core.schemas.artifacts import PersonaArtifact, PersonaQuote, ResearchArtifact, VoiceDna
from adk_core.text_utils import normalize_text as _normalize_text, top_terms as _top_terms
from modules.profile_utils import generate_contextual_questions


def _signature_phrases(quotes: list[str], limit: int = 6) -> list[str]:
    phrases: list[str] = []
    for quote in quotes:
        clean = _normalize_text(quote)
        if not clean:
            continue
        if len(clean.split()) <= 12:
            phrases.append(clean)
        else:
            phrases.append(" ".join(clean.split()[:12]))
    deduped: list[str] = []
    seen = set()
    for phrase in phrases:
        lowered = phrase.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(phrase)
        if len(deduped) >= limit:
            break
    return deduped


def _derive_voice_dna(research: ResearchArtifact) -> VoiceDna:
    quotes = [item.quote for item in research.verified_quote_candidates if item.quote]
    claim_texts = [item.text for item in research.extracted_claims if item.text]
    all_texts = quotes + claim_texts

    sentence_lengths = [len(_normalize_text(text).split()) for text in quotes if text]
    avg_sentence_length = sum(sentence_lengths) / len(sentence_lengths) if sentence_lengths else 0.0

    sentence_style: list[str] = []
    if avg_sentence_length >= 26:
        sentence_style.append("long-form sentences with layered clauses")
    elif avg_sentence_length >= 15:
        sentence_style.append("medium-length sentences with balanced pacing")
    else:
        sentence_style.append("short sentences with direct cadence")

    tonal_traits = []
    summary = _normalize_text(research.synthesis_summary).lower()
    if any(token in summary for token in ("builder", "operator", "execution", "ship")):
        tonal_traits.append("operator-minded and execution oriented")
    if any(token in summary for token in ("research", "evidence", "prove", "data")):
        tonal_traits.append("evidence first and analytical")
    if any(token in summary for token in ("mentor", "coach", "teach", "help")):
        tonal_traits.append("teacherly and generous")
    if not tonal_traits:
        tonal_traits.append("measured and grounded")

    return VoiceDna(
        tonal_traits=tonal_traits,
        sentence_style=sentence_style,
        lexical_preferences=_top_terms(all_texts, limit=10),
        signature_phrases=_signature_phrases(quotes),
    )


def _build_public_profile(
    research: ResearchArtifact, subject_name: str, voice_dna: VoiceDna
) -> dict[str, object]:
    identity = research.subject_identity or {}
    roles = identity.get("public_roles") or []
    orgs = identity.get("organizations") or []
    bio = _normalize_text(research.synthesis_summary)

    # Split orgs into education vs workplace
    education_keywords = {
        "university", "college", "school", "institute", "academy",
        "isb", "iit", "iim", "nit", "nift", "mit", "stanford", "harvard",
        "wharton", "kellogg", "insead", "schulich", "rotman", "ivey",
        "alumna", "alumni", "alumnus",
    }
    education: list[dict[str, object]] = []
    work_orgs: list[str] = []
    for org in orgs:
        if any(kw in org.lower() for kw in education_keywords):
            education.append({"institution": org, "degree": "", "field": ""})
        else:
            work_orgs.append(org)

    # Build work_experience from non-education orgs + roles
    # Filter out descriptor-only roles (no company context)
    descriptor_keywords = {"founder", "intrapreneur", "entrepreneur", "serial", "investor", "advisor", "mentor"}
    work_experience: list[dict[str, object]] = []
    used_roles: set = set()
    for org in work_orgs:
        matching_roles = [r for r in roles if org.lower() in r.lower()]
        if matching_roles:
            for role in matching_roles:
                work_experience.append({"company": org, "role": role})
                used_roles.add(role)
        else:
            # Assign the first non-descriptor role
            for role in roles:
                if role not in used_roles and not any(kw in role.lower() for kw in descriptor_keywords):
                    work_experience.append({"company": org, "role": role})
                    used_roles.add(role)
                    break
            else:
                work_experience.append({"company": org, "role": ""})

    # Key achievements from high-confidence claims
    key_achievements: list[str] = []
    for claim in research.extracted_claims:
        if claim.confidence >= 0.7 and claim.claim_type in ("achievement", "fact", "role", "other"):
            text = _normalize_text(claim.text)
            if len(text) > 20 and len(text) < 200:
                key_achievements.append(text)
        if len(key_achievements) >= 5:
            break

    # Speaking style from voice DNA
    speaking_style = ""
    if voice_dna.tonal_traits:
        speaking_style = ". ".join(
            trait.capitalize() for trait in voice_dna.tonal_traits
        )
        if voice_dna.sentence_style:
            speaking_style += ". " + voice_dna.sentence_style[0].capitalize()

    # Pinned questions — conversation starters based on work, achievements, traits, and expertise
    expertise = identity.get("expertise_topics") or []

    # Personality traits from tonal traits
    personality_traits = [t.split(" and ")[0].strip() for t in voice_dna.tonal_traits]

    # Location → nationality
    locations = identity.get("locations") or []
    nationality = ""
    if locations:
        loc = locations[0]
        for country in ["India", "Canada", "United States", "UK", "Australia", "Singapore"]:
            if country.lower() in loc.lower():
                nationality = country
                break
        if not nationality:
            nationality = loc

    public_profile = {
        "name": identity.get("canonical_name") or subject_name,
        "bio": bio,
        "occupation": roles[0] if roles else "",
        "headline": ", ".join(roles)[:240],
        "locations": locations,
        "organizations": orgs,
        "expertise_topics": expertise,
        # LinkedIn-style fields
        "areas_of_expertise": expertise,
        "work_experience": work_experience,
        "education": education,
        "key_achievements": key_achievements,
        "personality_traits": personality_traits,
        "speaking_style": speaking_style,
        "nationality": nationality,
        "citations_enabled": True,
    }
    public_profile["pinned_questions"] = generate_contextual_questions(
        {
            **public_profile,
            "occupation": public_profile.get("occupation") or public_profile.get("headline"),
        },
        limit=4,
    )
    return public_profile


def _build_identity_pack(public_profile: dict[str, object], voice_dna: VoiceDna) -> dict[str, object]:
    return {
        "name": public_profile.get("name"),
        "headline": public_profile.get("headline"),
        "bio": public_profile.get("bio"),
        "signature_phrases": voice_dna.signature_phrases,
        "tonal_traits": voice_dna.tonal_traits,
        "lexical_preferences": voice_dna.lexical_preferences,
    }


def _build_thinking_style(research: ResearchArtifact) -> dict[str, object]:
    claim_types = Counter(item.claim_type for item in research.extracted_claims if item.claim_type)
    dominant = [name for name, _count in claim_types.most_common(3)]
    if not dominant:
        dominant = ["operator"]
    return {
        "dominant_modes": dominant,
        "summary": _normalize_text(research.synthesis_summary),
    }


def _build_values(research: ResearchArtifact) -> list[str]:
    values: list[str] = []
    summary = _normalize_text(research.synthesis_summary).lower()
    if "trust" in summary or "credibility" in summary:
        values.append("opt for credibility over performative certainty")
    if "product" in summary or "builder" in summary:
        values.append("prefer shipping and iteration over abstract posturing")
    if "research" in summary or "evidence" in summary:
        values.append("show the evidence behind the conclusion")
    if not values:
        values.append("prefer clear evidence and concrete language")
    return values


def _build_communication_rules(research: ResearchArtifact, voice_dna: VoiceDna) -> list[str]:
    rules = [
        "Stay in the first-person voice of the subject.",
        "Sound like the subject, not like a generic assistant.",
        "Prefer grounded specifics over generic reassurance.",
    ]
    if voice_dna.signature_phrases:
        rules.append("Echo the subject's signature phrasing when it feels natural.")
    if research.verified_quote_candidates:
        rules.append("Use verified quotes as texture, not as constant direct quotation.")
    return rules


def materialize_persona_artifact(
    *,
    twin_id: str,
    research_artifact: ResearchArtifact,
) -> PersonaArtifact:
    subject_identity = research_artifact.subject_identity or {}
    subject_name = subject_identity.get("canonical_name") or subject_identity.get("name") or twin_id
    voice_dna = _derive_voice_dna(research_artifact)

    quote_pack = [
        PersonaQuote(
            quote=item.quote,
            source_id=item.source_id,
            confidence=item.confidence,
            context=item.context,
        )
        for item in research_artifact.verified_quote_candidates[:12]
    ]

    public_profile = _build_public_profile(research_artifact, subject_name, voice_dna)
    persona_identity_pack = _build_identity_pack(public_profile, voice_dna)

    retrieval_seeds = []
    retrieval_seeds.extend(
        [item.text for item in research_artifact.extracted_claims[:20] if _normalize_text(item.text)]
    )
    retrieval_seeds.extend(
        [item.event for item in research_artifact.timeline[:12] if _normalize_text(item.event)]
    )
    retrieval_seeds.extend(subject_identity.get("expertise_topics") or [])

    version = datetime.now(timezone.utc).strftime("adk-%Y%m%dT%H%M%SZ")

    return PersonaArtifact(
        twin_id=twin_id,
        version=version,
        subject_name=subject_name,
        identity_frame=subject_identity,
        thinking_style=_build_thinking_style(research_artifact),
        values_and_decision_heuristics=_build_values(research_artifact),
        communication_rules=_build_communication_rules(research_artifact, voice_dna),
        voice_dna=voice_dna,
        quote_pack=quote_pack,
        retrieval_seeds=[seed for seed in retrieval_seeds if _normalize_text(seed)],
        claims=research_artifact.extracted_claims,
        timeline=research_artifact.timeline,
        public_profile=public_profile,
        persona_identity_pack=persona_identity_pack,
        provenance={
            "research_summary": research_artifact.synthesis_summary,
            "source_count": len(research_artifact.source_registry),
            "claim_count": len(research_artifact.extracted_claims),
            "timeline_count": len(research_artifact.timeline),
            "quote_count": len(research_artifact.verified_quote_candidates),
            "compile_metadata": research_artifact.compile_metadata,
        },
    )
