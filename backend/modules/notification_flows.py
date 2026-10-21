"""Notification flow registry models and persistence helpers."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AudienceSpec(BaseModel):
    segment: Literal["all_active", "plan", "flag_not_used", "single_user", "user_list"]
    plan: str | None = None
    flag: str | None = None
    user_ids: list[str] = Field(default_factory=list)


class FlowGuardrails(BaseModel):
    max_recipients: int = 500
    throttle_per_min: int = 30
    dry_run_required: bool = True
    exempt_from_caps: bool = False


class NotificationFlowCreate(BaseModel):
    key: str
    name: str
    kind: Literal["transactional", "lifecycle", "announcement"]
    trigger_type: Literal["event", "cron", "manual"]
    audience_spec: AudienceSpec
    email_type: str
    category: str
    context_overrides: dict[str, Any] = Field(default_factory=dict)
    schedule_cron: str | None = None
    guardrails: FlowGuardrails = Field(default_factory=FlowGuardrails)
    created_by: str
    tenant_id: str | None = None


class NotificationFlow(NotificationFlowCreate):
    id: str
    status: str
    approved_by: str | None = None
    approved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class NotificationFlowRun(BaseModel):
    id: str
    tenant_id: str | None = None
    flow_id: str
    flow_run_key: str
    trigger_kind: Literal["scheduled", "manual", "event", "dry_run"]
    audience_count: int = 0
    enqueued: int = 0
    skipped: int = 0
    failed: int = 0
    open_count: int | None = None
    click_count: int | None = None
    conversion_count: int | None = None
    outcome_measured_at: datetime | None = None
    status: str = "pending"
    summary: dict[str, Any] = Field(default_factory=dict)
    audience_snapshot_hash: str | None = None
    created_at: datetime
    updated_at: datetime


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _flow_from_row(row: dict[str, Any]) -> NotificationFlow:
    data = dict(row)
    data["audience_spec"] = AudienceSpec.model_validate(data.get("audience_spec") or {})
    data["guardrails"] = FlowGuardrails.model_validate(data.get("guardrails") or {})
    data["context_overrides"] = data.get("context_overrides") or {}
    return NotificationFlow.model_validate(data)


def _run_from_row(row: dict[str, Any]) -> NotificationFlowRun:
    return NotificationFlowRun.model_validate(dict(row))


def create_flow(sb: Any, data: NotificationFlowCreate) -> NotificationFlow:
    now = _utcnow_iso()
    payload = data.model_dump(mode="json")
    payload["audience_spec"] = data.audience_spec.model_dump(mode="json")
    payload["guardrails"] = data.guardrails.model_dump(mode="json")
    payload["status"] = "proposed"
    payload["created_at"] = now
    payload["updated_at"] = now
    try:
        resp = sb.table("notification_flows").insert(payload).execute()
        rows = resp.data or []
        if not rows:
            raise HTTPException(status_code=500, detail="notification flow insert returned no rows")
        return _flow_from_row(rows[0])
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[notification_flows] create_flow failed key=%s", data.key)
        raise HTTPException(status_code=500, detail="create notification flow failed") from exc


def get_flow(sb: Any, flow_id: str) -> NotificationFlow:
    try:
        resp = (
            sb.table("notification_flows")
            .select("*")
            .eq("id", flow_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            raise HTTPException(status_code=404, detail="notification flow not found")
        return _flow_from_row(rows[0])
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[notification_flows] get_flow failed flow_id=%s", flow_id)
        raise HTTPException(status_code=500, detail="get notification flow failed") from exc


def get_flow_by_key(sb: Any, key: str) -> NotificationFlow | None:
    try:
        resp = (
            sb.table("notification_flows")
            .select("*")
            .eq("key", key)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return _flow_from_row(rows[0]) if rows else None
    except Exception as exc:
        logger.exception("[notification_flows] get_flow_by_key failed key=%s", key)
        raise HTTPException(status_code=500, detail="get notification flow by key failed") from exc


def list_flows(sb: Any, status: str | None = None) -> list[NotificationFlow]:
    try:
        query = sb.table("notification_flows").select("*").order("created_at", desc=True)
        if status:
            query = query.eq("status", status)
        resp = query.execute()
        return [_flow_from_row(row) for row in (resp.data or [])]
    except Exception as exc:
        logger.exception("[notification_flows] list_flows failed status=%s", status)
        raise HTTPException(status_code=500, detail="list notification flows failed") from exc


def update_flow_status(
    sb: Any,
    flow_id: str,
    status: str,
    approved_by: str | None = None,
) -> NotificationFlow:
    patch: dict[str, Any] = {"status": status, "updated_at": _utcnow_iso()}
    if approved_by:
        patch["approved_by"] = approved_by
        patch["approved_at"] = _utcnow_iso()
    try:
        resp = (
            sb.table("notification_flows")
            .update(patch)
            .eq("id", flow_id)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            raise HTTPException(status_code=404, detail="notification flow not found")
        return _flow_from_row(rows[0])
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[notification_flows] update_flow_status failed flow_id=%s", flow_id)
        raise HTTPException(status_code=500, detail="update notification flow failed") from exc


def update_flow_draft(
    sb: Any,
    flow_id: str,
    *,
    name: str | None = None,
    context_overrides: dict[str, Any] | None = None,
) -> NotificationFlow:
    patch: dict[str, Any] = {"updated_at": _utcnow_iso()}
    if name is not None:
        patch["name"] = name
    if context_overrides is not None:
        patch["context_overrides"] = context_overrides
    try:
        resp = (
            sb.table("notification_flows")
            .update(patch)
            .eq("id", flow_id)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            raise HTTPException(status_code=404, detail="notification flow not found")
        return _flow_from_row(rows[0])
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[notification_flows] update_flow_draft failed flow_id=%s", flow_id)
        raise HTTPException(status_code=500, detail="update notification flow draft failed") from exc


def create_run(
    sb: Any,
    flow_id: str,
    trigger_kind: Literal["scheduled", "manual", "event", "dry_run"],
    audience_count: int,
    *,
    run_id: str | None = None,
    tenant_id: str | None = None,
    flow_run_key: str | None = None,
) -> str:
    now = _utcnow_iso()
    row_id = run_id or str(uuid.uuid4())
    key = flow_run_key or f"{flow_id}:{trigger_kind}:{row_id}"
    payload = {
        "id": row_id,
        "tenant_id": tenant_id,
        "flow_id": flow_id,
        "flow_run_key": key,
        "trigger_kind": trigger_kind,
        "audience_count": audience_count,
        "status": "running",
        "created_at": now,
        "updated_at": now,
    }
    try:
        if run_id:
            resp = sb.table("notification_flow_runs").upsert(payload, on_conflict="id").execute()
        else:
            resp = sb.table("notification_flow_runs").insert(payload).execute()
        rows = resp.data or []
        if not rows:
            raise HTTPException(status_code=500, detail="notification flow run insert returned no rows")
        return str(rows[0]["id"])
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[notification_flows] create_run failed flow_id=%s", flow_id)
        raise HTTPException(status_code=500, detail="create notification flow run failed") from exc


def update_run(sb: Any, run_id: str, **fields: Any) -> NotificationFlowRun:
    patch = dict(fields)
    patch["updated_at"] = _utcnow_iso()
    try:
        resp = (
            sb.table("notification_flow_runs")
            .update(patch)
            .eq("id", run_id)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            raise HTTPException(status_code=404, detail="notification flow run not found")
        return _run_from_row(rows[0])
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[notification_flows] update_run failed run_id=%s", run_id)
        raise HTTPException(status_code=500, detail="update notification flow run failed") from exc


def close_run(
    sb: Any,
    run_id: str,
    *,
    status: str,
    enqueued: int,
    skipped: int,
    failed: int = 0,
    summary: dict[str, Any] | None = None,
) -> NotificationFlowRun:
    patch: dict[str, Any] = {
        "status": status,
        "enqueued": enqueued,
        "skipped": skipped,
        "failed": failed,
    }
    if summary is not None:
        patch["summary"] = summary
    return update_run(sb, run_id, **patch)


def get_run(sb: Any, run_id: str) -> NotificationFlowRun:
    try:
        resp = (
            sb.table("notification_flow_runs")
            .select("*")
            .eq("id", run_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            raise HTTPException(status_code=404, detail="notification flow run not found")
        return _run_from_row(rows[0])
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[notification_flows] get_run failed run_id=%s", run_id)
        raise HTTPException(status_code=500, detail="get notification flow run failed") from exc


def list_runs(sb: Any, flow_id: str | None = None, limit: int = 50) -> list[NotificationFlowRun]:
    try:
        query = (
            sb.table("notification_flow_runs")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
        )
        if flow_id:
            query = query.eq("flow_id", flow_id)
        resp = query.execute()
        return [_run_from_row(row) for row in (resp.data or [])]
    except Exception as exc:
        logger.exception("[notification_flows] list_runs failed flow_id=%s", flow_id)
        raise HTTPException(status_code=500, detail="list notification flow runs failed") from exc
