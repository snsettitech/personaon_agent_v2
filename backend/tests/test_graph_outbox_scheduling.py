"""Tests for delayed graph_outbox scheduling."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch


def _result(data: Any) -> SimpleNamespace:
    return SimpleNamespace(data=data)


def test_submit_writes_next_attempt_after_when_provided() -> None:
    from modules.graph_outbox import GraphOperationType, GraphOutbox

    captured_insert: list[dict[str, Any]] = []
    scheduled = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)

    select_chain = MagicMock()
    select_chain.eq.return_value = select_chain
    select_chain.in_.return_value = select_chain
    select_chain.execute.return_value = _result([])

    insert_chain = MagicMock()
    insert_chain.execute.return_value = _result([{"id": "job-1"}])

    table = MagicMock()
    table.select.return_value = select_chain
    table.insert.side_effect = lambda payload: (
        captured_insert.append(payload) or insert_chain
    )

    with patch("modules.graph_outbox.supabase") as mock_sb, \
         patch("modules.graph_outbox.enqueue_job"):
        mock_sb.table.return_value = table
        GraphOutbox().submit(
            tenant_id="tenant-1",
            twin_id="twin-1",
            operation=GraphOperationType.SEND_ACTION_ITEM_REMINDER,
            idempotency_key="action_item_reminder:meet-1:0",
            payload={"meeting_id": "meet-1"},
            next_attempt_after=scheduled,
        )

    assert captured_insert
    assert captured_insert[0]["next_attempt_after"] == scheduled.isoformat()


def test_submit_raises_on_legacy_schema_when_next_attempt_after_set() -> None:
    """Regression for review blocker #4 (F2.4).

    On a schema that lacks `scope_id`/`creator_id` (pre-Phase 1 deployment),
    the legacy fallback previously did `legacy_record.pop("next_attempt_after",
    None)` — silently dropping the schedule. That caused delayed reminders
    to fire immediately because the worker treats NULL as "run now".
    """
    from modules.graph_outbox import GraphOperationType, GraphOutbox

    scheduled = datetime(2099, 5, 28, 12, 0, tzinfo=timezone.utc)

    select_chain = MagicMock()
    select_chain.eq.return_value = select_chain
    select_chain.in_.return_value = select_chain
    select_chain.execute.return_value = _result([])

    # The first insert raises with a 'scope_id column' missing error,
    # triggering the legacy fallback branch.
    insert_chain = MagicMock()
    insert_chain.execute.side_effect = Exception(
        "column graph_outbox.scope_id does not exist"
    )

    table = MagicMock()
    table.select.return_value = select_chain
    table.insert.return_value = insert_chain

    import pytest

    with patch("modules.graph_outbox.supabase") as mock_sb, \
         patch("modules.graph_outbox.enqueue_job"):
        mock_sb.table.return_value = table
        with pytest.raises(RuntimeError, match="cannot preserve next_attempt_after"):
            GraphOutbox().submit(
                tenant_id="tenant-1",
                twin_id="twin-1",
                operation=GraphOperationType.SEND_ACTION_ITEM_REMINDER,
                idempotency_key="action_item_reminder:meet-1:0",
                payload={"meeting_id": "meet-1"},
                next_attempt_after=scheduled,
            )
