"""
Tests for notification worker handlers (Phase 28-02).

Requirements: MTG-21 (CRON scheduler + auth), MTG-23 (post-meeting follow-up),
              MTG-24 (weekly digest), MTG-26 (deduplication via meeting_notifications),
              MTG-27 (notification preferences)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# MTG-21: CRON scheduler authentication
# ---------------------------------------------------------------------------

def test_pre_meeting_cron_rejects_no_auth():
    """POST /v2/cron/pre-meeting-check returns 401 when no valid auth is provided."""
    import os
    from fastapi.testclient import TestClient

    # Patch env to have CRON_SECRET set (enables secret path) but provide no header
    with (
        patch.dict(os.environ, {"CLOUD_RUN_SERVICE_URL": "", "CRON_SECRET": "secret-123"}),
        patch("modules.observability.supabase"),
    ):
        # Re-import to pick up patched env
        import importlib
        import routers.notifications as notifications_module
        importlib.reload(notifications_module)

        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(notifications_module.router)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/v2/cron/pre-meeting-check")
        assert response.status_code == 401


def test_pre_meeting_cron_enqueues_jobs():
    """The CRON handler enqueues GENERATE_MEETING_BRIEFING jobs for upcoming meetings."""
    import os
    from fastapi.testclient import TestClient

    mock_meetings = [
        {"id": "m-1", "twin_id": "twin-1", "tenant_id": "tenant-1", "title": "Standup",
         "attendees": ["Alice"], "meeting_start": "2026-04-15T10:00:00"},
        {"id": "m-2", "twin_id": "twin-2", "tenant_id": "tenant-2", "title": "Review",
         "attendees": ["Bob"], "meeting_start": "2026-04-15T10:30:00"},
    ]

    mock_meetings_resp = MagicMock()
    mock_meetings_resp.data = mock_meetings

    mock_outbox = MagicMock()

    with (
        patch.dict(os.environ, {"CLOUD_RUN_SERVICE_URL": "", "CRON_SECRET": "secret-123"}),
        patch("modules.observability.supabase") as mock_supabase,
        patch("modules.graph_outbox.get_graph_outbox", return_value=mock_outbox),
    ):
        import importlib
        import routers.notifications as notifications_module
        importlib.reload(notifications_module)

        mock_supabase.table.return_value.select.return_value.gte.return_value.lte.return_value.execute.return_value = mock_meetings_resp

        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(notifications_module.router)
        client = TestClient(app)

        response = client.post(
            "/v2/cron/pre-meeting-check",
            headers={"X-Cron-Secret": "secret-123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["data"]["enqueued"] == 2


# ---------------------------------------------------------------------------
# MTG-23: Post-meeting follow-up enqueue path
# ---------------------------------------------------------------------------

def test_followup_enqueued_after_index():
    """Verifies that _process_index_meeting_transcript enqueues GENERATE_MEETING_FOLLOWUP."""
    import asyncio

    job = {
        "id": "job-idx-1",
        "payload": {"meeting_id": "meeting-789"},
    }

    mock_meeting_resp = MagicMock()
    mock_meeting_resp.data = {
        "id": "meeting-789",
        "twin_id": "twin-abc",
        "tenant_id": "tenant-xyz",
        "transcript_raw": [{"speaker": "Alice", "text": "Hello world"}],
        "transcript_text": "Alice: Hello world",
    }

    mock_chunks = [{"id": "chunk-1", "text": "Alice: Hello world"}]
    mock_outbox = MagicMock()

    with (
        patch("modules.graph_outbox_worker.supabase") as mock_supabase,
        patch("services.meeting_indexer.chunk_transcript_by_turns", return_value=mock_chunks),
        patch("services.meeting_indexer.index_meeting_chunks", new_callable=AsyncMock, return_value=1),
        patch("services.meeting_indexer.extract_entities", new_callable=AsyncMock, return_value={}),
        patch("modules.graph_outbox_worker.get_graph_outbox", return_value=mock_outbox),
    ):
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_meeting_resp
        mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        from modules.graph_outbox_worker import _process_index_meeting_transcript
        result = asyncio.run(_process_index_meeting_transcript(job))

    assert result is True
    # Verify followup job was submitted to outbox
    mock_outbox.submit.assert_called_once()
    submit_kwargs = mock_outbox.submit.call_args
    from modules.graph_outbox import GraphOperationType
    assert submit_kwargs.kwargs["operation"] == GraphOperationType.GENERATE_MEETING_FOLLOWUP
    assert submit_kwargs.kwargs["payload"]["meeting_id"] == "meeting-789"


# ---------------------------------------------------------------------------
# MTG-26: Deduplication via meeting_notifications
# ---------------------------------------------------------------------------

def test_claim_slot_returns_false_on_duplicate():
    """claim_notification_slot returns False when row already exists (upsert ignored)."""
    # Supabase upsert with ignore_duplicates=True returns empty data when row already exists
    mock_resp = MagicMock()
    mock_resp.data = []  # empty = duplicate was ignored

    with patch("modules.observability.supabase") as mock_supabase:
        mock_supabase.table.return_value.upsert.return_value.execute.return_value = mock_resp

        from services.notification_service import claim_notification_slot
        result = claim_notification_slot("twin-abc", "meeting-123", "pre_meeting_briefing", "tenant-xyz")

    assert result is False


def test_handler_skips_if_slot_already_claimed():
    """Briefing handler returns True without sending if claim_notification_slot returns False."""
    job = {
        "id": "job-1",
        "twin_id": "twin-abc",
        "tenant_id": "tenant-xyz",
        "payload": {"meeting_id": "meeting-123"},
    }

    with (
        patch("services.notification_service.load_notification_prefs") as mock_prefs,
        patch("services.notification_service.claim_notification_slot") as mock_claim,
        patch("services.email_service.send_email", new_callable=AsyncMock) as mock_send,
    ):
        mock_prefs.return_value = {"pre_meeting": True, "post_meeting": True, "weekly_digest": True}
        mock_claim.return_value = False  # already sent

        import asyncio
        from modules.graph_outbox_worker import _process_generate_meeting_briefing
        result = asyncio.run(_process_generate_meeting_briefing(job))

    assert result is True
    mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# MTG-27: Notification preferences gate
# ---------------------------------------------------------------------------

def test_handler_respects_disabled_pref():
    """Handler skips sending and returns True when pre_meeting pref is disabled."""
    job = {
        "id": "job-2",
        "twin_id": "twin-abc",
        "tenant_id": "tenant-xyz",
        "payload": {"meeting_id": "meeting-456"},
    }

    with (
        patch("services.notification_service.load_notification_prefs") as mock_prefs,
        patch("services.notification_service.claim_notification_slot") as mock_claim,
        patch("services.email_service.send_email", new_callable=AsyncMock) as mock_send,
    ):
        mock_prefs.return_value = {"pre_meeting": False, "post_meeting": True, "weekly_digest": True}

        import asyncio
        from modules.graph_outbox_worker import _process_generate_meeting_briefing
        result = asyncio.run(_process_generate_meeting_briefing(job))

    assert result is True
    mock_claim.assert_not_called()
    mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# MTG-24: Weekly digest skip threshold
# ---------------------------------------------------------------------------

def test_digest_skips_twins_with_few_meetings():
    """Weekly digest handler returns True (skip) when twin has < 3 completed meetings in past 7 days."""
    import asyncio

    job = {
        "id": "job-digest-1",
        "twin_id": "twin-abc",
        "tenant_id": "tenant-xyz",
        "payload": {"twin_id": "twin-abc"},
    }

    # Only 2 meetings — below the MIN_MEETINGS_FOR_DIGEST=3 threshold
    mock_meetings_resp = MagicMock()
    mock_meetings_resp.data = [
        {"id": "m-1", "title": "Meeting 1", "summary_json": {"executive_summary": "Summary 1"}},
        {"id": "m-2", "title": "Meeting 2", "summary_json": {"executive_summary": "Summary 2"}},
    ]

    mock_prefs_resp = MagicMock()
    mock_prefs_resp.data = {"settings": {}}  # weekly_digest defaults to True

    mock_claim_resp = MagicMock()
    mock_claim_resp.data = [{"id": "notif-1"}]  # claim succeeds

    with (
        patch("services.notification_service.load_notification_prefs") as mock_prefs,
        patch("services.notification_service.claim_notification_slot") as mock_claim,
        patch("services.email_service.send_email", new_callable=AsyncMock) as mock_send,
        patch("modules.graph_outbox_worker.get_supabase_client") as mock_sb_client,
        patch("modules.graph_outbox_worker.supabase") as mock_supabase,
    ):
        mock_prefs.return_value = {"pre_meeting": True, "post_meeting": True, "weekly_digest": True}
        mock_claim.return_value = True  # claim succeeds

        # Mock the service-role client meetings query
        mock_admin_sb = MagicMock()
        mock_sb_client.return_value = mock_admin_sb
        mock_admin_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.execute.return_value = mock_meetings_resp

        # Mock the module-level supabase used for skipped update
        mock_supabase.table.return_value.update.return_value.eq.return_value.is_.return_value.eq.return_value.execute.return_value = MagicMock()

        from modules.graph_outbox_worker import _process_generate_weekly_digest
        result = asyncio.run(_process_generate_weekly_digest(job))

    assert result is True
    mock_send.assert_not_called()  # skipped — insufficient meetings


# ---------------------------------------------------------------------------
# Agentic notification flow executor
# ---------------------------------------------------------------------------


def _notification_flow(*, status="active", max_recipients=500, exempt=False, kind="announcement"):
    from modules.notification_flows import (
        AudienceSpec,
        FlowGuardrails,
        NotificationFlow,
    )

    return NotificationFlow(
        id="flow-1",
        tenant_id="platform",
        key="feature_launch_v1",
        name="Feature Launch",
        kind=kind,
        trigger_type="manual",
        audience_spec=AudienceSpec(segment="all_active"),
        email_type="feature_launch",
        category="announcements",
        context_overrides={"subject": "New in PersonaOn"},
        schedule_cron=None,
        guardrails=FlowGuardrails(
            max_recipients=max_recipients,
            throttle_per_min=0,
            dry_run_required=True,
            exempt_from_caps=exempt,
        ),
        created_by="agent:notification_agent",
        status=status,
        approved_by=None,
        approved_at=None,
        created_at="2026-06-26T00:00:00+00:00",
        updated_at="2026-06-26T00:00:00+00:00",
    )


def _resolved_audience(count=3):
    from modules.audience import RecipientRow, ResolvedAudience

    recipients = [
        RecipientRow(user_id=f"user-{i}", email=f"user{i}@example.com", tenant_id=f"tenant-{i}")
        for i in range(count)
    ]
    return ResolvedAudience(recipients=recipients, count=count, segment_label="test")


@pytest.mark.asyncio
async def test_dry_run_returns_count_no_enqueue():
    from modules.graph_outbox_worker import _process_run_notification_flow

    outbox = MagicMock()
    with (
        patch("modules.notification_flows.get_flow", return_value=_notification_flow()),
        patch("modules.audience.resolve_audience", new_callable=AsyncMock, return_value=_resolved_audience(3)),
        patch("modules.notification_flows.create_run", return_value="run-dry"),
        patch("modules.notification_flows.close_run") as mock_close,
        patch("modules.graph_outbox_worker.get_graph_outbox", return_value=outbox),
    ):
        result = await _process_run_notification_flow(
            {"id": "job-1", "operation": "run_notification_flow", "payload": {"flow_id": "flow-1", "dry_run": True}}
        )

    assert result is True
    outbox.submit.assert_not_called()
    mock_close.assert_called_once()
    assert mock_close.call_args.kwargs["enqueued"] == 0
    assert mock_close.call_args.kwargs["skipped"] == 3


@pytest.mark.asyncio
async def test_live_run_enqueues_per_recipient():
    from modules.graph_outbox import GraphOperationType
    from modules.graph_outbox_worker import _process_run_notification_flow

    outbox = MagicMock()
    with (
        patch("modules.notification_flows.get_flow", return_value=_notification_flow()),
        patch("modules.audience.resolve_audience", new_callable=AsyncMock, return_value=_resolved_audience(3)),
        patch("modules.notification_flows.create_run", return_value="run-1"),
        patch("modules.notification_flows.close_run"),
        patch("modules.graph_outbox_worker.get_graph_outbox", return_value=outbox),
        patch("services.notification_outcomes.schedule_notification_outcome_measurement") as mock_schedule,
    ):
        result = await _process_run_notification_flow(
            {
                "id": "job-2",
                "operation": "run_notification_flow",
                "payload": {"flow_id": "flow-1", "flow_run_id": "run-1", "dry_run": False},
            }
        )

    assert result is True
    assert outbox.submit.call_count == 3
    period_keys = [call.kwargs["payload"]["period_key"] for call in outbox.submit.call_args_list]
    assert period_keys == ["user-0", "user-1", "user-2"]
    assert {call.kwargs["operation"] for call in outbox.submit.call_args_list} == {
        GraphOperationType.SEND_LIFECYCLE_EMAIL
    }
    mock_schedule.assert_called_once()


@pytest.mark.asyncio
async def test_run_reuses_flow_run_id_on_retry():
    from modules.graph_outbox_worker import _process_run_notification_flow

    outbox = MagicMock()
    with (
        patch("modules.notification_flows.get_flow", return_value=_notification_flow()),
        patch("modules.audience.resolve_audience", new_callable=AsyncMock, return_value=_resolved_audience(2)),
        patch("modules.notification_flows.create_run", return_value="retry-run") as mock_create,
        patch("modules.notification_flows.close_run"),
        patch("modules.graph_outbox_worker.get_graph_outbox", return_value=outbox),
        patch("services.notification_outcomes.schedule_notification_outcome_measurement"),
    ):
        result = await _process_run_notification_flow(
            {
                "id": "job-3",
                "operation": "run_notification_flow",
                "payload": {"flow_id": "flow-1", "flow_run_id": "retry-run", "dry_run": False},
            }
        )

    assert result is True
    assert mock_create.call_args.kwargs["run_id"] == "retry-run"
    assert {call.kwargs["scope_id"] for call in outbox.submit.call_args_list} == {"retry-run"}


@pytest.mark.asyncio
async def test_cap_enforcement():
    from modules.graph_outbox_worker import _process_run_notification_flow

    outbox = MagicMock()
    with (
        patch("modules.notification_flows.get_flow", return_value=_notification_flow(max_recipients=2)),
        patch("modules.audience.resolve_audience", new_callable=AsyncMock, return_value=_resolved_audience(5)),
        patch("modules.notification_flows.create_run", return_value="run-cap"),
        patch("modules.notification_flows.close_run"),
        patch("modules.graph_outbox_worker.get_graph_outbox", return_value=outbox),
        patch("services.notification_outcomes.schedule_notification_outcome_measurement"),
    ):
        result = await _process_run_notification_flow(
            {"id": "job-4", "operation": "run_notification_flow", "payload": {"flow_id": "flow-1", "dry_run": False}}
        )

    assert result is True
    assert outbox.submit.call_count == 2


@pytest.mark.asyncio
async def test_flow_not_active_returns_true():
    from modules.graph_outbox_worker import _process_run_notification_flow

    outbox = MagicMock()
    with (
        patch("modules.notification_flows.get_flow", return_value=_notification_flow(status="paused")),
        patch("modules.audience.resolve_audience", new_callable=AsyncMock) as mock_resolve,
        patch("modules.graph_outbox_worker.get_graph_outbox", return_value=outbox),
    ):
        result = await _process_run_notification_flow(
            {"id": "job-5", "operation": "run_notification_flow", "payload": {"flow_id": "flow-1", "dry_run": False}}
        )

    assert result is True
    mock_resolve.assert_not_called()
    outbox.submit.assert_not_called()


@pytest.mark.asyncio
async def test_announcement_per_recipient_dedup():
    from modules.graph_outbox_worker import _process_run_notification_flow

    outbox = MagicMock()
    with (
        patch("modules.notification_flows.get_flow", return_value=_notification_flow()),
        patch("modules.audience.resolve_audience", new_callable=AsyncMock, return_value=_resolved_audience(3)),
        patch("modules.notification_flows.create_run", return_value="same-run"),
        patch("modules.notification_flows.close_run"),
        patch("modules.graph_outbox_worker.get_graph_outbox", return_value=outbox),
        patch("services.notification_outcomes.schedule_notification_outcome_measurement"),
    ):
        result = await _process_run_notification_flow(
            {
                "id": "job-6",
                "operation": "run_notification_flow",
                "payload": {"flow_id": "flow-1", "flow_run_id": "same-run", "dry_run": False},
            }
        )

    assert result is True
    keys = [call.kwargs["idempotency_key"] for call in outbox.submit.call_args_list]
    assert keys == ["notif-same-run-user-0", "notif-same-run-user-1", "notif-same-run-user-2"]
    assert {call.kwargs["payload"]["scope_id"] for call in outbox.submit.call_args_list} == {"same-run"}


@pytest.mark.asyncio
async def test_transactional_exempt_from_caps():
    from modules.graph_outbox_worker import _process_run_notification_flow

    outbox = MagicMock()
    with (
        patch(
            "modules.notification_flows.get_flow",
            return_value=_notification_flow(max_recipients=1, exempt=True, kind="transactional"),
        ),
        patch("modules.audience.resolve_audience", new_callable=AsyncMock, return_value=_resolved_audience(3)),
        patch("modules.notification_flows.create_run", return_value="run-transactional"),
        patch("modules.notification_flows.close_run"),
        patch("modules.graph_outbox_worker.get_graph_outbox", return_value=outbox),
        patch("services.notification_outcomes.schedule_notification_outcome_measurement"),
    ):
        result = await _process_run_notification_flow(
            {
                "id": "job-7",
                "operation": "run_notification_flow",
                "payload": {"flow_id": "flow-1", "flow_run_id": "run-transactional", "dry_run": False},
            }
        )

    assert result is True
    assert outbox.submit.call_count == 3


@pytest.mark.asyncio
async def test_dispatch_routes_process_notification_event():
    from modules import graph_outbox_worker
    from modules.graph_outbox import GraphOperationType

    job = {
        "id": "job-process-event",
        "operation": GraphOperationType.PROCESS_NOTIFICATION_EVENT.value,
        "payload": {"event_id": "event-1"},
    }

    with patch.object(graph_outbox_worker, "_process_notification_event", return_value=True) as mock_handler:
        assert await graph_outbox_worker._dispatch(job) is True

    mock_handler.assert_awaited_once_with(job)


@pytest.mark.asyncio
async def test_process_notification_event_enqueues_generated_lifecycle_email():
    from datetime import datetime, timezone

    from modules.audience import RecipientRow, ResolvedAudience
    from modules.graph_outbox import GraphOperationType
    from modules.notification_events import NotificationEvent
    from services.notification_agent import GENERATED_EMAIL_TYPE, process_notification_event

    event = NotificationEvent(
        id="event-access-1",
        tenant_id="tenant-1",
        event_type="account.access_granted",
        actor_id="admin-1",
        subject_id="user-1",
        context_json={"source": "test"},
        status="pending",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    audience = ResolvedAudience(
        recipients=[RecipientRow(user_id="user-1", email="user@example.com", tenant_id="tenant-1")],
        count=1,
        segment_label="user_list",
    )
    outbox = MagicMock()

    with (
        patch("modules.notification_events.get_notification_event", return_value=event),
        patch("services.notification_agent.mark_notification_event_processing"),
        patch("services.notification_agent.mark_notification_event_processed") as mark_processed,
        patch("services.notification_agent.mark_notification_event_failed") as mark_failed,
        patch("services.notification_agent.resolve_audience", new_callable=AsyncMock, return_value=audience),
        patch("services.notification_agent.get_graph_outbox", return_value=outbox),
        patch("services.notification_agent.get_flow_by_key", return_value=_notification_flow(kind="transactional", exempt=True)),
        patch("services.notification_agent._stable_event_run_id", return_value="run-event"),
        patch("services.notification_agent.create_run", return_value="run-event"),
        patch("services.notification_agent.close_run"),
        patch("services.notification_agent.retrieve_prior_outcomes", return_value=[]),
        patch("services.notification_agent.schedule_notification_outcome_measurement") as mock_schedule,
    ):
        assert await process_notification_event(MagicMock(), "event-access-1") is True

    outbox.submit.assert_called_once()
    kwargs = outbox.submit.call_args.kwargs
    assert kwargs["operation"] == GraphOperationType.SEND_LIFECYCLE_EMAIL
    assert kwargs["idempotency_key"] == "notif-event-event-access-1-user-1"
    assert kwargs["payload"]["email_type"] == GENERATED_EMAIL_TYPE
    assert kwargs["payload"]["category"] == "account"
    assert kwargs["payload"]["scope_id"] == "run-event"
    assert kwargs["payload"]["period_key"] == "user-1"
    assert kwargs["payload"]["payload"]["generated_email"] is True
    assert kwargs["payload"]["payload"]["memory_context_count"] == 0
    assert kwargs["payload"]["payload"]["subject"]
    assert kwargs["payload"]["payload"]["body"]
    mock_schedule.assert_called_once()
    mark_processed.assert_called_once()
    assert mark_processed.call_args.args[1] == event.id
    mark_failed.assert_not_called()


@pytest.mark.asyncio
async def test_process_notification_event_tenant_id_propagated():
    """Tenant id from the event must flow through to the submitted outbox job."""
    from datetime import datetime, timezone

    from modules.audience import RecipientRow, ResolvedAudience
    from modules.notification_events import NotificationEvent
    from services.notification_agent import process_notification_event

    event = NotificationEvent(
        id="event-tenant-check",
        tenant_id="tenant-abc",
        event_type="account.access_granted",
        actor_id="admin-1",
        subject_id="user-1",
        context_json={},
        status="pending",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    audience = ResolvedAudience(
        recipients=[RecipientRow(user_id="user-1", email="user@example.com", tenant_id="tenant-abc")],
        count=1,
        segment_label="user_list",
    )
    outbox = MagicMock()

    with (
        patch("modules.notification_events.get_notification_event", return_value=event),
        patch("services.notification_agent.mark_notification_event_processing"),
        patch("services.notification_agent.mark_notification_event_processed"),
        patch("services.notification_agent.mark_notification_event_failed"),
        patch("services.notification_agent.resolve_audience", new_callable=AsyncMock, return_value=audience),
        patch("services.notification_agent.get_graph_outbox", return_value=outbox),
        patch("services.notification_agent.get_flow_by_key", return_value=_notification_flow(kind="transactional", exempt=True)),
        patch("services.notification_agent._stable_event_run_id", return_value="run-tenant"),
        patch("services.notification_agent.create_run", return_value="run-tenant"),
        patch("services.notification_agent.close_run"),
        patch("services.notification_agent.retrieve_prior_outcomes", return_value=[]),
        patch("services.notification_agent.schedule_notification_outcome_measurement"),
    ):
        result = await process_notification_event(MagicMock(), "event-tenant-check")

    assert result is True
    kwargs = outbox.submit.call_args.kwargs
    assert kwargs["tenant_id"] == "tenant-abc", "tenant_id must not be None or empty"
    assert kwargs["payload"]["tenant_id"] == "tenant-abc"


@pytest.mark.asyncio
async def test_process_feature_launch_event_creates_proposed_generated_flow():
    from datetime import datetime, timezone

    from modules.notification_events import NotificationEvent
    from services.notification_agent import GENERATED_EMAIL_TYPE, process_notification_event

    event = NotificationEvent(
        id="event-feature-1",
        tenant_id="tenant-1",
        event_type="feature.launched",
        actor_id="admin-1",
        subject_id="workspace_search",
        context_json={
            "flag": "workspace_search",
            "feature_name": "Workspace Search",
            "description": "Search across your PersonaOn workspace.",
            "cta_path": "/dashboard/search",
        },
        status="pending",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    with (
        patch("modules.notification_events.get_notification_event", return_value=event),
        patch("services.notification_agent.mark_notification_event_processing"),
        patch("services.notification_agent.mark_notification_event_processed") as mark_processed,
        patch("services.notification_agent.mark_notification_event_failed") as mark_failed,
        patch("services.notification_agent.get_flow_by_key", return_value=None),
        patch("services.notification_agent.create_flow") as create_flow,
        patch("services.notification_agent.retrieve_prior_outcomes", return_value=[]),
        patch("services.notification_agent.get_graph_outbox") as outbox_factory,
    ):
        assert await process_notification_event(MagicMock(), "event-feature-1") is True

    create_flow.assert_called_once()
    created = create_flow.call_args.args[1]
    assert created.email_type == GENERATED_EMAIL_TYPE
    assert created.kind == "announcement"
    assert created.context_overrides["generated_email"] is True
    assert created.context_overrides["subject"] == "New in PersonaOn: Workspace Search"
    assert created.context_overrides["body"] == "Search across your PersonaOn workspace."
    assert created.context_overrides["cta_path"] == "/dashboard/search"
    outbox_factory.assert_not_called()
    mark_processed.assert_called_once()
    assert mark_processed.call_args.args[1] == event.id
    mark_failed.assert_not_called()
