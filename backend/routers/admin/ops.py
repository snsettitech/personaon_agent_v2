"""Admin: graph_outbox operator tools + system health.

Stuck or failed jobs no longer require manual DB intervention -- operators can
list failures + retry a specific job via these endpoints.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, ValidationError

from modules.auth_guard import require_admin
from services.gcp_alert_auth import verify_gcp_alert_webhook

from ._common import _safe_query, _supabase

logger = logging.getLogger(__name__)

router = APIRouter()

# Alert sources wired up so far. Extend when a new GCP notification channel is
# pointed at this webhook.
ALLOWED_ALERT_SOURCES = ("gcp_uptime", "gcp_billing")


class GcpAlertIncidentPayload(BaseModel):
    """Best-effort model of a GCP Cloud Monitoring webhook incident payload.

    UNCERTAINTY FLAG: this field set (incident_id/resource_name/state/
    policy_name/condition_name/started_at/ended_at/summary/url) was
    reconstructed from general knowledge of Cloud Monitoring's documented
    webhook notification format -- it was NOT verified against live GCP docs
    or a real captured payload in this task. ``extra="allow"`` means any
    field GCP actually sends (including ones not listed here, or a
    differently-shaped body from a Pub/Sub-to-webhook relay used for billing
    budgets) is preserved rather than rejected or silently dropped. Re-check
    this shape against a real payload before relying on any specific field.
    """

    model_config = ConfigDict(extra="allow")

    incident_id: str | None = None
    resource_id: str | None = None
    resource_name: str | None = None
    state: str | None = None
    started_at: int | None = None
    ended_at: int | None = None
    policy_name: str | None = None
    condition_name: str | None = None
    summary: str | None = None
    url: str | None = None


class GcpAlertWebhookPayload(BaseModel):
    """Permissive envelope for the inbound alert webhook body. See
    ``GcpAlertIncidentPayload`` for the uncertainty note on exact GCP shape."""

    model_config = ConfigDict(extra="allow")

    incident: GcpAlertIncidentPayload | None = None
    version: str | None = None


@router.get("/ops/health")
def ops_health(user: dict = Depends(require_admin)) -> dict[str, Any]:
    """System health: graph_outbox queue depth by status + recent throughput."""
    sb = _supabase()

    def count(status: str, *, since_iso: str | None = None) -> int:
        try:
            q = sb.table("graph_outbox").select("id", count="exact").eq("status", status)
            if since_iso:
                q = q.gte("updated_at", since_iso)
            return q.limit(0).execute().count or 0
        except Exception as exc:
            logger.warning("[ops] health count failed status=%s err=%r", status, exc)
            return 0

    day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    return {
        "graph_outbox": {
            "pending": count("pending"),
            "processing": count("processing"),
            "failed": count("failed"),
            "completed_24h": count("completed", since_iso=day_ago),
        }
    }


@router.get("/graph-outbox/failed")
def list_failed_graph_outbox_jobs(
    limit: int = Query(default=50, le=500),
    operation: str | None = Query(default=None, description="Filter by operation (exact match)"),
    user: dict = Depends(require_admin),
) -> list[dict[str, Any]]:
    """List the most recent jobs in status='failed'."""
    sb = _supabase()
    query = (
        sb.table("graph_outbox")
        .select("id, operation, tenant_id, twin_id, status, attempt_count, max_attempts, error_message, created_at, updated_at, failed_at")
        .eq("status", "failed")
        .order("updated_at", desc=True)
        .limit(limit)
    )
    if operation:
        query = query.eq("operation", operation)
    return _safe_query(query)


@router.get("/graph-outbox/stuck")
def list_stuck_graph_outbox_jobs(
    minutes: int = Query(default=30, ge=1, le=1440, description="Min minutes in 'processing' to count as stuck"),
    user: dict = Depends(require_admin),
) -> list[dict[str, Any]]:
    """List jobs currently stuck in status='processing' beyond ``minutes``."""
    sb = _supabase()
    threshold = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    return _safe_query(
        sb.table("graph_outbox")
        .select("id, operation, tenant_id, twin_id, status, attempt_count, max_attempts, error_message, created_at, updated_at")
        .eq("status", "processing")
        .lt("updated_at", threshold)
        .order("updated_at", desc=False)  # oldest first
        .limit(100)
    )


@router.post("/graph-outbox/retry/{job_id}")
def retry_graph_outbox_job(
    job_id: str,
    reset_attempts: bool = Query(default=True, description="Reset attempt_count to 0 so the job has a fresh retry budget"),
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """Reset a failed or stuck job to ``status='pending'`` so the worker picks it up.

    Idempotent: if the job is already ``pending``, this is a no-op.
    """
    sb = _supabase()
    resp = (
        sb.table("graph_outbox")
        .select("id, status, operation, attempt_count")
        .eq("id", job_id)
        .limit(1)
        .execute()
    )
    rows = getattr(resp, "data", None) or []
    if not rows:
        raise HTTPException(status_code=404, detail="job not found")
    job = rows[0]
    if job["status"] not in ("failed", "processing"):
        return {
            "status": "noop",
            "data": {"job_id": job_id, "current_status": job["status"]},
        }

    now_iso = datetime.now(timezone.utc).isoformat()
    update_payload: dict[str, Any] = {
        "status": "pending",
        "updated_at": now_iso,
        "next_attempt_after": now_iso,  # eligible immediately
        "error_message": f"admin_retry by user={user.get('user_id')} at {now_iso}",
    }
    if reset_attempts:
        update_payload["attempt_count"] = 0

    update = (
        sb.table("graph_outbox")
        .update(update_payload)
        .eq("id", job_id)
        .execute()
    )
    if not getattr(update, "data", None):
        raise HTTPException(status_code=500, detail="update returned no rows")

    logger.warning(
        "[admin] graph_outbox retry job=%s operation=%s reset_attempts=%s by_user=%s",
        job_id, job.get("operation"), reset_attempts, user.get("user_id"),
    )
    return {
        "status": "ok",
        "data": {
            "job_id": job_id,
            "operation": job.get("operation"),
            "new_status": "pending",
            "attempt_count": 0 if reset_attempts else job.get("attempt_count"),
        },
    }


@router.post("/ops/alerts/webhook/{source}")
async def receive_ops_alert_webhook(source: str, request: Request) -> dict[str, Any]:
    """Ingest a GCP Cloud Monitoring alert (uptime-check failure or billing-budget
    threshold breach) so it lands on the admin ops page instead of email/Slack.

    Auth: shared secret via ``services.gcp_alert_auth.verify_gcp_alert_webhook``
    (GCP_ALERT_WEBHOOK_SECRET) -- this is an inbound platform webhook with no
    user session, so it deliberately does not use ``require_admin``. See that
    module's docstring for the real uncertainty around which auth carrier GCP
    actually uses (Basic Auth vs. header vs. query token).

    Payload: accepted permissively via ``GcpAlertWebhookPayload`` -- the exact
    GCP webhook JSON shape was not verified against live docs in this task;
    see that model's docstring for the uncertainty flag.
    """
    if source not in ALLOWED_ALERT_SOURCES:
        raise HTTPException(status_code=404, detail=f"unknown alert source: {source}")

    if not verify_gcp_alert_webhook(
        authorization_header=request.headers.get("authorization", ""),
        secret_header=request.headers.get("x-ops-webhook-secret", ""),
        secret_query_param=request.query_params.get("secret", ""),
    ):
        logger.warning("[ops] alert webhook rejected: invalid/missing shared secret source=%s", source)
        raise HTTPException(status_code=401, detail="invalid webhook secret")

    raw_body = await request.body()
    try:
        payload = (
            GcpAlertWebhookPayload.model_validate_json(raw_body)
            if raw_body
            else GcpAlertWebhookPayload()
        )
    except ValidationError as exc:
        logger.warning("[ops] alert webhook payload failed validation source=%s err=%r", source, exc)
        raise HTTPException(status_code=422, detail="invalid alert payload") from exc

    incident = payload.incident
    title = (
        (incident.summary if incident else None)
        or (incident.condition_name if incident else None)
        or f"{source} alert"
    )
    # Normalize case/whitespace before comparing -- the real GCP payload shape
    # for `incident.state` was never verified against live docs (see
    # GcpAlertIncidentPayload docstring), so an exact lowercase match alone is
    # too brittle. This does not resolve the underlying uncertainty about the
    # field name/shape itself -- if GCP sends a state value or payload shape
    # this doesn't anticipate, alerts will still land as "info" without a real
    # captured payload to verify against.
    incident_state = (incident.state or "").strip().lower() if incident else ""
    severity = "critical" if incident_state == "open" else "info"

    row: dict[str, Any] = {
        "source": source,
        "severity": severity,
        "title": title,
        "detail": payload.model_dump(mode="json"),
    }

    sb = _supabase()
    try:
        inserted = sb.table("ops_alerts").insert(row).execute()
    except Exception as exc:
        logger.exception("[ops] failed to insert ops_alerts row source=%s", source)
        raise HTTPException(status_code=500, detail="failed to record alert") from exc

    rows = getattr(inserted, "data", None) or []
    logger.warning("[ops] alert ingested source=%s severity=%s title=%s", source, severity, title)
    return {"status": "ok", "data": rows[0] if rows else row}


@router.get("/ops/alerts")
def list_ops_alerts(
    limit: int = Query(default=50, le=200),
    source: str | None = Query(default=None, description="Filter by source (gcp_uptime, gcp_billing)"),
    unresolved_only: bool = Query(default=False, description="Only return alerts with resolved_at IS NULL"),
    user: dict = Depends(require_admin),
) -> list[dict[str, Any]]:
    """List recent ops_alerts rows for the admin ops page to render.

    Deliberately does NOT use ``_safe_query`` here. That helper swallows any
    exception and returns ``[]``, which would make a missing/un-applied
    ``ops_alerts`` migration (or any other DB error) indistinguishable from a
    genuinely healthy "no alerts" state -- the exact failure mode that already
    hid a dead pipeline once on this project (widget_leads migration never
    applied to staging). The write side of this pipeline
    (``receive_ops_alert_webhook``) already raises HTTPException 500 for the
    identical root cause; mirror that here so the read side fails loudly too.
    """
    sb = _supabase()
    query = (
        sb.table("ops_alerts")
        .select("id, source, severity, title, detail, created_at, resolved_at")
        .order("created_at", desc=True)
        .limit(limit)
    )
    if source:
        query = query.eq("source", source)
    if unresolved_only:
        query = query.is_("resolved_at", "null")
    try:
        result = query.execute()
    except Exception as exc:
        logger.exception("[ops] failed to query ops_alerts (table missing or migration not applied?)")
        raise HTTPException(status_code=500, detail="failed to load ops alerts") from exc
    return result.data or []
