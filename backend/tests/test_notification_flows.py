"""Tests for agentic notification flow foundations."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tests._supabase_mock import fluent


FLOW_ROW = {
    "id": "11111111-1111-4111-8111-111111111111",
    "tenant_id": None,
    "key": "feature_launch_v1",
    "name": "Feature Launch",
    "kind": "announcement",
    "trigger_type": "manual",
    "audience_spec": {"segment": "all_active"},
    "email_type": "feature_launch",
    "category": "announcements",
    "context_overrides": {},
    "schedule_cron": None,
    "status": "proposed",
    "guardrails": {"max_recipients": 500, "throttle_per_min": 30},
    "created_by": "agent:notification_agent",
    "approved_by": None,
    "approved_at": None,
    "created_at": "2026-06-26T00:00:00+00:00",
    "updated_at": "2026-06-26T00:00:00+00:00",
}


def test_create_flow_and_get_by_key():
    from modules.notification_flows import (
        AudienceSpec,
        NotificationFlowCreate,
        create_flow,
        get_flow_by_key,
    )

    sb = fluent([FLOW_ROW])
    created = create_flow(
        sb,
        NotificationFlowCreate(
            key="feature_launch_v1",
            name="Feature Launch",
            kind="announcement",
            trigger_type="manual",
            audience_spec=AudienceSpec(segment="all_active"),
            email_type="feature_launch",
            category="announcements",
            created_by="agent:notification_agent",
        ),
    )
    loaded = get_flow_by_key(sb, "feature_launch_v1")

    assert created.id == FLOW_ROW["id"]
    assert loaded is not None
    assert loaded.key == "feature_launch_v1"
    assert loaded.audience_spec.segment == "all_active"


def test_update_flow_status_proposed_to_active():
    from modules.notification_flows import update_flow_status

    row = {**FLOW_ROW, "status": "active", "approved_by": "admin@example.com"}
    flow = update_flow_status(fluent([row]), FLOW_ROW["id"], "active", "admin@example.com")

    assert flow.status == "active"
    assert flow.approved_by == "admin@example.com"


def test_create_run_returns_id():
    from modules.notification_flows import create_run

    run_id = "22222222-2222-4222-8222-222222222222"
    sb = fluent([{"id": run_id}])

    assert create_run(sb, FLOW_ROW["id"], "manual", 3) == run_id


@pytest.mark.asyncio
async def test_dispatch_routes_measure_notification_outcome():
    from modules import graph_outbox_worker
    from modules.graph_outbox import GraphOperationType

    job = {
        "id": "job-notif-stub",
        "operation": GraphOperationType.MEASURE_NOTIFICATION_OUTCOME.value,
        "payload": {"flow_run_id": "run-1", "flow_id": FLOW_ROW["id"]},
    }

    with patch.object(
        graph_outbox_worker,
        "_process_measure_notification_outcome",
        return_value=True,
    ) as mock_handler:
        assert await graph_outbox_worker._dispatch(job) is True

    mock_handler.assert_awaited_once_with(job)


@pytest.mark.asyncio
async def test_dispatch_routes_run_notification_flow():
    from modules import graph_outbox_worker
    from modules.graph_outbox import GraphOperationType

    job = {
        "id": "job-notif-run",
        "operation": GraphOperationType.RUN_NOTIFICATION_FLOW.value,
        "payload": {"flow_id": FLOW_ROW["id"]},
    }

    with patch.object(
        graph_outbox_worker,
        "_process_run_notification_flow",
        return_value=True,
    ) as mock_handler:
        assert await graph_outbox_worker._dispatch(job) is True

    mock_handler.assert_awaited_once_with(job)


@pytest.mark.asyncio
async def test_dispatch_routes_process_notification_event():
    from modules import graph_outbox_worker
    from modules.graph_outbox import GraphOperationType

    job = {
        "id": "job-notif-event",
        "operation": GraphOperationType.PROCESS_NOTIFICATION_EVENT.value,
        "payload": {"event_id": "event-1"},
    }

    with patch.object(
        graph_outbox_worker,
        "_process_notification_event",
        return_value=True,
    ) as mock_handler:
        assert await graph_outbox_worker._dispatch(job) is True

    mock_handler.assert_awaited_once_with(job)


def test_email_definitions_include_account_templates():
    from services.lifecycle_email_service import CATEGORY_PREF_FIELD, EMAIL_DEFINITIONS

    assert EMAIL_DEFINITIONS["access_granted"]["category"] == "account"
    assert EMAIL_DEFINITIONS["access_granted"]["subject"] == "You're in — your PersonaOn access is ready"
    assert EMAIL_DEFINITIONS["account_suspended"]["category"] == "account"
    assert EMAIL_DEFINITIONS["account_suspended"]["cta_path"] == "mailto:support@personaon.com"
    assert EMAIL_DEFINITIONS["feature_launch"]["category"] == "announcements"
    assert EMAIL_DEFINITIONS["feature_launch"]["subject"] == "New in PersonaOn: {feature_name}"
    assert EMAIL_DEFINITIONS["feature_launch"]["body"] == "{feature_summary}"
    assert CATEGORY_PREF_FIELD["announcements"] == "announcements_enabled"


def test_category_account_claim_succeeds():
    from services.lifecycle_email_service import claim_lifecycle_email_event

    event_row = {
        "id": "33333333-3333-4333-8333-333333333333",
        "idempotency_key": "lifecycle:user-1:access_granted:user:run-1:user-1",
    }

    with patch("modules.observability.supabase", fluent([event_row])):
        claimed = claim_lifecycle_email_event(
            user_id="user-1",
            tenant_id="tenant-1",
            email_type="access_granted",
            category="account",
            scope_type="user",
            scope_id="run-1",
            period_key="user-1",
            recipient_email="user@example.com",
        )

    assert claimed is not None
    assert claimed["id"] == event_row["id"]


def test_category_account_migration_expands_check():
    migration = Path(__file__).resolve().parents[2] / "supabase/migrations/20260626000150_notification_category_check.sql"
    sql = migration.read_text(encoding="utf-8")

    assert "'account'" in sql
    assert "'announcements'" in sql


@pytest.mark.asyncio
async def test_seed_transactional_flows_reactivates_existing_builtin_flow():
    from modules.notification_flows import NotificationFlow
    from services import notification_seed

    sb = fluent([])
    paused = FLOW_ROW | {
        "id": "flow-access-granted",
        "key": "access_granted",
        "kind": "transactional",
        "trigger_type": "event",
        "audience_spec": {"segment": "single_user"},
        "email_type": "access_granted",
        "category": "account",
        "status": "paused",
        "guardrails": {"max_recipients": 1, "throttle_per_min": 60, "dry_run_required": False, "exempt_from_caps": True},
    }

    with (
        patch.object(
            notification_seed,
            "get_flow_by_key",
            # SEED_FLOWS grew beyond two entries; key the response by flow key
            # instead of relying on call order.
            side_effect=lambda _sb, key: NotificationFlow.model_validate(paused) if key == "access_granted" else None,
        ),
        patch.object(notification_seed, "create_flow", return_value=NotificationFlow.model_validate(FLOW_ROW)),
        patch.object(notification_seed, "update_flow_status") as mock_update,
    ):
        await notification_seed.seed_transactional_flows(sb)

    mock_update.assert_any_call(sb, "flow-access-granted", "active", approved_by="system:seed")
