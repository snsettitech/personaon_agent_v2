from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class _Result:
    data: Any


class _Query:
    def __init__(self, sb: _FakeSupabase, table_name: str):
        self.sb = sb
        self.table_name = table_name
        self.filters: list[tuple[str, str, Any]] = []
        self.in_filters: list[tuple[str, set[Any]]] = []
        self.update_patch: dict[str, Any] | None = None
        self.limit_count: int | None = None

    def select(self, *_args: Any, **_kwargs: Any) -> _Query:
        return self

    def eq(self, column: str, value: Any) -> _Query:
        self.filters.append((column, "eq", value))
        return self

    def in_(self, column: str, values: list[Any]) -> _Query:
        self.in_filters.append((column, set(values)))
        return self

    def limit(self, count: int) -> _Query:
        self.limit_count = count
        return self

    def update(self, patch: dict[str, Any]) -> _Query:
        self.update_patch = dict(patch)
        return self

    def execute(self) -> _Result:
        if self.update_patch is not None:
            rows = self._matching_rows()
            for row in rows:
                row.update(self.update_patch)
            self.sb.updates.append((self.table_name, dict(self.update_patch), list(self.filters)))
            return _Result(rows)

        rows = [dict(row) for row in self._matching_rows()]
        if self.limit_count is not None:
            rows = rows[: self.limit_count]
        return _Result(rows)

    def _matching_rows(self) -> list[dict[str, Any]]:
        rows = self.sb.rows.get(self.table_name, [])
        for column, _operator, value in self.filters:
            rows = [row for row in rows if row.get(column) == value]
        for column, values in self.in_filters:
            rows = [row for row in rows if row.get(column) in values]
        return rows


class _FakeSupabase:
    def __init__(self, rows: dict[str, list[dict[str, Any]]]):
        self.rows = rows
        self.updates: list[tuple[str, dict[str, Any], list[tuple[str, str, Any]]]] = []

    def table(self, table_name: str) -> _Query:
        return _Query(self, table_name)


def _run_row() -> dict[str, Any]:
    return {
        "id": "run-1",
        "tenant_id": "tenant-1",
        "flow_id": "flow-1",
        "flow_run_key": "flow-1:manual:run-1",
        "audience_count": 3,
        "enqueued": 3,
        "skipped": 0,
        "failed": 0,
        "status": "completed",
        "summary": {"segment": "all_active"},
        "created_at": "2026-06-28T14:00:00+00:00",
    }


def _event_row(index: int, *, message_id: str | None, status: str = "sent") -> dict[str, Any]:
    return {
        "id": f"event-{index}",
        "user_id": f"user-{index}",
        "tenant_id": "tenant-1",
        "email_type": "feature_launch",
        "category": "announcements",
        "scope_type": "announcement",
        "scope_id": "run-1",
        "period_key": f"user-{index}",
        "recipient_email": f"user{index}@example.com",
        "status": status,
        "resend_message_id": message_id,
        "payload": {"subject": "New in PersonaOn", "cta_label": "Try it now"},
        "created_at": "2026-06-28T14:05:00+00:00",
    }


def _webhook_row(svix_id: str, event_type: str, message_id: str) -> dict[str, Any]:
    return {
        "svix_id": svix_id,
        "event_type": event_type,
        "resend_message_id": message_id,
        "payload": {},
        "received_at": "2026-06-28T14:00:00+00:00",
    }


def _fake_sb(*, webhooks: list[dict[str, Any]] | None = None) -> _FakeSupabase:
    return _FakeSupabase(
        {
            "notification_flow_runs": [_run_row()],
            "notification_flows": [
                {
                    "id": "flow-1",
                    "tenant_id": "tenant-1",
                    "email_type": "feature_launch",
                    "category": "announcements",
                    "context_overrides": {
                        "event_type": "feature.launched",
                        "flag": "workspace_search",
                    },
                }
            ],
            "lifecycle_email_events": [
                _event_row(1, message_id="msg-1"),
                _event_row(2, message_id="msg-2"),
                _event_row(3, message_id="msg-3"),
            ],
            "resend_webhook_events": webhooks
            if webhooks is not None
            else [
                _webhook_row("svix-1", "email.opened", "msg-1"),
                _webhook_row("svix-2", "email.opened", "msg-2"),
                _webhook_row("svix-3", "email.clicked", "msg-2"),
            ],
        }
    )


def test_measures_three_recipients_two_opens_one_click_one_conversion():
    from services.notification_outcomes import measure_notification_outcome

    sb = _fake_sb()
    memory_calls: list[tuple[Any, dict[str, Any]]] = []
    measured_at = datetime(2026, 6, 28, 14, 30, tzinfo=timezone.utc)

    outcome = measure_notification_outcome(
        sb,
        "run-1",
        conversion_counter=lambda _user_ids, _event_name, _start, _end: 1,
        memory_writer=lambda *args: memory_calls.append(args),
        measured_at=measured_at,
    )

    assert outcome.recipient_count == 3
    assert outcome.sent_count == 3
    assert outcome.open_count == 2
    assert outcome.click_count == 1
    assert outcome.conversion_count == 1
    assert outcome.conversion_source == "posthog"
    assert outcome.opened_message_ids == ["msg-1", "msg-2"]
    assert outcome.clicked_message_ids == ["msg-2"]

    update = sb.updates[0][1]
    assert update["open_count"] == 2
    assert update["click_count"] == 1
    assert update["conversion_count"] == 1
    assert update["outcome_measured_at"] == measured_at.isoformat()
    assert update["summary"]["segment"] == "all_active"
    assert update["summary"]["outcome"]["conversion_count"] == 1
    assert len(memory_calls) == 1
    assert memory_calls[0][1].flow_run_id == "run-1"
    assert memory_calls[0][1].open_rate == 2 / 3
    assert memory_calls[0][1].conversion_rate == 1 / 3


def test_duplicate_webhooks_are_counted_once_per_message():
    from services.notification_outcomes import measure_notification_outcome

    sb = _fake_sb(
        webhooks=[
            _webhook_row("svix-1", "email.opened", "msg-1"),
            _webhook_row("svix-dup", "email.opened", "msg-1"),
            _webhook_row("svix-2", "email.opened", "msg-2"),
            _webhook_row("svix-3", "email.clicked", "msg-2"),
            _webhook_row("svix-4", "email.clicked", "msg-2"),
        ]
    )

    outcome = measure_notification_outcome(
        sb,
        "run-1",
        conversion_counter=lambda _user_ids, _event_name, _start, _end: 0,
        memory_writer=lambda *_args: None,
    )

    assert outcome.open_count == 2
    assert outcome.click_count == 1
    assert outcome.opened_message_ids == ["msg-1", "msg-2"]
    assert outcome.clicked_message_ids == ["msg-2"]


def test_missing_posthog_config_falls_back_to_zero_conversions():
    from services.notification_outcomes import measure_notification_outcome

    sb = _fake_sb()
    sb.rows["notification_flows"][0]["context_overrides"] = {}

    outcome = measure_notification_outcome(
        sb,
        "run-1",
        memory_writer=lambda *_args: None,
    )

    assert outcome.conversion_count == 0
    assert outcome.conversion_source == "not_configured"
    assert sb.updates[0][1]["conversion_count"] == 0


def test_memory_writer_receives_one_outcome_memory_call():
    from services.notification_outcomes import measure_notification_outcome

    sb = _fake_sb()
    calls: list[tuple[Any, dict[str, Any]]] = []

    measure_notification_outcome(
        sb,
        "run-1",
        conversion_counter=lambda _user_ids, _event_name, _start, _end: 1,
        memory_writer=lambda *args: calls.append(args),
    )

    assert len(calls) == 1
    call_sb, memory = calls[0]
    assert call_sb is sb
    assert memory.flow_run_id == "run-1"
    assert memory.event_type == "feature.launched"
    assert memory.email_type == "feature_launch"
    assert memory.category == "announcements"
    assert memory.open_count == 2
    assert memory.click_count == 1
    assert memory.subject == "New in PersonaOn"


def test_schedule_notification_outcome_measurement_uses_stable_idempotency_key():
    from datetime import datetime, timezone

    from modules.graph_outbox import GraphOperationType
    from services.notification_outcomes import schedule_notification_outcome_measurement

    outbox = _MockOutbox()
    schedule_notification_outcome_measurement(
        outbox=outbox,
        tenant_id="tenant-1",
        flow_run_id="run-1",
        flow_id="flow-1",
        now=datetime(2026, 6, 28, tzinfo=timezone.utc),
    )

    assert len(outbox.calls) == 1
    call = outbox.calls[0]
    assert call["operation"] == GraphOperationType.MEASURE_NOTIFICATION_OUTCOME
    assert call["idempotency_key"] == "measure-notification-outcome-run-1"
    assert call["scope_id"] == "run-1"
    assert call["payload"] == {"flow_run_id": "run-1", "flow_id": "flow-1"}


class _MockOutbox:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def submit(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
