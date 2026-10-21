"""
Graph Outbox Worker

Processes graph_memory operations from graph_outbox directly.
This keeps graph-memory writes independent of the generic jobs queue.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from adk_core.services.persona_core.deep_brief import run_deep_brief
from adk_core.services.persona_core.deep_brief_merge import (
    deep_cache_is_fresh,
    merge_deep_into_brief,
)
from adk_core.services.vector_store import search as vector_search
from modules.graph_contradiction_detector import process_contradiction_evaluation_job
from modules.graph_memory_core import GraphMemoryCore
from modules.graph_outbox import GraphOperationType, get_graph_outbox
from modules.graph_snapshot_manager import refresh_scope_snapshot, refresh_twin_snapshot
from modules.observability import get_supabase_client, supabase
from modules.posthog_analytics import ph_capture_exception

# Heavy bot-dispatch imports lifted to module-top (Bug 1 fix).
# Previously these were lazy-imported inside _process_schedule_meeting_bot,
# which on a cold Cloud Run worker instance added 90–120s of import time
# per job (Firecrawl, Google ADK, Recall SDK chain). Lifting them runs
# the import once at worker boot, amortized across all jobs the instance
# handles. Job dispatch latency drops from ~120s to <5s.
from routers.gemini_live import issue_meeting_token  # noqa: E402
from services.recall_service import (  # noqa: E402
    create_bot,
    create_gemini_live_bot,
    create_voice_bot,
    format_bot_name,
)

logger = logging.getLogger(__name__)
SYSTEM_TWIN_ID = os.getenv("SYSTEM_TWIN_ID", "00000000-0000-4000-8000-000000000000")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _short_hash(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _infer_claim_type(sentence: str) -> str:
    lower = sentence.lower()
    if any(token in lower for token in ("prefer", "like", "dislike", "want")):
        return "preference"
    if any(token in lower for token in ("believe", "think", "opinion")):
        return "belief"
    if any(token in lower for token in ("should", "must", "best", "worst")):
        return "opinion"
    return "fact"


def _split_claim_candidates(text: str, max_claims: int = 10) -> list[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []

    chunks = re.split(r"[.\n!?;]+", normalized)
    seen = set()
    claims: list[str] = []
    for raw in chunks:
        sentence = _normalize_text(raw)
        if len(sentence) < 24:
            continue
        if sentence in seen:
            continue
        seen.add(sentence)
        claims.append(sentence[:400])
        if len(claims) >= max_claims:
            break

    if claims:
        return claims

    return [normalized[:220]]


async def _run_db(callable_obj):
    return await asyncio.to_thread(callable_obj)


def _extract_primary_attendee(summary: dict[str, Any], meeting: dict[str, Any]) -> str | None:
    """Return a primary attendee name for use in the recap email subject.

    Order of preference:
      1. summary["people_observed"][0]["name"]
      2. meeting["attendees_json"][0] -> displayName / name / email
    Returns None if nothing usable.
    """
    people = summary.get("people_observed") if isinstance(summary.get("people_observed"), list) else []
    for person in people:
        if isinstance(person, dict):
            name = str(person.get("name") or "").strip()
            if name:
                return name

    attendees = meeting.get("attendees_json") if isinstance(meeting.get("attendees_json"), list) else []
    for attendee in attendees:
        if isinstance(attendee, dict):
            for key in ("displayName", "name", "email"):
                candidate = str(attendee.get(key) or "").strip()
                if candidate:
                    return candidate
        elif isinstance(attendee, str) and attendee.strip():
            return attendee.strip()
    return None


async def _list_pending_job_ids(limit: int = 1) -> list[str]:
    # Use naive UTC timestamp (no +00:00 offset) — the "+" in a URL query string
    # is decoded as a space by PostgREST, producing invalid timestamp syntax.
    now_iso = datetime.utcnow().isoformat()

    def _query():
        result = (
            supabase.table("graph_outbox")
            .select("id")
            .eq("status", "pending")
            .or_(f"next_attempt_after.is.null,next_attempt_after.lte.{now_iso}")
            .order("priority", desc=True)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return [str(row.get("id")) for row in (result.data or []) if row.get("id")]

    try:
        return await _run_db(_query)
    except Exception as exc:
        logger.error("[GraphOutboxWorker] failed to list pending jobs: %s", exc)
        return []


async def _claim_job(job_id: str, worker_id: str) -> dict[str, Any] | None:
    now_iso = _utcnow_iso()

    def _claim_rpc():
        return supabase.rpc(
            "claim_graph_outbox_job",
            {
                "p_job_id": job_id,
                "p_worker_id": worker_id,
                "p_now": now_iso,
            },
        ).execute()

    try:
        claimed = await _run_db(_claim_rpc)
        if not claimed.data:
            return None
    except Exception as exc:
        # Backward-compatible fallback if RPC is unavailable.
        error_text = str(exc or "")
        if "42702" in error_text or 'column reference "id" is ambiguous' in error_text:
            logger.info(
                "[GraphOutboxWorker] claim RPC unavailable for %s, using fallback update path",
                job_id,
            )
        else:
            logger.warning("[GraphOutboxWorker] claim RPC failed for %s: %s", job_id, exc)

        def _fallback_claim():
            return (
                supabase.table("graph_outbox")
                .update({"status": "processing", "updated_at": now_iso})
                .eq("id", job_id)
                .eq("status", "pending")
                .execute()
            )

        fallback = await _run_db(_fallback_claim)
        if not fallback.data:
            return None

    def _load():
        return supabase.table("graph_outbox").select("*").eq("id", job_id).single().execute()

    loaded = await _run_db(_load)
    return loaded.data if loaded and loaded.data else None


async def _mark_job_completed(job_id: str, payload: dict[str, Any] | None = None):
    now_iso = _utcnow_iso()
    update_data: dict[str, Any] = {
        "status": "completed",
        "updated_at": now_iso,
        "completed_at": now_iso,
        "error_message": None,
    }
    if payload is not None:
        update_data["payload"] = payload

    def _update():
        return (
            supabase.table("graph_outbox")
            .update(update_data)
            .eq("id", job_id)
            .execute()
        )

    await _run_db(_update)


async def _mark_job_failed(
    job: dict[str, Any],
    error_message: str,
    *,
    permanent: bool = False,
):
    """Mark a job failed.

    Layer 3 (worker-smooth): callers can pass ``permanent=True`` for errors
    that retries cannot fix (malformed payload, 4xx HTTP, ValueError on
    required field). The job goes straight to ``status='failed'`` with
    ``attempt_count`` maxed out, skipping the retry-backoff dance.

    Default ``permanent=False`` preserves the historical retry-up-to-5x
    behavior for transient errors (5xx, network, supabase 503, Gemini 429).
    """
    job_id = str(job.get("id"))
    attempt_count = int(job.get("attempt_count") or 0)
    max_attempts = int(job.get("max_attempts") or 5)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    safe_error = (error_message or "unknown error")[:2000]

    # Detect Gemini/Google 429 / quota exhaustion / LLM budget exceeded — use a
    # longer minimum backoff so the worker doesn't burn all retries within 60s.
    is_rate_limit = any(
        marker in safe_error
        for marker in ("429", "RESOURCE_EXHAUSTED", "quota", "rate limit", "rateLimitExceeded", "LlmBudgetExceeded")
    )

    if permanent or attempt_count >= max_attempts:
        payload = {
            "status": "failed",
            "updated_at": now_iso,
            "failed_at": now_iso,
            "error_message": safe_error,
            # Set attempt_count to max so observability dashboards can
            # distinguish "fast-failed (permanent)" from "retried out".
            "attempt_count": max_attempts if permanent else attempt_count,
        }
    else:
        base_backoff = min(2 ** max(attempt_count, 1), 3600)
        backoff_seconds = max(60, base_backoff) if is_rate_limit else base_backoff
        payload = {
            "status": "pending",
            "attempt_count": attempt_count + 1,  # increment so jobs exhaust retries and reach failed
            "updated_at": now_iso,
            "error_message": safe_error,
            "next_attempt_after": (now + timedelta(seconds=backoff_seconds)).isoformat(),
        }

    def _update():
        return supabase.table("graph_outbox").update(payload).eq("id", job_id).execute()

    await _run_db(_update)


# ---------------------------------------------------------------------------
# Layer 1: per-job timeout. The default JOB_TIMEOUT_SECONDS protects every
# handler from holding a worker slot forever. Long-running handlers (deep
# brief, persona research, web enrichment, indexing) get explicit higher
# limits via _PER_OP_TIMEOUT_OVERRIDES. Adjust per Cloud Run instance limits
# and the slowest legitimate handler in each class.
# ---------------------------------------------------------------------------
_JOB_TIMEOUT_DEFAULT_SECONDS = int(os.getenv("GRAPH_OUTBOX_JOB_TIMEOUT_SECONDS", "300"))

# Override map. Keys are GraphOperationType.value strings. Override only for
# operations that legitimately exceed the default and have documented bounded
# upper limits (so the override doesn't just hide a runaway loop).
_PER_OP_TIMEOUT_OVERRIDES: dict[str, int] = {
    "generate_deep_brief": 600,         # 90s soft cap inside handler + buffer
    "persona_research": 900,            # multi-step ADK ReAct loop
    "enrich_from_web": 900,             # multi-step Firecrawl agent
    "index_meeting_transcript": 600,    # chunking + embedding large transcripts
    "process_meeting_transcript": 600,  # Recall STT fetch can be slow
    "process_desktop_sdk_recording": 600,
    "generate_meeting_summary": 600,    # analyze_meeting() Gemini call
    "enhance_notes": 600,                # Gemini merge of transcript + notes
    "generate_meeting_briefing": 600,
    "generate_meeting_followup": 600,
    "extract_memory_candidates": 600,
}


def _timeout_for_operation(operation: str) -> int:
    return _PER_OP_TIMEOUT_OVERRIDES.get(operation, _JOB_TIMEOUT_DEFAULT_SECONDS)


# ---------------------------------------------------------------------------
# Layer 3: classify exceptions as transient vs permanent. Permanent errors
# go straight to status='failed' without retry; transient errors take the
# normal retry-with-backoff path.
# ---------------------------------------------------------------------------
def _is_permanent_error(exc: BaseException) -> bool:
    """Return True if the error is permanent (no retry will help).

    Permanent signals:
      * ValueError / TypeError / KeyError / AttributeError on payload shape
      * Pydantic ValidationError
      * httpx.HTTPStatusError with a 4xx response code (except 408/429)
      * Explicit ``PermanentJobError`` raise from a handler
      * Substring matches in the error message ("invalid_payload",
        "missing required field", "unknown operation type", etc.)

    Conservative default: when in doubt, treat as transient and let the
    retry path run. Better to retry once unnecessarily than to fast-fail
    a transient blip.
    """
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        # Timeouts are NOT permanent on their own -- a slow Pinecone call
        # might succeed next time. Layer 1 catches genuine deadlocks via
        # the per-job timeout; Layer 3 routes those through the normal
        # retry path so the second attempt has a chance.
        return False

    if isinstance(exc, (ValueError, TypeError, KeyError, AttributeError)):
        return True

    # Pydantic validation -- imported lazily to avoid coupling.
    try:
        from pydantic import ValidationError  # type: ignore

        if isinstance(exc, ValidationError):
            return True
    except Exception:
        pass

    # httpx 4xx (except 408/429 which are retryable).
    try:
        import httpx  # type: ignore

        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code
            if 400 <= status_code < 500 and status_code not in (408, 429):
                return True
    except Exception:
        pass

    # Message-substring fast paths.
    text = str(exc or "").lower()
    for marker in (
        "invalid_payload",
        "missing required field",
        "missing required",
        "unknown operation",
        "not a valid uuid",
        "schema validation failed",
        "p_json_column",  # the RPC's allow-list rejection
    ):
        if marker in text:
            return True

    return False


# ---------------------------------------------------------------------------
# Layer 2: zombie sweep. Resets jobs that have been at status='processing'
# for too long -- the symptom of a crashed worker, an OOM kill, or a wedged
# DB connection inside a handler. Uses ``updated_at`` as the proxy for
# "when did this job last move" since every claim/complete/fail writes it.
#
# Returns the number of rows reset so the worker loop can log a heartbeat.
# Safe to call on every iteration: the SELECT is cheap and the UPDATE only
# touches stale rows.
# ---------------------------------------------------------------------------
_ZOMBIE_STALE_AFTER_SECONDS = int(os.getenv("GRAPH_OUTBOX_ZOMBIE_STALE_SECONDS", "1800"))  # 30 min


async def reset_zombie_jobs(stale_after_seconds: int | None = None) -> int:
    """Reset stale ``processing`` jobs so they don't hold the queue forever.

    A job is a zombie if ``status='processing' AND updated_at < now() - stale_after_seconds``.
    Behavior:
      * If attempt_count < max_attempts: reset to ``pending`` (will be re-claimed
        with a fresh attempt counter increment).
      * Else: mark ``failed`` with a clear error message so operators see it.

    Returns the number of rows reset.
    """
    threshold_seconds = (
        stale_after_seconds if stale_after_seconds is not None else _ZOMBIE_STALE_AFTER_SECONDS
    )
    now = datetime.now(timezone.utc)
    threshold_iso = (now - timedelta(seconds=threshold_seconds)).isoformat()
    now_iso = now.isoformat()

    def _select_zombies():
        return (
            supabase.table("graph_outbox")
            .select("id,attempt_count,max_attempts,operation,error_message")
            .eq("status", "processing")
            .lt("updated_at", threshold_iso)
            .limit(50)  # bounded so a single sweep can't dominate the worker
            .execute()
        )

    try:
        resp = await _run_db(_select_zombies)
    except Exception as exc:
        logger.warning("[GraphOutboxWorker] zombie sweep SELECT failed: %s", exc)
        return 0

    rows = getattr(resp, "data", None) or []
    if not rows:
        return 0

    reset_count = 0
    for row in rows:
        job_id = str(row.get("id"))
        attempt_count = int(row.get("attempt_count") or 0)
        max_attempts = int(row.get("max_attempts") or 5)
        operation = row.get("operation") or "unknown"
        prior_err = row.get("error_message") or ""

        if attempt_count >= max_attempts:
            payload: dict[str, Any] = {
                "status": "failed",
                "updated_at": now_iso,
                "failed_at": now_iso,
                "error_message": (
                    f"zombie_sweep: stuck in processing >{threshold_seconds}s; max_attempts exhausted. "
                    f"prior_error={prior_err[:500]}"
                )[:2000],
            }
        else:
            payload = {
                "status": "pending",
                "attempt_count": attempt_count + 1,
                "updated_at": now_iso,
                "next_attempt_after": now_iso,  # eligible immediately
                "error_message": (
                    f"zombie_sweep: reset from processing after >{threshold_seconds}s. "
                    f"prior_error={prior_err[:500]}"
                )[:2000],
            }

        def _update(_payload=payload, _id=job_id):
            return supabase.table("graph_outbox").update(_payload).eq("id", _id).execute()

        try:
            await _run_db(_update)
            reset_count += 1
            logger.warning(
                "[GraphOutboxWorker] zombie_sweep reset job=%s operation=%s -> %s (attempt %d/%d)",
                job_id,
                operation,
                payload["status"],
                attempt_count + (1 if payload["status"] == "pending" else 0),
                max_attempts,
            )
        except Exception as exc:
            logger.warning(
                "[GraphOutboxWorker] zombie_sweep UPDATE failed job=%s: %s", job_id, exc
            )

    return reset_count


async def _refresh_snapshot(
    tenant_id: str,
    twin_id: str,
    correlation_id: str | None,
    scope_id: str | None = None,
) -> bool:
    try:
        if scope_id:
            if "__" in scope_id:
                _, creator_id = scope_id.split("__", 1)
                return await refresh_twin_snapshot(
                    tenant_id=tenant_id,
                    twin_id=twin_id,
                    correlation_id=correlation_id,
                    creator_id=creator_id,
                )
            return await refresh_scope_snapshot(scope_id, correlation_id=correlation_id)
        return await refresh_twin_snapshot(
            tenant_id=tenant_id,
            twin_id=twin_id,
            correlation_id=correlation_id,
        )
    except Exception as exc:
        logger.warning("[GraphOutboxWorker] snapshot refresh failed: %s", exc)
        return False


async def _persist_claims(
    *,
    tenant_id: str,
    twin_id: str,
    scope_id: str | None,
    correlation_id: str | None,
    payload: dict[str, Any],
) -> int:
    source_type = str(payload.get("source_type") or "graph_memory")
    source_ref = str(payload.get("source_ref") or payload.get("run_id") or "unknown")
    text = str(payload.get("text") or payload.get("content") or payload.get("body") or "").strip()

    claim_inputs: list[str] = []
    raw_claims = payload.get("claims")
    if isinstance(raw_claims, list):
        for item in raw_claims:
            if isinstance(item, str):
                claim_inputs.append(_normalize_text(item))
            elif isinstance(item, dict):
                claim_inputs.append(_normalize_text(str(item.get("text") or item.get("claim_text") or "")))

    if not claim_inputs:
        claim_inputs = _split_claim_candidates(text)

    if not claim_inputs:
        return 0

    group_id = scope_id or f"{tenant_id}__{twin_id}"
    now_iso = _utcnow_iso()
    rows: list[dict[str, Any]] = []
    for claim_text in claim_inputs:
        if not claim_text:
            continue
        claim_id = _short_hash(f"{group_id}:{source_ref}:{claim_text}")
        row: dict[str, Any] = {
            "tenant_id": tenant_id,
            "twin_id": twin_id,
            "group_id": group_id,
            "claim_id": claim_id,
            "claim_text": claim_text,
            "claim_type": _infer_claim_type(claim_text),
            "confidence": 0.75,
            "content_hash": _short_hash(claim_text, length=24),
            "source_type": source_type,
            "source_ref": source_ref,
            "extracted_at": now_iso,
            "correlation_id": correlation_id,
        }
        if scope_id:
            row["scope_id"] = scope_id
        rows.append(row)

    if not rows:
        return 0

    def _upsert():
        return (
            supabase.table("graph_claims")
            .upsert(rows, on_conflict="tenant_id,twin_id,claim_id")
            .execute()
        )

    await _run_db(_upsert)
    return len(rows)


async def _process_create_episode(job: dict[str, Any]) -> bool:
    payload = job.get("payload") or {}
    episode_name = str(payload.get("name") or "Deep Research Episode")
    episode_body = str(payload.get("body") or payload.get("content") or "").strip()
    tenant_id = str(job.get("tenant_id") or "")
    twin_id = str(job.get("twin_id") or "")
    if not tenant_id or not twin_id:
        raise ValueError("create_episode job missing tenant_id or twin_id")
    if not episode_body:
        raise ValueError("create_episode job missing body")

    scope_id = str(payload.get("scope_id") or job.get("scope_id") or "").strip() or None
    creator_id = str(payload.get("creator_id") or job.get("creator_id") or "").strip() or None
    correlation_id = str(job.get("correlation_id") or payload.get("correlation_id") or "")

    logger.info(
        "[GraphOutboxWorker] processing create_episode job=%s name=%s",
        job.get("id"),
        episode_name[:120],
    )
    logger.info("[GraphOutboxWorker] processing job=%s operation=create_episode", job.get('id'))

    client = GraphMemoryCore(
        tenant_id=tenant_id,
        twin_id=twin_id,
        correlation_id=correlation_id or None,
        creator_id=creator_id or None,
        scope_id=scope_id,
    )
    await client.create_episode(
        name=episode_name,
        body=episode_body,
        source_type=str(payload.get("source_type") or "graph_outbox"),
        source_ref=str(payload.get("source_ref") or job.get("id") or "unknown"),
        timestamp=str(payload.get("timestamp") or ""),
        async_write=False,
    )
    await _refresh_snapshot(
        tenant_id=tenant_id,
        twin_id=twin_id,
        correlation_id=correlation_id or None,
        scope_id=scope_id,
    )
    return True


async def _process_create_claims(job: dict[str, Any]) -> bool:
    payload = job.get("payload") or {}
    tenant_id = str(job.get("tenant_id") or "")
    twin_id = str(job.get("twin_id") or "")
    if not tenant_id or not twin_id:
        raise ValueError("create_claims job missing tenant_id or twin_id")

    scope_id = str(payload.get("scope_id") or job.get("scope_id") or "").strip() or None
    correlation_id = str(job.get("correlation_id") or payload.get("correlation_id") or "")

    claim_count = await _persist_claims(
        tenant_id=tenant_id,
        twin_id=twin_id,
        scope_id=scope_id,
        correlation_id=correlation_id or None,
        payload=payload,
    )
    logger.info(
        "[GraphOutboxWorker] processing create_claims job=%s persisted_claims=%s scope=%s",
        job.get("id"),
        claim_count,
        scope_id or "legacy",
    )
    logger.info(
        "[GraphOutboxWorker] processing job=%s operation=create_claims claims=%s",
        job.get('id'),
        claim_count,
    )

    await _refresh_snapshot(
        tenant_id=tenant_id,
        twin_id=twin_id,
        correlation_id=correlation_id or None,
        scope_id=scope_id,
    )
    return True


async def _process_extract_claims(job: dict[str, Any]) -> bool:
    # Treat as alias for create_claims so legacy payloads still flow.
    logger.info("[GraphOutboxWorker] processing job=%s operation=extract_claims", job.get('id'))
    return await _process_create_claims(job)


async def _process_evaluate_contradictions(job: dict[str, Any]) -> bool:
    payload = job.get("payload") or {}
    tenant_id = str(job.get("tenant_id") or "")
    twin_id = str(job.get("twin_id") or "")
    if not tenant_id or not twin_id:
        raise ValueError("evaluate_contradictions job missing tenant_id or twin_id")

    correlation_id = str(job.get("correlation_id") or payload.get("correlation_id") or "")
    logger.info("[GraphOutboxWorker] processing job=%s operation=evaluate_contradictions", job.get('id'))
    return await process_contradiction_evaluation_job(
        tenant_id=tenant_id,
        twin_id=twin_id,
        payload=payload,
        correlation_id=correlation_id or None,
    )


async def _process_refresh_snapshot(job: dict[str, Any]) -> bool:
    payload = job.get("payload") or {}
    tenant_id = str(job.get("tenant_id") or "")
    twin_id = str(job.get("twin_id") or "")
    if not tenant_id or not twin_id:
        raise ValueError("refresh_snapshot job missing tenant_id or twin_id")

    scope_id = str(payload.get("scope_id") or job.get("scope_id") or "").strip() or None
    correlation_id = str(job.get("correlation_id") or payload.get("correlation_id") or "")
    logger.info("[GraphOutboxWorker] processing job=%s operation=refresh_snapshot", job.get('id'))
    return await _refresh_snapshot(
        tenant_id=tenant_id,
        twin_id=twin_id,
        correlation_id=correlation_id or None,
        scope_id=scope_id,
    )


async def _process_persona_research(job: dict[str, Any]) -> bool:
    payload = job.get("payload") or {}
    run_id = str(payload.get("run_id") or "").strip()
    tenant_id = str(payload.get("tenant_id") or job.get("tenant_id") or "").strip()
    user_id = str(payload.get("user_id") or "").strip()

    if not run_id or not tenant_id or not user_id:
        raise ValueError("persona_research job missing run_id, tenant_id, or user_id")

    logger.info("[GraphOutboxWorker] processing job=%s operation=persona_research run_id=%s", job.get('id'), run_id)
    from modules.name_deep_research_service import get_name_deep_research_service
    service = get_name_deep_research_service()
    await service.execute_run(run_id=run_id, tenant_id=tenant_id, user_id=user_id)
    return True


async def _process_stripe_meter_event(job: dict[str, Any]) -> bool:
    """Report a Stripe meter event. Idempotent via event identifier."""
    import os

    import stripe
    payload = job.get("payload") or {}
    event_name = payload.get("event_name", "")
    user_id = payload.get("user_id", "")
    value = int(payload.get("value", 0))
    identifier = payload.get("identifier", "")

    if not all([event_name, user_id, value, identifier]):
        logger.error("[StripeMeter] invalid payload job_id=%s payload=%s", job.get("id"), payload)
        return True  # don't retry — bad payload

    # Resolve Stripe customer_id
    def _get_customer():
        return (
            supabase.table("users")
            .select("stripe_customer_id")
            .eq("id", user_id)
            .single()
            .execute()
        )

    try:
        row = await _run_db(_get_customer)
        customer_id = (row.data or {}).get("stripe_customer_id")
    except Exception as exc:
        logger.exception("[StripeMeter] customer lookup failed user=%s: %s", user_id, exc)
        return False  # retry

    if not customer_id:
        logger.warning("[StripeMeter] no stripe_customer_id for user=%s — skipping", user_id)
        return True  # user never subscribed, don't retry

    # Report meter event
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not stripe.api_key:
        logger.error("[StripeMeter] STRIPE_SECRET_KEY not set")
        return False  # retry

    def _report():
        return stripe.billing.MeterEvent.create(
            event_name=event_name,
            payload={
                "stripe_customer_id": customer_id,
                "value": str(value),
            },
            identifier=identifier,
        )

    try:
        await _run_db(_report)
        logger.info("[StripeMeter] reported event=%s user=%s value=%d", event_name, user_id, value)
        return True
    except Exception as exc:
        logger.exception("[StripeMeter] Stripe API error — will retry: %s", exc)
        return False  # retry


async def _process_link_meeting_contacts(job: dict[str, Any]) -> bool:
    """Phase F.2/F.3 — Link meeting participants to contacts rows + extract recap people.

    Payload: {meeting_id, tenant_id, twin_id}
    twin_id may be missing for desktop_sdk recordings (meetings.twin_id=null);
    we resolve the tenant's first active twin as a fallback.
    Returns True on success, False on retriable failure.
    """
    payload = job.get("payload") or {}
    meeting_id = payload.get("meeting_id")
    tenant_id = payload.get("tenant_id") or str(job.get("tenant_id") or "")
    twin_id = payload.get("twin_id") or str(job.get("twin_id") or "")
    if not (meeting_id and tenant_id):
        logger.warning("[link_meeting_contacts] missing payload fields job=%s", job.get("id"))
        return False

    # Resolve a twin if payload didn't have one (desktop_sdk recordings have
    # meetings.twin_id=null, so twin_id may be absent or "None").
    if not twin_id or twin_id == "None":
        try:
            twin_resp = (
                supabase.table("twins")
                .select("id")
                .eq("tenant_id", tenant_id)
                .eq("status", "active")
                .order("created_at", desc=False)
                .limit(1)
                .execute()
            )
            t_row = (getattr(twin_resp, "data", None) or [None])[0]
            twin_id = t_row["id"] if t_row else ""
        except Exception:
            logger.exception(
                "[link_meeting_contacts] twin lookup failed tenant=%s", tenant_id
            )

    if not twin_id:
        logger.info(
            "[link_meeting_contacts] no twin available for tenant=%s; skipping", tenant_id
        )
        return True  # mark done; nothing to do

    try:
        from services.contact_resolver import link_meeting_contacts, upsert_name_only_contacts

        # Existing email-based link path
        link_meeting_contacts(meeting_id, tenant_id, twin_id)

        # NEW (Phase F.3): extract recap people + upsert name-only contacts
        try:
            meeting_resp = await _run_db(
                lambda: supabase.table("meetings")
                .select("title, meeting_start, recap_extras_json, summary_json")
                .eq("id", meeting_id)
                .maybe_single()
                .execute()
            )
            meeting_row = getattr(meeting_resp, "data", None) or {}
        except Exception:
            logger.exception(
                "[link_meeting_contacts] meeting fetch for recap extraction failed"
            )
            meeting_row = {}

        if meeting_row:
            owner_name = ""
            try:
                # public.users actually has columns (full_name, email) — earlier
                # attempts to select display_name/name returned NULL silently
                # because supabase-py doesn't error on missing select fields.
                u_resp = await _run_db(
                    lambda: supabase.table("users")
                    .select("full_name, email")
                    .eq("tenant_id", tenant_id)
                    .limit(1)
                    .execute()
                )
                u_row = (getattr(u_resp, "data", None) or [None])[0] or {}
                owner_name = (u_row.get("full_name") or "").strip()
                if not owner_name and u_row.get("email"):
                    owner_name = u_row["email"].split("@")[0]
            except Exception:
                logger.info(
                    "[link_meeting_contacts] owner-name lookup failed; continuing"
                )

            from services.meeting_people_extractor import extract_people_from_recap

            people = await extract_people_from_recap(
                title=meeting_row.get("title"),
                owner_name=owner_name or "the owner",
                recap_extras=meeting_row.get("recap_extras_json"),
                summary_json=meeting_row.get("summary_json"),
                tenant_id=tenant_id,
            )
            if people:
                counts = upsert_name_only_contacts(
                    tenant_id=tenant_id,
                    twin_id=twin_id,
                    people=people,
                    meeting_id=meeting_id,
                    meeting_started_iso=meeting_row.get("meeting_start"),
                )
                logger.info(
                    "[link_meeting_contacts] name-only contacts meeting=%s "
                    "created=%d updated=%d skipped=%d",
                    meeting_id,
                    counts["created"],
                    counts["updated"],
                    counts["skipped"],
                )
        return True
    except Exception:
        logger.exception("[link_meeting_contacts] worker failed job=%s", job.get("id"))
        return False


async def _process_recall_calendar_sync(job: dict[str, Any]) -> bool:
    """Pull updated calendar events from Recall and upsert into ``meetings``.

    Triggered by the ``calendar.sync_events`` webhook → enqueued by
    ``routers/recall_calendar_webhook.py``. Recall fires this whenever
    events on the calendar are created/updated/deleted; the actual event
    payload must be pulled with
    ``GET /api/v2/calendars/{id}/calendar-events/?updated_at__gte=...``.
    """
    job_id = str(job.get("id") or "")
    payload = job.get("payload") or {}
    recall_calendar_id = str(payload.get("recall_calendar_id") or "")
    twin_id = str(payload.get("twin_id") or "")
    tenant_id_hint = str(payload.get("tenant_id") or "")
    last_updated_ts = payload.get("last_updated_ts")

    if not recall_calendar_id or not twin_id:
        logger.error(
            "[RecallCalSync] missing required fields job=%s payload_keys=%s",
            job_id, list(payload.keys()),
        )
        # Bad payload — don't retry, will never succeed.
        return True

    try:
        from services import recall_calendar_v2
        from services.recall_calendar_v2 import CalendarSyncTruncatedError
        events = await recall_calendar_v2.list_calendar_events(
            recall_calendar_id,
            updated_at__gte=last_updated_ts,
        )
    except CalendarSyncTruncatedError as exc:
        # Initial full sync hit the page cap with more pages still pending --
        # we missed real events. Persist the failure on
        # tool_connectors.last_error so the UI can surface a "calendar
        # partially synced -- please contact support" message instead of
        # silently dropping multi-year history. The job is marked completed
        # (return True) so it doesn't retry forever -- retrying would just
        # hit the same cap; operator action via last_error is required to
        # recover.
        logger.error(
            "[RecallCalSync] initial sync truncated twin=%s recall_cal=%s pages=%d events=%d",
            twin_id, recall_calendar_id, exc.pages, exc.events_fetched,
        )
        truncated_message = (
            f"calendar_sync_truncated: fetched {exc.events_fetched} events "
            f"across {exc.pages} pages, more remain. Please contact support."
        )

        def _stamp_last_error() -> Any:
            return (
                supabase.table("tool_connectors")
                .update({
                    "last_error": truncated_message,
                    "updated_at": _utcnow_iso(),
                })
                .eq("twin_id", twin_id)
                .eq("recall_calendar_id", recall_calendar_id)
                .execute()
            )

        try:
            await _run_db(_stamp_last_error)
        except Exception:
            logger.exception(
                "[RecallCalSync] failed to stamp last_error twin=%s recall_cal=%s",
                twin_id, recall_calendar_id,
            )
        return True  # terminal -- don't retry, operator-recoverable via last_error
    except Exception as exc:
        logger.exception(
            "[RecallCalSync] list_calendar_events failed twin=%s recall_cal=%s: %s",
            twin_id, recall_calendar_id, exc,
        )
        return False  # transient — retry

    # Resolve tenant_id from the twins row when the webhook payload didn't
    # carry one (older tool_connectors rows may not have tenant_id set).
    tenant_id = tenant_id_hint
    if not tenant_id:
        def _lookup_tenant():
            return (
                supabase.table("twins")
                .select("tenant_id")
                .eq("id", twin_id)
                .single()
                .execute()
            )
        try:
            twin_resp = await _run_db(_lookup_tenant)
        except Exception as exc:
            logger.exception(
                "[RecallCalSync] twin tenant lookup failed twin=%s: %s",
                twin_id, exc,
            )
            return False  # transient

        tenant_id = str((twin_resp.data or {}).get("tenant_id") or "")
        if not tenant_id:
            logger.warning(
                "[RecallCalSync] twin missing tenant_id twin=%s — skipping",
                twin_id,
            )
            return True

    now_iso = _utcnow_iso()
    upserts = 0
    cancellations = 0

    # Terminal statuses we must never downgrade back to "scheduled" on a sync.
    # Once a meeting has been completed/processed/failed/canceled, that state
    # is the source of truth for downstream workers; a calendar refresh should
    # only update metadata (title, time, attendees), not lifecycle state.
    _TERMINAL_STATUSES = {"completed", "processing", "failed", "canceled"}

    for event_data in events:
        # Recall event shape: {id, platform, calendar_id, start_time, end_time,
        #   meeting_url, ical_uid, status, title|summary, attendees, organizer, ...}
        provider_event_id = (
            event_data.get("id")
            or event_data.get("platform_id")
            or event_data.get("ical_uid")
        )
        if not provider_event_id:
            continue
        provider_event_id = str(provider_event_id)

        # ical_uid (RFC 5545 iCalendar UID) is the stable cross-platform event
        # identity -- it survives Recall calendar churn (disconnect+reconnect
        # creates a new recall_calendar_id but the underlying Google/Outlook
        # event keeps the same ical_uid). Use it as the PRIMARY uniqueness
        # key when present; fall back to legacy provider_event_id-based scope
        # only for rows pre-ical_uid backfill.
        #
        # Empty-string ical_uid ("" from a malformed provider response) takes
        # the legacy path -- we don't want to insert an empty-string into the
        # ical_uid column and have it match the partial index (it wouldn't
        # match anyway because the index has WHERE ical_uid IS NOT NULL, but
        # an empty string is its own kind of garbage). Length-cap as a
        # defensive guard against pathological provider data; RFC 5545 has
        # no official cap but 1024 chars is generous.
        ical_uid_raw = event_data.get("ical_uid")
        ical_uid = (
            str(ical_uid_raw)[:1024]
            if ical_uid_raw and isinstance(ical_uid_raw, (str, bytes))
            else None
        )

        _event_instance_id_for_cancel = event_data.get("instance_id") or ""
        _calendar_id_for_cancel = (
            event_data.get("calendar_id") or recall_calendar_id or ""
        )
        _provider_for_cancel = event_data.get("platform") or "google_calendar"
        if str(event_data.get("status") or "").lower() == "deleted":
            if ical_uid:
                def _mark_canceled(
                    uid: str = ical_uid,
                    iid: str = _event_instance_id_for_cancel,
                ):
                    return (
                        supabase.table("meetings")
                        .update({"status": "canceled", "last_synced_at": now_iso})
                        .eq("twin_id", twin_id)
                        .eq("ical_uid", uid)
                        .eq("provider_event_instance_id", iid)
                        .execute()
                    )
            else:
                # Legacy fallback (pre-backfill rows have ical_uid=NULL).
                # Scope by the full 5-tuple to avoid cross-calendar cascades.
                def _mark_canceled(
                    pid: str = provider_event_id,
                    iid: str = _event_instance_id_for_cancel,
                    cid: str = _calendar_id_for_cancel,
                    prov: str = _provider_for_cancel,
                ):
                    return (
                        supabase.table("meetings")
                        .update({"status": "canceled", "last_synced_at": now_iso})
                        .eq("twin_id", twin_id)
                        .eq("provider", prov)
                        .eq("provider_calendar_id", cid)
                        .eq("provider_event_id", pid)
                        .eq("provider_event_instance_id", iid)
                        .execute()
                    )
            try:
                await _run_db(_mark_canceled)
                cancellations += 1
            except Exception as exc:
                logger.warning(
                    "[RecallCalSync] cancel failed event=%s twin=%s: %s",
                    provider_event_id, twin_id, exc,
                )
            continue

        # Guard: Recall sometimes emits events without time bounds (recurring
        # event templates, partial events). Skip those rather than insert
        # NULL meeting_start/end which would break downstream bot dispatch.
        if not event_data.get("start_time") or not event_data.get("end_time"):
            logger.warning(
                "[RecallCalSync] event missing time bounds — skipping event=%s twin=%s",
                provider_event_id, twin_id,
            )
            continue

        # Match the 5-column unique index defined in
        # 20260505_phase30_meeting_os_foundation.sql:125-133. The COALESCE
        # expressions in that index use '' for NULL, so we have to pass ''
        # (not None) for the optional id fields or PostgREST will fall back
        # to a plain INSERT and we'll get duplicate rows on every webhook.
        provider_event_instance_id = event_data.get("instance_id") or ""
        provider_calendar_id = (
            event_data.get("calendar_id") or recall_calendar_id or ""
        )

        row = {
            "twin_id": twin_id,
            "tenant_id": tenant_id,
            "provider": event_data.get("platform") or "google_calendar",
            "ical_uid": ical_uid,  # primary cross-platform stable identity
            "provider_event_id": provider_event_id,
            "provider_event_instance_id": provider_event_instance_id,
            "provider_calendar_id": provider_calendar_id,
            "title": (
                event_data.get("title")
                or event_data.get("summary")
                or (event_data.get("raw") or {}).get("summary")
                or (event_data.get("raw") or {}).get("title")
                or "Untitled meeting"
            ),
            "meeting_start": event_data.get("start_time"),
            "meeting_end": event_data.get("end_time"),
            "meet_link": event_data.get("meeting_url"),
            "attendees_json": event_data.get("attendees") or [],
            "organizer_email": (event_data.get("organizer") or {}).get("email"),
            "last_synced_at": now_iso,
            "updated_at": now_iso,
        }

        # Preserve terminal lifecycle status. A calendar.sync_events refresh
        # must never revert a completed/processing/failed/canceled meeting back
        # to "scheduled" (which would re-dispatch the bot). We SELECT the
        # current row by ical_uid (stable across Recall calendar churn) when
        # available, falling back to the legacy provider_event_id scope for
        # rows that pre-date the ical_uid backfill.
        if ical_uid:
            def _lookup_existing_status(
                uid: str = ical_uid,
                iid: str = provider_event_instance_id,
            ):
                return (
                    supabase.table("meetings")
                    .select("status")
                    .eq("twin_id", twin_id)
                    .eq("ical_uid", uid)
                    .eq("provider_event_instance_id", iid)
                    .limit(1)
                    .execute()
                )
        else:
            def _lookup_existing_status(
                pid: str = provider_event_id,
                iid: str = provider_event_instance_id,
            ):
                return (
                    supabase.table("meetings")
                    .select("status")
                    .eq("twin_id", twin_id)
                    .eq("provider_event_id", pid)
                    .eq("provider_event_instance_id", iid)
                    .limit(1)
                    .execute()
                )

        # H6 (TOCTOU): treat SELECT failure DIFFERENTLY from SELECT-empty.
        # A transient lookup failure must NOT be interpreted as "no row exists"
        # because then we'd write status='scheduled' over a row that's already
        # in a terminal state (completed/processing/failed/canceled), which
        # would re-dispatch the bot. When the lookup fails, omit lifecycle
        # fields from the upsert entirely -- the existing row's status,
        # twin_attends, and mode stay untouched; only metadata refreshes.
        lookup_succeeded = True
        try:
            existing = await _run_db(_lookup_existing_status)
        except Exception as exc:
            logger.warning(
                "[RecallCalSync] status lookup failed event=%s twin=%s: %s "
                "(will preserve existing lifecycle state on upsert)",
                provider_event_id, twin_id, exc,
            )
            existing = None
            lookup_succeeded = False

        existing_rows = (
            getattr(existing, "data", None) or [] if existing is not None else []
        )
        if lookup_succeeded and not existing_rows:
            # Verified new row — set the initial scheduled status. For existing
            # rows (or any case where we couldn't confirm row was new) we
            # deliberately omit status from the upsert so Postgres preserves
            # whatever state the row is currently in.
            row["status"] = "scheduled"
            # Calendar-synced meetings default to OPT-OUT for bot attendance.
            # Schema default for twin_attends is TRUE (set by the booking flow's
            # needs), but for events the user merely has on their calendar we
            # don't assume consent until they explicitly toggle "Persona
            # attendance". mode='off' until toggled.
            #
            # ONLY set on a VERIFIED INSERT -- if we set on UPDATE too, the
            # next calendar.sync_events webhook would clobber the user's
            # toggled twin_attends=true back to false.
            row["twin_attends"] = False
            row["mode"] = "off"

        # Manual INSERT-or-UPDATE (PostgREST .upsert(on_conflict=...) doesn't
        # match the partial expression indexes on this table -- swallowed 400
        # silently dropped writes prior to this fix; see PR #178). The UPDATE
        # scope mirrors whichever unique key applies:
        #   * ical_uid present -> (twin_id, ical_uid, provider_event_instance_id)
        #     -- stable across Recall calendar churn. This is the new
        #     idx_meetings_ical_uid_unique partial index.
        #   * ical_uid NULL    -> (twin_id, provider, provider_calendar_id,
        #     provider_event_id, provider_event_instance_id) -- legacy
        #     5-tuple, only hit on rows pre-ical_uid backfill.
        provider_for_match = row["provider"]
        if lookup_succeeded and existing_rows:
            if ical_uid:
                def _do_update(
                    payload_row: dict = row,
                    uid: str = ical_uid,
                    iid: str = provider_event_instance_id,
                ):
                    return (
                        supabase.table("meetings")
                        .update(payload_row)
                        .eq("twin_id", twin_id)
                        .eq("ical_uid", uid)
                        .eq("provider_event_instance_id", iid)
                        .execute()
                    )
            else:
                def _do_update(
                    payload_row: dict = row,
                    pid: str = provider_event_id,
                    iid: str = provider_event_instance_id,
                    pcal: str = provider_calendar_id,
                    prov: str = provider_for_match,
                ):
                    return (
                        supabase.table("meetings")
                        .update(payload_row)
                        .eq("twin_id", twin_id)
                        .eq("provider", prov)
                        .eq("provider_calendar_id", pcal)
                        .eq("provider_event_id", pid)
                        .eq("provider_event_instance_id", iid)
                        .execute()
                    )
            try:
                await _run_db(_do_update)
                upserts += 1
            except Exception as exc:
                logger.warning(
                    "[RecallCalSync] update failed event=%s twin=%s: %s",
                    provider_event_id, twin_id, exc,
                )
        else:
            def _do_insert(payload_row: dict = row):
                return (
                    supabase.table("meetings")
                    .insert(payload_row)
                    .execute()
                )
            try:
                await _run_db(_do_insert)
                upserts += 1
            except Exception as exc:
                logger.warning(
                    "[RecallCalSync] insert failed event=%s twin=%s: %s",
                    provider_event_id, twin_id, exc,
                )

    # Elevated to logger.warning so the completion summary is visible in
    # Cloud Run's prod log stream (root logger at WARNING; INFO is suppressed).
    # Without this, operators have zero visibility into sync runs and can't
    # tell whether a webhook->worker->meetings pipeline run actually processed
    # any events. See feedback_cloud_run_log_levels.md.
    logger.warning(
        "[RecallCalSync] completed job=%s twin=%s recall_cal=%s upserts=%d cancellations=%d total_events=%d",
        job_id, twin_id, recall_calendar_id, upserts, cancellations, len(events),
    )
    return True


async def _process_resolve_meeting_speakers(job: dict[str, Any]) -> bool:
    """Fetch Recall bot's participant list, resolve to nodes, write to meeting_participants.

    Triggered by bot.done webhook (Phase 30-K). Idempotent: re-running just
    upserts the same rows (existing row check per ``(meeting_id, diarization_label)``).

    Source: GET /api/v1/bot/{bot_id} returns the bot object including a participants
    array. For each participant we try to resolve their email to a nodes row (the
    relationship-graph entity); unmatched attendees get a stub nodes row created
    with ``source='meeting_attendees'``.

    Returns True on full or partial success (do NOT retry on data shape issues);
    returns False only on transient infra failures (Recall API, missing payload).
    """
    job_id = str(job.get("id") or "")
    payload = job.get("payload") or {}
    meeting_id = str(payload.get("meeting_id") or "").strip()
    bot_id = str(payload.get("bot_id") or "").strip()
    twin_id = str(payload.get("twin_id") or "").strip()
    tenant_id = str(payload.get("tenant_id") or "").strip()

    if not (meeting_id and bot_id and twin_id and tenant_id):
        logger.error(
            "[ResolveSpeakers] missing required fields job=%s meeting=%s bot=%s",
            job_id, meeting_id, bot_id,
        )
        return False

    try:
        from services.recall_service import get_bot
        bot = await get_bot(bot_id)
    except Exception as exc:
        logger.exception("[ResolveSpeakers] get_bot failed bot=%s: %s", bot_id, exc)
        return False

    # Recall bot response shape: top-level "participants" array (V1). Be defensive.
    participants = bot.get("participants") or []
    if not isinstance(participants, list):
        logger.warning(
            "[ResolveSpeakers] bot.participants not a list bot=%s type=%s",
            bot_id, type(participants).__name__,
        )
        return True  # acknowledge — nothing to do

    if not participants:
        logger.info(
            "[ResolveSpeakers] empty participant list bot=%s meeting=%s",
            bot_id, meeting_id,
        )
        return True

    resolved = 0
    created_stubs = 0

    for idx, p in enumerate(participants):
        if not isinstance(p, dict):
            continue

        # Recall's participant fields: id (str), name (str), email (str, optional,
        # since May 2026 Participant Emails feature). Diarization label is
        # "speaker_{idx}" by Recall convention when not explicit.
        name = (p.get("name") or "").strip() or None
        email = (p.get("email") or "").strip().lower() or None
        diarization_label = str(
            p.get("speaker_id") or p.get("speaker") or f"speaker_{idx}"
        )

        # Skip if no identifying info at all
        if not name and not email:
            continue

        # Resolve email → nodes (or create stub)
        person_node_id: str | None = None
        if email:
            try:
                node_resp = await _run_db(lambda email=email: (
                    supabase.table("nodes")
                    .select("id")
                    .eq("twin_id", twin_id)
                    .eq("type", "person")
                    .ilike("properties->>email", email)
                    .limit(1)
                    .execute()
                ))
                if node_resp.data:
                    person_node_id = node_resp.data[0]["id"]
                else:
                    # Create stub node so the diarization label has somewhere
                    # to point. Downstream enrichment can fill in the gaps.
                    stub_payload = {
                        "twin_id": twin_id,
                        "name": name or email,
                        "type": "person",
                        "properties": {
                            "email": email,
                            "source": "meeting_attendees",
                        },
                        "status": "active",
                    }
                    stub = await _run_db(lambda payload=stub_payload: (
                        supabase.table("nodes")
                        .insert(payload)
                        .execute()
                    ))
                    if stub.data:
                        person_node_id = stub.data[0]["id"]
                        created_stubs += 1
            except Exception as exc:
                logger.warning(
                    "[ResolveSpeakers] node resolve failed email=%s meeting=%s: %s",
                    email, meeting_id, exc,
                )

        # Upsert into meeting_participants (idempotent on meeting_id+label)
        try:
            existing = await _run_db(lambda label=diarization_label: (
                supabase.table("meeting_participants")
                .select("id")
                .eq("meeting_id", meeting_id)
                .eq("diarization_label", label)
                .limit(1)
                .execute()
            ))
            row_payload = {
                "meeting_id": meeting_id,
                "participant_name": name,
                "participant_email": email,
                "diarization_label": diarization_label,
                "person_node_id": person_node_id,
            }
            if existing.data:
                existing_id = existing.data[0]["id"]
                await _run_db(lambda eid=existing_id, body=row_payload: (
                    supabase.table("meeting_participants")
                    .update(body)
                    .eq("id", eid)
                    .execute()
                ))
            else:
                await _run_db(lambda body=row_payload: (
                    supabase.table("meeting_participants")
                    .insert(body)
                    .execute()
                ))
            if person_node_id:
                resolved += 1
        except Exception as exc:
            logger.warning(
                "[ResolveSpeakers] upsert failed meeting=%s label=%s: %s",
                meeting_id, diarization_label, exc,
            )

    logger.info(
        "[ResolveSpeakers] meeting=%s participants=%d resolved=%d stubs_created=%d",
        meeting_id, len(participants), resolved, created_stubs,
    )
    return True


async def _process_run_notification_flow(job: dict[str, Any]) -> bool:
    """Resolve an active notification flow and fan out lifecycle email jobs."""
    job_id = str(job.get("id") or "")
    logger.info(
        "[notifications] run_notification_flow started job_id=%s operation=%s",
        job_id,
        job.get("operation"),
    )
    try:
        from modules.audience import resolve_audience
        from modules.notification_flows import (
            AudienceSpec,
            close_run,
            create_run,
            get_flow,
        )

        payload = job.get("payload") or {}
        flow_id = str(payload.get("flow_id") or "").strip()
        if not flow_id:
            logger.error("[notifications] missing flow_id job_id=%s", job_id)
            return False

        flow = get_flow(supabase, flow_id)
        if flow.status != "active":
            logger.warning(
                "[notifications] flow not active status=%s flow_id=%s job_id=%s",
                flow.status,
                flow_id,
                job_id,
            )
            return True

        audience_override = payload.get("audience_override")
        if isinstance(audience_override, list) and audience_override:
            audience_spec = AudienceSpec(segment="user_list", user_ids=[str(v) for v in audience_override])
        else:
            audience_spec = flow.audience_spec

        resolved = await resolve_audience(supabase, audience_spec)
        recipients = list(resolved.recipients)
        actual_count = len(recipients)

        max_recipients = flow.guardrails.max_recipients
        if not flow.guardrails.exempt_from_caps and actual_count > max_recipients:
            logger.warning(
                "[notifications] audience exceeds cap capped=%d actual=%d flow_id=%s",
                max_recipients,
                actual_count,
                flow_id,
            )
            recipients = recipients[:max_recipients]

        dry_run = bool(payload.get("dry_run", False))
        if dry_run:
            flow_run_id = create_run(supabase, flow_id, "dry_run", actual_count, tenant_id=flow.tenant_id)
            close_run(
                supabase,
                flow_run_id,
                status="completed",
                enqueued=0,
                skipped=actual_count,
                summary={"segment": resolved.segment_label},
            )
            logger.info(
                "[notifications] dry_run complete count=%d flow_id=%s job_id=%s",
                actual_count,
                flow_id,
                job_id,
            )
            return True

        flow_run_id = str(payload.get("flow_run_id") or uuid.uuid4())
        create_run(
            supabase,
            flow_id,
            "manual",
            actual_count,
            run_id=flow_run_id,
            tenant_id=flow.tenant_id,
            flow_run_key=f"{flow_id}:manual:{flow_run_id}",
        )

        outbox = get_graph_outbox()
        enqueued = 0
        skipped = 0
        throttle = max(0, int(flow.guardrails.throttle_per_min or 0))
        scope_type = "announcement" if flow.kind == "announcement" else "user"

        for index, recipient in enumerate(sorted(recipients, key=lambda item: item.user_id)):
            # Stagger sends via next_attempt_after instead of sleeping inside the worker.
            # Each batch of `throttle` recipients gets a 60-second window.
            if throttle > 0:
                from datetime import datetime, timedelta, timezone as _tz
                batch_window = index // throttle
                next_after = (
                    datetime.now(_tz.utc) + timedelta(minutes=batch_window)
                    if batch_window > 0
                    else None
                )
            else:
                next_after = None
            try:
                outbox.submit(
                    tenant_id=recipient.tenant_id,
                    twin_id=SYSTEM_TWIN_ID,
                    operation=GraphOperationType.SEND_LIFECYCLE_EMAIL,
                    idempotency_key=f"notif-{flow_run_id}-{recipient.user_id}",
                    scope_id=flow_run_id,
                    next_attempt_after=next_after,
                    payload={
                        "user_id": recipient.user_id,
                        "tenant_id": recipient.tenant_id,
                        "twin_id": SYSTEM_TWIN_ID,
                        "email_type": flow.email_type,
                        "category": flow.category,
                        "scope_type": scope_type,
                        "scope_id": flow_run_id,
                        "period_key": recipient.user_id,
                        "recipient_email": recipient.email,
                        "recipient_user_id": recipient.user_id,
                        "payload": dict(flow.context_overrides),
                    },
                )
                enqueued += 1
            except Exception as exc:
                logger.exception(
                    "[notifications] enqueue failed user_id=%s flow_id=%s exc=%r",
                    recipient.user_id,
                    flow_id,
                    exc,
                )
                skipped += 1

        close_run(
            supabase,
            flow_run_id,
            status="completed",
            enqueued=enqueued,
            skipped=skipped,
            summary={"segment": resolved.segment_label},
        )
        if enqueued > 0:
            from services.notification_outcomes import schedule_notification_outcome_measurement
            _outcome_tenant = flow.tenant_id or str(payload.get("tenant_id") or job.get("tenant_id") or "")
            if not _outcome_tenant:
                logger.warning("[notifications] no tenant_id for outcome measurement flow_id=%s — skipping", flow_id)
            else:
                schedule_notification_outcome_measurement(
                    outbox=outbox,
                    tenant_id=_outcome_tenant,
                    flow_run_id=flow_run_id,
                    flow_id=flow_id,
                )
        logger.info(
            "[notifications] run complete enqueued=%d skipped=%d flow_id=%s job_id=%s",
            enqueued,
            skipped,
            flow_id,
            job_id,
        )
        return True
    except Exception:
        logger.exception("[notifications] run_notification_flow failed job_id=%s", job_id)
        return False


async def _process_notification_event(job: dict[str, Any]) -> bool:
    """Process a notification event into generated lifecycle email jobs."""
    payload = job.get("payload") or {}
    event_id = str(payload.get("event_id") or "").strip()
    if not event_id:
        logger.error("[notifications] missing event_id job_id=%s", job.get("id"))
        return False
    try:
        from services.notification_agent import process_notification_event

        return await process_notification_event(supabase, event_id)
    except Exception as exc:
        logger.exception("[notifications] process_notification_event failed event_id=%s", event_id)
        try:
            from modules.notification_events import mark_notification_event_failed
            mark_notification_event_failed(supabase, event_id, str(exc)[:2000])
        except Exception:
            pass
        return False


async def _process_measure_notification_outcome(job: dict[str, Any]) -> bool:
    payload = job.get("payload") or {}
    flow_run_id = str(payload.get("flow_run_id") or "").strip()
    if not flow_run_id:
        logger.error("[notifications] missing flow_run_id job_id=%s", job.get("id"))
        return False
    try:
        from services.notification_outcomes import measure_notification_outcome

        await asyncio.to_thread(measure_notification_outcome, supabase, flow_run_id)
        return True
    except Exception:
        logger.exception("[notifications] measure_notification_outcome failed flow_run_id=%s", flow_run_id)
        return False


async def _process_lead_captured(job: dict[str, Any]) -> bool:
    """Emit a notification event when a visitor is captured in the lead funnel.

    Inserts a notification_events row (event_type='lead.captured') and enqueues
    a PROCESS_NOTIFICATION_EVENT job so the owner's configured notification flows
    can fan out (e.g. email alert, Slack ping). Best-effort: a failure here must
    not retroactively block the capture that already succeeded.
    """
    payload = job.get("payload") or {}
    lead_id = str(payload.get("lead_id") or "").strip()
    twin_id = str(job.get("twin_id") or "").strip()
    if not lead_id or not twin_id:
        logger.error("[leads] missing lead_id or twin_id job_id=%s", job.get("id"))
        return False
    try:
        from modules.graph_outbox import GraphOperationType, get_graph_outbox
        from modules.notification_events import NotificationEventCreate, emit_notification_event

        lead_resp = (
            supabase.table("widget_leads")
            .select("visitor_name, visitor_email, inferred_intent, inferred_visitor_type")
            .eq("id", lead_id)
            .single()
            .execute()
        )
        lead_data = lead_resp.data or {}

        # Resolve the twin owner's auth UID — tenant_id on twins IS the Supabase Auth UID.
        # The notification audience resolver looks up users by this ID, so we must pass
        # the owner's auth UID as tenant_id, not the twin's UUID.
        twin_resp = (
            supabase.table("twins")
            .select("tenant_id")
            .eq("id", twin_id)
            .single()
            .execute()
        )
        owner_id = (twin_resp.data or {}).get("tenant_id") or twin_id

        event = await asyncio.to_thread(
            emit_notification_event,
            supabase,
            NotificationEventCreate(
                tenant_id=owner_id,
                event_type="lead.captured",
                subject_id=lead_id,
                context_json={
                    "lead_id": lead_id,
                    "twin_id": twin_id,
                    "visitor_name": lead_data.get("visitor_name"),
                    "visitor_email": lead_data.get("visitor_email"),
                    "inferred_intent": lead_data.get("inferred_intent"),
                    "inferred_visitor_type": lead_data.get("inferred_visitor_type"),
                },
            ),
        )
        get_graph_outbox().submit(
            tenant_id=owner_id,
            twin_id=twin_id,
            operation=GraphOperationType.PROCESS_NOTIFICATION_EVENT,
            idempotency_key=f"process_lead_event_{event.id}",
            payload={"event_id": event.id, "event_type": event.event_type},
        )
        logger.info("[leads] notification event emitted lead_id=%s event_id=%s", lead_id, event.id)
        return True
    except Exception:
        logger.exception("[leads] _process_lead_captured failed lead_id=%s", lead_id)
        return False


async def _dispatch(job: dict[str, Any]) -> bool:
    operation = str(job.get("operation") or "").lower()

    if operation == GraphOperationType.CREATE_EPISODE.value:
        return await _process_create_episode(job)
    if operation == GraphOperationType.CREATE_CLAIMS.value:
        return await _process_create_claims(job)
    if operation == GraphOperationType.EXTRACT_CLAIMS.value:
        return await _process_extract_claims(job)
    if operation == GraphOperationType.EVALUATE_CONTRADICTIONS.value:
        return await _process_evaluate_contradictions(job)
    if operation == GraphOperationType.REFRESH_SNAPSHOT.value:
        return await _process_refresh_snapshot(job)
    if operation == GraphOperationType.PERSONA_RESEARCH.value:
        return await _process_persona_research(job)
    if operation == GraphOperationType.ENRICH_FROM_WEB.value:
        return await _process_enrich_from_web(job)
    if operation == GraphOperationType.FIRECRAWL_EXTRACT.value:
        return await _process_firecrawl_extract(job)
    if operation == GraphOperationType.SCHEDULE_MEETING_BOT.value:
        return await _process_schedule_meeting_bot(job)
    if operation == GraphOperationType.PROCESS_MEETING_TRANSCRIPT.value:
        return await _process_meeting_transcript(job)
    if operation == GraphOperationType.PROCESS_DESKTOP_SDK_RECORDING.value:
        return await _process_desktop_sdk_recording(job)
    if operation == GraphOperationType.GENERATE_MEETING_SUMMARY.value:
        return await _process_generate_meeting_summary(job)
    if operation == GraphOperationType.INDEX_MEETING_TRANSCRIPT.value:
        return await _process_index_meeting_transcript(job)
    if operation == GraphOperationType.GENERATE_MEETING_BRIEFING.value:
        return await _process_generate_meeting_briefing(job)
    if operation == GraphOperationType.GENERATE_DEEP_BRIEF.value:
        return await _process_generate_deep_brief(job)
    if operation == GraphOperationType.GENERATE_MEETING_FOLLOWUP.value:
        return await _process_generate_meeting_followup(job)
    if operation == GraphOperationType.GENERATE_WEEKLY_DIGEST.value:
        return await _process_generate_weekly_digest(job)
    if operation == GraphOperationType.SEND_LIFECYCLE_EMAIL.value:
        return await _process_send_lifecycle_email(job)
    if operation == GraphOperationType.SEND_ACTION_ITEM_REMINDER.value:
        return await _process_send_action_item_reminder(job)
    if operation == GraphOperationType.SEND_FOLLOWUP_DRAFT.value:
        return await _process_send_followup_draft(job)
    if operation == GraphOperationType.ROUTE_RECAP_EDIT_TO_STORE.value:
        return await _process_route_recap_edit_to_store(job)
    if operation == GraphOperationType.WARM_MEETING_CACHE.value:
        return await _handle_warm_meeting_cache(job)
    if operation == GraphOperationType.ENRICH_TWIN_RESPONSES.value:
        return await _process_enrich_twin_responses(job)
    if operation == GraphOperationType.PREP_MEETING_CONTEXT.value:
        return await _handle_prep_meeting_context(job)
    if operation == GraphOperationType.STRIPE_METER_EVENT.value:
        return await _process_stripe_meter_event(job)
    if operation == GraphOperationType.LINK_MEETING_CONTACTS.value:
        return await _process_link_meeting_contacts(job)
    if operation == GraphOperationType.EXTRACT_MEMORY_CANDIDATES.value:
        return await _process_extract_memory_candidates(job)
    if operation == GraphOperationType.RECALL_CALENDAR_SYNC.value:
        return await _process_recall_calendar_sync(job)
    if operation == GraphOperationType.RESOLVE_MEETING_SPEAKERS.value:
        return await _process_resolve_meeting_speakers(job)
    if operation == GraphOperationType.ENHANCE_NOTES.value:
        return await _process_enhance_notes(job)
    if operation == GraphOperationType.RECAP_TIMEOUT_CHECK.value:
        return await _process_recap_timeout_check(job)
    if operation == GraphOperationType.RUN_NOTIFICATION_FLOW.value:
        return await _process_run_notification_flow(job)
    if operation == GraphOperationType.PROCESS_NOTIFICATION_EVENT.value:
        return await _process_notification_event(job)
    if operation == GraphOperationType.MEASURE_NOTIFICATION_OUTCOME.value:
        return await _process_measure_notification_outcome(job)
    if operation == GraphOperationType.LEAD_CAPTURED.value:
        return await _process_lead_captured(job)

    # Known-but-unimplemented operations: these enum values exist in
    # GraphOperationType but have no handler wired up. Returning True
    # silently marks the job completed, which masks the fact that real
    # work never happened -- a job enqueued for any of these would be a
    # silent no-op (CRITICAL finding in the 2026-05-31 audit). Instead,
    # we return False so the job retries to exhaustion and then lands on
    # the failed pile where operators can see it.
    if operation in (
        GraphOperationType.UPDATE_CLAIM_STATUS.value,
        GraphOperationType.CREATE_RELATIONSHIP.value,
        GraphOperationType.DELETE_TWIN_GRAPH.value,
        GraphOperationType.EXTRACT_COMMITMENTS.value,
    ):
        logger.error(
            "[GraphOutboxWorker] known-but-unhandled operation=%s job=%s "
            "-- no dispatcher branch wired; failing the job so operators can see it",
            operation, job.get("id"),
        )
        return False

    # Truly unknown operation (e.g. a typo, a stale job from a removed enum,
    # or a future enum value running on an old worker). Fail rather than
    # silently complete so the operator sees the queue is mis-configured.
    logger.error(
        "[GraphOutboxWorker] unsupported operation=%s job=%s "
        "-- no enum match; failing the job",
        operation, job.get("id"),
    )
    return False


async def _process_extract_memory_candidates(job: dict[str, Any]) -> bool:
    """Extract memory candidates from a meeting recap and insert into memory_candidates.

    Reads recap_extras_json + summary_json from the meeting row, calls the
    memory_candidate_extractor service, and inserts candidate rows with
    status='pending' for user review.

    Returns True on success, False on failure (triggers retry via graph_outbox).
    """
    payload = job.get("payload") or {}
    tenant_id = str(payload.get("tenant_id") or "")
    twin_id = str(payload.get("twin_id") or "")
    meeting_id = str(payload.get("meeting_id") or "")
    try:
        meeting_resp = await _run_db(
            lambda: supabase.table("meetings")
            .select("recap_extras_json, summary_json")
            .eq("id", meeting_id)
            .single()
            .execute()
        )
        m = getattr(meeting_resp, "data", None) or {}

        # Owner lookup: public.users.full_name where tenant_id matches.
        u_resp = await _run_db(
            lambda: supabase.table("users")
            .select("full_name, email")
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        u_row = (getattr(u_resp, "data", None) or [None])[0] or {}
        owner_name = (u_row.get("full_name") or "").strip()
        if not owner_name and u_row.get("email"):
            owner_name = u_row["email"].split("@")[0]

        from services.memory_candidate_extractor import extract_memory_candidates

        candidates = await extract_memory_candidates(
            tenant_id=tenant_id,
            twin_id=twin_id,
            meeting_id=meeting_id,
            owner_name=owner_name,
            recap_extras=m.get("recap_extras_json"),
            summary_json=m.get("summary_json"),
        )
        if candidates:
            rows = [
                {
                    **c,
                    "tenant_id": tenant_id,
                    "twin_id": twin_id,
                    "meeting_id": meeting_id,
                    "status": "pending",
                }
                for c in candidates
            ]
            # idempotent — retries produce no duplicates
            await _run_db(
                lambda: supabase.table("memory_candidates")
                .upsert(
                    rows,
                    on_conflict="memory_candidates_meeting_text_kind_unique",
                    ignore_duplicates=True,
                )
                .execute()
            )
        logger.info(
            "[Worker] extract_memory_candidates done meeting_id=%s count=%d",
            meeting_id,
            len(candidates),
        )
        return True
    except Exception:
        logger.exception(
            "[Worker] extract_memory_candidates failed job_id=%s", job.get("id")
        )
        return False


async def _process_enhance_notes(job: dict[str, Any]) -> bool:
    """Granola Batch 3: AI-merge the user's live notes + the live transcript
    segments into clean enhanced notes (the headline feature).

    Reads `user_notes_json` from the meeting row and the transcript from
    `meeting_transcript_segments` (NOT `transcript_url` — the live segments are
    already in Postgres at Stop, so this runs immediately and is not gated on
    the batch re-transcription chain). Writes `enhanced_notes_json` plus the
    `enhanced_notes_status` / `recap_stage` / `recap_progress` progression.

    Status transitions:
      generating → ready    (merge produced an artifact)
      generating → skipped  (no notes AND no transcript — nothing to merge)
      generating → failed   (Gemini/budget/malformed failure; returns False → retry)

    Returns True on success or 'skipped' (terminal), False on failure (retry),
    per the graph_outbox contract — never raises.
    """
    from datetime import datetime, timezone

    payload = job.get("payload") or {}
    job_id = str(job.get("id") or "")
    meeting_id = str(payload.get("meeting_id") or "")
    tenant_id = str(payload.get("tenant_id") or job.get("tenant_id") or "")
    twin_id = str(payload.get("twin_id") or "") or None

    if not meeting_id:
        logger.warning("[EnhanceNotes] missing meeting_id job=%s", job_id)
        return True  # nothing to retry

    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    try:
        # Load the meeting row for notes + tenant fallback.
        meeting_resp = await _run_db(
            lambda: supabase.table("meetings")
            .select("user_notes_json, tenant_id, twin_id, enhanced_notes_status")
            .eq("id", meeting_id)
            .maybe_single()
            .execute()
        )
        m = getattr(meeting_resp, "data", None)
        if not m:
            logger.warning("[EnhanceNotes] meeting row not found meeting_id=%s job=%s", meeting_id, job_id)
            return True  # row soft-deleted between enqueue and run; nothing to retry

        tenant_id = tenant_id or str(m.get("tenant_id") or "")
        twin_id = twin_id or (str(m.get("twin_id")) if m.get("twin_id") else None)

        user_notes_json = m.get("user_notes_json") or {}
        user_notes_text = ""
        if isinstance(user_notes_json, dict):
            user_notes_text = str(user_notes_json.get("text") or "")

        # Mark generating + recap_stage='enhancing' before the LLM call so the
        # UI's progressive reveal reflects in-flight work.
        await _run_db(
            lambda: supabase.table("meetings").update({
                "enhanced_notes_status": "generating",
                "recap_stage": "enhancing",
                "recap_progress": 70,
                "updated_at": _now(),
            }).eq("id", meeting_id).eq("tenant_id", tenant_id).execute()
        )

        # Load the live transcript segments (NOT transcript_url).
        seg_resp = await _run_db(
            lambda: supabase.table("meeting_transcript_segments")
            .select("seq, speaker, text, start_ms")
            .eq("meeting_id", meeting_id)
            .order("seq")
            .execute()
        )
        segments = getattr(seg_resp, "data", None) or []

        # Skip path: nothing to merge at all.
        if not user_notes_text.strip() and not segments:
            await _run_db(
                lambda: supabase.table("meetings").update({
                    "enhanced_notes_status": "skipped",
                    "recap_stage": "enhanced_ready",
                    "recap_progress": 100,
                    "updated_at": _now(),
                }).eq("id", meeting_id).eq("tenant_id", tenant_id).execute()
            )
            logger.info(
                "[EnhanceNotes] no notes and no segments meeting_id=%s — status=skipped", meeting_id,
            )
            return True

        from services.enhanced_notes_service import generate_enhanced_notes

        artifact = await generate_enhanced_notes(
            tenant_id=tenant_id,
            twin_id=twin_id,
            meeting_id=meeting_id,
            user_notes_text=user_notes_text,
            segments=segments,
        )

        if artifact is None:
            # Soft failure (budget/Gemini/malformed). Mark failed and retry.
            await _run_db(
                lambda: supabase.table("meetings").update({
                    "enhanced_notes_status": "failed",
                    "updated_at": _now(),
                }).eq("id", meeting_id).eq("tenant_id", tenant_id).execute()
            )
            logger.warning("[EnhanceNotes] generation returned None meeting_id=%s — retry", meeting_id)
            return False

        await _run_db(
            lambda: supabase.table("meetings").update({
                "enhanced_notes_json": artifact,
                "enhanced_notes_status": "ready",
                "recap_stage": "enhanced_ready",
                "recap_progress": 100,
                "updated_at": _now(),
            }).eq("id", meeting_id).eq("tenant_id", tenant_id).execute()
        )
        logger.info(
            "[EnhanceNotes] wrote enhanced_notes_json meeting_id=%s sections=%d",
            meeting_id, len(artifact.get("sections") or []),
        )
        return True
    except Exception:
        logger.exception("[EnhanceNotes] worker failed job=%s meeting_id=%s", job_id, meeting_id)
        # Best-effort status flip so the UI isn't stuck on 'generating'.
        # Scope to tenant_id when known (tenant_scope_mutations policy); fall
        # back to id-only if the SELECT failed before tenant_id was resolved, so
        # the UI is never left stuck on 'generating'.
        def _flip_failed() -> Any:
            q = supabase.table("meetings").update({
                "enhanced_notes_status": "failed",
                "updated_at": _now(),
            }).eq("id", meeting_id)
            if tenant_id:
                q = q.eq("tenant_id", tenant_id)
            return q.execute()

        try:
            await _run_db(_flip_failed)
        except Exception:
            logger.exception("[EnhanceNotes] failed to flip status to failed meeting_id=%s", meeting_id)
        return False


# Recordings whose recap has not reached a terminal state within this window
# are considered stuck and flipped to failed so the UI stops spinning. Tunable
# via env for staging experiments; defaults to 10 minutes per the plan.
RECAP_STUCK_TIMEOUT_SECONDS = int(os.getenv("RECAP_STUCK_TIMEOUT_SECONDS", "600"))

# A recording is "in a terminal state" — and MUST NEVER be touched by the
# watchdog — when its status is one of these. `completed`/`ready` are success
# terminals; `failed`/`deleted` are already-final. This is the never-touch guard.
_RECAP_TERMINAL_STATUSES = {"completed", "ready", "failed", "deleted"}
# enhanced_notes_status terminals — a row that already settled here is done.
_ENHANCED_TERMINAL_STATUSES = {"ready", "skipped", "failed"}


async def _process_recap_timeout_check(job: dict[str, Any]) -> bool:
    """Granola Batch 5 reliability watchdog — flip recaps stuck too long to failed.

    A recap should march `recording → processing → completed` (with
    enhanced_notes_status `pending → generating → ready/skipped`). If the worker
    crashed, the webhook never landed, or a Gemini outage exhausted retries, a
    row can sit in a non-terminal state forever and the UI shows an eternal
    spinner. This scan flips any row past RECAP_STUCK_TIMEOUT_SECONDS to a
    user-visible failed state.

    A row is "stuck" when, AND ONLY when, BOTH hold:
      1. it is NOT in a terminal state  (status not in {completed,ready,failed,
         deleted} AND enhanced_notes_status not in {ready,skipped,failed}), and
      2. it has not been updated within the timeout window.
    AND it is in an active recap state:
         status == 'processing'  OR  enhanced_notes_status in ('pending','generating')

    NEVER-TOUCH-COMPLETED GUARD: the SELECT excludes terminal statuses, and each
    candidate row is RE-CHECKED in Python before any UPDATE (defense-in-depth
    against clock skew / a row that completed between the scan and the write).
    The UPDATE itself is also status-scoped so it is a no-op if the row reached a
    terminal state in the race window.

    IDEMPOTENT + REPEATABLE: flips set status='failed', which immediately removes
    the row from the stuck set, so re-running the scan (the worker poll loop, or
    a retry of this job) produces no further writes. There is no per-meeting
    payload — this scan is global and safe to fire on a schedule.

    Returns True (done) on a clean scan, False only on an unexpected DB error so
    graph_outbox retries the scan. Never raises (graph_outbox contract).
    """
    from datetime import datetime, timezone

    job_id = str(job.get("id") or "")
    payload = job.get("payload") or {}

    # An optional meeting_id narrows the scan to the recording this watchdog was
    # armed for at Stop. Absent (a scheduled global sweep) -> scan all tenants.
    target_meeting_id = str(payload.get("meeting_id") or "").strip() or None

    now = datetime.now(timezone.utc)
    cutoff_iso = (now - timedelta(seconds=RECAP_STUCK_TIMEOUT_SECONDS)).isoformat()

    def _select_stuck() -> Any:
        # Active-recap predicate: status='processing' OR enhanced_notes in
        # (pending,generating). PostgREST .or_ groups these; the .neq filters
        # below exclude terminal statuses so a completed/failed/deleted row is
        # never even returned (the primary never-touch-completed guard).
        q = (
            supabase.table("meetings")
            .select("id, status, enhanced_notes_status, recap_stage, updated_at")
            .or_(
                "status.eq.processing,"
                "enhanced_notes_status.eq.pending,"
                "enhanced_notes_status.eq.generating"
            )
            .lte("updated_at", cutoff_iso)
            .neq("status", "completed")
            .neq("status", "failed")
            .neq("status", "deleted")
            .limit(200)
        )
        if target_meeting_id:
            q = q.eq("id", target_meeting_id)
        return q.execute()

    try:
        resp = await _run_db(_select_stuck)
    except Exception:
        logger.exception("[RecapTimeout] stuck-row scan failed job=%s", job_id)
        return False  # retry the scan

    rows = getattr(resp, "data", None) or []
    if not rows:
        logger.info("[RecapTimeout] scan clean — no stuck recaps job=%s", job_id)
        return True

    flipped = 0
    for row in rows:
        meeting_id = str(row.get("id") or "")
        if not meeting_id:
            continue

        status = str(row.get("status") or "")
        enhanced_status = str(row.get("enhanced_notes_status") or "")

        # NEVER-TOUCH guard (defense-in-depth, re-checked per row): even though
        # the SELECT excluded terminal statuses, a row could have completed in
        # the scan→write window (clock skew / a worker finishing concurrently).
        # Skip anything that is now terminal.
        if status in _RECAP_TERMINAL_STATUSES:
            logger.info(
                "[RecapTimeout] skip terminal status=%s meeting=%s", status, meeting_id,
            )
            continue
        if enhanced_status in _ENHANCED_TERMINAL_STATUSES:
            logger.info(
                "[RecapTimeout] skip terminal enhanced_status=%s meeting=%s",
                enhanced_status, meeting_id,
            )
            continue

        # Flip to a user-visible failed state. recap_stage is ALSO set to
        # 'failed' (allowed by the CHECK as of 20260611000400) so the frontend's
        # isRecapInProgress() sees a terminal stage and stops rendering a
        # perpetual skeleton (QG2 H1). status='failed' + enhanced_notes_status=
        # 'failed' + recap_stage='failed' are the authoritative terminal signals
        # the UI keys off. The UPDATE is status-scoped so it no-ops if the row
        # reached a terminal state in the race window (it only matches rows still
        # NOT completed/failed/deleted) — the SQL-level never-touch-completed
        # guard.
        update_payload = {
            "status": "failed",
            "enhanced_notes_status": "failed",
            "recap_stage": "failed",
            "recap_error_reason": "Recap timed out — processing took too long.",
            "updated_at": now.isoformat(),
        }

        def _flip(mid: str = meeting_id, body: dict[str, Any] = update_payload) -> Any:
            return (
                supabase.table("meetings")
                .update(body)
                .eq("id", mid)
                .neq("status", "completed")
                .neq("status", "failed")
                .neq("status", "deleted")
                .execute()
            )

        try:
            flip_resp = await _run_db(_flip)
        except Exception:
            # A missing recap_error_reason column (pre-migration) shouldn't lose
            # the failure flip — retry without it. Other errors fail the scan so
            # it retries.
            logger.warning(
                "[RecapTimeout] flip failed for meeting=%s — retrying without recap_error_reason",
                meeting_id,
            )
            fallback_body = {
                k: v for k, v in update_payload.items() if k != "recap_error_reason"
            }

            def _flip_fallback(mid: str = meeting_id, body: dict[str, Any] = fallback_body) -> Any:
                return (
                    supabase.table("meetings")
                    .update(body)
                    .eq("id", mid)
                    .neq("status", "completed")
                    .neq("status", "failed")
                    .neq("status", "deleted")
                    .execute()
                )

            try:
                flip_resp = await _run_db(_flip_fallback)
            except Exception:
                logger.exception(
                    "[RecapTimeout] flip permanently failed meeting=%s", meeting_id,
                )
                return False  # retry the whole scan

        affected = getattr(flip_resp, "data", None) or []
        if affected:
            flipped += 1
            logger.warning(
                "[RecapTimeout] flipped stuck recap to failed meeting=%s prev_status=%s "
                "prev_enhanced=%s updated_at=%s",
                meeting_id, status, enhanced_status, row.get("updated_at"),
            )

    logger.info(
        "[RecapTimeout] scan complete job=%s candidates=%d flipped=%d timeout_s=%d",
        job_id, len(rows), flipped, RECAP_STUCK_TIMEOUT_SECONDS,
    )
    return True


async def sweep_stuck_recaps() -> bool:
    """Run the recap-timeout watchdog as a GLOBAL sweep (no specific meeting).

    The per-meeting ``recap_timeout_check`` job is armed at desktop-recording Stop
    only — bot/Recall meetings never arm it, so a bot recap wedged in 'processing'
    would linger forever. The worker poll loop calls this periodically so stuck
    recaps from ANY source are flipped to 'failed' regardless of how they started.

    Reuses _process_recap_timeout_check with an empty payload (target_meeting_id
    None -> global scan). Idempotent and never raises (graph_outbox contract).
    """
    return await _process_recap_timeout_check(
        {"id": "worker_periodic_recap_sweep", "payload": {}}
    )


async def _process_route_recap_edit_to_store(job: dict[str, Any]) -> bool:
    """Classify a recap edit and stamp recap_edits.store_routing.

    Both SELECT and UPDATE filter by tenant_id (defense-in-depth per Layer 1
    feedback_tenant_scope_mutations memory). A cross-tenant edit_id in the
    payload would now return zero rows and short-circuit with True (done,
    nothing to retry) rather than letting Gemini classify a row owned by a
    different tenant.
    """
    payload = job.get("payload") or {}
    job_id = str(job.get("id") or "")
    edit_id = str(payload.get("edit_id") or "")
    tenant_id = str(payload.get("tenant_id") or job.get("tenant_id") or "")
    if not edit_id:
        logger.warning("[RecapEditRouter] missing edit_id job=%s", job_id)
        return True

    try:
        def _build_select() -> Any:
            q = (
                supabase.table("recap_edits")
                .select("id,field,before,after,tenant_id,store_routing")
                .eq("id", edit_id)
            )
            if tenant_id:
                q = q.eq("tenant_id", tenant_id)
            return q.maybe_single().execute()

        edit_resp = await _run_db(_build_select)
        edit = getattr(edit_resp, "data", None) or {}
        if not edit:
            logger.warning(
                "[RecapEditRouter] edit not found or cross-tenant id=%s tenant=%s",
                edit_id, tenant_id,
            )
            return True

        # Skip-if-already-routed guard. Two workers racing on the same job
        # (or a retry after a partial DB write) would otherwise re-run the
        # Gemini classification and could overwrite a correct routing with
        # a different value due to LLM variance. Idempotency_key dedupes at
        # the queue level but doesn't protect re-claim windows.
        if edit.get("store_routing"):
            logger.info(
                "[RecapEditRouter] already routed id=%s store=%s — skipping",
                edit_id, edit.get("store_routing"),
            )
            return True

        from services.recap_router import classify_edit_to_store

        store = await classify_edit_to_store(
            field=str(edit.get("field") or ""),
            before=edit.get("before"),
            after=edit.get("after"),
            tenant_id=tenant_id,
        )

        def _build_update() -> Any:
            q = (
                supabase.table("recap_edits")
                .update({"store_routing": store})
                .eq("id", edit_id)
            )
            if tenant_id:
                q = q.eq("tenant_id", tenant_id)
            return q.execute()

        await _run_db(_build_update)
        logger.info("[RecapEditRouter] routed edit=%s store=%s job=%s", edit_id, store, job_id)
        return True
    except Exception:
        logger.exception("[RecapEditRouter] failed job=%s edit=%s", job_id, edit_id)
        return False


async def _process_send_action_item_reminder(job: dict[str, Any]) -> bool:
    """Send an email reminder for one meeting action item."""
    payload = job.get("payload") or {}
    job_id = str(job.get("id") or "")
    meeting_id = str(payload.get("meeting_id") or "")
    recipient_email = str(payload.get("recipient_email") or "").strip()
    user_id = str(payload.get("user_id") or "").strip()
    tenant_id = str(payload.get("tenant_id") or job.get("tenant_id") or "").strip()
    try:
        action_item_index = int(payload.get("action_item_index"))
    except Exception:
        action_item_index = -1

    if not meeting_id or action_item_index < 0 or not recipient_email:
        # Redact payload values; the recipient_email field is PII and the
        # payload may also contain user_id / tenant_id. Log only the key
        # names so we can debug shape issues without leaking address data.
        logger.warning(
            "[ActionItemReminder] bad payload job=%s payload_keys=%s",
            job_id, sorted(list(payload.keys())),
        )
        return True

    # F6.1 (BLOCKER): a missing user_id MUST NOT be silently substituted with
    # tenant_id below — the preferences SELECT and is_email_suppressed call
    # use user_id as the lookup key, and falling back to tenant_id bypasses
    # both the opt-out preference and the suppression list. Refuse to send
    # rather than relay around the user's controls.
    if not user_id:
        logger.warning(
            "[ActionItemReminder] refusing send: empty user_id in payload job=%s meeting=%s",
            job_id, meeting_id,
        )
        return True

    # F6.NIT (S8/N1): empty tenant_id would degrade to an unscoped SELECT.
    # The enqueue path always writes tenant_id; treat empty as a corrupt
    # payload and refuse rather than soft-fall-through.
    if not tenant_id:
        logger.error(
            "[ActionItemReminder] refusing send: empty tenant_id job=%s meeting=%s",
            job_id, meeting_id,
        )
        return True

    # F6.3 (HIGH H2): defense-in-depth — re-validate recipient_email at the
    # worker boundary too. The router validates at enqueue (closes the
    # open-relay primary gate), but a future code path that enqueues without
    # the guard, or a corrupt outbox row, would otherwise still relay.
    from modules.email_validation import is_valid_email
    if not is_valid_email(recipient_email):
        logger.warning(
            "[ActionItemReminder] refusing send: invalid recipient_email job=%s meeting=%s",
            job_id, meeting_id,
        )
        return True

    try:
        # Defense-in-depth tenant filter on SELECT (Layer 1 lesson —
        # feedback_tenant_scope_mutations.md). Without it, a cross-tenant
        # meeting_id in the payload could be loaded by this worker.
        def _build_meeting_select() -> Any:
            return (
                supabase.table("meetings")
                .select("id,title,tenant_id,twin_id,action_items")
                .eq("id", meeting_id)
                .eq("tenant_id", tenant_id)
                .maybe_single()
                .execute()
            )

        meeting_resp = await _run_db(_build_meeting_select)
        meeting = getattr(meeting_resp, "data", None) or {}
        if not meeting:
            logger.warning(
                "[ActionItemReminder] meeting not found or cross-tenant id=%s tenant=%s",
                meeting_id, tenant_id,
            )
            return True

        action_items = meeting.get("action_items") or []
        if not isinstance(action_items, list) or action_item_index >= len(action_items):
            logger.warning("[ActionItemReminder] action item missing meeting=%s index=%s", meeting_id, action_item_index)
            return True
        item = action_items[action_item_index] if isinstance(action_items[action_item_index], dict) else {}
        item_text = str(item.get("text") or "").strip()
        if not item_text:
            logger.warning("[ActionItemReminder] action item text empty meeting=%s index=%s", meeting_id, action_item_index)
            return True

        tenant_id = str(meeting.get("tenant_id") or tenant_id)

        # user_id is guaranteed non-empty by the early refuse-send guard
        # above (F6.1), so the prefs and suppression lookups always use the
        # actual user, never a tenant_id fallback.
        prefs_resp = await _run_db(
            lambda: supabase.table("notification_preferences")
            .select("action_item_reminders_enabled")
            .eq("user_id", user_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        # supabase-py .maybe_single().execute() returns None (not a response
        # object) when zero rows match — which is the common case for a user
        # who has never set notification_preferences. Guard with getattr like
        # the meeting/edit selects above, else this AttributeErrors and the
        # reminder job retries forever. (Found via local worker test — the
        # unit tests mocked prefs_resp to always be a response object.)
        prefs = (getattr(prefs_resp, "data", None) or {})
        if prefs.get("action_item_reminders_enabled") is False:
            logger.info("[ActionItemReminder] disabled user=%s meeting=%s", user_id, meeting_id)
            return True

        from services.lifecycle_email_service import is_email_suppressed
        if await asyncio.to_thread(is_email_suppressed, user_id=user_id, email=recipient_email):
            logger.info("[ActionItemReminder] suppressed user=%s email=%s", user_id, recipient_email)
            return True

        # NOTE: deliberately NOT calling claim_notification_slot here.
        # That helper's unique key is (twin_id, meeting_id, notification_type)
        # which is per-meeting, not per-item. With 5 action items on one
        # meeting, claim_notification_slot would let only the first
        # reminder through and silently drop the other 4 as "already sent".
        # Per-item dedup is already provided by the graph_outbox
        # idempotency_key (action_item_reminder:{meeting_id}:{idx}) +
        # Resend's own idempotency_key passed at the send_email call below.

        from services.email_service import build_action_item_reminder_html, send_email

        frontend_url = (
            os.getenv("NEXT_PUBLIC_FRONTEND_URL")
            or os.getenv("FRONTEND_URL")
            or os.getenv("PUBLIC_SITE_URL")
            or "https://www.personaon.com"
        ).rstrip("/")
        link = f"{frontend_url}/dashboard/meetings/{meeting_id}"
        html = build_action_item_reminder_html(
            meeting_title=str(meeting.get("title") or "Meeting"),
            item_text=item_text,
            due_at=str(item.get("due_at") or "") or None,
            link=link,
        )
        msg_id = await send_email(
            to=recipient_email,
            subject=f"Action item reminder: {item_text[:60]}",
            html=html,
            text=f"Action item from {meeting.get('title') or 'Meeting'}: {item_text}",
            idempotency_key=str(job.get("idempotency_key") or f"action_item_reminder:{meeting_id}:{action_item_index}"),
        )

        # meeting_notifications UPDATE intentionally removed:
        # we no longer claim a per-meeting slot at the start of this handler
        # (see comment above send_email). The graph_outbox row's status
        # (completed/failed) is the canonical per-item audit signal; Resend's
        # message_id (logged below) + Resend's webhook events track delivery
        # state. Keeping a stale per-meeting meeting_notifications row would
        # have been actively misleading once a single meeting sends multiple
        # reminders.
        logger.info(
            "[ActionItemReminder] sent meeting=%s index=%s msg=%s job=%s",
            meeting_id, action_item_index, msg_id, job_id,
        )
        return True
    except Exception:
        logger.exception("[ActionItemReminder] failed job=%s meeting=%s", job_id, meeting_id)
        return False


async def _process_send_followup_draft(job: dict[str, Any]) -> bool:
    """Send an owner-approved follow-up draft email (Home v1 'Respond').

    The owner approves a draft via the drafts API, which enqueues this job; the
    actual send happens here, off the request path. Idempotent via the
    graph_outbox idempotency_key + Resend's own idempotency_key.
    """
    payload = job.get("payload") or {}
    job_id = str(job.get("id") or "")
    draft_id = str(payload.get("draft_id") or "").strip()
    tenant_id = str(payload.get("tenant_id") or job.get("tenant_id") or "").strip()

    if not draft_id or not tenant_id:
        logger.warning(
            "[SendFollowupDraft] bad payload job=%s payload_keys=%s",
            job_id, sorted(list(payload.keys())),
        )
        return True

    try:
        # Defense-in-depth tenant filter on SELECT — a cross-tenant draft_id in
        # the payload must not be loadable by this worker (the service-role
        # client bypasses RLS).
        draft_resp = await _run_db(
            lambda: supabase.table("action_drafts")
            .select("id,tenant_id,twin_id,status,proposed_action")
            .eq("id", draft_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        draft = getattr(draft_resp, "data", None) or {}
        if not draft:
            logger.warning(
                "[SendFollowupDraft] draft not found or cross-tenant id=%s tenant=%s job=%s",
                draft_id, tenant_id, job_id,
            )
            return True

        if draft.get("status") == "executed":
            logger.info("[SendFollowupDraft] already executed draft=%s job=%s", draft_id, job_id)
            return True

        proposed = draft.get("proposed_action") or {}
        params = proposed.get("params") or {}
        recipient = str(params.get("to") or "").strip()
        subject = str(params.get("subject") or "").strip()
        body = str(params.get("body") or "").strip()

        # Defense-in-depth: re-validate recipient at the worker boundary too
        # (anti open-relay; the tool and API also validate at enqueue).
        from modules.email_validation import is_valid_email
        if not is_valid_email(recipient):
            logger.warning(
                "[SendFollowupDraft] refusing send: invalid recipient draft=%s job=%s",
                draft_id, job_id,
            )
            return True

        if not body:
            logger.warning("[SendFollowupDraft] empty body draft=%s job=%s", draft_id, job_id)
            return True

        from html import escape as _html_escape
        from services.email_service import send_email

        safe_body = _html_escape(body).replace("\n", "<br>")
        msg_id = await send_email(
            to=recipient,
            subject=subject or "Following up",
            html=f"<div>{safe_body}</div>",
            text=body,
            idempotency_key=str(job.get("idempotency_key") or f"send_followup:{draft_id}"),
        )

        await _run_db(
            lambda: supabase.table("action_drafts")
            .update({"status": "executed"})
            .eq("id", draft_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        logger.info(
            "[SendFollowupDraft] sent draft=%s msg=%s job=%s", draft_id, msg_id, job_id,
        )
        return True
    except Exception:
        logger.exception("[SendFollowupDraft] failed job=%s draft=%s", job_id, draft_id)
        return False


async def _process_send_lifecycle_email(job: dict[str, Any]) -> bool:
    """Send a lifecycle education/activity email from a graph outbox job."""
    payload = job.get("payload") or {}
    job_id = str(job.get("id") or "")
    user_id = str(payload.get("user_id") or "").strip()
    tenant_id = str(payload.get("tenant_id") or job.get("tenant_id") or "").strip()
    twin_id = str(payload.get("twin_id") or job.get("twin_id") or "").strip()
    recipient_email = str(payload.get("recipient_email") or "").strip()
    email_type = str(payload.get("email_type") or "").strip()
    category = str(payload.get("category") or "").strip()
    scope_type = str(payload.get("scope_type") or "user").strip()
    scope_id = str(payload.get("scope_id") or user_id).strip()
    period_key = str(payload.get("period_key") or "once").strip()
    context = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    candidate_reason = str(payload.get("candidate_reason") or context.get("candidate_reason") or "unspecified")
    cta_path = str(payload.get("cta_path") or context.get("cta_path") or "")
    event_id = str(payload.get("event_id") or "").strip()
    idempotency_key = str(payload.get("idempotency_key") or "").strip()
    reply_to_email = str(payload.get("reply_to_email") or "").strip() or None

    # Fast path: visitor confirmation — sent to the visitor, not the owner.
    # Bypasses preference/unsubscribe machinery (visitor has no owner account).
    if email_type == "visitor_confirmation":
        visitor_email = str(payload.get("visitor_recipient_email") or "").strip()
        if not visitor_email:
            logger.warning("[LifecycleEmailWorker] visitor_confirmation missing email job=%s", job_id)
            return True
        try:
            from services.email_service import send_email
            from services.lifecycle_email_service import build_visitor_confirmation_email

            vc = build_visitor_confirmation_email(
                persona_name=str(payload.get("persona_name") or "your contact"),
                persona_handle=str(payload.get("persona_handle") or ""),
                visitor_name=str(payload.get("visitor_name") or ""),
                inferred_intent=payload.get("inferred_intent"),
                persona_page_url=str(payload.get("persona_page_url") or ""),
                booking_url=str(payload.get("booking_url") or "") or None,
                frontend_url=str(payload.get("frontend_url") or ""),
            )
            await send_email(
                to=visitor_email,
                subject=vc["subject"],
                html=vc["html"],
                idempotency_key=str(payload.get("scope_id") or "") or None,
            )
            logger.info("[LifecycleEmailWorker] visitor_confirmation sent to=%s job=%s", visitor_email, job_id)
        except Exception:
            logger.exception("[LifecycleEmailWorker] visitor_confirmation send failed job=%s", job_id)
            return False
        return True

    if not all([user_id, tenant_id, recipient_email, email_type, category, scope_type, scope_id, period_key]):
        logger.warning("[LifecycleEmailWorker] bad payload job=%s payload=%s", job_id, payload)
        return True

    try:
        from services.lifecycle_email_service import (
            claim_lifecycle_email_event,
            generate_unsubscribe_token,
            is_category_enabled,
            is_email_suppressed,
            load_lifecycle_preferences,
            mark_lifecycle_event_failed,
            mark_lifecycle_event_sent,
            mark_lifecycle_event_skipped,
            build_lifecycle_email,
        )
        from services.email_service import send_email

        if not event_id:
            claimed = await asyncio.to_thread(
                claim_lifecycle_email_event,
                user_id=user_id,
                tenant_id=tenant_id,
                email_type=email_type,
                category=category,
                scope_type=scope_type,
                scope_id=scope_id,
                period_key=period_key,
                recipient_email=recipient_email,
                payload=context,
            )
            if not claimed:
                logger.info("[LifecycleEmailWorker] already claimed type=%s scope=%s period=%s", email_type, scope_id, period_key)
                return True
            event_id = str(claimed.get("id") or "")
            idempotency_key = str(claimed.get("idempotency_key") or idempotency_key)

        prefs = await asyncio.to_thread(load_lifecycle_preferences, user_id, tenant_id)
        if not is_category_enabled(prefs, category):
            await asyncio.to_thread(mark_lifecycle_event_skipped, event_id=event_id, reason="preference_disabled")
            return True

        if await asyncio.to_thread(is_email_suppressed, user_id=user_id, email=recipient_email):
            await asyncio.to_thread(mark_lifecycle_event_skipped, event_id=event_id, reason="suppressed")
            return True

        frontend_url = (
            os.getenv("NEXT_PUBLIC_FRONTEND_URL")
            or os.getenv("FRONTEND_URL")
            or os.getenv("PUBLIC_SITE_URL")
            or "https://www.personaon.com"
        ).rstrip("/")
        api_url = (
            os.getenv("LIFECYCLE_PUBLIC_API_URL")
            or os.getenv("PUBLIC_API_URL")
            or os.getenv("NEXT_PUBLIC_BACKEND_URL")
            or os.getenv("CLOUD_RUN_SERVICE_URL")
            or frontend_url
        ).rstrip("/")
        token = generate_unsubscribe_token(user_id)
        if email_type == "meeting_recap_ready":
            from services.lifecycle_email_service import build_meeting_recap_email
            email = build_meeting_recap_email(
                frontend_url=frontend_url,
                preferences_url=f"{frontend_url}/dashboard/settings?tab=notifications",
                unsubscribe_url=f"{api_url}/v2/notifications/unsubscribe/{token}",
                context=context,
            )
        elif email_type == "meeting_brief_ready":
            from services.lifecycle_email_service import build_meeting_brief_email
            email = build_meeting_brief_email(
                frontend_url=frontend_url,
                preferences_url=f"{frontend_url}/dashboard/settings?tab=notifications",
                unsubscribe_url=f"{api_url}/v2/notifications/unsubscribe/{token}",
                context=context,
            )
        else:
            email = build_lifecycle_email(
                email_type=email_type,
                frontend_url=frontend_url,
                preferences_url=f"{frontend_url}/dashboard/settings?tab=notifications",
                unsubscribe_url=f"{api_url}/v2/notifications/unsubscribe/{token}",
                context=context,
            )
        tags = list(email.get("tags") or [])
        tags.extend(
            [
                {"name": "user_id", "value": user_id[:64]},
                {"name": "tenant_id", "value": tenant_id[:64]},
                {"name": "twin_id", "value": twin_id[:64]},
                {"name": "candidate_reason", "value": candidate_reason[:64]},
            ]
        )
        msg_id = await send_email(
            to=recipient_email,
            subject=str(email["subject"]),
            html=str(email["html"]),
            text=str(email["text"]),
            headers=email.get("headers") or {},
            tags=tags,
            reply_to=reply_to_email or os.getenv("LIFECYCLE_REPLY_TO") or None,
            from_address=os.getenv("LIFECYCLE_FROM_ADDRESS", "PersonaOn <notifications@mail.personaon.com>"),
            idempotency_key=idempotency_key or None,
        )
        await asyncio.to_thread(mark_lifecycle_event_sent, event_id=event_id, resend_message_id=msg_id)
        try:
            from modules.posthog_analytics import ph_capture

            ph_capture(
                user_id=user_id,
                event="lifecycle_email_sent",
                properties={
                    "email_type": email_type,
                    "category": category,
                    "scope_type": scope_type,
                    "period_key": period_key,
                    "candidate_reason": candidate_reason,
                    "cta_path": cta_path,
                },
            )
        except Exception:
            pass
        logger.info("[LifecycleEmailWorker] sent type=%s user=%s job=%s", email_type, user_id, job_id)
        return True
    except Exception as exc:
        logger.exception("[LifecycleEmailWorker] failed job=%s type=%s", job_id, email_type)
        if event_id:
            try:
                from services.lifecycle_email_service import mark_lifecycle_event_failed

                await asyncio.to_thread(mark_lifecycle_event_failed, event_id=event_id, error_message=str(exc))
            except Exception:
                pass
        return False


async def _process_firecrawl_extract(job: dict[str, Any]) -> bool | None:
    """Background Firecrawl profile extraction — runs during onboarding while user fills the form.

    Stores the full ProfileSchema result back into the job payload under
    'extraction_result' so the frontend can poll GET /auth/extraction/{id}.

    Return contract (graph_outbox dispatcher):
        * ``None``  -- handler called ``_mark_job_completed`` itself; the
          dispatcher must NOT mark the job again. This is the success path.
        * exceptions propagate -- if the final self-mark raises, we
          re-raise so the outer ``process_next_graph_outbox_job`` exception
          handler runs ``_mark_job_failed`` and the retry path takes over.

    The previous version always returned None implicitly. If the
    ``_mark_job_completed`` call itself raised (transient DB blip, network
    flap on the Supabase write), the function still returned None and the
    dispatcher skipped error handling -- the job sat in "processing"
    permanently. We now wrap the final mark in try/except and re-raise so
    the outer handler fails the job and the retry path takes over.
    """
    import asyncio

    payload = job.get("payload") or {}
    job_id = str(job.get("id") or "")
    person_name = str(payload.get("person_name") or "").strip()
    context = str(payload.get("context") or "").strip() or None

    if not person_name:
        logger.warning("[FirecrawlExtract] missing person_name for job=%s", job_id)
        # Mark completed with empty result so frontend doesn't wait forever.
        # If THIS mark fails, re-raise so the outer dispatcher fails the
        # job rather than leaving it stuck in 'processing'.
        try:
            await _mark_job_completed(job_id, payload={**payload, "extraction_result": {}})
        except Exception:
            logger.exception(
                "[FirecrawlExtract] _mark_job_completed failed for job=%s (no person_name) -- re-raising",
                job_id,
            )
            raise
        return None

    logger.info("[FirecrawlExtract] starting extraction for '%s' job=%s", person_name, job_id)
    try:
        from adk_core.services.firecrawl_service import extract_profile
        extracted = await asyncio.to_thread(extract_profile, person_name, context)
        logger.info("[FirecrawlExtract] completed for '%s' job=%s", person_name, job_id)
        final_payload = {**payload, "extraction_result": extracted}
    except TimeoutError:
        logger.warning("[FirecrawlExtract] timeout for '%s' job=%s", person_name, job_id)
        final_payload = {**payload, "extraction_result": {}, "error": "timeout"}
    except Exception as exc:
        logger.error("[FirecrawlExtract] failed for '%s' job=%s: %s", person_name, job_id, exc)
        final_payload = {**payload, "extraction_result": {}, "error": str(exc)}

    # Wrap the terminal self-mark so a DB failure here doesn't strand the
    # job in 'processing'. Re-raise: process_next_graph_outbox_job's outer
    # try/except catches it and calls _mark_job_failed, which the retry
    # loop will then re-claim.
    try:
        await _mark_job_completed(job_id, payload=final_payload)
    except Exception:
        logger.exception(
            "[FirecrawlExtract] _mark_job_completed failed for job=%s -- re-raising so dispatcher fails the job",
            job_id,
        )
        raise

    return None


async def _process_enrich_from_web(job: dict[str, Any]) -> bool:
    """Background web enrichment using a single LlmAgent with search + scrape tools."""
    import asyncio

    payload = job.get("payload") or {}
    twin_id = str(job.get("twin_id") or "").strip()
    subject_name = str(payload.get("subject_name") or "").strip()

    if not twin_id or not subject_name:
        logger.warning("[Enrich] Missing twin_id or subject_name, skipping")
        return True

    logger.info("[Enrich] Starting web enrichment for twin=%s subject=%s", twin_id, subject_name)

    try:
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService

        from adk_core.agents.enrichment_agent import build_enrichment_agent
        from adk_core.model_names import research_model_name
        from adk_core.services.vector_store import upsert_text_chunks

        model = research_model_name()
        organization = str(payload.get("organization") or "").strip()
        headline = str(payload.get("headline") or "").strip()
        bio_summary = str(payload.get("bio") or "").strip()[:500]
        agent = build_enrichment_agent(
            model=model,
            subject_name=subject_name,
            organization=organization,
            headline=headline,
            bio_summary=bio_summary,
        )
        runner = Runner(agent=agent, app_name="personaon_enrich", session_service=InMemorySessionService())

        session = await runner.session_service.create_session(
            app_name="personaon_enrich",
            user_id=f"worker_{twin_id}",
            state={},
        )

        from google.genai import types as genai_types

        enrichment_text = ""
        scraped_sources = []

        async for event in runner.run_async(
            user_id=session.user_id,
            session_id=session.id,
            new_message=genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=f"Find new information about {subject_name}")],
            ),
        ):
            # Collect scraped sources from tool state
            if hasattr(event, "actions") and event.actions:
                for _action in event.actions.tool_actions if hasattr(event.actions, "tool_actions") else []:
                    pass  # Tool results accumulate in session state

            # Collect final text output
            if hasattr(event, "content") and event.content:
                for part in event.content.parts or []:
                    if hasattr(part, "text") and part.text:
                        enrichment_text += part.text

        # Extract scraped sources from session state
        final_session = await runner.session_service.get_session(
            app_name="personaon_enrich",
            user_id=session.user_id,
            session_id=session.id,
        )
        state = final_session.state if final_session else {}
        scraped_json = state.get("temp:scraped_sources_json", "[]")

        import json
        try:
            scraped_sources = json.loads(scraped_json) if isinstance(scraped_json, str) else scraped_json
        except (json.JSONDecodeError, TypeError):
            scraped_sources = []

        # Vectorize scraped content
        total_chunks = 0
        for source in scraped_sources:
            if not isinstance(source, dict):
                continue
            text = source.get("extracted_text") or source.get("text") or ""
            if len(text) < 50:
                continue
            url = source.get("url", "unknown")
            title = source.get("title", "")
            chunks = await upsert_text_chunks(
                text=text,
                twin_id=twin_id,
                source=f"web_enrichment:{url}",
                metadata={"source_url": url, "source_title": title},
            )
            total_chunks += chunks

        # Also vectorize the enrichment summary itself
        if enrichment_text and len(enrichment_text) > 50:
            total_chunks += await upsert_text_chunks(
                text=enrichment_text,
                twin_id=twin_id,
                source="enrichment_summary",
            )

        logger.info("[Enrich] Completed for twin=%s: %s sources, %s chunks", twin_id, len(scraped_sources), total_chunks)
        return True

    except asyncio.TimeoutError:
        logger.warning("[Enrich] Timeout for twin=%s", twin_id)
        return False
    except Exception as exc:
        logger.error("[Enrich] Failed for twin=%s: %s", twin_id, exc)
        return False


async def _process_generate_meeting_summary(job: dict[str, Any]) -> bool:
    """Analyze transcript and store structured summary + speaker analytics.

    Reads the meeting row, calls analyze_meeting(), writes summary fields back to
    meetings table, and upserts per-speaker rows into meeting_analytics.

    Returns:
        True  — success or permanent skip (short meeting, missing row, no meeting_id)
        False — retriable failure (null transcript_raw, unexpected exception)
    """
    payload = job.get("payload") or {}
    job_id = str(job.get("id") or "")
    meeting_id = str(payload.get("meeting_id") or "")

    if not meeting_id:
        logger.warning("[MeetingSummary] missing meeting_id job=%s", job_id)
        return True

    try:
        meeting_resp = await _run_db(
            lambda: supabase.table("meetings")
            .select(
                "id,title,transcript_raw,transcript_text,duration_seconds,"
                "tenant_id,twin_id,meeting_start,attendees_json,recap_corrected_at"
            )
            .eq("id", meeting_id)
            .single()
            .execute()
        )
        meeting = meeting_resp.data

        if not meeting:
            logger.warning("[MeetingSummary] meeting not found id=%s", meeting_id)
            return True

        # ── Short-circuit guard (Wave 7a) ──────────────────────────────────
        # If the user has already corrected the recap, do NOT overwrite
        # their edits with a fresh LLM run. The audit pattern is one-way:
        # once recap_corrected_at is set, user is the source of truth.
        #
        # NOTE: `summary_json` (legacy back-compat column) is not written
        # on this path. Any code that falls back to `summary_json` for
        # rendering will see stale/null data. The frontend's
        # `hasNewRecapData()` switches on `recap_version != null` first
        # (which user edits always satisfy), so the legacy path is never
        # hit for edited meetings. If a future reader adds a different
        # fallback heuristic, account for this gap.
        if meeting.get("recap_corrected_at"):
            logger.info(
                "[MeetingSummary] recap_corrected_at set — skipping regeneration meeting=%s",
                meeting_id,
            )
            return True

        if not meeting.get("transcript_raw"):
            if not meeting.get("transcript_text"):
                # Genuinely empty meeting — no speech captured. Skip permanently.
                logger.info(
                    "[MeetingSummary] no transcript meeting=%s — permanent skip", meeting_id
                )
                return True
            # transcript_text exists but transcript_raw not yet written — race, retry.
            logger.warning(
                "[MeetingSummary] transcript_raw null but transcript_text present meeting=%s — retrying",
                meeting_id,
            )
            return False

        # lazy import to avoid loading heavy analysis module at worker startup
        from services.meeting_analyzer import (
            _estimate_duration_from_transcript,
            analyze_meeting,
        )

        transcript_entries = meeting.get("transcript_raw") or []
        duration = meeting.get("duration_seconds") or _estimate_duration_from_transcript(
            transcript_entries
        )
        min_duration = int(os.getenv("MEETING_SUMMARY_MIN_DURATION_SECONDS", "120"))
        if duration < min_duration:
            logger.info(
                "[MeetingSummary] skipping short meeting=%s duration=%s threshold=%s",
                meeting_id, duration, min_duration,
            )
            return True
        summary, analytics = await analyze_meeting(meeting)

        # Resolve tenant_id BEFORE the UPDATE so we can dual-scope the write.
        # Service-role workers must always filter by (id, tenant_id) on meeting
        # rows — see docs/audits/2026-05-31-desktop-sdk-recording-audit.md C2.
        tenant_id = meeting["tenant_id"]

        now_iso = _utcnow_iso()
        await _run_db(
            lambda: supabase.table("meetings").update({
                # Backward-compatible columns (kept for one release)
                "summary": summary.get("recap", ""),  # fallback to recap narrative
                "summary_json": summary,
                # New typed columns (Task 0.4 migration — RecapContract shape)
                "recap": summary.get("recap", ""),
                "intent_vs_outcome": summary.get("intent_vs_outcome"),
                "action_items": summary.get("action_items", []),
                "commitments": summary.get("commitments", []),
                "decisions": summary.get("decisions", []),
                "topics": summary.get("topics", []),
                "unanswered_questions": summary.get("unanswered_questions", []),
                "people_observed": summary.get("people_observed", []),
                "my_positions": summary.get("my_positions", []),
                "style_sample": summary.get("style_sample", ""),
                "recap_version": 1,
                "updated_at": now_iso,
            }).eq("id", meeting_id).eq("tenant_id", tenant_id).execute()
        )
        rows = [
            {
                "meeting_id": meeting_id,
                "tenant_id": str(tenant_id),
                "participant_name": a["participant_name"],
                "talk_time_seconds": a["talk_time_seconds"],
                "talk_time_pct": a["talk_time_pct"],
                "word_count": a["word_count"],
                "words_per_minute": a["words_per_minute"],
                "filler_word_count": a["filler_word_count"],
                "sentiment_label": a.get("sentiment_label", "neutral"),
                "sentiment_score": a.get("sentiment_score", 0.5),
                "created_at": now_iso,
            }
            for a in analytics
        ]

        if rows:
            await _run_db(
                lambda: supabase.table("meeting_analytics").upsert(
                    rows, on_conflict="meeting_id,participant_name"
                ).execute()
            )

        logger.info(
            "[MeetingSummary] completed meeting=%s speakers=%d job=%s",
            meeting_id, len(rows), job_id,
        )

        # Trigger downstream transcript indexing (Phase 27)
        try:
            outbox = get_graph_outbox()
            outbox.submit(
                tenant_id=str(meeting["tenant_id"]),
                twin_id=str(meeting["twin_id"]),
                operation=GraphOperationType.INDEX_MEETING_TRANSCRIPT,
                idempotency_key=f"meeting_index:{meeting_id}",
                payload={"meeting_id": meeting_id},
                priority=3,
            )
        except Exception as enqueue_exc:
            logger.warning(
                "[MeetingSummary] failed to enqueue index job meeting=%s: %s",
                meeting_id, enqueue_exc,
            )

        # Enqueue recap email — non-fatal; recap is already persisted in-app.
        try:
            twin_id = str(meeting["twin_id"])
            meeting_tenant_id = str(meeting["tenant_id"])

            twin_resp = await _run_db(
                lambda: supabase.table("twins")
                .select("name, tenant_id")
                .eq("id", twin_id)
                .single()
                .execute()
            )
            if not twin_resp.data:
                logger.warning(
                    "[MeetingSummary] twin not found for recap email twin=%s", twin_id
                )
            else:
                user_resp = await _run_db(
                    lambda: supabase.table("users")
                    .select("id, email")
                    .eq("tenant_id", twin_resp.data["tenant_id"])
                    .limit(1)
                    .execute()
                )
                user_rows = user_resp.data if isinstance(user_resp.data, list) else []
                if not user_rows:
                    logger.warning(
                        "[MeetingSummary] no user found for recap email tenant=%s",
                        twin_resp.data["tenant_id"],
                    )
                else:
                    user_email = str(user_rows[0].get("email") or "").strip()
                    user_id = str(user_rows[0].get("id") or "").strip()
                    if not user_email or not user_id:
                        logger.warning(
                            "[MeetingSummary] user row missing email/id for recap email tenant=%s",
                            twin_resp.data["tenant_id"],
                        )
                    else:
                        primary_attendee = _extract_primary_attendee(summary, meeting) or "your meeting"
                        subject = f"Recap of your call with {primary_attendee}"
                        cta_path = f"/dashboard/meetings/{meeting_id}"

                        get_graph_outbox().submit(
                            tenant_id=meeting_tenant_id,
                            twin_id=twin_id,
                            operation=GraphOperationType.SEND_LIFECYCLE_EMAIL,
                            idempotency_key=f"meeting_recap_ready:{meeting_id}",
                            payload={
                                "user_id": user_id,
                                "tenant_id": meeting_tenant_id,
                                "twin_id": twin_id,
                                "recipient_email": user_email,
                                "email_type": "meeting_recap_ready",
                                "category": "meeting_recap",
                                "scope_type": "meeting",
                                "scope_id": meeting_id,
                                "period_key": "once",
                                "payload": {
                                    "subject": subject,
                                    "cta_path": cta_path,
                                    "meeting_id": meeting_id,
                                    "meeting_title": meeting.get("title") or "Meeting",
                                    "meeting_start": meeting.get("meeting_start"),
                                    "recap": summary.get("recap"),
                                    "action_items": summary.get("action_items", []),
                                    "commitments": summary.get("commitments", []),
                                    "decisions": summary.get("decisions", []),
                                    "unanswered_questions": summary.get("unanswered_questions", []),
                                },
                            },
                        )
                        logger.info(
                            "[MeetingSummary] recap email enqueued meeting=%s", meeting_id
                        )
        except Exception as exc:
            logger.warning(
                "[MeetingSummary] recap email enqueue failed meeting=%s: %s",
                meeting_id, exc,
            )

        return True

    except Exception:
        logger.exception("[MeetingSummary] failed job=%s meeting=%s", job_id, meeting_id)
        return False


async def _process_enrich_twin_responses(job: dict[str, Any]) -> bool:
    """Post-hoc KB source attribution for meeting twin responses.

    Queries the twin's pgvector KB for each non-deferral response, computes
    confidence as mean(top-k similarity scores), and stores sources as JSONB.
    """
    payload = job.get("payload") or {}
    job_id = str(job.get("id") or "")
    meeting_id = str(payload.get("meeting_id") or "")
    twin_id = str(job.get("twin_id") or "")

    if not meeting_id or not twin_id:
        logger.warning("[EnrichTwin] missing meeting_id or twin_id job=%s", job_id)
        return True

    try:
        rows_resp = await _run_db(
            lambda: supabase.table("meeting_twin_responses")
            .select("id,turn_seq,response_text")
            .eq("meeting_id", meeting_id)
            .eq("is_deferral", False)
            .execute()
        )
        rows = rows_resp.data or []

        if not rows:
            logger.info("[EnrichTwin] no rows to enrich meeting=%s", meeting_id)
            return True

        for row in rows:
            response_text = row.get("response_text") or ""
            if not response_text:
                continue

            hits = await vector_search(query=response_text, twin_id=twin_id, top_k=3)

            if hits:
                confidence = round(sum(h["score"] for h in hits) / len(hits), 4)
                sources = [
                    {"source_id": h["source_id"], "filename": h.get("filename"), "url": h.get("url"), "score": h["score"]}
                    for h in hits
                ]
            else:
                confidence = None
                sources = None

            await _run_db(
                lambda row=row, conf=confidence, srcs=sources: supabase.table("meeting_twin_responses")
                .update({"confidence": conf, "sources": srcs})
                .eq("id", row["id"])
                .execute()
            )

        logger.info("[EnrichTwin] completed meeting=%s rows=%d job=%s", meeting_id, len(rows), job_id)
        return True

    except Exception as exc:
        logger.exception("[EnrichTwin] failed job=%s meeting=%s: %s", job_id, meeting_id, exc)
        return False


def _store_meeting_entities(
    meeting_id: str,
    twin_id: str,
    tenant_id: str,
    entities: dict[str, list[str]],
) -> None:
    """Upsert extracted entities into meeting_entities table."""
    now_iso = _utcnow_iso()
    rows: list[dict[str, Any]] = []
    for entity_type, values in entities.items():
        for value in values:
            if not value:
                continue
            rows.append({
                "meeting_id": meeting_id,
                "twin_id": twin_id,
                "tenant_id": tenant_id,
                "entity_type": entity_type,   # "people", "companies", or "topics"
                "entity_value": value,         # already normalized lowercase
                "created_at": now_iso,
            })

    if not rows:
        return

    try:
        supabase.table("meeting_entities").upsert(
            rows, on_conflict="twin_id,entity_type,entity_value"
        ).execute()
    except Exception as exc:
        # Entity storage is non-critical — log and continue
        logger.warning(
            "[MeetingIndex] failed to store entities meeting=%s: %s",
            meeting_id, exc,
        )


async def _process_index_meeting_transcript(job: dict[str, Any]) -> bool:
    """Chunk meeting transcript into speaker turns, index vectors, and extract entities.

    Payload keys: meeting_id
    Returns True (done) or False (retry).
    """
    payload = job.get("payload") or {}
    job_id = str(job.get("id") or "")
    meeting_id = str(payload.get("meeting_id") or "")

    if not meeting_id:
        logger.warning("[MeetingIndex] missing meeting_id job=%s", job_id)
        return True

    try:
        meeting_resp = await _run_db(
            lambda: supabase.table("meetings")
            .select("id,twin_id,tenant_id,transcript_raw,transcript_text")
            .eq("id", meeting_id)
            .single()
            .execute()
        )
        meeting = meeting_resp.data
        if not meeting:
            logger.warning("[MeetingIndex] meeting not found id=%s", meeting_id)
            return True

        transcript_raw = meeting.get("transcript_raw")
        if not transcript_raw:
            logger.warning("[MeetingIndex] transcript_raw null meeting=%s, will retry", meeting_id)
            return False

        twin_id = str(meeting["twin_id"])
        transcript_text = meeting.get("transcript_text") or ""

        # Lazy import to avoid loading at worker startup
        from services.meeting_indexer import (
            chunk_transcript_by_turns,
            extract_entities,
            index_meeting_chunks,
        )

        # 1. Chunk by speaker turns
        chunks = chunk_transcript_by_turns(transcript_raw)
        if not chunks:
            logger.info("[MeetingIndex] no chunks produced meeting=%s", meeting_id)
            return True

        # 2. Index chunks as vectors
        total = await index_meeting_chunks(
            meeting_id=meeting_id,
            twin_id=twin_id,
            chunks=chunks,
        )

        # 3. Extract and store entities
        entities = await extract_entities(
            transcript_text,
            tenant_id=str(meeting["tenant_id"]),
        )
        _store_meeting_entities(
            meeting_id=meeting_id,
            twin_id=twin_id,
            tenant_id=str(meeting["tenant_id"]),
            entities=entities,
        )

        logger.info(
            "[MeetingIndex] completed meeting=%s chunks=%d vectors=%d entities=%d job=%s",
            meeting_id,
            len(chunks),
            total,
            sum(len(v) for v in entities.values()),
            job_id,
        )

        # Trigger downstream follow-up notification (Phase 28)
        try:
            outbox = get_graph_outbox()
            outbox.submit(
                tenant_id=str(meeting["tenant_id"]),
                twin_id=str(meeting["twin_id"]),
                operation=GraphOperationType.GENERATE_MEETING_FOLLOWUP,
                idempotency_key=f"meeting_followup:{meeting_id}",
                payload={"meeting_id": meeting_id},
                priority=2,
            )
        except Exception as enqueue_exc:
            logger.warning(
                "[MeetingIndex] failed to enqueue followup job meeting=%s: %s",
                meeting_id,
                enqueue_exc,
            )

        return True

    except Exception:
        logger.exception("[MeetingIndex] failed job=%s meeting=%s", job_id, meeting_id)
        return False


async def _handle_prep_meeting_context(job: dict[str, Any]) -> bool:
    """Pre-fetch KB context on bot.joining_call and persist to meetings.context_prep (Phase 30-D)."""
    payload = job.get("payload") or {}
    meeting_id = str(payload.get("meeting_id") or "")
    twin_id = str(payload.get("twin_id") or "")
    if not meeting_id or not twin_id:
        logger.warning("[Worker] PREP_MEETING_CONTEXT missing meeting_id or twin_id job=%s", job.get("id"))
        return False
    try:
        from services.meeting_context_prep import prep_meeting_context
        result = await prep_meeting_context(meeting_id, twin_id)
        logger.info("[Worker] PREP_MEETING_CONTEXT meeting=%s ok=%s", meeting_id, result)
        return result
    except Exception as exc:
        logger.exception("[Worker] PREP_MEETING_CONTEXT failed meeting=%s: %s", meeting_id, exc)
        return False


async def _handle_warm_meeting_cache(job: dict[str, Any]) -> bool:
    """Pre-load KB context before meeting starts (Phase 29)."""
    payload = job.get("payload") or {}
    twin_id = str(payload.get("twin_id") or "")
    meeting_id = str(payload.get("meeting_id") or "")
    if not twin_id or not meeting_id:
        logger.warning("[Worker] WARM_MEETING_CACHE missing twin_id or meeting_id")
        return False
    try:
        from services.meeting_voice_service import warm_meeting_cache
        result = await warm_meeting_cache(twin_id, meeting_id)
        logger.info("[Worker] WARM_MEETING_CACHE completed meeting=%s result=%s", meeting_id, result)
        return result
    except Exception as exc:
        logger.exception("[Worker] WARM_MEETING_CACHE failed meeting=%s: %s", meeting_id, exc)
        return False


async def process_next_graph_outbox_job(worker_id: str) -> bool:
    pending_ids = await _list_pending_job_ids(limit=1)
    if not pending_ids:
        return False

    for job_id in pending_ids:
        job = await _claim_job(job_id=job_id, worker_id=worker_id)
        if not job:
            continue

        # Layer 4: promote claim/complete/fail logs to WARNING so they
        # survive Cloud Run's WARNING root logger filter. Operators need
        # to see job lifecycle for stuck-job triage.
        logger.warning(
            "[GraphOutboxWorker] claimed job=%s operation=%s scope=%s attempt=%s/%s",
            job.get("id"),
            job.get("operation"),
            job.get("scope_id"),
            job.get("attempt_count"),
            job.get("max_attempts"),
        )

        # Layer 1: per-job timeout. Without this, a deadlocked handler
        # (Pinecone hang, ADK infinite loop, wedged Supabase connection)
        # holds the worker slot until process restart -- and the job
        # re-claims on restart, hanging again. asyncio.wait_for cancels
        # the inner coroutine on timeout; we mark the job failed via the
        # normal retry path (timeout is transient by default).
        operation = str(job.get("operation") or "")
        timeout_s = _timeout_for_operation(operation)

        try:
            success = await asyncio.wait_for(_dispatch(job), timeout=timeout_s)
            if success is True:
                await _mark_job_completed(str(job.get("id")))
                logger.warning("[GraphOutboxWorker] completed job=%s operation=%s", job.get("id"), operation)
            elif success is None:
                # Handler already marked the job completed (e.g. stored result in payload)
                logger.warning(
                    "[GraphOutboxWorker] completed job=%s operation=%s (self-marked)",
                    job.get("id"), operation,
                )
            else:
                await _mark_job_failed(job, "operation returned unsuccessful status")
                logger.warning("[GraphOutboxWorker] requeued job=%s operation=%s (unsuccessful)", job.get("id"), operation)
            return True
        except asyncio.TimeoutError as exc:
            # Layer 1: timeout. Treat as transient by default (single slow
            # call may succeed next attempt). After max_attempts the normal
            # path marks it permanently failed.
            err_msg = f"timeout after {timeout_s}s (operation={operation})"
            await _mark_job_failed(job, err_msg, permanent=False)
            logger.warning(
                "[GraphOutboxWorker] TIMEOUT job=%s operation=%s after %ds -- will retry",
                job.get("id"), operation, timeout_s,
            )
            # Side-effect only: visibility into job timeouts via PostHog
            # Error Tracking. Does not alter the retry/backoff contract above.
            ph_capture_exception(
                exc,
                context={
                    "job_id": job.get("id"),
                    "operation": operation,
                    "tenant_id": job.get("tenant_id"),
                    "outcome": "timeout_retry",
                },
            )
            return True
        except Exception as exc:
            # Layer 3: fast-fail permanent errors (malformed payload, 4xx
            # HTTP, etc.). Transient errors take the normal retry path.
            permanent = _is_permanent_error(exc)
            await _mark_job_failed(job, str(exc), permanent=permanent)
            if permanent:
                logger.warning(
                    "[GraphOutboxWorker] PERMANENT FAIL job=%s operation=%s error=%s -- no retry",
                    job.get("id"), operation, exc,
                )
            else:
                logger.exception(
                    "[GraphOutboxWorker] job failed job=%s operation=%s error=%s",
                    job.get("id"), operation, exc,
                )
            # Side-effect only: visibility into job failures via PostHog
            # Error Tracking. Does not alter the retry/permanent-fail
            # contract above (ph_capture_exception swallows its own errors).
            ph_capture_exception(
                exc,
                context={
                    "job_id": job.get("id"),
                    "operation": operation,
                    "tenant_id": job.get("tenant_id"),
                    "outcome": "permanent_fail" if permanent else "transient_retry",
                },
            )
            return True

    return False


async def _process_schedule_meeting_bot(job: dict[str, Any]) -> bool:
    """Create a Recall.ai bot to join a scheduled meeting.

    Payload keys: booking_id, twin_id, meet_link, proposed_start,
                  visitor_name, tenant_id
    Returns True (done) or False (retry).
    """
    payload = job.get("payload") or {}
    job_id = str(job.get("id") or "")
    twin_id = str(payload.get("twin_id") or "")
    meet_link = str(payload.get("meet_link") or "")
    proposed_start = payload.get("proposed_start")
    visitor_name = str(payload.get("visitor_name") or "Unknown")
    tenant_id = str(payload.get("tenant_id") or job.get("tenant_id") or "")

    if not meet_link:
        logger.warning("[MeetingBot] no meet_link for job=%s", job_id)
        return True  # nothing to do, not a retry-worthy failure

    try:
        # Fetch twin owner name — include tenant_id scope per security rules.
        # Heavy imports (gemini_live + recall_service) are now lifted to module-top
        # to avoid the per-job cold-start that previously hung worker dispatch.
        twin_resp = (
            supabase.table("twins")
            .select("name, settings")
            .eq("id", twin_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        owner_name = twin_resp.data.get("name", "User") if twin_resp.data else "User"
        twin_settings = dict((twin_resp.data or {}).get("settings") or {})
        bot_name = format_bot_name(owner_name)
        # NOTE: The worker has no native_audio path (only the HTTP join-now route does).
        # MEETING_NATIVE_AUDIO_ENABLED is read here only to preserve gate symmetry with
        # the router. If MEETING_NATIVE_AUDIO_ENABLED=true on the worker, the short-circuit
        # skips and the gemini→voice cascade runs — never native_audio.
        native_audio_enabled = os.getenv("MEETING_NATIVE_AUDIO_ENABLED", "false").lower() == "true"
        gemini_enabled = os.getenv("MEETING_GEMINI_LIVE_ENABLED", "false").lower() == "true"

        # Two callers for this handler:
        #   1. Booking flow (calendar_booking.py):
        #      no existing meeting row — we INSERT one.
        #   2. Calendar sync + toggle-attendance (meeting_voice.py):
        #      row already exists — we UPDATE the existing meeting_id.
        # The deciding signal is `payload.meeting_id`.
        existing_meeting_id = payload.get("meeting_id")
        if existing_meeting_id:
            meeting_id = str(existing_meeting_id)
            # Flip attendance + mode on the existing row. Idempotent — re-runs
            # leave the row in the same state. mode='note_taker' is the
            # canonical "bot attends to transcribe, doesn't speak" mode in
            # the schema CHECK constraint (see 20260505_phase30 migration).
            supabase.table("meetings").update({
                "twin_attends": True,
                "mode": "note_taker",
            }).eq("id", meeting_id).eq("twin_id", twin_id).eq("tenant_id", tenant_id).execute()
        else:
            # No existing meeting_id (booking flow). Resolve-or-create by ical_uid so
            # a booking and its calendar-synced twin converge on ONE row: the booking
            # created a real Google Calendar event whose iCalUID Recall later syncs
            # back. Without this the booking insert + calendar sync make two rows for
            # the same meeting (the duplicate-meeting bug).
            ical_uid = payload.get("ical_uid") or None
            provider_event_id = payload.get("provider_event_id") or None
            existing_row = None
            if ical_uid:
                lookup = (
                    supabase.table("meetings")
                    .select("id")
                    .eq("twin_id", twin_id)
                    .eq("tenant_id", tenant_id)
                    .eq("ical_uid", ical_uid)
                    .limit(1)
                    .execute()
                )
                existing_row = (lookup.data or [None])[0]
            if existing_row:
                # Calendar sync already materialized this event — attach the bot to it.
                meeting_id = str(existing_row["id"])
                supabase.table("meetings").update({
                    "twin_attends": True,
                    "mode": "note_taker",
                    "booking_id": payload.get("booking_id"),
                }).eq("id", meeting_id).eq("twin_id", twin_id).eq("tenant_id", tenant_id).execute()
            else:
                # Create meeting row first so we have an ID to pass to the voice bot's
                # voice-agent.html (needed for the per-meeting WebSocket routing).
                # Stamp ical_uid/provider_event_id so a LATER calendar sync of the same
                # event finds this row and updates it instead of inserting a duplicate.
                insert_payload = {
                    "twin_id": twin_id,
                    "tenant_id": tenant_id,
                    "booking_id": payload.get("booking_id"),
                    "meet_link": meet_link,
                    "title": f"Meeting with {visitor_name}",
                    "status": "scheduled",
                    "twin_attends": True,
                    "mode": "note_taker",
                    "meeting_start": proposed_start,
                }
                if ical_uid:
                    insert_payload["ical_uid"] = ical_uid
                if provider_event_id:
                    insert_payload["provider_event_id"] = provider_event_id
                insert_resp = supabase.table("meetings").insert(insert_payload).execute()
                if not insert_resp.data:
                    logger.error("[MeetingBot] failed to insert meetings row job=%s", job_id)
                    return False
                meeting_id = insert_resp.data[0]["id"]

        metadata = {
            "twin_id": twin_id,
            "meeting_id": meeting_id,
            "booking_id": str(payload.get("booking_id") or ""),
            "tenant_id": tenant_id,
        }

        # Default to transcript-only when neither MEETING_NATIVE_AUDIO_ENABLED nor
        # MEETING_GEMINI_LIVE_ENABLED is set. The recap engine (Task P1.4.A) consumes
        # the transcript; the bot does not speak. Task 0.1 of meeting-loop-graduation.
        if not native_audio_enabled and not gemini_enabled:
            try:
                bot_result = await create_bot(
                    meeting_url=meet_link,
                    bot_name=bot_name,
                    metadata=metadata,
                    join_at=proposed_start,
                )
                logger.info("[MeetingBot] transcript bot created meeting=%s", meeting_id)
            except Exception:
                logger.exception(
                    "[MeetingBot] transcript bot failed meeting=%s job=%s",
                    meeting_id,
                    job_id,
                )
                return False
        else:
            # Existing cascade preserved verbatim for staging (flag-enabled paths):
            # prefer gemini-live when enabled, fall back to voice bot, then transcript.
            try:
                if gemini_enabled:
                    api_key_token = issue_meeting_token(twin_id, meeting_id)
                    voice_name = twin_settings.get("gemini_voice") or "Kore"
                    try:
                        bot_result = await create_gemini_live_bot(
                            meeting_url=meet_link,
                            bot_name=bot_name,
                            twin_id=twin_id,
                            meeting_id=meeting_id,
                            voice_name=voice_name,
                            api_key_token=api_key_token,
                            metadata=metadata,
                            join_at=proposed_start,
                        )
                        logger.info(
                            "[MeetingBot] gemini-live bot created meeting=%s voice=%s",
                            meeting_id,
                            voice_name,
                        )
                    except Exception as gemini_exc:
                        logger.warning(
                            "[MeetingBot] gemini-live bot failed, falling back to voice bot: %s",
                            gemini_exc,
                        )
                        bot_result = await create_voice_bot(
                            meeting_url=meet_link,
                            bot_name=bot_name,
                            twin_id=twin_id,
                            meeting_id=meeting_id,
                            metadata=metadata,
                            join_at=proposed_start,
                        )
                        logger.info("[MeetingBot] voice bot created meeting=%s", meeting_id)
                else:
                    bot_result = await create_voice_bot(
                        meeting_url=meet_link,
                        bot_name=bot_name,
                        twin_id=twin_id,
                        meeting_id=meeting_id,
                        metadata=metadata,
                        join_at=proposed_start,
                    )
                    logger.info("[MeetingBot] voice bot created meeting=%s", meeting_id)
            except Exception as voice_exc:
                logger.warning(
                    "[MeetingBot] voice bot failed, falling back to transcript bot: %s",
                    voice_exc,
                )
                bot_result = await create_bot(
                    meeting_url=meet_link,
                    bot_name=bot_name,
                    metadata=metadata,
                    join_at=proposed_start,
                )
                logger.info("[MeetingBot] transcript fallback bot created meeting=%s", meeting_id)

        recall_bot_id = bot_result.get("id", "")

        # Stamp bot id on the meeting row -- dual-scope by (id, tenant_id).
        # Audit 2026-05-31 second pass: this was the most dangerous unscoped
        # write because it both sets recall_bot_id (downstream linkage) and
        # is reachable from a worker payload that an attacker could craft if
        # any future code path lets payload.meeting_id be cross-tenant.
        supabase.table("meetings").update({
            "recall_bot_id": recall_bot_id,
        }).eq("id", meeting_id).eq("tenant_id", tenant_id).execute()

        logger.info(
            "[MeetingBot] bot scheduled bot_id=%s twin=%s job=%s",
            recall_bot_id, twin_id, job_id,
        )
        return True

    except Exception:
        logger.exception("[MeetingBot] failed to schedule bot job=%s", job_id)
        return False  # triggers retry with backoff


async def _process_meeting_transcript(job: dict[str, Any]) -> bool:
    """Fetch diarized transcript from Recall.ai and store in meetings table.

    Payload keys: bot_id, meeting_id
    Returns True (done) or False (retry).
    """
    payload = job.get("payload") or {}
    job_id = str(job.get("id") or "")
    bot_id = str(payload.get("bot_id") or "")
    meeting_id = str(payload.get("meeting_id") or "")

    if not bot_id or not meeting_id:
        logger.warning(
            "[MeetingTranscript] missing bot_id or meeting_id job=%s", job_id
        )
        return True  # nothing to retry

    try:
        from datetime import timezone

        # Native audio path: transcript was already flushed to DB by teardown_session
        # before this job ran. Detect this by checking if transcript_text is populated.
        # If so, skip the Recall API fetch (which would return empty for native audio
        # bots that have no STT provider) and go straight to summary generation.
        existing_resp = await _run_db(
            lambda: supabase.table("meetings")
            .select("transcript_text,transcript_raw,tenant_id,twin_id,status")
            .eq("id", meeting_id)
            .single()
            .execute()
        )
        existing = existing_resp.data or {}

        # Capture tenant_id BEFORE any UPDATE so subsequent writes are
        # dual-scoped by (id, tenant_id). Audit 2026-05-31 second pass.
        meeting_tenant_id = str(existing.get("tenant_id") or "")
        if not meeting_tenant_id:
            logger.warning(
                "[MeetingTranscript] missing tenant_id on meeting=%s job=%s — refusing UPDATE",
                meeting_id, job_id,
            )
            return True

        if existing.get("transcript_text"):
            logger.warning(
                "[MeetingTranscript] native audio transcript already in DB meeting=%s tenant=%s — skipping Recall fetch",
                meeting_id, meeting_tenant_id,
            )
            # Mark completed and enqueue summary
            now_iso = datetime.now(timezone.utc).isoformat()
            await _run_db(
                lambda: supabase.table("meetings").update({
                    "status": "completed",
                    "updated_at": now_iso,
                }).eq("id", meeting_id).eq("tenant_id", meeting_tenant_id).execute()
            )
        else:
            # Recall STT path: fetch diarized transcript from Recall's API
            from services.recall_service import get_bot_transcript
            transcript_entries = await get_bot_transcript(bot_id)

            if not transcript_entries:
                # Empty Recall response is expected for native audio bots (no STT
                # provider configured — Gemini handles transcription). If teardown_session
                # failed before writing transcript_text, writing [] here would permanently
                # wipe any ADK transcript that arrives later. Skip the write and proceed
                # to summary enqueue — the summary worker will handle an empty transcript.
                logger.warning(
                    "[MeetingTranscript] empty Recall transcript bot=%s meeting=%s — skipping overwrite",
                    bot_id, meeting_id,
                )
            else:
                lines: list[str] = []
                for entry in transcript_entries:
                    participant = entry.get("participant") or {}
                    speaker = participant.get("name", "Unknown")
                    words = entry.get("words", [])
                    text = (
                        " ".join(w.get("text", "") for w in words)
                        if isinstance(words, list)
                        else str(words)
                    )
                    if text.strip():
                        lines.append(f"{speaker}: {text.strip()}")
                transcript_text = "\n".join(lines)

                now_iso = datetime.now(timezone.utc).isoformat()
                # Dual-scope by (id, tenant_id) -- see comment above on the
                # native-audio branch. Audit 2026-05-31 second pass.
                await _run_db(
                    lambda: supabase.table("meetings").update({
                        "transcript_raw": transcript_entries,
                        "transcript_text": transcript_text,
                        "status": "completed",
                        "updated_at": now_iso,
                    }).eq("id", meeting_id).eq("tenant_id", meeting_tenant_id).execute()
                )

                logger.info(
                    "[MeetingTranscript] stored Recall transcript meeting=%s bot=%s lines=%d job=%s",
                    meeting_id, bot_id, len(lines), job_id,
                )

        # Trigger downstream summary generation for both paths
        try:
            m = existing or {}
            tenant_id = m.get("tenant_id") or ""
            twin_id_val = m.get("twin_id") or ""
            if not tenant_id or not twin_id_val:
                # Re-fetch if we didn't have it
                refetch = await _run_db(
                    lambda: supabase.table("meetings")
                    .select("tenant_id,twin_id")
                    .eq("id", meeting_id)
                    .single()
                    .execute()
                )
                if refetch.data:
                    tenant_id = str(refetch.data["tenant_id"])
                    twin_id_val = str(refetch.data["twin_id"])

            if tenant_id and twin_id_val:
                outbox = get_graph_outbox()
                outbox.submit(
                    tenant_id=str(tenant_id),
                    twin_id=str(twin_id_val),
                    operation=GraphOperationType.GENERATE_MEETING_SUMMARY,
                    idempotency_key=f"meeting_summary:{meeting_id}",
                    payload={"meeting_id": meeting_id},
                    priority=4,
                )
                logger.info(
                    "[MeetingTranscript] enqueued summary job meeting=%s", meeting_id
                )
                outbox.submit(
                    tenant_id=str(tenant_id),
                    twin_id=str(twin_id_val),
                    operation=GraphOperationType.ENRICH_TWIN_RESPONSES,
                    idempotency_key=f"enrich_twin_responses:{meeting_id}",
                    payload={"meeting_id": meeting_id},
                    priority=4,
                )
                logger.info("[MeetingTranscript] enqueued enrich job meeting=%s", meeting_id)
        except Exception as enqueue_exc:
            logger.warning(
                "[MeetingTranscript] failed to enqueue summary job meeting=%s: %s",
                meeting_id, enqueue_exc,
            )

        return True

    except Exception:
        logger.exception("[MeetingTranscript] failed job=%s", job_id)
        return False  # retry


def _safe_https_url(url: Any) -> str | None:
    """Reject non-https values before persisting to media-URL columns.

    Defense-in-depth: even though the URLs originate from Recall's API over
    TLS, a compromised account could in theory inject a javascript: URI or
    HTTP fallback that the desktop UI later opens. We accept only https:.
    """
    if isinstance(url, str) and url.startswith("https://"):
        return url
    if url:
        logger.warning(
            "[DesktopSDKRecording] rejected non-https media url scheme=%r",
            str(url).split(":", 1)[0] if ":" in str(url) else "<none>",
        )
    return None


def _flatten_transcript_to_text(entries: list[dict[str, Any]]) -> str:
    """Flatten Recall diarized transcript JSON into speaker-prefixed text."""
    lines: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        participant = entry.get("participant") or {}
        speaker = str(participant.get("name") or entry.get("speaker") or "Speaker")
        words = entry.get("words")
        if isinstance(words, list):
            text = " ".join(
                str(word.get("text") or "")
                for word in words
                if isinstance(word, dict)
            )
        else:
            text = str(entry.get("text") or words or "")
        if text.strip():
            lines.append(f"{speaker}: {text.strip()}")
    return "\n".join(lines)


async def _process_desktop_sdk_recording(job: dict[str, Any]) -> bool:
    """Fetch Recall.ai Recording metadata for a Desktop SDK upload and update
    the matching `meetings` row.

    Fires from the /v2/meetings/webhook/recall endpoint on `sdk_upload.complete`.

    Payload keys: recall_recording_id, meeting_id (optional fallback), tenant_id
    Returns True (done) or False (retry).
    """
    from datetime import datetime, timezone

    payload = job.get("payload") or {}
    job_id = str(job.get("id") or "")
    recall_recording_id = str(payload.get("recall_recording_id") or "")
    meeting_id_hint = str(payload.get("meeting_id") or "")
    tenant_id = str(payload.get("tenant_id") or job.get("tenant_id") or "")

    if not recall_recording_id:
        logger.warning(
            "[DesktopSDKRecording] missing recall_recording_id job=%s", job_id,
        )
        return True  # nothing to retry

    try:
        from services.recall_service import download_transcript_json, get_recording

        recording = await get_recording(recall_recording_id)

        media = recording.get("media_shortcuts") or {}
        video = (media.get("video_mixed") or {}).get("data") or {}
        transcript = (media.get("transcript") or {}).get("data") or {}
        events = (media.get("participant_events") or {}).get("data") or {}

        video_url = _safe_https_url(video.get("download_url"))
        transcript_url = _safe_https_url(transcript.get("download_url"))
        speaker_timeline_url = _safe_https_url(events.get("speaker_timeline_download_url"))

        started_at = recording.get("started_at")
        completed_at = recording.get("completed_at")
        duration_seconds: int | None = None
        if started_at and completed_at:
            try:
                start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                duration_seconds = int((end_dt - start_dt).total_seconds())
            except Exception:
                # Skipping duration on parse failure shouldn't be silent — it
                # means downstream UI can't show recording length.
                logger.warning(
                    "[DesktopSDKRecording] could not parse timestamps started=%s completed=%s",
                    started_at, completed_at,
                )

        update_payload = {
            "status": "completed",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if video_url:
            update_payload["video_url"] = video_url
        if transcript_url:
            update_payload["transcript_url"] = transcript_url
        if speaker_timeline_url:
            update_payload["speaker_timeline_url"] = speaker_timeline_url
        if duration_seconds is not None:
            update_payload["duration_seconds"] = duration_seconds
        if completed_at:
            update_payload["meeting_end"] = completed_at

        transcript_entries: list[dict[str, Any]] = []
        if transcript_url:
            try:
                transcript_entries = await download_transcript_json(transcript_url)
                transcript_text = _flatten_transcript_to_text(transcript_entries)
                if transcript_entries:
                    update_payload["transcript_raw"] = transcript_entries
                    update_payload["transcript_text"] = transcript_text
            except Exception:
                logger.exception(
                    "[DesktopSDKRecording] failed to download transcript recording=%s job=%s",
                    recall_recording_id,
                    job_id,
                )

        # Match by recall_recording_id (canonical) with a meeting_id fallback in
        # case the webhook arrived before the row was persisted on the upload path.
        # Both paths ALSO filter by tenant_id when known (defense-in-depth per
        # project memory feedback_tenant_scope_mutations.md).
        def _build_primary() -> Any:
            q = supabase.table("meetings").update(update_payload).eq(
                "recall_recording_id", recall_recording_id,
            )
            if tenant_id:
                q = q.eq("tenant_id", tenant_id)
            return q.execute()

        resp = await _run_db(_build_primary)
        rows = getattr(resp, "data", None) or []

        if not rows and meeting_id_hint:
            logger.info(
                "[DesktopSDKRecording] no row by recall_recording_id=%s, falling back to meeting_id=%s",
                recall_recording_id, meeting_id_hint,
            )

            def _build_fallback() -> Any:
                q = supabase.table("meetings").update(update_payload).eq(
                    "id", meeting_id_hint,
                )
                if tenant_id:
                    q = q.eq("tenant_id", tenant_id)
                return q.execute()

            resp = await _run_db(_build_fallback)
            rows = getattr(resp, "data", None) or []

        if not rows:
            # Deliberate: mark the job done rather than retry. The row may have
            # been soft-deleted by the user between webhook delivery and worker
            # run, or never persisted (e.g. POST /sdk-upload failed). Retrying
            # forever wouldn't recover those cases; we log a warning so an
            # operator can investigate.
            logger.warning(
                "[DesktopSDKRecording] no meeting row matched recording=%s",
                recall_recording_id,
            )
            return True

        logger.info(
            "[DesktopSDKRecording] updated meeting recording=%s duration=%s video=%s transcript=%s",
            recall_recording_id,
            duration_seconds,
            bool(video_url),
            bool(transcript_url),
        )

        # Extract meeting identity once — needed by both transcript and contact jobs.
        _meeting_row = rows[0] if rows else {}
        meeting_id = str(_meeting_row.get("id") or meeting_id_hint or "")
        tenant_for_enqueue = str(_meeting_row.get("tenant_id") or tenant_id or "")
        twin_for_enqueue = str(_meeting_row.get("twin_id") or "")

        if transcript_entries:
            # Skip-if-already-populated guard. F6.5 (review fix): the UPDATE
            # response above does NOT reliably carry recap_extras_json (it
            # wasn't in update_payload and supabase-py's RETURNING shape is
            # not contractually guaranteed across versions). Do an explicit
            # SELECT to fetch the persisted recap_extras_json before
            # deciding to skip. Without this, the guard could silently fail
            # closed and every retry overwrites user edits.
            existing_extras = None
            if meeting_id:
                try:
                    extras_resp = await _run_db(
                        lambda: supabase.table("meetings")
                        .select("recap_extras_json")
                        .eq("id", meeting_id)
                        .maybe_single()
                        .execute()
                    )
                    existing_extras = (getattr(extras_resp, "data", None) or {}).get("recap_extras_json")
                except Exception:
                    logger.exception(
                        "[DesktopSDKRecording] failed to read recap_extras_json for skip guard meeting=%s",
                        meeting_id,
                    )
                    existing_extras = None
            if existing_extras:
                logger.info(
                    "[DesktopSDKRecording] recap_extras_json already populated meeting=%s — skipping extraction",
                    meeting_id,
                )
            else:
                try:
                    from services.recap_extras_service import extract_recap_extras

                    extras = await extract_recap_extras(
                        str(update_payload.get("transcript_text") or ""),
                        title=_meeting_row.get("title"),
                        tenant_id=tenant_for_enqueue or None,
                    )
                    if extras and meeting_id:
                        # Dual-scope by (id, tenant_id). tenant_for_enqueue is
                        # the authoritative tenant resolved earlier in this
                        # handler. Audit 2026-05-31 second pass.
                        _recap_tenant = tenant_for_enqueue
                        await _run_db(
                            lambda: supabase.table("meetings").update({
                                "recap_extras_json": extras,
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            }).eq("id", meeting_id).eq("tenant_id", _recap_tenant).execute()
                        )
                    # Materialize structured meeting_commitments rows from extras.
                    # Owner lookup mirrors _process_link_meeting_contacts (~line 574).
                    if extras:
                        from services.commitment_extractor import structured_commitments_from_extras

                        _commit_owner_name = ""
                        try:
                            _u_resp = await _run_db(
                                lambda: supabase.table("users")
                                .select("full_name, email")
                                .eq("tenant_id", tenant_for_enqueue)
                                .limit(1)
                                .execute()
                            )
                            _u_row = (getattr(_u_resp, "data", None) or [None])[0] or {}
                            _commit_owner_name = (_u_row.get("full_name") or "").strip()
                            if not _commit_owner_name and _u_row.get("email"):
                                _commit_owner_name = _u_row["email"].split("@")[0]
                        except Exception:
                            logger.info(
                                "[DesktopSDKRecording] owner-name lookup for commitments failed meeting=%s; continuing",
                                meeting_id,
                            )

                        structured = structured_commitments_from_extras(
                            extras, owner_name=_commit_owner_name
                        )
                        if structured and meeting_id:
                            _commit_rows = [
                                {
                                    "tenant_id": tenant_for_enqueue,
                                    "twin_id": twin_for_enqueue,
                                    "meeting_id": meeting_id,
                                    "direction": c["direction"],
                                    "text": c["text"],
                                    "assignee_name": c["assignee_name"],
                                    "due_at": c["due_at"],
                                    "content_hash": c["content_hash"],
                                    "source": "recap_extras",
                                }
                                for c in structured
                            ]
                            try:
                                await _run_db(
                                    lambda: supabase.table("meeting_commitments")
                                    .upsert(
                                        _commit_rows,
                                        on_conflict="meeting_id,content_hash,source",
                                        ignore_duplicates=True,
                                    )
                                    .execute()
                                )
                                logger.info(
                                    "[DesktopSDKRecording] upserted %d commitment(s) meeting=%s",
                                    len(_commit_rows),
                                    meeting_id,
                                )
                            except Exception:
                                logger.exception(
                                    "[DesktopSDKRecording] commitment upsert failed meeting_id=%s",
                                    meeting_id,
                                )
                        # Enqueue memory candidate extraction after commitments are upserted.
                        if meeting_id and tenant_for_enqueue and twin_for_enqueue:
                            try:
                                outbox = get_graph_outbox()
                                outbox.submit(
                                    tenant_id=tenant_for_enqueue,
                                    twin_id=twin_for_enqueue,
                                    operation=GraphOperationType.EXTRACT_MEMORY_CANDIDATES,
                                    idempotency_key=f"extract_memory_candidates:{meeting_id}",
                                    payload={
                                        "tenant_id": tenant_for_enqueue,
                                        "twin_id": twin_for_enqueue,
                                        "meeting_id": meeting_id,
                                    },
                                )
                                logger.info(
                                    "[DesktopSDKRecording] enqueued extract_memory_candidates meeting=%s",
                                    meeting_id,
                                )
                            except Exception:
                                logger.exception(
                                    "[DesktopSDKRecording] failed to enqueue extract_memory_candidates meeting=%s",
                                    meeting_id,
                                )
                except Exception:
                    logger.exception(
                        "[DesktopSDKRecording] recap extras extraction failed recording=%s meeting=%s",
                        recall_recording_id,
                        meeting_id,
                    )
            if meeting_id and tenant_for_enqueue:
                try:
                    outbox = get_graph_outbox()
                    outbox.submit(
                        tenant_id=tenant_for_enqueue,
                        twin_id=twin_for_enqueue,
                        operation=GraphOperationType.GENERATE_MEETING_SUMMARY,
                        idempotency_key=f"meeting_summary:{meeting_id}",
                        payload={"meeting_id": meeting_id},
                        priority=4,
                    )
                    logger.info(
                        "[DesktopSDKRecording] enqueued summary job meeting=%s",
                        meeting_id,
                    )
                except Exception as enqueue_exc:
                    logger.warning(
                        "[DesktopSDKRecording] failed to enqueue summary meeting=%s: %s",
                        meeting_id,
                        enqueue_exc,
                    )

        # Wire: enqueue identity linking for this meeting's participants.
        # Best-effort — missing twin_id (ad-hoc desktop_sdk recordings without a
        # twin owner) means we can't tenant-scope contacts, so skip + log.
        if meeting_id and tenant_for_enqueue and twin_for_enqueue:
            try:
                outbox = get_graph_outbox()
                outbox.submit(
                    tenant_id=tenant_for_enqueue,
                    twin_id=twin_for_enqueue,
                    operation=GraphOperationType.LINK_MEETING_CONTACTS,
                    idempotency_key=f"link_meeting_contacts:{meeting_id}",
                    payload={
                        "meeting_id": meeting_id,
                        "tenant_id": tenant_for_enqueue,
                        "twin_id": twin_for_enqueue,
                    },
                )
                logger.info(
                    "[DesktopSDKRecording] enqueued link_meeting_contacts meeting=%s",
                    meeting_id,
                )
            except Exception:
                logger.exception(
                    "[DesktopSDKRecording] failed to enqueue link_meeting_contacts meeting=%s",
                    meeting_id,
                )
        else:
            logger.info(
                "[DesktopSDKRecording] skip link_meeting_contacts: meeting_id=%s tenant=%s twin=%s",
                meeting_id, tenant_for_enqueue, twin_for_enqueue,
            )
        return True

    except Exception:
        logger.exception("[DesktopSDKRecording] failed job=%s", job_id)
        return False  # retry


async def _process_generate_meeting_briefing(job: dict[str, Any]) -> bool:
    """Generate and send pre-meeting briefing email.

    Payload keys: meeting_id
    Returns True (done/skipped) or False (retry on unexpected failure).
    """
    payload = job.get("payload") or {}
    job_id = str(job.get("id") or "")
    meeting_id = str(payload.get("meeting_id") or "")
    twin_id = str(job.get("twin_id") or "")
    tenant_id = str(job.get("tenant_id") or "")

    if not meeting_id or not twin_id:
        logger.warning(
            "[MeetingBriefing] missing meeting_id or twin_id job=%s", job_id
        )
        return True

    try:
        from adk_core.services.persona_core.brief import generate_brief
        from services.email_service import send_email
        from services.notification_service import (
            _get_user_email,
            build_briefing_email_from_brief_json,
            claim_notification_slot,
            load_notification_prefs,
            release_notification_slot,
        )

        # Guard: check user preferences
        prefs = await asyncio.to_thread(load_notification_prefs, twin_id)
        if not prefs.get("pre_meeting"):
            logger.info(
                "[MeetingBriefing] disabled by prefs twin=%s", twin_id
            )
            return True

        # Guard: atomic dedup — returns False if already sent
        if not await asyncio.to_thread(
            claim_notification_slot, twin_id, meeting_id, "pre_meeting_briefing", tenant_id
        ):
            logger.info(
                "[MeetingBriefing] already sent twin=%s meeting=%s",
                twin_id,
                meeting_id,
            )
            return True

        # Load meeting record — CRITICAL: scope to twin_id + tenant_id.
        # Without these filters, a poisoned job payload referencing another
        # tenant's meeting_id would load that meeting and email its content
        # to the job's owner. The brief_json UPDATE below also filters by
        # both, but the SELECT must be scoped at the source to prevent
        # leaking even read-only meeting data into a brief we then email.
        meeting_resp = await _run_db(
            lambda: supabase.table("meetings")
            .select("*")
            .eq("id", meeting_id)
            .eq("twin_id", twin_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        meeting = meeting_resp.data if meeting_resp else None
        if not meeting:
            logger.warning(
                "[MeetingBriefing] meeting not found or out of scope "
                "id=%s twin=%s tenant=%s",
                meeting_id, twin_id, tenant_id,
            )
            # Mark as skipped (NOT release) — the meeting either doesn't
            # exist or is out of our tenant scope, so retrying gains
            # nothing and would loop forever per cron tick. Skipped status
            # also serves as audit trail for "we got a job for a meeting
            # we couldn't access."
            await _run_db(
                lambda: supabase.table("meeting_notifications").update(
                    {"status": "skipped"}
                ).eq("twin_id", twin_id).eq("meeting_id", meeting_id).eq(
                    "tenant_id", tenant_id
                ).eq("notification_type", "pre_meeting_briefing").execute()
            )
            return True

        # Resolve recipient email up front. Two reasons:
        #   1. Bail early if missing — avoids wasting Gemini call + DB
        #      write on a brief we can't deliver.
        #   2. Pass into generate_brief so the user is excluded from
        #      their own participant_insights[] for invited meetings.
        user_email = await asyncio.to_thread(_get_user_email, tenant_id)
        if not user_email:
            logger.warning(
                "[MeetingBriefing] no user email tenant=%s — releasing slot for retry",
                tenant_id,
            )
            await asyncio.to_thread(
                release_notification_slot,
                twin_id, meeting_id, "pre_meeting_briefing", tenant_id,
            )
            return True

        # Build the structured brief via the canonical engine.
        # Persist brief_json so the lazy GET on the page reuses it instead of
        # re-generating. Both paths now share one source of truth (W9a).
        try:
            brief_json = await generate_brief(
                twin_id=twin_id,
                meeting_id=meeting_id,
                meeting=meeting,
                self_email=user_email,
                tenant_id=tenant_id,
            )
        except Exception as exc:
            logger.exception(
                "[MeetingBriefing] generate_brief failed meeting=%s: %s",
                meeting_id, exc,
            )
            # Release the slot so the retry can attempt generation again
            # instead of finding the slot taken and short-circuiting to
            # "already sent" (which leaves the user with no email).
            await asyncio.to_thread(
                release_notification_slot,
                twin_id, meeting_id, "pre_meeting_briefing", tenant_id,
            )
            return False

        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            await _run_db(
                lambda: supabase.table("meetings").update({
                    "brief_json": brief_json,
                    "brief_generated_at": now_iso,
                })
                .eq("id", meeting_id)
                .eq("twin_id", twin_id)
                .eq("tenant_id", tenant_id)
                .execute()
            )
        except Exception as exc:
            # Persist failure shouldn't block the email — the brief is still
            # valid in memory; user's page will re-generate on next view.
            logger.warning(
                "[MeetingBriefing] brief_json persist failed meeting=%s: %s",
                meeting_id, exc,
            )

        # Format email from the structured brief — no extra LLM call.
        result = await build_briefing_email_from_brief_json(
            brief_json=brief_json, meeting=meeting, twin_id=twin_id
        )
        if not result:
            # Brief too sparse to email — mark notification as skipped
            # (keep the row so we don't re-attempt; user can still view the
            # brief on the meeting page).
            await _run_db(
                lambda: supabase.table("meeting_notifications").update(
                    {"status": "skipped"}
                ).eq("twin_id", twin_id).eq("meeting_id", meeting_id).eq(
                    "tenant_id", tenant_id
                ).eq("notification_type", "pre_meeting_briefing").execute()
            )
            return True

        # Send email — release slot on failure so retries can re-attempt
        # rather than finding the row already "sending" and short-circuiting.
        try:
            msg_id = await send_email(
                to=user_email,
                subject=result["subject"],
                html=result["html"],
            )
        except Exception as exc:
            logger.exception(
                "[MeetingBriefing] send_email failed meeting=%s: %s",
                meeting_id, exc,
            )
            await asyncio.to_thread(
                release_notification_slot,
                twin_id, meeting_id, "pre_meeting_briefing", tenant_id,
            )
            return False

        # Update notification record to sent
        await _run_db(
            lambda: supabase.table("meeting_notifications").update(
                {
                    "status": "sent",
                    "resend_message_id": msg_id,
                    "sent_at": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%S"
                    ),
                }
            ).eq("twin_id", twin_id).eq("meeting_id", meeting_id).eq(
                "notification_type", "pre_meeting_briefing"
            ).execute()
        )

        logger.info(
            "[MeetingBriefing] sent meeting=%s twin=%s job=%s",
            meeting_id,
            twin_id,
            job_id,
        )
        return True

    except Exception:
        logger.exception(
            "[MeetingBriefing] failed job=%s meeting=%s", job_id, meeting_id
        )
        return False


async def _process_generate_meeting_followup(job: dict[str, Any]) -> bool:
    """Generate and send post-meeting follow-up email in the twin's persona voice.

    Reads summary_json from the meetings table, generates a follow-up draft
    via Gemini, and sends it to the twin owner.

    Payload keys: meeting_id
    Returns True (done/skipped) or False (retry on unexpected failure).
    """
    payload = job.get("payload") or {}
    job_id = str(job.get("id") or "")
    meeting_id = str(payload.get("meeting_id") or "")
    twin_id = str(job.get("twin_id") or "")
    tenant_id = str(job.get("tenant_id") or "")

    if not meeting_id or not twin_id:
        logger.warning(
            "[MeetingFollowup] missing meeting_id or twin_id job=%s", job_id
        )
        return True

    try:
        from services.email_service import send_email
        from services.notification_service import (
            _get_user_email,
            claim_notification_slot,
            generate_followup,
            load_notification_prefs,
        )

        # Guard: check user preferences
        prefs = await asyncio.to_thread(load_notification_prefs, twin_id)
        if not prefs.get("post_meeting"):
            logger.info(
                "[MeetingFollowup] disabled by prefs twin=%s", twin_id
            )
            return True

        # Guard: atomic dedup — returns False if already sent
        if not await asyncio.to_thread(
            claim_notification_slot, twin_id, meeting_id, "post_meeting_followup", tenant_id
        ):
            logger.info(
                "[MeetingFollowup] already sent twin=%s meeting=%s",
                twin_id,
                meeting_id,
            )
            return True

        # Load meeting record with summary_json
        meeting_resp = await _run_db(
            lambda: supabase.table("meetings")
            .select("*")
            .eq("id", meeting_id)
            .single()
            .execute()
        )
        meeting = meeting_resp.data
        if not meeting:
            logger.warning(
                "[MeetingFollowup] meeting not found id=%s", meeting_id
            )
            return True

        # Generate follow-up content
        result = await generate_followup(meeting=meeting, twin_id=twin_id)
        if not result:
            # No summary available — mark notification as skipped
            await _run_db(
                lambda: supabase.table("meeting_notifications").update(
                    {"status": "skipped"}
                ).eq("twin_id", twin_id).eq("meeting_id", meeting_id).eq(
                    "notification_type", "post_meeting_followup"
                ).execute()
            )
            return True

        # Resolve recipient email
        user_email = await asyncio.to_thread(_get_user_email, tenant_id)
        if not user_email:
            logger.warning(
                "[MeetingFollowup] no user email tenant=%s", tenant_id
            )
            return True

        # Send email
        msg_id = await send_email(
            to=user_email,
            subject=result["subject"],
            html=result["html"],
        )

        # Update notification record to sent
        await _run_db(
            lambda: supabase.table("meeting_notifications").update(
                {
                    "status": "sent",
                    "resend_message_id": msg_id,
                    "sent_at": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%S"
                    ),
                }
            ).eq("twin_id", twin_id).eq("meeting_id", meeting_id).eq(
                "notification_type", "post_meeting_followup"
            ).execute()
        )

        logger.info(
            "[MeetingFollowup] sent meeting=%s twin=%s job=%s",
            meeting_id,
            twin_id,
            job_id,
        )
        return True

    except Exception:
        logger.exception(
            "[MeetingFollowup] failed job=%s meeting=%s", job_id, meeting_id
        )
        return False


async def _process_generate_weekly_digest(job: dict[str, Any]) -> bool:
    """Generate and send weekly digest email for a twin.

    Queries completed meetings from the past 7 days, aggregates summaries,
    and sends a digest email in the twin's persona voice.

    CRITICAL ordering: claim_notification_slot is called BEFORE generate_digest
    to prevent duplicate Gemini API calls in concurrent worker deployments.

    Payload keys: twin_id
    Returns True (done/skipped) or False (retry on unexpected failure).
    """
    payload = job.get("payload") or {}
    job_id = str(job.get("id") or "")
    twin_id = str(payload.get("twin_id") or job.get("twin_id") or "")
    tenant_id = str(job.get("tenant_id") or "")

    if not twin_id:
        logger.warning("[WeeklyDigest] missing twin_id job=%s", job_id)
        return True

    try:
        from services.email_service import send_email
        from services.notification_service import (
            _get_user_email,
            claim_notification_slot,
            generate_digest,
            load_notification_prefs,
        )

        # Guard: check user preferences
        prefs = await asyncio.to_thread(load_notification_prefs, twin_id)
        if not prefs.get("weekly_digest"):
            logger.info("[WeeklyDigest] disabled by prefs twin=%s", twin_id)
            return True

        # Guard: atomic dedup — claim BEFORE generating to prevent duplicate Gemini calls
        # meeting_id=None for digest (partial unique index on week boundary)
        now_date = datetime.now(timezone.utc).date()
        week_of = now_date.fromordinal(now_date.toordinal() - now_date.weekday()).isoformat()
        if not await asyncio.to_thread(
            claim_notification_slot,
            twin_id,
            None,
            "weekly_digest",
            tenant_id,
            week_of=week_of,
        ):
            logger.info("[WeeklyDigest] already sent this week twin=%s", twin_id)
            return True

        # Use service-role client for meetings query (worker has no user JWT)
        sb_admin = get_supabase_client()
        seven_days_ago = (
            datetime.now(timezone.utc) - timedelta(days=7)
        ).strftime("%Y-%m-%dT%H:%M:%S")

        meetings_resp = await _run_db(
            lambda: sb_admin.table("meetings")
            .select("id,title,summary_json,meeting_end")
            .eq("twin_id", twin_id)
            .eq("status", "completed")
            .gte("meeting_end", seven_days_ago)
            .execute()
        )
        meetings = meetings_resp.data or []

        if len(meetings) < 3:
            logger.info(
                "[WeeklyDigest] insufficient meetings twin=%s count=%d — skipping",
                twin_id,
                len(meetings),
            )
            # Mark as skipped to preserve audit trail
            await _run_db(
                lambda: supabase.table("meeting_notifications").update(
                    {"status": "skipped"}
                ).eq("twin_id", twin_id).eq("week_of", week_of).eq(
                    "notification_type", "weekly_digest"
                ).execute()
            )
            return True

        # Generate digest content (claim already succeeded above)
        result = await generate_digest(twin_id=twin_id, meetings=meetings)
        if not result:
            # Returned None (redundant path after claim, but guard anyway)
            await _run_db(
                lambda: supabase.table("meeting_notifications").update(
                    {"status": "skipped"}
                ).eq("twin_id", twin_id).eq("week_of", week_of).eq(
                    "notification_type", "weekly_digest"
                ).execute()
            )
            return True

        # Resolve recipient email
        user_email = await asyncio.to_thread(_get_user_email, tenant_id)
        if not user_email:
            logger.warning("[WeeklyDigest] no user email tenant=%s", tenant_id)
            return True

        # Send email
        msg_id = await send_email(
            to=user_email,
            subject=result["subject"],
            html=result["html"],
        )

        # Update notification record to sent
        await _run_db(
            lambda: supabase.table("meeting_notifications").update(
                {
                    "status": "sent",
                    "resend_message_id": msg_id,
                    "sent_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                }
            ).eq("twin_id", twin_id).eq("week_of", week_of).eq(
                "notification_type", "weekly_digest"
            ).execute()
        )

        logger.info(
            "[WeeklyDigest] sent twin=%s meetings=%d job=%s",
            twin_id,
            len(meetings),
            job_id,
        )
        return True

    except Exception:
        logger.exception("[WeeklyDigest] failed job=%s twin=%s", job_id, twin_id)
        return False


async def _process_generate_deep_brief(job: dict[str, Any]) -> bool:
    """Phase 30 / W9d: opt-in deep research mode for the pre-meeting brief.

    Runs the salvaged adk_core.agents.brief_agent.py (ADK ReAct loop) over
    KB + past meetings + web + news + scrape tools to enrich the meeting's
    brief_json. Merges into the existing fast-path brief; never replaces.

    Payload: {meeting_id}

    Flow:
      1. Flag check (BRIEF_DEEP_MODE_ENABLED) — discard if off
      2. Tenant-scoped meeting fetch
      3. Per-meeting 24h cache check via deep_generated_at
      4. Run deep brief agent (~25-45s, 90s hard timeout)
      5. Merge result into existing brief_json (overlay; never replace)
      6. Persist with tenant scope

    Returns True (job done) on terminal skip/success outcomes. Returns
    False when DB, agent, or persist failures should be retried by the
    outbox worker.
    """
    if os.getenv("BRIEF_DEEP_MODE_ENABLED", "false").lower() not in {
        "true",
        "1",
        "yes",
        "on",
    }:
        logger.info(
            "[DeepBrief] BRIEF_DEEP_MODE_ENABLED off — discarding job=%s",
            job.get("id"),
        )
        return True

    payload = job.get("payload") or {}
    meeting_id = str(payload.get("meeting_id") or "")
    twin_id = str(job.get("twin_id") or "")
    tenant_id = str(job.get("tenant_id") or "")
    job_id = str(job.get("id") or "")

    if not meeting_id or not twin_id or not tenant_id:
        logger.warning(
            "[DeepBrief] missing required ids meeting=%s twin=%s tenant=%s job=%s",
            meeting_id, twin_id, tenant_id, job_id,
        )
        return True

    # 1. Load meeting + existing brief_json. Tenant-scoped to prevent
    # the cross-tenant leak vector W9a Task 8 audit caught in the
    # briefing handler.
    try:
        meeting_resp = await _run_db(
            lambda: supabase.table("meetings")
            .select("*")
            .eq("id", meeting_id)
            .eq("twin_id", twin_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
    except Exception as exc:
        logger.exception(
            "[DeepBrief] meeting fetch failed job=%s: %s", job_id, exc,
        )
        return False
    meeting = meeting_resp.data if meeting_resp else None
    if not meeting:
        logger.warning(
            "[DeepBrief] meeting not found or out of scope id=%s twin=%s tenant=%s",
            meeting_id, twin_id, tenant_id,
        )
        return True  # terminal — no point retrying

    # 2. Cache check — 24h TTL. Skip the run when a recent deep brief exists.
    existing_brief = meeting.get("brief_json")
    if deep_cache_is_fresh(existing_brief):
        logger.info(
            "[DeepBrief] cache hit (< 24h) — skipping run meeting=%s",
            meeting_id,
        )
        return True

    # 3. Run the deep brief agent.
    deep_output = await run_deep_brief(
        twin_id=twin_id, tenant_id=tenant_id, meeting=meeting,
    )
    if deep_output is None:
        # run_deep_brief logged the reason; we keep the fast-path brief
        # intact, but the outbox job must retry instead of completing.
        # Otherwise the stable idempotency key points future clicks at a
        # completed job that never wrote deep_generated_at.
        logger.warning(
            "[DeepBrief] deep run produced no usable output meeting=%s",
            meeting_id,
        )
        return False

    # 4. Merge + persist. Fast-path brief must exist already (the lazy GET
    # writes it on first view); if somehow it doesn't, fall back to using
    # the deep_output directly as a partial brief.
    fast_brief = existing_brief if isinstance(existing_brief, dict) else {}
    merged = merge_deep_into_brief(
        fast_brief=fast_brief, deep_output=deep_output,
    )
    try:
        await _run_db(
            lambda: supabase.table("meetings")
            .update({"brief_json": merged})
            .eq("id", meeting_id)
            .eq("twin_id", twin_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
    except Exception as exc:
        logger.warning(
            "[DeepBrief] persist failed meeting=%s: %s",
            meeting_id, exc,
        )
        # The user never sees the deep brief unless the merge is stored,
        # so retry even though the next attempt may pay LLM cost again.
        return False

    logger.info(
        "[DeepBrief] completed meeting=%s twin=%s job=%s "
        "participants=%d talking_points=%d sources_used=%s",
        meeting_id, twin_id, job_id,
        len(merged.get("participant_insights") or []),
        len(merged.get("talking_points") or []),
        merged.get("sources_used"),
    )
    return True


async def process_graph_outbox_batch(worker_id: str, limit: int = 10) -> int:
    processed = 0
    for _ in range(max(1, limit)):
        handled = await process_next_graph_outbox_job(worker_id=worker_id)
        if not handled:
            break
        processed += 1
    return processed
