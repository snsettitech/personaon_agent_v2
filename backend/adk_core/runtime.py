"""Execution helpers and event translation for the ADK runtime."""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any
from collections.abc import Callable

from adk_core.app import (
    get_session_service,
)
from adk_core.schemas.artifacts import PersonaArtifact
from adk_core.tools._common import url_source_id
from adk_core.state_keys import AppKey, TempKey
from modules.profile_utils import normalize_external_url

logger = logging.getLogger(__name__)


def _sanitize_error(exc: Exception) -> str:
    """Sanitize exception for storage/client display — strip paths and stack details."""
    msg = str(exc)
    msg = re.sub(r'(?:/[a-zA-Z0-9_./-]+)+\.py', '[internal]', msg)
    msg = re.sub(r'line \d+', '', msg)
    return msg[:200]


def _text_from_event(event: Any) -> str:
    if not getattr(event, "content", None) or not getattr(event.content, "parts", None):
        return ""
    parts = []
    for part in event.content.parts:
        if getattr(part, "text", None):
            parts.append(part.text)
    return "".join(parts)




def _coerce_json_text(raw: Any) -> str:
    if raw is None:
        raise ValueError("Expected JSON payload, got None.")
    if isinstance(raw, (dict, list)):
        return json.dumps(raw)
    text = str(raw).strip()
    if not text:
        raise ValueError("Expected JSON payload, got blank text.")

    candidates: list[str] = []
    fenced_blocks = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    candidates.extend(block.strip() for block in fenced_blocks if block.strip())

    start_object = text.find("{")
    end_object = text.rfind("}")
    if start_object != -1 and end_object != -1 and end_object > start_object:
        candidates.append(text[start_object : end_object + 1].strip())

    start_array = text.find("[")
    end_array = text.rfind("]")
    if start_array != -1 and end_array != -1 and end_array > start_array:
        candidates.append(text[start_array : end_array + 1].strip())

    candidates.append(text)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        return json.dumps(parsed)
    raise ValueError("Unable to extract valid JSON from model output.")


def _stable_session_id(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(parts)))


def _persona_prompt_block(artifact: dict[str, Any]) -> str:
    return json.dumps(
        {
            "identity_frame": artifact.get("identity_frame") or {},
            "thinking_style": artifact.get("thinking_style") or {},
            "values_and_decision_heuristics": artifact.get("values_and_decision_heuristics") or [],
            "communication_rules": artifact.get("communication_rules") or [],
            "voice_dna": artifact.get("voice_dna") or {},
        }
    )


def _coerce_json_obj(raw: Any, default: Any) -> Any:
    try:
        return json.loads(_coerce_json_text(raw))
    except Exception:
        return default


def _confidence_value(raw: Any) -> float:
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw or "").strip().lower()
    if text in {"high", "strong"}:
        return 0.85
    if text in {"medium", "moderate"}:
        return 0.6
    if text in {"low", "weak"}:
        return 0.35
    try:
        return float(text)
    except Exception:
        return 0.0


def _normalize_records(
    rows: Any,
    *,
    required_fields: list[str],
    extra_fields: dict[str, Callable] | None = None,
    aliases: dict[str, list[str]] | None = None,
    auto_id: str | None = None,
) -> list[dict[str, Any]]:
    """Generic normalizer for research output records.

    Args:
        rows: Raw list of dicts from LLM output.
        required_fields: Fields that must be non-empty after stripping.
        extra_fields: Additional fields with coercion functions (e.g. confidence).
        aliases: Map of canonical field name -> list of alternative field names.
        auto_id: If set, auto-generate an ID field with this prefix when missing.
    """
    normalized: list[dict[str, Any]] = []
    for idx, row in enumerate(rows or [], start=1):
        if not isinstance(row, dict):
            continue
        # Resolve aliases first
        resolved: dict[str, Any] = {}
        for key, val in row.items():
            resolved[key] = val
        if aliases:
            for canonical, alts in aliases.items():
                if not resolved.get(canonical):
                    for alt in alts:
                        if resolved.get(alt):
                            resolved[canonical] = resolved[alt]
                            break
        # Check required fields
        record: dict[str, str] = {}
        skip = False
        for field in required_fields:
            val = str(resolved.get(field) or "").strip()
            if not val:
                skip = True
                break
            record[field] = val
        if skip:
            continue
        # Auto-ID
        if auto_id:
            record[f"{auto_id}_id"] = str(resolved.get(f"{auto_id}_id") or f"{auto_id}-{idx}")
        # Extra fields with coercion
        for field, fn in (extra_fields or {}).items():
            record[field] = fn(resolved.get(field))
        # source_ids list (common pattern)
        if "source_ids" in resolved:
            record["source_ids"] = [str(s) for s in (resolved.get("source_ids") or []) if s]
        # Passthrough optional string fields
        for opt_field in ("claim_type", "speaker", "context", "source_id"):
            if opt_field in resolved and opt_field not in record:
                val = str(resolved.get(opt_field) or "").strip()
                if val:
                    record[opt_field] = val
        normalized.append(record)
    return normalized


def _normalize_claims(rows: Any) -> list[dict[str, Any]]:
    return _normalize_records(
        rows,
        required_fields=["text"],
        extra_fields={"confidence": _confidence_value},
        auto_id="claim",
    )


def _normalize_timeline(rows: Any) -> list[dict[str, Any]]:
    return _normalize_records(
        rows,
        required_fields=["date_or_range", "event"],
        extra_fields={"confidence": _confidence_value},
    )


def _normalize_quotes(rows: Any) -> list[dict[str, Any]]:
    return _normalize_records(
        rows,
        required_fields=["quote", "source_id"],
        extra_fields={"confidence": _confidence_value},
        aliases={"quote": ["quote_text"]},
    )


def _build_research_artifact_payload(state: dict[str, Any]) -> dict[str, Any]:
    gathered = _coerce_json_obj(state.get("gathered_research_json"), {})
    identity = _coerce_json_obj(state.get("identity_analysis_json"), {})
    evidence = _coerce_json_obj(state.get("evidence_analysis_json"), {})
    research_warnings = _coerce_json_obj(state.get(TempKey.RESEARCH_WARNINGS_JSON), [])

    # Source registry: prefer agent-scraped sources.
    # temp: keys are stripped on session save, so fall back to app:preloaded_sources_json
    # (persisted through session reload) before the old gathered format.
    scraped_sources = _coerce_json_obj(state.get("temp:scraped_sources_json"), [])
    if not (isinstance(scraped_sources, list) and scraped_sources):
        scraped_sources = _coerce_json_obj(state.get(AppKey.PRELOADED_SOURCES_JSON), [])
    if isinstance(scraped_sources, list) and scraped_sources:
        source_registry = scraped_sources
    else:
        source_registry = gathered.get("source_registry") or []
    claims = _normalize_claims(evidence.get("extracted_claims"))
    timeline = _normalize_timeline(evidence.get("timeline"))
    quotes = _normalize_quotes(evidence.get("quote_candidates"))
    if not quotes:
        quotes = _normalize_quotes(gathered.get("verified_quote_candidates"))

    subject_name = str(
        gathered.get("subject_name")
        or state.get("app:subject_name")
        or ""
    ).strip()
    subject_identity = {
        "canonical_name": identity.get("canonical_name") or subject_name,
        "public_roles": identity.get("public_roles") or [],
        "organizations": identity.get("organizations") or [],
        "locations": identity.get("locations") or [],
        "expertise_topics": identity.get("expertise_topics") or [],
        "short_bio": identity.get("short_bio") or str(state.get("research_gather_summary") or "").strip(),
        "evidence_notes": identity.get("evidence_notes") or "",
    }

    return {
        "subject_identity": subject_identity,
        "source_registry": source_registry,
        "extracted_claims": claims,
        "timeline": timeline,
        "verified_quote_candidates": quotes,
        "synthesis_summary": subject_identity["short_bio"] or f"Research summary for {subject_name}".strip(),
        "compile_metadata": {
            "generated_by": "adk_research_pipeline_fallback",
            "source_count": len(source_registry),
            "quote_count": len(quotes),
            "gather_stats": gathered.get("gather_stats") or {},
            "research_warnings": research_warnings if isinstance(research_warnings, list) else [],
            "seed_urls": _coerce_json_obj(state.get(AppKey.SEED_URLS_JSON), []),
        },
    }


def _normalize_research_artifact_payload(
    payload: dict[str, Any],
    *,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return fallback
    subject_identity = payload.get("subject_identity")
    if not isinstance(subject_identity, dict):
        subject_identity = fallback.get("subject_identity") or {}
    source_registry = payload.get("source_registry")
    if not isinstance(source_registry, list):
        source_registry = fallback.get("source_registry") or []
    synthesis_summary = str(
        payload.get("synthesis_summary")
        or fallback.get("synthesis_summary")
        or ""
    ).strip()
    compile_metadata = payload.get("compile_metadata")
    if not isinstance(compile_metadata, dict):
        compile_metadata = fallback.get("compile_metadata") or {}

    return {
        "subject_identity": subject_identity,
        "source_registry": source_registry,
        "extracted_claims": _normalize_claims(
            payload.get("extracted_claims") or fallback.get("extracted_claims")
        ),
        "timeline": _normalize_timeline(payload.get("timeline") or fallback.get("timeline")),
        "verified_quote_candidates": _normalize_quotes(
            payload.get("verified_quote_candidates") or fallback.get("verified_quote_candidates")
        ),
        "synthesis_summary": synthesis_summary,
        "compile_metadata": compile_metadata,
    }


def _normalize_persona_artifact_payload(
    payload: dict[str, Any],
    *,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return fallback
    allowed_keys = set(PersonaArtifact.model_fields.keys())
    normalized = dict(fallback)
    normalized.update({key: value for key, value in payload.items() if key in allowed_keys})
    return normalized


# Use centralized CITATION_STATE_KEYS from state_keys module


def _normalize_seed_urls(seed_urls: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen = set()
    for raw in seed_urls or []:
        url = normalize_external_url(raw)
        if not url or url in seen:
            continue
        seen.add(url)
        normalized.append(url)
    return normalized


def _is_linkedin_url(url: str) -> bool:
    return "linkedin.com/in/" in url.lower()


async def _scrape_linkedin_via_agent(url: str, subject_name: str) -> str:
    """Use Firecrawl's agent() to extract LinkedIn profile content.

    The agent uses AI to navigate past the login wall — basic scrape()
    gets blocked.  Returns the extracted text or empty string on failure.
    """
    import asyncio as _aio

    from adk_core.services.firecrawl_service import extract_profile, profile_to_text

    context = f"LinkedIn profile at {url}"
    try:
        profile = await _aio.wait_for(
            _aio.to_thread(extract_profile, subject_name, context),
            timeout=90,  # Must fit within Cloud Run 300s budget alongside ADK research
        )
        return profile_to_text(profile)
    except Exception as exc:
        logger.warning("LinkedIn agent extraction failed for %s: %s", url, exc)
        return ""


async def _preload_seed_state(
    seed_urls: list[str],
    subject_name: str = "",
) -> dict[str, Any]:
    search_results = [
        {
            "index": idx,
            "url": url,
            "title": "User-confirmed seed URL",
            "snippet": "High-trust source provided during onboarding.",
        }
        for idx, url in enumerate(seed_urls, start=1)
    ]
    scraped_sources: list[dict[str, Any]] = []
    warnings: list[str] = []

    if not seed_urls:
        return {
            "search_results_json": json.dumps(search_results),
            "scraped_sources_json": json.dumps(scraped_sources),
            "research_warnings_json": json.dumps(warnings),
        }

    try:
        from modules.firecrawl_client import get_firecrawl_client

        firecrawl = get_firecrawl_client()
    except Exception as exc:
        firecrawl = None
        warnings.append(f"Seed research setup failed: {exc}")

    if not firecrawl:
        warnings.append("Firecrawl is unavailable, so seed URLs could not be scraped immediately.")
        return {
            "search_results_json": json.dumps(search_results),
            "scraped_sources_json": json.dumps(scraped_sources),
            "research_warnings_json": json.dumps(warnings),
        }

    for idx, url in enumerate(seed_urls, start=1):
        extracted_text = ""
        title = "User-confirmed seed URL"
        quality = "scraped"

        # LinkedIn requires the Firecrawl agent (AI navigation) — basic
        # scrape() hits the login wall and returns nothing.
        if _is_linkedin_url(url):
            logger.info("Using Firecrawl agent for LinkedIn seed: %s", url)
            extracted_text = await _scrape_linkedin_via_agent(url, subject_name)
            if extracted_text:
                title = f"LinkedIn profile — {subject_name}"
                quality = "full"
            else:
                warnings.append(f"LinkedIn agent extraction returned no content for {url}.")
                quality = "error"
        else:
            try:
                result = await firecrawl.scrape_with_retry(url)
                metadata = getattr(result, "metadata", None) or {}
                quality = getattr(getattr(result, "quality", None), "value", "") or getattr(result, "quality", "")
                extracted_text = (getattr(result, "content", "") or "")[:50000]
                title = str(metadata.get("title") or title)
                if quality and str(quality).lower() != "full":
                    warnings.append(f"Seed URL returned {quality} content for {url}.")
            except Exception as exc:
                warnings.append(f"Seed scrape failed for {url}: {exc}")
                quality = "error"

        if not extracted_text:
            warnings.append(f"Seed URL returned no readable text for {url}.")

        scraped_sources.append(
            {
                "source_id": url_source_id(url, idx),
                "url": url,
                "title": title,
                "extracted_text": extracted_text,
                "quality": str(quality or "scraped"),
                "org_mentioned": True,
                "subject_mentioned": True,
                "provider": "firecrawl_agent" if _is_linkedin_url(url) else "firecrawl_seed",
            }
        )

    return {
        "search_results_json": json.dumps(search_results),
        "scraped_sources_json": json.dumps(scraped_sources),
        "research_warnings_json": json.dumps(warnings),
    }


async def _ensure_session(
    *,
    app_name: str,
    session_id: str,
    user_id: str,
    state: dict[str, Any],
) -> None:
    session = await get_session_service().get_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
    )
    if session is not None:
        # Delete and recreate: temp: keys are stripped on save, so an existing
        # session will be missing them. Recreating ensures all keys (including
        # temp: defaults) are present when ADK injects instruction templates.
        # Conversation history lives in the conversations table, not the session.
        await get_session_service().delete_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
        )
    await get_session_service().create_session(
        app_name=app_name,
        user_id=user_id,
        state=state,
        session_id=session_id,
    )

# Research and compiler pipelines removed.
# Replaced by single-agent enrichment (see adk_core/agents/enrichment_agent.py).
# Chat pipeline removed.
# Replaced by agent_service.chat_stream (see adk_core/services/agent_service.py).
