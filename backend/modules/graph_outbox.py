"""
Graph Memory Outbox

Reliable async writes using existing job_queue infrastructure.
Idempotent job submission with at-least-once delivery.

Single-Profile Scope Migration:
- All deduplication includes scope_id
- scope_id: "{tenant_id}__{creator_id}" (single-profile boundary)
- Critical fix: dedup query now filters by scope_id to prevent cross-scope collisions
"""

import uuid
import logging
from typing import Any
from datetime import datetime
from enum import Enum

from modules.graph_memory_config import get_graph_memory_config
from modules.job_queue import enqueue_job
from modules.observability import supabase

logger = logging.getLogger(__name__)


class GraphOperationType(Enum):
    CREATE_EPISODE = "create_episode"
    CREATE_CLAIMS = "create_claims"
    UPDATE_CLAIM_STATUS = "update_claim_status"
    CREATE_RELATIONSHIP = "create_relationship"
    DELETE_TWIN_GRAPH = "delete_twin_graph"
    REFRESH_SNAPSHOT = "refresh_snapshot"
    # Phase 2: Escalation integration
    EXTRACT_CLAIMS = "extract_claims"
    EVALUATE_CONTRADICTIONS = "evaluate_contradictions"
    # Persona research: long-running, dispatched to worker
    PERSONA_RESEARCH = "persona_research"
    # Background web enrichment: single-agent search + scrape
    ENRICH_FROM_WEB = "enrich_from_web"
    # Background Firecrawl profile extraction (runs during onboarding while user fills form)
    FIRECRAWL_EXTRACT = "firecrawl_extract"
    # Phase 25: Meeting Intelligence
    SCHEDULE_MEETING_BOT = "schedule_meeting_bot"
    PROCESS_MEETING_TRANSCRIPT = "process_meeting_transcript"
    # Phase 26: Meeting Summaries
    GENERATE_MEETING_SUMMARY = "generate_meeting_summary"
    # Phase 27: Meeting Knowledge Base
    INDEX_MEETING_TRANSCRIPT = "index_meeting_transcript"
    # Phase 28: Proactive Notifications
    GENERATE_MEETING_BRIEFING = "generate_meeting_briefing"
    GENERATE_MEETING_FOLLOWUP = "generate_meeting_followup"
    GENERATE_WEEKLY_DIGEST = "generate_weekly_digest"
    SEND_LIFECYCLE_EMAIL = "send_lifecycle_email"
    # Phase 30 / W9d: opt-in deep research mode for the pre-meeting brief.
    # Enqueued ONLY by POST /v2/meetings/{twin}/{meeting}/brief/deep when
    # the user explicitly clicks "Run deep research". Long-running
    # (~25-45s) ADK ReAct loop with web + KB + scrape tools. Must never
    # be enqueued by cron or any automated path. Feature-flagged at both
    # the API layer and the worker layer via BRIEF_DEEP_MODE_ENABLED.
    GENERATE_DEEP_BRIEF = "generate_deep_brief"
    # Phase 29: Active Twin in Meetings
    WARM_MEETING_CACHE = "warm_meeting_cache"
    # Phase 29: Post-meeting KB attribution for twin responses
    ENRICH_TWIN_RESPONSES = "enrich_twin_responses"
    # Phase 30: Pre-session KB context prep (stored in meetings.context_prep)
    PREP_MEETING_CONTEXT = "prep_meeting_context"
    # Phase 5: Stripe usage meter reporting (async, non-blocking)
    STRIPE_METER_EVENT = "stripe_meter_event"
    # Layer 1 (Sooraj/mvp): Desktop SDK transcript fetch on sdk_upload.complete
    PROCESS_DESKTOP_SDK_RECORDING = "process_desktop_sdk_recording"
    # Layer 2: action item reminders and recap edit routing
    SEND_ACTION_ITEM_REMINDER = "send_action_item_reminder"
    ROUTE_RECAP_EDIT_TO_STORE = "route_recap_edit_to_store"
    # Phase F.2: People surface — cross-meeting identity linking
    LINK_MEETING_CONTACTS = "link_meeting_contacts"
    # Batch A: Extract action-item commitments from meeting transcripts
    EXTRACT_COMMITMENTS = "extract_commitments"
    # Batch B: Extract memory candidates from meeting transcripts
    EXTRACT_MEMORY_CANDIDATES = "extract_memory_candidates"
    # Phase 30-D: Recall.ai Calendar V2 sync (event ingest via webhook trigger)
    RECALL_CALENDAR_SYNC = "recall_calendar_sync"
    # Phase 30-K: Resolve meeting speakers from Recall bot participant list
    RESOLVE_MEETING_SPEAKERS = "resolve_meeting_speakers"
    # Granola Batch 3: AI-merge user notes + live transcript into enhanced notes
    ENHANCE_NOTES = "enhance_notes"
    # Granola Batch 5: reliability watchdog flipping stuck recaps to failed
    RECAP_TIMEOUT_CHECK = "recap_timeout_check"
    # Home v1 "Respond": send an owner-approved follow-up draft email
    SEND_FOLLOWUP_DRAFT = "send_followup_draft"
    # Agentic notifications: flow executor and outcome measurement.
    RUN_NOTIFICATION_FLOW = "run_notification_flow"
    PROCESS_NOTIFICATION_EVENT = "process_notification_event"
    MEASURE_NOTIFICATION_OUTCOME = "measure_notification_outcome"
    # Visitor lead capture: notify persona owner when a visitor submits contact info.
    LEAD_CAPTURED = "lead_captured"


class GraphOutbox:
    """
    Outbox pattern for graph memory writes.

    1. Jobs stored in graph_outbox table (durability)
    2. Enqueued to Redis job queue (processing)
    3. Worker processes with idempotency
    4. Completed jobs marked as done

    Single-Profile Scope:
    - All jobs are scoped by scope_id
    - Deduplication is scope-isolated (critical bug fix)
    """

    def __init__(self):
        self.config = get_graph_memory_config()

    @staticmethod
    def _normalize_db_uuid(value: str | None, *, namespace: str) -> str:
        """
        Normalize identifiers for UUID-backed graph_outbox columns.

        Production tenant/twin IDs are already UUIDs, but tests and a few legacy
        fallback paths can still pass descriptive strings such as "default" or
        "test-tenant-a-1234". Those values should not crash outbox submission.
        """
        raw = str(value or "").strip() or f"{namespace}:default"
        try:
            return str(uuid.UUID(raw))
        except Exception:
            return str(uuid.uuid5(uuid.NAMESPACE_URL, f"graph-outbox:{namespace}:{raw}"))

    @staticmethod
    def _is_missing_column_error(error: Exception, column: str) -> bool:
        """Detect schema-cache/column-missing errors from PostgREST/Postgres."""
        err = str(error).lower()
        column = column.lower()
        return (
            f"'{column}' column" in err
            or f"column graph_outbox.{column} does not exist" in err
            or f"{column} does not exist" in err
        )

    def submit(
        self,
        tenant_id: str,
        twin_id: str,
        operation: GraphOperationType,
        idempotency_key: str,
        payload: dict[str, Any],
        priority: int = 0,
        correlation_id: str | None = None,
        scope_id: str | None = None,
        creator_id: str | None = None,
        next_attempt_after: datetime | None = None,
    ) -> str:
        """
        Submit operation to outbox.

        CRITICAL FIX: Deduplication now includes scope_id to prevent cross-scope
        collisions where two different profiles could have the same idempotency key.

        Args:
            tenant_id: Tenant ID
            twin_id: Twin ID (legacy, kept for backward compat)
            operation: Type of graph operation
            idempotency_key: Deterministic key for deduplication
            payload: Operation-specific data
            priority: Job priority (higher = processed first)
            correlation_id: For tracing
            scope_id: Single-profile scope ID (optional but recommended)
            creator_id: Creator ID for single-profile (optional)
            next_attempt_after: Optional UTC timestamp for delayed processing

        Returns:
            Job ID
        """
        job_id = str(uuid.uuid4())
        op_value = operation.value if hasattr(operation, "value") else str(operation)
        db_tenant_id = self._normalize_db_uuid(tenant_id, namespace="tenant")
        db_twin_id = self._normalize_db_uuid(
            twin_id or scope_id or creator_id or "default",
            namespace="twin",
        )

        # CRITICAL FIX: Scope-isolated deduplication
        # This prevents cross-scope collisions where scope A and scope B
        # could have jobs with the same idempotency_key
        try:
            if scope_id:
                # Single-profile mode: filter by scope_id
                try:
                    existing = supabase.table("graph_outbox").select("id, status").eq(
                        "tenant_id", db_tenant_id
                    ).eq("scope_id", scope_id).eq(
                        "idempotency_key", idempotency_key
                    ).in_("status", ["pending", "processing", "completed"]).execute()
                except Exception as scope_error:
                    # Backward compatibility when single-profile migration is not applied yet.
                    if self._is_missing_column_error(scope_error, "scope_id"):
                        logger.warning(
                            "[GraphOutbox] scope_id column missing; falling back to twin_id dedupe"
                        )
                        existing = supabase.table("graph_outbox").select("id, status").eq(
                            "tenant_id", db_tenant_id
                        ).eq("twin_id", db_twin_id).eq(
                            "idempotency_key", idempotency_key
                        ).in_("status", ["pending", "processing", "completed"]).execute()
                    else:
                        raise
            else:
                # Legacy mode: filter by twin_id (backward compatibility during rollout)
                existing = supabase.table("graph_outbox").select("id, status").eq(
                    "tenant_id", db_tenant_id
                ).eq("twin_id", db_twin_id).eq(
                    "idempotency_key", idempotency_key
                ).in_("status", ["pending", "processing", "completed"]).execute()

            if existing.data:
                existing_job = existing.data[0]
                scope_info = f"scope={scope_id[:20]}..." if scope_id else f"twin={twin_id}"
                logger.info(
                    f"[GraphOutbox] Deduplicating job with idempotency_key {idempotency_key[:16]}... "
                    f"{scope_info} Existing job: {existing_job['id']} ({existing_job['status']})"
                )
                return existing_job["id"]
        except Exception as e:
            logger.warning(f"[GraphOutbox] Deduplication check failed: {e}")

        # Create outbox record with scope_id
        now = datetime.utcnow().isoformat()
        outbox_record = {
            "id": job_id,
            "tenant_id": db_tenant_id,
            "twin_id": db_twin_id,
            "scope_id": scope_id,  # NEW: Single-profile scope
            "creator_id": creator_id,  # NEW: Creator ID for quick reference
            "operation": op_value,
            "idempotency_key": idempotency_key,
            "payload": payload,
            "status": "pending",
            "priority": priority,
            "attempt_count": 0,
            "max_attempts": self.config.max_retries,
            "correlation_id": correlation_id,
            "next_attempt_after": next_attempt_after.isoformat() if next_attempt_after else None,
            "created_at": now,
            "updated_at": now
        }

        try:
            supabase.table("graph_outbox").insert(outbox_record).execute()
        except Exception as e:
            # Backward compatibility with pre-migration schema (no scope_id/creator_id columns).
            if self._is_missing_column_error(e, "scope_id") or self._is_missing_column_error(e, "creator_id"):
                # Refuse to silently drop a delayed-job schedule. The legacy
                # fallback exists to support pre-scope_id schemas (older
                # deployments that haven't run migration_graph_memory_phase1
                # yet); it must NOT silently fire a delayed reminder
                # immediately by dropping next_attempt_after.
                if next_attempt_after is not None:
                    raise RuntimeError(
                        "graph_outbox legacy fallback cannot preserve "
                        "next_attempt_after — apply migration_graph_memory_"
                        "phase1.sql or upgrade the schema before enqueueing "
                        "scheduled jobs. Original insert error: " + str(e)
                    ) from e
                legacy_record = dict(outbox_record)
                legacy_record.pop("scope_id", None)
                legacy_record.pop("creator_id", None)
                legacy_record.pop("next_attempt_after", None)
                logger.warning(
                    "[GraphOutbox] scope columns missing; retrying insert in legacy schema mode"
                )
                try:
                    supabase.table("graph_outbox").insert(legacy_record).execute()
                except Exception as legacy_error:
                    logger.error(f"[GraphOutbox] Failed to create legacy outbox record: {legacy_error}")
                    raise
            else:
                logger.error(f"[GraphOutbox] Failed to create outbox record: {e}")
                raise

        # Enqueue to job queue with scope info
        try:
            enqueue_job(
                job_id=job_id,
                job_type="graph_memory",
                priority=priority,
                metadata={
                    "tenant_id": tenant_id,
                    "twin_id": twin_id,
                    "scope_id": scope_id,
                    "creator_id": creator_id,
                    "operation": op_value,
                    "correlation_id": correlation_id
                }
            )
            scope_info = f"scope={scope_id[:20]}..." if scope_id else f"twin={twin_id}"
            logger.info(f"[GraphOutbox] Submitted job {job_id} for {op_value} ({scope_info})")
        except Exception as e:
            logger.error(f"[GraphOutbox] Failed to enqueue job: {e}")
            # Job is in outbox table, will be picked up by DB dequeue

        return job_id

    def claim_job(self, job_id: str, worker_id: str) -> dict[str, Any] | None:
        """
        Atomically claim job for processing.
        Uses UPDATE...WHERE for race condition safety.
        """
        now = datetime.utcnow().isoformat()

        try:
            # Use RPC for atomic claim if available
            result = supabase.rpc(
                "claim_graph_outbox_job",
                {
                    "p_job_id": job_id,
                    "p_worker_id": worker_id,
                    "p_now": now
                }
            ).execute()

            if result.data:
                return result.data[0]

            # Fallback: manual claim with status check
            result = supabase.table("graph_outbox").update({
                "status": "processing",
                "updated_at": now,
                "attempt_count": supabase.rpc("increment_attempt", {})
            }).eq("id", job_id).eq("status", "pending").execute()

            if result.data:
                return result.data[0]

            return None

        except Exception as e:
            logger.error(f"[GraphOutbox] Claim failed: {e}")
            return None

    def complete_job(self, job_id: str, success: bool, error_message: str | None = None):
        """Mark job as completed or failed."""
        now = datetime.utcnow().isoformat()

        if success:
            try:
                supabase.table("graph_outbox").update({
                    "status": "completed",
                    "updated_at": now,
                    "completed_at": now
                }).eq("id", job_id).execute()
                logger.debug(f"[GraphOutbox] Job {job_id} completed")
            except Exception as e:
                logger.error(f"[GraphOutbox] Failed to mark job complete: {e}")
        else:
            # Check retry count
            try:
                job = supabase.table("graph_outbox").select("attempt_count, max_attempts").eq(
                    "id", job_id
                ).single().execute()

                if job.data and job.data["attempt_count"] >= job.data["max_attempts"]:
                    # Max retries reached - mark failed
                    supabase.table("graph_outbox").update({
                        "status": "failed",
                        "updated_at": now,
                        "error_message": error_message,
                        "failed_at": now
                    }).eq("id", job_id).execute()
                    logger.error(f"[GraphOutbox] Job {job_id} failed permanently after {job.data['attempt_count']} attempts")
                else:
                    # Retry later
                    supabase.table("graph_outbox").update({
                        "status": "pending",
                        "updated_at": now,
                        "error_message": error_message,
                        "next_attempt_after": self._calculate_retry_time(job.data["attempt_count"])
                    }).eq("id", job_id).execute()
                    logger.warning(f"[GraphOutbox] Job {job_id} will retry (attempt {job.data['attempt_count']})")

            except Exception as e:
                logger.error(f"[GraphOutbox] Failed to update job status: {e}")

    def _calculate_retry_time(self, attempt_count: int) -> str:
        """Calculate next retry time with exponential backoff."""
        import datetime
        delay_seconds = min(2 ** attempt_count, 3600)  # Max 1 hour
        next_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=delay_seconds)
        return next_time.isoformat()

    def get_pending_jobs(self, limit: int = 100, scope_id: str | None = None) -> list[dict[str, Any]]:
        """
        Get pending jobs for processing.

        Args:
            limit: Maximum number of jobs to fetch
            scope_id: Optional scope filter for single-profile isolation
        """
        now = datetime.utcnow().isoformat()

        try:
            query = supabase.table("graph_outbox").select("*").eq(
                "status", "pending"
            ).or_(f"next_attempt_after.is.null,next_attempt_after.lte.{now}").order(
                "priority", desc=True
            ).order("created_at", desc=False).limit(limit)

            # Filter by scope if provided (single-profile mode)
            if scope_id:
                query = query.eq("scope_id", scope_id)

            result = query.execute()
            return result.data or []
        except Exception as e:
            if scope_id and self._is_missing_column_error(e, "scope_id"):
                logger.warning("[GraphOutbox] scope_id missing; retrying get_pending_jobs without scope filter")
                try:
                    result = supabase.table("graph_outbox").select("*").eq(
                        "status", "pending"
                    ).or_(f"next_attempt_after.is.null,next_attempt_after.lte.{now}").order(
                        "priority", desc=True
                    ).order("created_at", desc=False).limit(limit).execute()
                    return result.data or []
                except Exception:
                    pass
            logger.error(f"[GraphOutbox] Failed to fetch pending jobs: {e}")
            return []

    def get_depth(self, scope_id: str | None = None) -> int:
        """
        Get current outbox depth for monitoring.

        Args:
            scope_id: Optional scope filter for single-profile monitoring
        """
        try:
            query = supabase.table("graph_outbox").select("id", count="exact").eq(
                "status", "pending"
            )

            if scope_id:
                query = query.eq("scope_id", scope_id)

            result = query.execute()
            return result.count or 0
        except Exception as e:
            if scope_id and self._is_missing_column_error(e, "scope_id"):
                logger.warning("[GraphOutbox] scope_id missing; retrying get_depth without scope filter")
                try:
                    result = supabase.table("graph_outbox").select("id", count="exact").eq(
                        "status", "pending"
                    ).execute()
                    return result.count or 0
                except Exception:
                    pass
            logger.error(f"[GraphOutbox] Failed to get depth: {e}")
            return 0

    def get_stats(self, scope_id: str | None = None) -> dict[str, int]:
        """
        Get outbox statistics.

        Args:
            scope_id: Optional scope filter for single-profile stats
        """
        try:
            base_query = supabase.table("graph_outbox")

            def _query_counts(with_scope: bool):
                if with_scope and scope_id:
                    return (
                        base_query.select("id", count="exact").eq("status", "pending").eq("scope_id", scope_id).execute(),
                        base_query.select("id", count="exact").eq("status", "processing").eq("scope_id", scope_id).execute(),
                        base_query.select("id", count="exact").eq("status", "completed").eq("scope_id", scope_id).execute(),
                        base_query.select("id", count="exact").eq("status", "failed").eq("scope_id", scope_id).execute(),
                    )
                return (
                    base_query.select("id", count="exact").eq("status", "pending").execute(),
                    base_query.select("id", count="exact").eq("status", "processing").execute(),
                    base_query.select("id", count="exact").eq("status", "completed").execute(),
                    base_query.select("id", count="exact").eq("status", "failed").execute(),
                )

            try:
                pending, processing, completed, failed = _query_counts(with_scope=bool(scope_id))
            except Exception as scoped_error:
                if scope_id and self._is_missing_column_error(scoped_error, "scope_id"):
                    logger.warning("[GraphOutbox] scope_id missing; retrying get_stats without scope filter")
                    pending, processing, completed, failed = _query_counts(with_scope=False)
                else:
                    raise

            return {
                "pending": pending.count or 0,
                "processing": processing.count or 0,
                "completed": completed.count or 0,
                "failed": failed.count or 0
            }
        except Exception as e:
            logger.error(f"[GraphOutbox] Failed to get stats: {e}")
            return {"pending": 0, "processing": 0, "completed": 0, "failed": 0}


# Global outbox instance
_outbox_instance: GraphOutbox | None = None


def get_graph_outbox() -> GraphOutbox:
    """Get or create global outbox instance."""
    global _outbox_instance
    if _outbox_instance is None:
        _outbox_instance = GraphOutbox()
    return _outbox_instance


def reset_outbox():
    """Reset outbox (for testing)."""
    global _outbox_instance
    _outbox_instance = None
