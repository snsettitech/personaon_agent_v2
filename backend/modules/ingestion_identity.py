"""Identity (resume/CV) source helpers for the ingestion router (PON-8).

Resume uploads labelled ``identity`` propose Passport claims — never approved
facts. Kept out of ``routers/ingestion.py`` so that router stops growing.
"""

from __future__ import annotations

import logging

from modules.observability import supabase

logger = logging.getLogger(__name__)

# PostgREST/Postgres codes for "column does not exist": 42703 from Postgres,
# PGRST204 when PostgREST's schema cache doesn't know the column.
_MISSING_COLUMN_CODES = frozenset({"42703", "PGRST204"})
_metadata_column_missing_logged = False


def _is_missing_column_error(exc: Exception) -> bool:
    return str(getattr(exc, "code", "") or "") in _MISSING_COLUMN_CODES


def _log_metadata_column_missing(source_id: str) -> None:
    """Log the absent ``sources.metadata`` column once per process, then at debug."""
    global _metadata_column_missing_logged
    if _metadata_column_missing_logged:
        logger.debug("[Ingestion] sources.metadata column missing source=%s", source_id)
        return
    _metadata_column_missing_logged = True
    logger.info(
        "[Ingestion] sources.metadata column missing; source label not persisted "
        "(logged once per process) source=%s",
        source_id,
    )


def persist_source_label_metadata(
    *,
    source_id: str,
    twin_id: str,
    source_label: str | None,
    identity_confirmed: bool | None,
) -> None:
    """
    Best-effort persistence across evolving schemas.

    Every query is scoped to ``twin_id`` as well as ``source_id``.
    """
    if not source_label:
        return

    try:
        supabase.table("sources").update(
            {
                "source_label": source_label,
                "identity_label_confirmed": bool(identity_confirmed),
            }
        ).eq("id", source_id).eq("twin_id", twin_id).execute()
        return
    except Exception:
        # Older schemas lack these columns; fall back to the metadata JSON.
        logger.debug("[Ingestion] label columns unavailable source=%s", source_id, exc_info=True)

    try:
        existing = supabase.table("sources").select("metadata").eq("id", source_id).eq("twin_id", twin_id).single().execute()
        metadata = {}
        if existing.data and isinstance(existing.data.get("metadata"), dict):
            metadata = dict(existing.data["metadata"])
        metadata["source_label"] = source_label
        metadata["identity_label_confirmed"] = bool(identity_confirmed)
        supabase.table("sources").update({"metadata": metadata}).eq("id", source_id).eq("twin_id", twin_id).execute()
    except Exception as exc:
        if _is_missing_column_error(exc):
            # Schema supports neither the label columns nor metadata; best-effort.
            _log_metadata_column_missing(source_id)
            return
        logger.exception(
            "[Ingestion] could not persist source label source=%s label=%s",
            source_id,
            source_label,
        )


# =============================================================================

async def enrich_profile_from_resume(
    twin_id: str,
    resume_text: str,
    *,
    source_id: str | None = None,
    tenant_id: str | None = None,
    correlation_id: str | None = None,
) -> int:
    """Parse resume with Gemini and insert **proposed** Passport claims (PON-8).

    Does **not** write approved facts or merge into persona_profile / public_profile.
    Failures are non-fatal so ingestion is never blocked by enrichment errors.
    Re-runs on the same text are idempotent: claim fingerprints skip duplicates.

    Returns the number of newly proposed claims (0 on skip or failure).
    """
    try:
        if not source_id:
            logger.warning(
                "[PassportResume] missing source_id — skipping claim import twin=%s",
                twin_id,
            )
            return 0

        from modules.passport_resume_import import propose_claims_from_resume

        summary = propose_claims_from_resume(
            twin_id=twin_id,
            source_id=source_id,
            resume_text=resume_text,
            client=supabase,
            tenant_id=tenant_id,
            owner_user_id=tenant_id,
            correlation_id=correlation_id,
        )
        logger.info(
            "[PassportResume] done twin=%s source=%s proposed=%s skipped=%s corr=%s",
            twin_id,
            source_id,
            summary.get("proposed_count"),
            summary.get("skipped"),
            correlation_id,
        )
        return int(summary.get("proposed_count") or 0)
    except Exception:
        logger.exception(
            "[PassportResume] claim import failed (non-fatal) twin=%s source=%s corr=%s",
            twin_id,
            source_id,
            correlation_id,
        )
        return 0


async def propose_claims_for_duplicate_identity(
    *,
    existing: dict,
    twin_id: str,
    extracted_text: str,
    identity_confirmed: bool | None,
    user: dict | None,
    correlation_id: str | None,
) -> int:
    """Run resume claim import for a re-uploaded file now marked as identity.

    The content-hash dedupe returns the existing source early. Without this, a
    resume first uploaded as knowledge and re-uploaded as "my resume" would never
    propose Passport claims. Fingerprints make re-runs idempotent.
    """
    source_id = existing["id"]
    persist_source_label_metadata(
        source_id=source_id,
        twin_id=twin_id,
        source_label="identity",
        identity_confirmed=identity_confirmed,
    )
    stored_text = existing.get("content_text")
    resume_text = stored_text if isinstance(stored_text, str) and stored_text.strip() else extracted_text
    logger.info(
        "[PassportResume] duplicate identity upload — proposing claims twin=%s source=%s corr=%s",
        twin_id,
        source_id,
        correlation_id,
    )
    return await enrich_profile_from_resume(
        twin_id,
        resume_text,
        source_id=source_id,
        tenant_id=user.get("tenant_id") if isinstance(user, dict) else None,
        correlation_id=correlation_id,
    )
