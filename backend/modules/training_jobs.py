"""
Training Jobs Module
Manages training job lifecycle and processing.
"""
import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from modules.job_queue import enqueue_job
from modules.observability import supabase
from modules.posthog_analytics import ph_capture
from modules.twin_namespace import get_namespace_candidates_for_twin

logger = logging.getLogger(__name__)
# Note: process_and_index_text is imported inside process_training_job to avoid circular import


def _update_source_row(source_id: str, payload: dict[str, Any]) -> None:
    """
    Update a source row while tolerating deployments that already dropped
    the legacy `staging_status` column.
    """
    try:
        supabase.table("sources").update(payload).eq("id", source_id).execute()
    except Exception as update_error:
        message = str(update_error).lower()
        if "staging_status" in message and "sources" in message:
            fallback = dict(payload)
            fallback.pop("staging_status", None)
            supabase.table("sources").update(fallback).eq("id", source_id).execute()
        else:
            raise


def _schedule_metrics_update(twin_id: str) -> None:
    """
    Schedule training metrics update as a background task.

    This fire-and-forget approach ensures metrics recomputation doesn't
    block the job processing pipeline.
    """
    async def _update():
        try:
            from modules.training_metrics import (
                is_training_metrics_enabled,
                update_twin_training_metrics,
            )
            if is_training_metrics_enabled():
                await asyncio.to_thread(update_twin_training_metrics, twin_id)
        except Exception as e:
            logger.warning("[TrainingJobs] Background metrics update failed for twin %s: %s", twin_id, e)

    # Create and schedule the background task
    try:
        asyncio.create_task(_update())
    except Exception as e:
        logger.warning("[TrainingJobs] Failed to schedule metrics update: %s", e)


def create_training_job(source_id: str, twin_id: str, job_type: str = 'ingestion',
                       priority: int = 0, metadata: dict[str, Any] | None = None) -> str:
    """
    Creates job record and adds to Redis queue.

    Args:
        source_id: Source UUID
        twin_id: Twin UUID
        job_type: Type of job ('ingestion', 'reindex', 'health_check')
        priority: Priority level (higher = processed first, default 0)
        metadata: Optional job parameters

    Returns:
        Job ID (UUID)
    """
    job_id = str(uuid.uuid4())

    # Create job record in database
    supabase.table("training_jobs").insert({
        "id": job_id,
        "source_id": source_id,
        "twin_id": twin_id,
        "status": "queued",
        "job_type": job_type,
        "priority": priority,
        "metadata": metadata or {}
    }).execute()

    # Add to queue
    enqueue_job(job_id, job_type, priority, metadata)

    return job_id


def get_training_job(job_id: str) -> dict[str, Any] | None:
    """Fetches job details."""
    try:
        response = supabase.table("training_jobs").select("*").eq("id", job_id).single().execute()
        return response.data if response.data else None
    except Exception as e:
        logger.warning("Error fetching training job: %s", e)
        return None


def update_job_status(job_id: str, status: str, error_message: str | None = None,
                     metadata: dict[str, Any] | None = None):
    """
    Updates job status.

    Args:
        job_id: Job UUID
        status: New status ('queued', 'processing', 'needs_attention', 'complete', 'failed')
        error_message: Optional error message
        metadata: Optional metadata updates
    """
    update_data = {
        "status": status,
        "updated_at": datetime.utcnow().isoformat()
    }

    # Get current job to check existing fields
    current_job = get_training_job(job_id)

    if status == "processing" and current_job and not current_job.get("started_at"):
        update_data["started_at"] = datetime.utcnow().isoformat()

    if status in ("complete", "failed", "needs_attention") and current_job and not current_job.get("completed_at"):
        update_data["completed_at"] = datetime.utcnow().isoformat()

    if error_message:
        update_data["error_message"] = error_message

    if metadata:
        # Merge with existing metadata
        existing_metadata = current_job.get("metadata", {}) if current_job else {}
        existing_metadata.update(metadata)
        update_data["metadata"] = existing_metadata

    supabase.table("training_jobs").update(update_data).eq("id", job_id).execute()


def list_training_jobs(twin_id: str, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """
    Lists jobs with filtering.

    Args:
        twin_id: Twin UUID
        status: Optional status filter
        limit: Maximum number of jobs to return

    Returns:
        List of job records
    """
    query = supabase.table("training_jobs").select("*").eq("twin_id", twin_id)

    if status:
        query = query.eq("status", status)

    query = query.order("created_at", desc=True).limit(limit)

    response = query.execute()
    return response.data if response.data else []


async def process_training_job(job_id: str) -> bool:
    """
    Main processing logic (called by worker).

    Args:
        job_id: Job UUID

    Returns:
        True if successful, False otherwise
    """
    job = get_training_job(job_id)
    if not job:
        logger.warning("Job %s not found", job_id)
        return False

    source_id = job["source_id"]
    twin_id = job["twin_id"]
    job_type = job["job_type"]
    job_metadata = job.get("metadata") or {}
    correlation_id = job_metadata.get("correlation_id")

    source_data = {}
    citation_url = None
    provider = job_metadata.get("provider")

    try:
        # Update status to processing
        update_job_status(job_id, "processing")

        # Get source data
        source_response = supabase.table("sources").select("*").eq("id", source_id).single().execute()
        if not source_response.data:
            raise ValueError(f"Source {source_id} not found")

        source_data = source_response.data or {}
        extracted_text = source_data.get("content_text")
        filename = source_data.get("filename", "Unknown")
        citation_url = source_data.get("citation_url") or job_metadata.get("url")

        # ── Profile enrichment ─────────────────────────────────────────
        # Enqueued by auto_create._enqueue_enrichment() for instant-activation flow.
        if job_metadata.get("enrichment_type") == "profile_enrichment":
            from routers.auto_create import _run_extraction

            outcome = await _run_extraction(
                twin_id=twin_id,
                name=job_metadata.get("name", ""),
                context=job_metadata.get("context"),
                linkedin_url=job_metadata.get("linkedin_url"),
                linkedin_snapshot=job_metadata.get("linkedin_snapshot") or {},
                tenant_id=job_metadata.get("tenant_id", ""),
            )

            if not isinstance(outcome, dict):
                outcome = {
                    "state": "failed",
                    "db_status": "draft",
                    "chunk_count": 0,
                    "vector_indexed": False,
                    "publishable": False,
                    "failure_reason": "missing_extraction_outcome",
                }

            twin_settings: dict[str, Any] = {}
            twin_settings_loaded = False
            try:
                twin_row = supabase.table("twins").select("status, settings").eq("id", twin_id).single().execute()
                twin_settings = (twin_row.data or {}).get("settings") or {}
                twin_settings_loaded = True
            except Exception as _twin_check_exc:
                outcome = {
                    **outcome,
                    "publishable": False,
                    "failure_reason": "verification_failed",
                }
                logger.warning(
                    "[TrainingJobs] could not verify twin state post-extraction twin=%s err=%r - failing closed",
                    twin_id, _twin_check_exc,
                )

            publishable = (
                outcome.get("publishable") is True
                and outcome.get("state") == "active"
                and outcome.get("db_status") == "active"
                and outcome.get("vector_indexed") is True
                and (outcome.get("chunk_count") or 0) > 0
            )
            failure_reason = outcome.get("failure_reason")
            retryable_failure = failure_reason in {
                "vector_upsert_failed",
                "extraction_failed",
                "missing_extraction_outcome",
                "verification_failed",
            } or outcome.get("state") == "failed"

            if not publishable and twin_settings_loaded:
                try:
                    settings = {**twin_settings}
                    settings["enrichment_status"] = "needs_input"
                    widget = {**(settings.get("widget_settings") or {})}
                    widget["public_share_enabled"] = False
                    settings["widget_settings"] = widget
                    supabase.table("twins").update({"settings": settings}).eq("id", twin_id).execute()
                except Exception as _settings_exc:
                    logger.warning(
                        "[TrainingJobs] enrichment_status needs_input update failed (non-fatal): %s",
                        _settings_exc,
                    )

            if not publishable and retryable_failure:
                _update_source_row(source_id, {
                    "status": "failed",
                    "last_step": "extraction_failed",
                    "health_status": "unhealthy",
                })
                update_job_status(
                    job_id, "failed",
                    metadata={"enrichment_type": "profile_enrichment", "reason": failure_reason or "extraction_failed"},
                )
                _schedule_metrics_update(twin_id)
                return False

            if not publishable:
                _update_source_row(source_id, {
                    "status": "failed",
                    "last_step": "needs_input",
                    "health_status": "unhealthy",
                })
                update_job_status(
                    job_id, "complete",
                    metadata={"enrichment_type": "profile_enrichment", "reason": failure_reason or "needs_input"},
                )
                _schedule_metrics_update(twin_id)
                return True

            _update_source_row(source_id, {
                "status": "live",
                "last_step": "indexed",
                "health_status": "healthy",
            })
            update_job_status(
                job_id, "complete",
                metadata={"enrichment_type": "profile_enrichment"},
            )

            # POST /v2/enrich/{twin_id}/profile resets enrichment_status to
            # "queued" before re-enqueuing (routers/enrich.py:126), so that
            # field can't be used to detect "already notified" — it never
            # reads back as "completed" on a re-run. Use a separate flag that
            # a re-enrichment reset doesn't touch (routers/enrich.py:105-128
            # copies existing settings keys forward, only overwriting
            # enrichment_status/persona_quality) so this event fires exactly
            # once per twin, no matter how many times enrichment re-runs.
            #
            # That flag alone isn't race-safe: _enqueue_enrichment has no
            # idempotency key (routers/auto_create.py at twin creation, and
            # routers/enrich.py's "safe to call multiple times" re-enrich
            # endpoint, can both enqueue a profile_enrichment job for the
            # same twin_id), so two workers can each read twin_settings
            # before either writes it back. The plain boolean check below
            # would let both decide "I'm first". Instead we do the flag
            # write as a conditional UPDATE (only matches a row if the flag
            # is still unset in the DB right now) and only fire ph_capture
            # if OUR write actually matched — the loser's write matches zero
            # rows and skips the analytics call, closing the race.
            already_notified = bool(twin_settings.get("analytics_extraction_complete_sent"))

            won_analytics_race = False
            try:
                settings = {**twin_settings}
                settings["enrichment_status"] = "completed"
                widget = {**(settings.get("widget_settings") or {})}
                widget["public_share_enabled"] = True
                settings["widget_settings"] = widget

                if already_notified:
                    # Nothing to race for — already fired on a prior run.
                    supabase.table("twins").update({"settings": settings}).eq("id", twin_id).execute()
                else:
                    settings["analytics_extraction_complete_sent"] = True
                    cas_result = (
                        supabase.table("twins")
                        .update({"settings": settings})
                        .eq("id", twin_id)
                        .is_("settings->>analytics_extraction_complete_sent", "null")
                        .execute()
                    )
                    won_analytics_race = bool(cas_result.data)
                    if not won_analytics_race:
                        # Lost the race — a concurrent run already claimed the
                        # analytics fire between our read and this write.
                        # Still apply enrichment_status/widget_settings so
                        # this run's own completion state is correct.
                        supabase.table("twins").update({"settings": settings}).eq("id", twin_id).execute()
            except Exception as _settings_exc:
                logger.warning(
                    "[TrainingJobs] enrichment_status/public_share update failed (non-fatal): %s",
                    _settings_exc,
                )
                won_analytics_race = False

            # PostHog: signal that the user's onboarding extraction succeeded
            # so the signup_started -> published -> first_chat funnel
            # resolves. Restored from fix/onboarding-posthog-events (2f77d2a1)
            # after PR #37 dropped it; gated on won_analytics_race (not just
            # already_notified) so two concurrent enrichment runs for the
            # same twin can't both fire this event.
            #
            # Accepted tradeoff: the flag is durably written before
            # ph_capture is called, not after. A process crash in the narrow
            # window between the DB write committing and ph_capture running
            # would leave the flag set with no event actually sent (a silent
            # under-fire, recoverable only via manual DB edit) — same
            # non-atomicity class as the documented TOCTOU in
            # routers/onboarding.py's _resolve_handle. Reversing the order
            # would reopen the double-fire race above instead, which is the
            # far more likely failure mode (needs no crash, just a user
            # re-triggering enrichment) — not worth trading one for the
            # other without a real outbox/two-phase mechanism, which is
            # disproportionate for a funnel-completeness signal.
            # owner_user_id is the Supabase auth user.id, which matches the
            # PostHog distinct_id set by frontend posthog.identify().
            if won_analytics_race:
                twin_owner_user_id = str(twin_settings.get("owner_user_id") or "").strip()
                if twin_owner_user_id:
                    try:
                        chunk_count = int(outcome.get("chunk_count") or 0)
                        ph_capture(
                            user_id=twin_owner_user_id,
                            event="onboarding_extraction_complete",
                            properties={
                                "twin_id": twin_id,
                                "chunk_count": chunk_count,
                                "vector_indexed": bool(outcome.get("vector_indexed")),
                                "status": str(outcome.get("state") or "active"),
                            },
                        )
                    except Exception as _ph_exc:
                        logger.warning(
                            "[TrainingJobs] PostHog onboarding_extraction_complete failed (non-fatal): %s",
                            _ph_exc,
                        )

            _schedule_metrics_update(twin_id)
            return True

        # If this is a URL-based ingestion job, run the URL pipeline end-to-end.
        if job_type == "ingestion" and citation_url:
            from modules.ingestion import detect_url_provider, ingest_url_to_source
            provider = provider or detect_url_provider(citation_url)

            num_chunks = await ingest_url_to_source(
                source_id=source_id,
                twin_id=twin_id,
                url=citation_url,
                provider=provider,
                correlation_id=correlation_id
            )

            # Mark job complete. Source status is updated by the ingestion pipeline.
            update_job_status(job_id, "complete", metadata={
                "provider": provider,
                "url": citation_url,
                "chunks_created": num_chunks,
            })
            return True

        # Validate content_text exists
        if not extracted_text or len(extracted_text.strip()) == 0:
            # Fallback: reconstruct from chunks table
            logger.info("[Process Job] Source %s (%s) has no content_text, attempting to reconstruct from chunks...", source_id, filename)
            try:
                chunk_rows = supabase.table("chunks").select("content").eq("source_id", source_id).execute()
                if chunk_rows.data:
                    extracted_text = " ".join(row["content"] for row in chunk_rows.data if row.get("content"))
                    if extracted_text:
                        supabase.table("sources").update({
                            "content_text": extracted_text,
                            "extracted_text_length": len(extracted_text)
                        }).eq("id", source_id).execute()
                        logger.info("Reconstructed %s characters from chunks table", len(extracted_text))
                    else:
                        raise ValueError(
                            f"Source '{filename}' has no extracted text content and no chunks found. "
                            f"Please delete this source and re-upload it."
                        )
                else:
                    raise ValueError(
                        f"Source '{filename}' has no extracted text content and no chunks found. "
                        f"Please delete this source and re-upload it."
                    )
            except ValueError:
                raise
            except Exception as db_error:
                logger.error("Error reconstructing from chunks: %s", db_error)
                raise ValueError(
                    f"Source '{filename}' has no extracted text content. "
                    f"Could not reconstruct from chunks: {str(db_error)}. "
                    f"Please delete this source and re-upload it."
                )

        # Process based on job type
        if job_type == "ingestion":
            # Index existing content_text (file uploads or pre-extracted sources)
            from modules.ingestion import process_and_index_text
            from modules.ingestion_diagnostics import finish_step, start_step

            provider = provider or "file"
            num_chunks = await process_and_index_text(
                source_id,
                twin_id,
                extracted_text,
                metadata_override={
                    "filename": filename,
                    "type": "file",
                },
                provider=provider,
                correlation_id=correlation_id,
            )

            # Update source with chunk count and extracted text length
            _update_source_row(source_id, {
                "chunk_count": num_chunks,
                "extracted_text_length": len(extracted_text),
                "status": "live"
            })

            # Emit terminal "live" step event for UI.
            live_event_id = start_step(
                source_id=source_id,
                twin_id=twin_id,
                provider=provider,
                step="live",
                correlation_id=correlation_id,
                message="Source is live",
            )
            finish_step(
                event_id=live_event_id,
                source_id=source_id,
                twin_id=twin_id,
                provider=provider,
                step="live",
                status="completed",
                correlation_id=correlation_id,
                metadata={"chunks": num_chunks},
            )

            # Update job metadata
            update_job_status(job_id, "complete", metadata={"chunks_created": num_chunks})

            # Trigger training metrics recompute in background (fire-and-forget)
            _schedule_metrics_update(twin_id)

        elif job_type == "reindex":
            # Reindex existing content (delete old vectors and re-index)
            # This would require deleting old vectors from Pinecone first
            # For now, just re-index
            from modules.ingestion import process_and_index_text
            num_chunks = await process_and_index_text(source_id, twin_id, extracted_text)

            _update_source_row(source_id, {
                "chunk_count": num_chunks,
                "status": "live"
            })

            update_job_status(job_id, "complete", metadata={"chunks_created": num_chunks})

            # Trigger training metrics recompute in background (fire-and-forget)
            _schedule_metrics_update(twin_id)

        elif job_type == "health_check":
            # Run health checks (already done during ingestion, but can be re-run)
            from modules.health_checks import run_all_health_checks
            health_result = run_all_health_checks(
                source_id,
                twin_id,
                extracted_text,
                chunk_count=source_data.get("chunk_count"),
                source_data=source_data
            )

            # Update source health status
            supabase.table("sources").update({
                "health_status": health_result["overall_status"]
            }).eq("id", source_id).execute()

            update_job_status(job_id, "complete", metadata=health_result)
        else:
            raise ValueError(f"Unknown job type: {job_type}")

        return True

    except Exception as e:
        import traceback
        error_msg = str(e)
        error_traceback = traceback.format_exc()
        logger.error("Error processing job %s: %s", job_id, error_msg)
        logger.debug("Traceback: %s", error_traceback)
        update_job_status(job_id, "failed", error_message=f"{error_msg}\n\nTraceback:\n{error_traceback}")

        # Update source status (only if source_id is available)
        if source_id:
            try:
                from modules.ingestion import detect_url_provider
                from modules.ingestion_diagnostics import (
                    build_error,
                    diagnostics_schema_status,
                    finish_step,
                )

                provider = provider or (detect_url_provider(citation_url) if citation_url else "file")

                # Do not overwrite a provider-specific `last_error` if it was already captured.
                emit_generic_error = True
                diag_ok, _diag_err = diagnostics_schema_status()
                if diag_ok:
                    try:
                        current = (
                            supabase.table("sources")
                            .select("status,last_error,last_step")
                            .eq("id", source_id)
                            .eq("twin_id", twin_id)
                            .single()
                            .execute()
                        )
                        cur = current.data or {}
                        existing = cur.get("last_error")
                        if cur.get("status") == "error" and isinstance(existing, dict) and existing.get("code"):
                            emit_generic_error = False
                    except Exception:
                        # If schema drifts, fall back to emitting a generic error (it will be minimal anyway).
                        emit_generic_error = True

                if emit_generic_error:
                    step = (source_data.get("last_step") or "processing") if isinstance(source_data, dict) else "processing"
                    err = build_error(
                        code="INGESTION_JOB_FAILED",
                        message=error_msg,
                        provider=provider,
                        step=step,
                        correlation_id=correlation_id,
                        raw={"job_id": job_id, "url": citation_url},
                        exc=e,
                    )
                    finish_step(
                        event_id="",
                        source_id=source_id,
                        twin_id=twin_id,
                        provider=provider,
                        step=step,
                        status="error",
                        correlation_id=correlation_id,
                        error=err,
                    )
            except Exception as source_error:
                logger.warning("Error updating source status: %s", source_error)

        return False


async def process_training_queue(twin_ids: list) -> dict[str, Any]:
    """
    Process all queued training jobs for the given twin IDs.
    This is an async function that properly awaits job processing.

    Args:
        twin_ids: List of twin UUIDs to process jobs for

    Returns:
        Dict with processed, failed, remaining counts and errors
    """
    from modules.observability import supabase

    # Get all queued jobs for these twins
    try:
        query = supabase.table("training_jobs").select("id, twin_id, source_id") \
            .in_("twin_id", twin_ids).eq("status", "queued") \
            .order("priority", desc=True).limit(50)
        response = query.execute()
        queued_jobs = response.data or []
    except Exception as e:
        logger.error("Error fetching queued jobs: %s", e)
        return {
            "processed": 0,
            "failed": 0,
            "remaining": 0,
            "errors": [str(e)]
        }

    if not queued_jobs:
        return {
            "processed": 0,
            "failed": 0,
            "remaining": 0,
            "errors": []
        }

    processed = 0
    failed = 0
    errors = []

    # Process each job - properly await the async function
    for job in queued_jobs:
        job_id = job["id"]
        try:
            success = await process_training_job(job_id)
            if success:
                processed += 1
            else:
                failed += 1
                errors.append(f"Job {job_id}: Processing returned False")
        except Exception as e:
            failed += 1
            errors.append(f"Job {job_id}: {str(e)}")

    # Count remaining
    try:
        remaining_query = supabase.table("training_jobs") \
            .select("id", count="exact") \
            .in_("twin_id", twin_ids).eq("status", "queued")
        remaining_response = remaining_query.execute()
        remaining = remaining_response.count or 0
    except Exception:
        remaining = 0

    return {
        "processed": processed,
        "failed": failed,
        "remaining": remaining,
        "errors": errors
    }


# =============================================================================
# Dead Letter Queue & Retry Logic
# =============================================================================

MAX_RETRY_ATTEMPTS = 3  # Maximum number of retry attempts before DLQ
RETRY_DELAY_BASE_SECONDS = 30  # Base delay for exponential backoff


def should_retry_job(job: dict[str, Any], error_message: str) -> bool:
    """
    Determine if a failed job should be retried based on error type and attempt count.

    Args:
        job: The failed job record
        error_message: The error message from the failure

    Returns:
        True if job should be retried, False to send to DLQ
    """
    retry_count = job.get("retry_count", 0)

    # Don't retry if max attempts reached
    if retry_count >= MAX_RETRY_ATTEMPTS:
        logger.warning("[Retry] Job %s exceeded max retries (%s), sending to DLQ", job['id'], MAX_RETRY_ATTEMPTS)
        return False

    # Non-retryable error patterns
    non_retryable_patterns = [
        "YOUTUBE_TRANSCRIPT_UNAVAILABLE",
        "X_BLOCKED_OR_UNSUPPORTED",
        "LINKEDIN_BLOCKED_OR_REQUIRES_AUTH",
        "FILE_EXTRACTION_EMPTY",
        "FILE_EXTRACTION_FAILED",
        "Invalid YouTube URL",
        "No text extracted",
        "not available in your region",
        "requires authentication",
        "deleted, private, or not found",
    ]

    error_lower = error_message.lower()
    for pattern in non_retryable_patterns:
        if pattern.lower() in error_lower:
            logger.warning("[Retry] Job %s has non-retryable error pattern '%s', sending to DLQ", job['id'], pattern)
            return False

    return True


def calculate_retry_delay(retry_count: int) -> int:
    """
    Calculate delay for retry using exponential backoff with jitter.

    Args:
        retry_count: Current retry attempt (0-indexed)

    Returns:
        Delay in seconds
    """
    import random

    # Exponential backoff: 30s, 60s, 120s
    base_delay = RETRY_DELAY_BASE_SECONDS * (2 ** retry_count)

    # Add jitter (±25%) to prevent thundering herd
    jitter = random.uniform(0.75, 1.25)
    delay = int(base_delay * jitter)

    # Cap at 5 minutes
    return min(delay, 300)


def retry_training_job_with_backoff(job_id: str) -> bool:
    """
    Retry a failed training job with exponential backoff.

    Args:
        job_id: Job UUID to retry

    Returns:
        True if job was successfully re-queued, False otherwise
    """
    try:
        job = get_training_job(job_id)
        if not job:
            logger.warning("[Retry] Job %s not found", job_id)
            return False

        # Check if job is in a retryable state
        if job.get("status") not in ["failed", "needs_attention"]:
            logger.warning("[Retry] Job %s is not in failed state (status: %s)", job_id, job.get('status'))
            return False

        # Check retry eligibility
        error_message = job.get("error_message", "")
        if not should_retry_job(job, error_message):
            # Move to DLQ state (permanent failure)
            update_job_status(job_id, "dead_letter",
                error_message=f"PERMANENT FAILURE: {error_message}")
            return False

        # Increment retry count
        current_retry = job.get("retry_count", 0)
        new_retry_count = current_retry + 1
        delay_seconds = calculate_retry_delay(current_retry)

        # Calculate next attempt time
        from datetime import datetime, timedelta
        next_attempt_at = (datetime.utcnow() + timedelta(seconds=delay_seconds)).isoformat()

        # Update job for retry
        update_data = {
            "status": "queued",
            "retry_count": new_retry_count,
            "error_message": None,  # Clear error message
            "updated_at": datetime.utcnow().isoformat(),
        }

        # Update metadata with retry info
        metadata = job.get("metadata", {})
        metadata["retry_history"] = metadata.get("retry_history", []) + [{
            "attempt": new_retry_count,
            "previous_error": error_message[:500],  # Truncate long errors
            "retried_at": datetime.utcnow().isoformat(),
            "next_attempt_delay_seconds": delay_seconds,
        }]
        metadata["next_attempt_after"] = next_attempt_at
        update_data["metadata"] = metadata

        # Clear completed_at since we're retrying
        update_data["completed_at"] = None

        supabase.table("training_jobs").update(update_data).eq("id", job_id).execute()

        # Re-queue with delay (if Redis supports delayed queues) or immediate
        # For now, we rely on the next_attempt_after metadata for filtering
        enqueue_job(job_id, job.get("job_type", "ingestion"), job.get("priority", 0), metadata)

        logger.info("[Retry] Job %s re-queued for attempt %s/%s (delay: %ss)", job_id, new_retry_count, MAX_RETRY_ATTEMPTS, delay_seconds)
        return True

    except Exception as e:
        logger.error("[Retry] Error retrying job %s: %s", job_id, e)
        return False


def get_jobs_pending_retry() -> list[dict[str, Any]]:
    """
    Get jobs that are queued but waiting for their retry delay to pass.

    Returns:
        List of jobs ready to be processed
    """
    try:
        from datetime import datetime
        now = datetime.utcnow().isoformat()

        # Get queued jobs where next_attempt_after has passed or is null
        response = supabase.table("training_jobs") \
            .select("*") \
            .eq("status", "queued") \
            .or_(f"metadata->>next_attempt_after.is.null,metadata->>next_attempt_after.lte.{now}") \
            .order("priority", desc=True) \
            .order("created_at", desc=False) \
            .limit(50) \
            .execute()

        return response.data or []
    except Exception as e:
        logger.error("[Retry] Error fetching jobs pending retry: %s", e)
        return []


def get_dead_letter_jobs(twin_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """
    Get jobs that have exceeded max retries and are in dead letter state.

    Args:
        twin_id: Optional twin filter
        limit: Maximum results

    Returns:
        List of dead letter jobs
    """
    try:
        query = supabase.table("training_jobs") \
            .select("*") \
            .eq("status", "dead_letter")

        if twin_id:
            query = query.eq("twin_id", twin_id)

        response = query.order("updated_at", desc=True).limit(limit).execute()
        return response.data or []
    except Exception as e:
        logger.error("[DLQ] Error fetching dead letter jobs: %s", e)
        return []


def replay_dead_letter_job(job_id: str) -> bool:
    """
    Manually replay a job from the dead letter queue.
    Resets retry count and re-queues for processing.

    Args:
        job_id: Job UUID in dead letter state

    Returns:
        True if successfully replayed
    """
    try:
        job = get_training_job(job_id)
        if not job or job.get("status") != "dead_letter":
            logger.warning("[DLQ] Job %s not found or not in dead_letter state", job_id)
            return False

        # Reset for retry
        from datetime import datetime
        update_data = {
            "status": "queued",
            "retry_count": 0,  # Reset retry count
            "error_message": None,
            "updated_at": datetime.utcnow().isoformat(),
        }

        metadata = job.get("metadata", {})
        metadata["replayed_from_dlq_at"] = datetime.utcnow().isoformat()
        metadata["dlq_error"] = job.get("error_message")  # Preserve original error
        update_data["metadata"] = metadata

        supabase.table("training_jobs").update(update_data).eq("id", job_id).execute()

        enqueue_job(job_id, job.get("job_type", "ingestion"), job.get("priority", 0), metadata)

        logger.info("[DLQ] Job %s replayed from dead letter queue", job_id)
        return True

    except Exception as e:
        logger.error("[DLQ] Error replaying job %s: %s", job_id, e)
        return False


# Modify process_training_job to use retry logic
async def process_training_job_with_retry(job_id: str) -> bool:
    """
    Wrapper around process_training_job that handles automatic retries.

    Args:
        job_id: Job UUID

    Returns:
        True if job succeeded or was successfully queued for retry
    """
    from modules.training_jobs import process_training_job

    success = await process_training_job(job_id)

    if not success:
        # Try to retry with backoff
        retry_queued = retry_training_job_with_backoff(job_id)
        if retry_queued:
            # Return True because we successfully queued for retry
            # The job will be processed again later
            return True
        # If retry not queued, it went to DLQ - return False

    return success
