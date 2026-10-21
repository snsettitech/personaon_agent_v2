"""Admin user account notification event enqueue tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _event(event_id: str, event_type: str, subject_id: str):
    return SimpleNamespace(id=event_id, event_type=event_type, subject_id=subject_id)


def test_grant_all_enqueues_access_granted_event_job():
    from modules.graph_outbox import GraphOperationType
    from routers.admin import users

    outbox = MagicMock()
    outbox.submit.return_value = "job-1"
    event = _event("event-1", "account.access_granted", "user-1")
    with (
        patch.object(users, "set_entitlements", return_value={"status": "ok", "data": {"user_id": "user-1"}}),
        patch("services.account_notification_service.emit_notification_event", return_value=event) as emit,
        patch("services.account_notification_service.get_graph_outbox", return_value=outbox),
    ):
        result = users.grant_all_features("user-1", {"user_id": "admin-1", "email": "admin@personaon.com"})

    assert result["status"] == "ok"
    emitted = emit.call_args.args[1]
    assert emitted.event_type == "account.access_granted"
    assert emitted.actor_id == "admin-1"
    assert emitted.subject_id == "user-1"
    outbox.submit.assert_called_once()
    assert outbox.submit.call_args.kwargs["operation"] == GraphOperationType.PROCESS_NOTIFICATION_EVENT
    assert outbox.submit.call_args.kwargs["payload"]["event_id"] == "event-1"
    assert outbox.submit.call_args.kwargs["idempotency_key"] == "access-granted-user-1"
    assert outbox.submit.call_args.kwargs["scope_id"]


def test_suspend_enqueues_account_suspended_event_job():
    from modules.graph_outbox import GraphOperationType
    from routers.admin import users

    sb = MagicMock()
    outbox = MagicMock()
    outbox.submit.return_value = "job-2"
    event = _event("event-2", "account.suspended", "user-2")
    with (
        patch.object(users, "_supabase", return_value=sb),
        patch("modules.admin_audit.record_admin_action"),
        patch("services.account_notification_service.emit_notification_event", return_value=event) as emit,
        patch("services.account_notification_service.get_graph_outbox", return_value=outbox),
    ):
        result = users.suspend_user("user-2", {"user_id": "admin-1", "email": "admin@personaon.com"})

    assert result["data"]["suspended"] is True
    sb.auth.admin.update_user_by_id.assert_called_once()
    emitted = emit.call_args.args[1]
    assert emitted.event_type == "account.suspended"
    assert emitted.actor_id == "admin-1"
    outbox.submit.assert_called_once()
    assert outbox.submit.call_args.kwargs["operation"] == GraphOperationType.PROCESS_NOTIFICATION_EVENT
    assert outbox.submit.call_args.kwargs["payload"]["event_id"] == "event-2"
    assert outbox.submit.call_args.kwargs["idempotency_key"] == "account-suspended-user-2"


def test_account_notification_uses_stable_scope_for_duplicate_submit():
    from routers.admin import users

    sb = MagicMock()
    outbox = MagicMock()
    outbox.submit.return_value = "job-stable"
    with (
        patch.object(users, "_supabase", return_value=sb),
        patch("modules.admin_audit.record_admin_action"),
        patch(
            "services.account_notification_service.emit_notification_event",
            side_effect=[
                _event("event-stable-1", "account.suspended", "user-stable"),
                _event("event-stable-2", "account.suspended", "user-stable"),
            ],
        ),
        patch("services.account_notification_service.get_graph_outbox", return_value=outbox),
    ):
        users.suspend_user("user-stable", {"user_id": "admin-1", "email": "admin@personaon.com"})
        users.suspend_user("user-stable", {"user_id": "admin-1", "email": "admin@personaon.com"})

    first = outbox.submit.call_args_list[0].kwargs
    second = outbox.submit.call_args_list[1].kwargs
    assert first["idempotency_key"] == second["idempotency_key"] == "account-suspended-user-stable"
    assert first["scope_id"] == second["scope_id"]
    assert first["payload"]["event_id"] == "event-stable-1"
    assert second["payload"]["event_id"] == "event-stable-2"


def test_grant_all_notification_failure_does_not_block_grant():
    from routers.admin import users

    with (
        patch.object(users, "set_entitlements", return_value={"status": "ok", "data": {"user_id": "user-3"}}),
        patch(
            "services.account_notification_service.emit_notification_event",
            side_effect=RuntimeError("event table down"),
        ),
    ):
        result = users.grant_all_features("user-3", {"user_id": "admin-1", "email": "admin@personaon.com"})

    assert result["status"] == "ok"
