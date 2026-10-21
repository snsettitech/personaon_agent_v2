"""Admin notification flow endpoint tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def _active_flow(status: str = "active"):
    from modules.notification_flows import AudienceSpec, FlowGuardrails, NotificationFlow

    return NotificationFlow(
        id="flow-1",
        tenant_id=None,
        key="feature_launch_v1",
        name="Feature Launch",
        kind="announcement",
        trigger_type="manual",
        audience_spec=AudienceSpec(segment="all_active"),
        email_type="feature_launch",
        category="announcements",
        context_overrides={},
        schedule_cron=None,
        guardrails=FlowGuardrails(max_recipients=500, throttle_per_min=30),
        created_by="agent:notification_agent",
        status=status,
        approved_by="admin@example.com" if status == "active" else None,
        approved_at=None,
        created_at="2026-06-26T00:00:00+00:00",
        updated_at="2026-06-26T00:00:00+00:00",
    )


def _client(write_user=None, read_user=None) -> TestClient:
    from routers.admin import notifications

    app = FastAPI()
    app.include_router(notifications.router, prefix="/admin")
    app.dependency_overrides[notifications.require_admin] = (
        lambda: read_user or write_user or {"user_id": "admin-1", "email": "admin@personaon.com"}
    )
    app.dependency_overrides[notifications.require_admin_write] = (
        lambda: write_user or {"user_id": "admin-1", "email": "admin@personaon.com"}
    )
    return TestClient(app)


def test_approve_requires_admin_write():
    from routers.admin import notifications

    app = FastAPI()
    app.include_router(notifications.router, prefix="/admin")

    def deny_write():
        raise HTTPException(status_code=403, detail="Write privileges required")

    app.dependency_overrides[notifications.require_admin_write] = deny_write
    client = TestClient(app)

    response = client.post("/admin/notifications/flows/flow-1/approve")

    assert response.status_code == 403


def test_feature_launch_emits_event_and_queues_agent_processing():
    from modules.graph_outbox import GraphOperationType
    from routers.admin import notifications

    user = {"user_id": "admin-1", "tenant_id": "tenant-1", "email": "admin@personaon.com"}
    outbox = MagicMock()
    outbox.submit.return_value = "job-feature"
    event = SimpleNamespace(id="event-feature-1", event_type="feature.launched", subject_id="workspace_search")

    with (
        patch("routers.admin.notifications.emit_notification_event", return_value=event) as emit,
        patch("routers.admin.notifications.get_graph_outbox", return_value=outbox),
        patch("modules.admin_audit.record_admin_action") as audit,
    ):
        result = notifications.create_feature_launch_notification(
            notifications.FeatureLaunchCreate(
                flag="workspace_search",
                feature_name="Workspace Search",
                description="Search across your PersonaOn workspace.",
                cta_path="/dashboard/search",
            ),
            user,
        )

    assert result["data"]["event_id"] == "event-feature-1"
    emitted = emit.call_args.args[1]
    assert emitted.event_type == "feature.launched"
    assert emitted.subject_id == "workspace_search"
    assert emitted.context_json["feature_name"] == "Workspace Search"
    assert emitted.actor_id == "admin-1"
    assert emitted.tenant_id == "tenant-1"
    outbox.submit.assert_called_once()
    assert outbox.submit.call_args.kwargs["operation"] == GraphOperationType.PROCESS_NOTIFICATION_EVENT
    assert outbox.submit.call_args.kwargs["payload"]["event_id"] == "event-feature-1"
    audit.assert_called_once()


def test_approve_transitions_status():
    client = _client()
    with (
        patch("routers.admin.notifications.get_flow", return_value=_active_flow("proposed")),
        patch("routers.admin.notifications.update_flow_status", return_value=_active_flow("active")) as mock_update,
        patch("modules.admin_audit.record_admin_action"),
    ):
        response = client.post("/admin/notifications/flows/flow-1/approve")

    assert response.status_code == 200
    assert response.json()["data"]["flow"]["status"] == "active"
    mock_update.assert_called_once()
    assert mock_update.call_args.args[2] == "active"


def test_update_proposed_flow_draft_patches_generated_copy():
    from routers.admin import notifications

    proposed = _active_flow("proposed")
    proposed.context_overrides.update({
        "generated_email": True,
        "subject": "Old subject",
        "body": "Old body",
        "cta_label": "Try it",
        "cta_path": "/dashboard",
    })
    updated = proposed.model_copy(deep=True)
    updated.context_overrides.update({"subject": "New subject", "body": "New body"})
    with (
        patch("routers.admin.notifications.get_flow", return_value=proposed),
        patch("routers.admin.notifications.update_flow_draft", return_value=updated) as mock_update,
        patch("modules.admin_audit.record_admin_action") as mock_audit,
    ):
        result = notifications.update_notification_flow_draft(
            "flow-1",
            notifications.NotificationFlowDraftUpdate(subject="New subject", body="New body"),
            {"user_id": "admin-1", "email": "admin@personaon.com"},
        )

    assert result["data"]["flow"]["context_overrides"]["subject"] == "New subject"
    patch_context = mock_update.call_args.kwargs["context_overrides"]
    assert patch_context["generated_email"] is True
    assert patch_context["subject"] == "New subject"
    assert patch_context["body"] == "New body"
    assert patch_context["cta_path"] == "/dashboard"
    mock_audit.assert_called_once()


def test_approve_writes_audit_log():
    client = _client()
    with (
        patch("routers.admin.notifications.get_flow", return_value=_active_flow("proposed")),
        patch("routers.admin.notifications.update_flow_status", return_value=_active_flow("active")),
        patch("modules.admin_audit.record_admin_action") as mock_audit,
    ):
        response = client.post("/admin/notifications/flows/flow-1/approve")

    assert response.status_code == 200
    mock_audit.assert_called_once()
    assert mock_audit.call_args.kwargs["target_type"] == "notification_flow"


def test_run_dry_run_default():
    from modules.audience import ResolvedAudience

    client = _client()
    outbox = MagicMock()
    with (
        patch("routers.admin.notifications.get_flow", return_value=_active_flow("active")),
        patch(
            "routers.admin.notifications.resolve_audience",
            new_callable=AsyncMock,
            return_value=ResolvedAudience(recipients=[], count=7, segment_label="all_active"),
        ),
        patch("routers.admin.notifications.create_run", return_value="run-dry"),
        patch("routers.admin.notifications.close_run"),
        patch("routers.admin.notifications.get_graph_outbox", return_value=outbox),
        patch("modules.admin_audit.record_admin_action"),
    ):
        response = client.post("/admin/notifications/flows/flow-1/run")

    assert response.status_code == 200
    assert response.json()["data"]["dry_run"] is True
    assert response.json()["data"]["audience_count"] == 7
    outbox.submit.assert_not_called()


def test_run_live_requires_explicit_false():
    client = _client()
    outbox = MagicMock()
    outbox.submit.return_value = "job-live"
    with (
        patch("routers.admin.notifications.get_flow", return_value=_active_flow("active")),
        patch("routers.admin.notifications.get_graph_outbox", return_value=outbox),
        patch("modules.admin_audit.record_admin_action"),
    ):
        response = client.post("/admin/notifications/flows/flow-1/run?dry_run=false")

    assert response.status_code == 200
    assert response.json()["data"]["dry_run"] is False
    outbox.submit.assert_called_once()


def test_run_live_uses_stable_flow_run_id_for_retries():
    client = _client()
    first_outbox = MagicMock()
    first_outbox.submit.return_value = "job-live-1"
    second_outbox = MagicMock()
    second_outbox.submit.return_value = "job-live-1"

    with (
        patch("routers.admin.notifications.get_flow", return_value=_active_flow("active")),
        patch("routers.admin.notifications.get_graph_outbox", side_effect=[first_outbox, second_outbox]),
        patch("modules.admin_audit.record_admin_action"),
    ):
        first = client.post("/admin/notifications/flows/flow-1/run?dry_run=false")
        second = client.post("/admin/notifications/flows/flow-1/run?dry_run=false")

    assert first.status_code == 200
    assert second.status_code == 200
    first_kwargs = first_outbox.submit.call_args.kwargs
    second_kwargs = second_outbox.submit.call_args.kwargs
    assert first_kwargs["scope_id"] == second_kwargs["scope_id"]
    assert first_kwargs["idempotency_key"] == second_kwargs["idempotency_key"]
    assert first_kwargs["payload"]["flow_run_id"] == second_kwargs["payload"]["flow_run_id"]


def test_reject_archives_flow():
    client = _client()
    archived = _active_flow("archived")
    with (
        patch("routers.admin.notifications.get_flow", return_value=_active_flow("proposed")),
        patch("routers.admin.notifications.update_flow_status", return_value=archived) as mock_update,
        patch("modules.admin_audit.record_admin_action"),
    ):
        response = client.post("/admin/notifications/flows/flow-1/reject")

    assert response.status_code == 200
    assert response.json()["data"]["flow"]["status"] == "archived"
    assert mock_update.call_args.args[2] == "archived"


def test_reject_requires_proposed_status():
    client = _client()
    with (
        patch("routers.admin.notifications.get_flow", return_value=_active_flow("active")),
        patch("routers.admin.notifications.update_flow_status") as mock_update,
    ):
        response = client.post("/admin/notifications/flows/flow-1/reject")

    assert response.status_code == 409
    mock_update.assert_not_called()


def test_get_run_includes_recipient_events():
    from modules.notification_flows import NotificationFlowRun
    from tests._supabase_mock import fluent

    client = _client()
    run = NotificationFlowRun(
        id="run-1",
        tenant_id=None,
        flow_id="flow-1",
        flow_run_key="flow-1:manual:run-1",
        trigger_kind="manual",
        audience_count=1,
        enqueued=1,
        skipped=0,
        failed=0,
        status="completed",
        created_at="2026-06-26T00:00:00+00:00",
        updated_at="2026-06-26T00:00:00+00:00",
    )
    event = {
        "id": "event-1",
        "user_id": "user-1",
        "recipient_email": "user@example.com",
        "status": "sent",
        "resend_message_id": "resend-1",
        "error_message": None,
        "skip_reason": None,
        "sent_at": "2026-06-26T00:01:00+00:00",
        "created_at": "2026-06-26T00:00:00+00:00",
    }
    with (
        patch("routers.admin.notifications.get_run", return_value=run),
        patch("routers.admin.notifications._supabase", return_value=fluent([event])),
    ):
        response = client.get("/admin/notifications/runs/run-1")

    assert response.status_code == 200
    assert response.json()["data"]["recipients"] == [event]


def test_stale_events_endpoint_lists_stuck_sending_rows():
    from tests._supabase_mock import fluent

    client = _client()
    stale = {
        "id": "event-stale",
        "status": "sending",
        "resend_message_id": None,
        "created_at": "2026-06-27T14:00:00+00:00",
    }
    with patch("routers.admin.notifications._supabase", return_value=fluent([stale])):
        response = client.get("/admin/notifications/stale-events?stale_after_minutes=15")

    assert response.status_code == 200
    assert response.json()["data"]["events"] == [stale]
