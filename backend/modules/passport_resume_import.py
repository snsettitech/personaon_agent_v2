"""PON-8 — map resume extraction → proposed Passport claims (never silent approve)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any

from adk_core.model_names import research_model_name
from modules.passport_claim_types import is_allowed_claim_type
from modules.passport_claims import (
    ensure_professional_profile,
    insert_proposed_claim,
)

logger = logging.getLogger(__name__)

EXTRACTION_VERSION = "pon8-resume-v1"

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _fingerprint(claim_type: str, value_text: str) -> str:
    raw = f"{claim_type}|{value_text.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = _FENCE_RE.sub("", text).strip()
    return text


def parse_resume_extraction_json(raw: str) -> dict[str, Any]:
    """Parse model JSON; raise ValueError on invalid payload."""
    cleaned = _strip_fences(raw)
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("resume extraction must be a JSON object")
    return data


def claims_from_extraction(
    parsed: dict[str, Any],
) -> list[dict[str, Any]]:
    """Map Gemini resume JSON → list of {claim_type, value_json, value_text, confidence}."""
    out: list[dict[str, Any]] = []

    def add(claim_type: str, value_json: dict[str, Any], value_text: str, confidence: float = 0.75) -> None:
        if not is_allowed_claim_type(claim_type):
            return
        text = (value_text or "").strip()
        if not text:
            return
        out.append(
            {
                "claim_type": claim_type,
                "value_json": value_json,
                "value_text": text,
                "confidence": confidence,
            }
        )

    full_name = parsed.get("full_name") or parsed.get("name")
    if isinstance(full_name, str) and full_name.strip():
        add("full_name", {"text": full_name.strip()}, full_name.strip(), 0.85)

    headline = parsed.get("headline") or parsed.get("occupation")
    if isinstance(headline, str) and headline.strip():
        add("headline", {"text": headline.strip()}, headline.strip(), 0.8)

    bio = parsed.get("bio") or parsed.get("short_description")
    if isinstance(bio, str) and bio.strip():
        add("bio", {"text": bio.strip()}, bio.strip()[:2000], 0.7)

    education = parsed.get("education")
    if isinstance(education, list):
        for row in education:
            if not isinstance(row, dict):
                continue
            institution = str(row.get("institution") or "").strip()
            degree = str(row.get("degree") or "").strip()
            field = str(row.get("field") or "").strip()
            if not institution and not degree:
                continue
            parts = [p for p in (degree, field, institution) if p]
            add("education", row, " — ".join(parts), 0.75)

    work = parsed.get("work_experience")
    if isinstance(work, list):
        for row in work:
            if not isinstance(row, dict):
                continue
            company = str(row.get("company") or "").strip()
            role = str(row.get("role") or "").strip()
            if not company and not role:
                continue
            parts = [p for p in (role, company) if p]
            add("work_experience", row, " @ ".join(parts) if role and company else (role or company), 0.75)

    skills = parsed.get("areas_of_expertise") or parsed.get("skills")
    if isinstance(skills, list):
        for skill in skills:
            if isinstance(skill, str) and skill.strip():
                add("skill", {"name": skill.strip()}, skill.strip(), 0.7)
            elif isinstance(skill, dict):
                name = str(skill.get("name") or skill.get("skill") or "").strip()
                if name:
                    add("skill", skill, name, 0.7)

    return out


def extract_resume_fields_with_gemini(resume_text: str) -> dict[str, Any]:
    """Call Gemini; returns parsed dict. Raises on hard failures."""
    import google.genai as genai

    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY missing")

    client = genai.Client(api_key=api_key)
    prompt = (
        "Extract professional profile information from this resume/CV text. "
        "Return a JSON object with ONLY these keys (omit keys you cannot find evidence for):\n"
        "  full_name, headline, occupation, bio, short_description,\n"
        "  areas_of_expertise (array of strings),\n"
        "  education (array of {institution, degree, field, start_year, end_year}),\n"
        "  work_experience (array of {company, role, start_year, end_year, description})\n\n"
        "Rules: only include facts explicitly stated in the text. "
        "Return ONLY valid JSON, no markdown, no explanation.\n\n"
        f"Resume text (first 6000 chars):\n{resume_text[:6000]}"
    )
    response = client.models.generate_content(
        # ADK_RESEARCH_MODEL, else ADK_CHAT_MODEL, else the project Gemini default.
        model=research_model_name(),
        contents=prompt,
    )
    raw = (response.text or "").strip()
    return parse_resume_extraction_json(raw)


def propose_claims_from_resume(
    *,
    twin_id: str,
    source_id: str,
    resume_text: str,
    client: Any,
    tenant_id: str | None = None,
    owner_user_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Extract resume → insert proposed claims + evidence. Never writes approved facts.

    Returns summary: {profile_id, proposed_count, claim_ids, skipped}.
    """
    twin_res = (
        client.table("twins")
        .select("id, tenant_id, settings")
        .eq("id", twin_id)
        .single()
        .execute()
    )
    if not twin_res.data:
        raise ValueError(f"twin not found: {twin_id}")

    resolved_tenant = tenant_id or twin_res.data.get("tenant_id")
    if not resolved_tenant:
        raise ValueError("tenant_id required for passport claims")
    resolved_owner = owner_user_id or str(resolved_tenant)

    profile_id = ensure_professional_profile(
        tenant_id=str(resolved_tenant),
        twin_id=twin_id,
        owner_user_id=str(resolved_owner),
        client=client,
    )

    parsed = extract_resume_fields_with_gemini(resume_text)
    draft_claims = claims_from_extraction(parsed)

    claim_ids: list[str] = []
    skipped = 0
    for item in draft_claims:
        fp = _fingerprint(item["claim_type"], item["value_text"])
        try:
            claim_id = insert_proposed_claim(
                tenant_id=str(resolved_tenant),
                profile_id=profile_id,
                claim_type=item["claim_type"],
                value_json=item["value_json"],
                value_text=item["value_text"],
                client=client,
                confidence=item.get("confidence"),
                extraction_version=EXTRACTION_VERSION,
                fingerprint=fp,
                created_by="import",
            )
        except Exception as exc:
            # Unique fingerprint conflict → idempotent skip
            msg = str(exc).lower()
            if "duplicate" in msg or "unique" in msg:
                skipped += 1
                logger.info(
                    "[PassportResume] skip duplicate fingerprint type=%s twin=%s corr=%s",
                    item["claim_type"],
                    twin_id,
                    correlation_id,
                )
                continue
            raise

        client.table("claim_evidence").insert(
            {
                "tenant_id": str(resolved_tenant),
                "claim_id": claim_id,
                "source_id": source_id,
                "excerpt": item["value_text"][:500],
                "locator": {"kind": "resume_extract", "version": EXTRACTION_VERSION},
            }
        ).execute()
        claim_ids.append(claim_id)

    logger.info(
        "[PassportResume] proposed=%s skipped=%s twin=%s source=%s profile=%s corr=%s",
        len(claim_ids),
        skipped,
        twin_id,
        source_id,
        profile_id,
        correlation_id,
    )
    return {
        "profile_id": profile_id,
        "proposed_count": len(claim_ids),
        "claim_ids": claim_ids,
        "skipped": skipped,
    }
