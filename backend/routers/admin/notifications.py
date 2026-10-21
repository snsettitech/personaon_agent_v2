"""Admin: agentic notification flows."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from modules import admin_audit
from modules.audience import resolve_audience
from modules.auth_guard import require_admin, require_admin_write
from modules.graph_outbox import GraphOperationType, get_graph_outbox
from modules.notification_events import NotificationEventCreate, emit_notification_event
from modules.notification_flows import (
    close_run,
    create_run,
    get_flow,
    get_run,
    list_flows,
    list_runs,
    update_flow_draft,
    update_flow_status,
)
from services.lifecycle_email_monitoring import find_stale_sending_lifecycle_email_events

from ._common import _supabase

logger = logging.getLogger(__name__)
router = APIRouter()
SYSTEM_TWIN_ID = "00000000-0000-4000-8000-000000000000"


class FeatureLaunchCreate(BaseModel):
    flag: str = Field(min_length=1, max_length=120)
    feature_name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1000)
    cta_path: str = Field(default="/dashboard", max_length=300)


class NotificationFlowDraftUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    subject: str | None = Field(default=None, min_length=1, max_length=180)
    body: str | None = Field(default=None, min_length=1, max_length=2000)
    cta_label: str | None = Field(default=None, min_length=1, max_length=80)
    cta_path: str | None = Field(default=None, min_length=1, max_length=300)


def _stable_manual_run_id(flow_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"personaon:notification-flow:manual:{flow_id}"))


def _actor_label(user: dict[str, Any]) -> str:
    return str(user.get("email") or user.get("user_id") or user.get("id") or "admin")


def _flow_payload(flow) -> dict[str, Any]:
    return flow.model_dump(mode="json")


def _run_payload(run) -> dict[str, Any]:
    return run.model_dump(mode="json")


def _ensure_transition(current: str, target: str, allowed: set[str]) -> None:
    if current not in allowed:
        raise HTTPException(status_code=409, detail=f"cannot transition {current} to {target}")


@router.post("/notifications/feature-launches")
def create_feature_launch_notification(
    body: FeatureLaunchCreate,
    user: dict = Depends(require_admin_write),
) -> dict[str, Any]:
    sb = _supabase()
    actor_id = str(user.get("user_id") or user.get("id") or "")
    tenant_id = str(user.get("tenant_id") or actor_id or "")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="admin user missing tenant_id — cannot emit notification event")
    event = emit_notification_event(
        sb,
        NotificationEventCreate(
            tenant_id=tenant_id,
            event_type="feature.launched",
            actor_id=actor_id or None,
            subject_id=body.flag,
            context_json=body.model_dump(mode="json"),
        ),
    )
    job_id = get_graph_outbox().submit(
        tenant_id=tenant_id,
        twin_id=SYSTEM_TWIN_ID,
        operation=GraphOperationType.PROCESS_NOTIFICATION_EVENT,
        idempotency_key=f"feature-launched-{body.flag}-{event.id}",
        scope_id=event.id,
        payload={"event_id": event.id, "event_type": event.event_type, "subject_id": event.subject_id},
    )
    admin_audit.record_admin_action(
        actor=user,
        action=admin_audit.ACTION_NOTIFICATION_FEATURE_LAUNCHED,
        target_type="notification_event",
        target_id=event.id,
        details={"flag": body.flag, "feature_name": body.feature_name, "job_id": job_id},
    )
    return {"status": "ok", "data": {"event_id": event.id, "job_id": job_id}}


@router.get("/notifications/flows")
def list_notification_flows(
    status: str | None = Query(default=None),
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    flows = [_flow_payload(flow) for flow in list_flows(_supabase(), status=status)]
    return {"status": "ok", "data": {"flows": flows}}


@router.get("/notifications/flows/{flow_id}")
def get_notification_flow(flow_id: str, user: dict = Depends(require_admin)) -> dict[str, Any]:
    flow = get_flow(_supabase(), flow_id)
    return {"status": "ok", "data": {"flow": _flow_payload(flow)}}


@router.patch("/notifications/flows/{flow_id}")
def update_notification_flow_draft(
    flow_id: str,
    body: NotificationFlowDraftUpdate,
    user: dict = Depends(require_admin_write),
) -> dict[str, Any]:
    sb = _supabase()
    before = get_flow(sb, flow_id)
    _ensure_transition(before.status, "proposed", {"proposed"})
    context = dict(before.context_overrides)
    patch = body.model_dump(exclude_unset=True)
    for key in ("subject", "body", "cta_label", "cta_path"):
        if key in patch:
            context[key] = patch[key]
    flow = update_flow_draft(
        sb,
        flow_id,
        name=patch.get("name"),
        context_overrides=context,
    )
    admin_audit.record_admin_action(
        actor=user,
        action=admin_audit.ACTION_NOTIFICATION_FLOW_DRAFT_UPDATED,
        target_type="notification_flow",
        target_id=flow_id,
        details={"fields": sorted(patch.keys())},
    )
    return {"status": "ok", "data": {"flow": _flow_payload(flow)}}


@router.post("/notifications/flows/{flow_id}/approve")
def approve_flow(flow_id: str, user: dict = Depends(require_admin_write)) -> dict[str, Any]:
    sb = _supabase()
    before = get_flow(sb, flow_id)
    _ensure_transition(before.status, "active", {"proposed", "approved"})
    flow = update_flow_status(sb, flow_id, "active", approved_by=_actor_label(user))
    admin_audit.record_admin_action(
        actor=user,
        action=admin_audit.ACTION_NOTIFICATION_FLOW_APPROVED,
        target_type="notification_flow",
        target_id=flow_id,
        after={"status": "active"},
    )
    return {"status": "ok", "data": {"flow": _flow_payload(flow)}}


@router.post("/notifications/flows/{flow_id}/reject")
def reject_flow(flow_id: str, user: dict = Depends(require_admin_write)) -> dict[str, Any]:
    sb = _supabase()
    before = get_flow(sb, flow_id)
    _ensure_transition(before.status, "archived", {"proposed"})
    flow = update_flow_status(sb, flow_id, "archived")
    admin_audit.record_admin_action(
        actor=user,
        action=admin_audit.ACTION_NOTIFICATION_FLOW_REJECTED,
        target_type="notification_flow",
        target_id=flow_id,
        after={"status": "archived"},
    )
    return {"status": "ok", "data": {"flow": _flow_payload(flow)}}


@router.post("/notifications/flows/{flow_id}/pause")
def pause_flow(flow_id: str, user: dict = Depends(require_admin_write)) -> dict[str, Any]:
    sb = _supabase()
    before = get_flow(sb, flow_id)
    _ensure_transition(before.status, "paused", {"active"})
    flow = update_flow_status(sb, flow_id, "paused")
    admin_audit.record_admin_action(
        actor=user,
        action=admin_audit.ACTION_NOTIFICATION_FLOW_PAUSED,
        target_type="notification_flow",
        target_id=flow_id,
        after={"status": "paused"},
    )
    return {"status": "ok", "data": {"flow": _flow_payload(flow)}}


@router.post("/notifications/flows/{flow_id}/unpause")
def unpause_flow(flow_id: str, user: dict = Depends(require_admin_write)) -> dict[str, Any]:
    sb = _supabase()
    before = get_flow(sb, flow_id)
    _ensure_transition(before.status, "active", {"paused"})
    flow = update_flow_status(sb, flow_id, "active", approved_by=_actor_label(user))
    admin_audit.record_admin_action(
        actor=user,
        action=admin_audit.ACTION_NOTIFICATION_FLOW_APPROVED,
        target_type="notification_flow",
        target_id=flow_id,
        after={"status": "active"},
    )
    return {"status": "ok", "data": {"flow": _flow_payload(flow)}}


@router.post("/notifications/flows/{flow_id}/run")
async def run_flow(
    flow_id: str,
    dry_run: bool = Query(default=True),
    user: dict = Depends(require_admin_write),
) -> dict[str, Any]:
    sb = _supabase()
    flow = get_flow(sb, flow_id)
    flow_run_id = str(uuid.uuid4()) if dry_run else _stable_manual_run_id(flow_id)
    if dry_run:
        resolved = await resolve_audience(sb, flow.audience_spec)
        run_id = create_run(
            sb,
            flow_id,
            "dry_run",
            resolved.count,
            run_id=flow_run_id,
            tenant_id=flow.tenant_id,
            flow_run_key=f"{flow_id}:dry_run:{flow_run_id}",
        )
        close_run(
            sb,
            run_id,
            status="completed",
            enqueued=0,
            skipped=resolved.count,
            summary={"segment": resolved.segment_label},
        )
        admin_audit.record_admin_action(
            actor=user,
            action=admin_audit.ACTION_NOTIFICATION_FLOW_RUN,
            target_type="notification_flow",
            target_id=flow_id,
            details={"dry_run": True, "flow_run_id": run_id, "audience_count": resolved.count},
        )
        return {
            "status": "ok",
            "data": {
                "flow_run_id": run_id,
                "dry_run": True,
                "audience_count": resolved.count,
                "enqueued": 0,
            },
        }

    job_id = get_graph_outbox().submit(
        tenant_id=flow.tenant_id or str(user.get("tenant_id") or user.get("user_id") or flow_id),
        twin_id=SYSTEM_TWIN_ID,
        operation=GraphOperationType.RUN_NOTIFICATION_FLOW,
        idempotency_key=f"run-notification-flow-{flow_id}-{flow_run_id}",
        scope_id=flow_run_id,
        payload={"flow_id": flow_id, "flow_run_id": flow_run_id, "dry_run": False},
    )
    admin_audit.record_admin_action(
        actor=user,
        action=admin_audit.ACTION_NOTIFICATION_FLOW_RUN,
        target_type="notification_flow",
        target_id=flow_id,
        details={"dry_run": False, "flow_run_id": flow_run_id, "job_id": job_id},
    )
    return {
        "status": "ok",
        "data": {"flow_run_id": flow_run_id, "job_id": job_id, "dry_run": False},
    }


@router.get("/notifications/runs")
def list_flow_runs(
    flow_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    runs = [_run_payload(run) for run in list_runs(_supabase(), flow_id=flow_id, limit=limit)]
    return {"status": "ok", "data": {"runs": runs}}


@router.get("/notifications/stale-events")
def list_stale_lifecycle_email_events(
    stale_after_minutes: int = Query(default=30, ge=1, le=1440),
    limit: int = Query(default=100, ge=1, le=500),
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    events = find_stale_sending_lifecycle_email_events(
        _supabase(),
        stale_after_minutes=stale_after_minutes,
        limit=limit,
    )
    return {"status": "ok", "data": {"events": events}}


@router.get("/notifications/runs/{run_id}")
def get_flow_run(run_id: str, user: dict = Depends(require_admin)) -> dict[str, Any]:
    sb = _supabase()
    run = get_run(sb, run_id)
    events_resp = (
        sb.table("lifecycle_email_events")
        .select("id,user_id,recipient_email,status,resend_message_id,error_message,skip_reason,sent_at,created_at")
        .eq("scope_id", run_id)
        .order("created_at", desc=False)
        .execute()
    )
    return {"status": "ok", "data": {"run": _run_payload(run), "recipients": events_resp.data or []}}
