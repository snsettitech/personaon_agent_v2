"""Tests for Phase 30 action item reminder worker."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _result(data: Any) -> SimpleNamespace:
    return SimpleNamespace(data=data)


def _job() -> dict[str, Any]:
    return {
        "id": "job-reminder-1",
        "tenant_id": "tenant-1",
        "twin_id": "11111111-1111-1111-1111-111111111111",
        "operation": "send_action_item_reminder",
        "payload": {
            "meeting_id": "meet-1",
            "action_item_index": 0,
            "recipient_email": "owner@example.com",
            "user_id": "user-1",
        },
    }


@pytest.mark.asyncio
async def test_action_item_reminder_worker_sends_and_marks_sent() -> None:
    from modules.graph_outbox_worker import _process_send_action_item_reminder

    meeting = {
        "id": "meet-1",
        "title": "Launch planning",
        "tenant_id": "tenant-1",
        "twin_id": "11111111-1111-1111-1111-111111111111",
        "action_items": [{"text": "Send pricing", "due_at": "2999-05-28T12:00:00Z"}],
    }

    updates: list[dict[str, Any]] = []
    meeting_chain = MagicMock()
    meeting_chain.select.return_value = meeting_chain
    meeting_chain.eq.return_value = meeting_chain
    meeting_chain.maybe_single.return_value = meeting_chain
    meeting_chain.single.return_value = meeting_chain
    meeting_chain.execute.return_value = _result(meeting)

    prefs_chain = MagicMock()
    prefs_chain.select.return_value = prefs_chain
    prefs_chain.eq.return_value = prefs_chain
    prefs_chain.maybe_single.return_value = prefs_chain
    prefs_chain.execute.return_value = _result({"action_item_reminders_enabled": True})

    notif_chain = MagicMock()
    notif_chain.update.side_effect = lambda payload: (updates.append(payload) or notif_chain)
    notif_chain.eq.return_value = notif_chain
    notif_chain.execute.return_value = _result([{"id": "notif-1"}])

    def _table(name: str) -> MagicMock:
        if name == "notification_preferences":
            return prefs_chain
        if name == "meeting_notifications":
            return notif_chain
        return meeting_chain

    with patch("modules.graph_outbox_worker.supabase") as mock_sb, \
         patch("services.lifecycle_email_service.is_email_suppressed", return_value=False), \
         patch("services.email_service.send_email", new_callable=AsyncMock, return_value="msg-1") as mock_send:
        mock_sb.table.side_effect = _table
        ok = await _process_send_action_item_reminder(_job())

    assert ok is True
    # send_email called exactly once for this reminder. Per-item dedup is
    # provided by the graph_outbox idempotency_key (action_item_reminder:
    # {meeting_id}:{idx}) + Resend's idempotency_key — we deliberately no
    # longer call claim_notification_slot (its per-meeting key would have
    # silently dropped all items after the first; F2.3 review fix).
    mock_send.assert_awaited_once()
    send_kwargs = mock_send.await_args.kwargs
    assert send_kwargs["to"] == "owner@example.com"
    assert send_kwargs["idempotency_key"] == "action_item_reminder:meet-1:0"
    # meeting_notifications UPDATE intentionally not called any more.
    assert updates == []


@pytest.mark.asyncio
async def test_action_item_reminder_worker_sends_when_no_prefs_row() -> None:
    """Regression: a user with NO notification_preferences row.

    supabase-py `.maybe_single().execute()` returns None (not a response
    object) on zero rows. The worker previously did `prefs_resp.data` which
    AttributeError'd on None and failed the job forever. Reminders default
    to ENABLED when no preference row exists, so the email must still send.
    Found via a real local-DB worker run (the other tests always mocked
    prefs_resp to a response object, hiding this).
    """
    from modules.graph_outbox_worker import _process_send_action_item_reminder

    meeting = {
        "id": "meet-1",
        "title": "Launch planning",
        "tenant_id": "tenant-1",
        "twin_id": "11111111-1111-1111-1111-111111111111",
        "action_items": [{"text": "Send pricing", "due_at": "2999-05-28T12:00:00Z"}],
    }
    meeting_chain = MagicMock()
    meeting_chain.select.return_value = meeting_chain
    meeting_chain.eq.return_value = meeting_chain
    meeting_chain.maybe_single.return_value = meeting_chain
    meeting_chain.execute.return_value = _result(meeting)

    # prefs lookup returns None (the supabase-py zero-row behavior).
    prefs_chain = MagicMock()
    prefs_chain.select.return_value = prefs_chain
    prefs_chain.eq.return_value = prefs_chain
    prefs_chain.maybe_single.return_value = prefs_chain
    prefs_chain.execute.return_value = None  # <-- the bug condition

    def _table(name: str) -> MagicMock:
        if name == "notification_preferences":
            return prefs_chain
        return meeting_chain

    with patch("modules.graph_outbox_worker.supabase") as mock_sb, \
         patch("services.lifecycle_email_service.is_email_suppressed", return_value=False), \
         patch("services.email_service.send_email", new_callable=AsyncMock, return_value="msg-1") as mock_send:
        mock_sb.table.side_effect = _table
        ok = await _process_send_action_item_reminder(_job())

    assert ok is True
    mock_send.assert_awaited_once()  # defaults to enabled, sends


@pytest.mark.asyncio
async def test_action_item_reminder_worker_respects_disabled_preference() -> None:
    from modules.graph_outbox_worker import _process_send_action_item_reminder

    meeting_chain = MagicMock()
    meeting_chain.select.return_value = meeting_chain
    meeting_chain.eq.return_value = meeting_chain
    meeting_chain.maybe_single.return_value = meeting_chain
    meeting_chain.single.return_value = meeting_chain
    meeting_chain.execute.return_value = _result({
        "id": "meet-1",
        "title": "Launch planning",
        "tenant_id": "tenant-1",
        "twin_id": "11111111-1111-1111-1111-111111111111",
        "action_items": [{"text": "Send pricing"}],
    })

    prefs_chain = MagicMock()
    prefs_chain.select.return_value = prefs_chain
    prefs_chain.eq.return_value = prefs_chain
    prefs_chain.maybe_single.return_value = prefs_chain
    prefs_chain.execute.return_value = _result({"action_item_reminders_enabled": False})

    with patch("modules.graph_outbox_worker.supabase") as mock_sb, \
         patch("services.notification_service.claim_notification_slot", return_value=True), \
         patch("services.email_service.send_email", new_callable=AsyncMock) as mock_send:
        mock_sb.table.side_effect = lambda name: prefs_chain if name == "notification_preferences" else meeting_chain
        ok = await _process_send_action_item_reminder(_job())

    assert ok is True
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_action_item_reminder_worker_skips_suppressed_email() -> None:
    from modules.graph_outbox_worker import _process_send_action_item_reminder

    meeting_chain = MagicMock()
    meeting_chain.select.return_value = meeting_chain
    meeting_chain.eq.return_value = meeting_chain
    meeting_chain.maybe_single.return_value = meeting_chain
    meeting_chain.single.return_value = meeting_chain
    meeting_chain.execute.return_value = _result({
        "id": "meet-1",
        "title": "Launch planning",
        "tenant_id": "tenant-1",
        "twin_id": "11111111-1111-1111-1111-111111111111",
        "action_items": [{"text": "Send pricing"}],
    })
    prefs_chain = MagicMock()
    prefs_chain.select.return_value = prefs_chain
    prefs_chain.eq.return_value = prefs_chain
    prefs_chain.maybe_single.return_value = prefs_chain
    prefs_chain.execute.return_value = _result({"action_item_reminders_enabled": True})

    with patch("modules.graph_outbox_worker.supabase") as mock_sb, \
         patch("services.notification_service.claim_notification_slot", return_value=True), \
         patch("services.lifecycle_email_service.is_email_suppressed", return_value=True), \
         patch("services.email_service.send_email", new_callable=AsyncMock) as mock_send:
        mock_sb.table.side_effect = lambda name: prefs_chain if name == "notification_preferences" else meeting_chain
        ok = await _process_send_action_item_reminder(_job())

    assert ok is True
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_action_item_reminder_worker_sends_for_second_item_on_same_meeting() -> None:
    """Regression for review blocker #3 (F2.3): per-item dedup.

    Before the F2 fix, claim_notification_slot used a (twin_id, meeting_id,
    notification_type) unique key — so the FIRST action item reminder per
    meeting claimed the slot and every subsequent item silently dropped as
    'already sent'. Now the slot claim is removed and each item flows
    through independently (per-item dedup is provided by graph_outbox's
    idempotency_key which encodes the item index).
    """
    from modules.graph_outbox_worker import _process_send_action_item_reminder

    meeting = {
        "id": "meet-1",
        "title": "Launch planning",
        "tenant_id": "tenant-1",
        "twin_id": "11111111-1111-1111-1111-111111111111",
        "action_items": [
            {"text": "Item A", "due_at": "2999-05-28T12:00:00Z"},
            {"text": "Item B", "due_at": "2999-05-28T12:00:00Z"},
        ],
    }
    meeting_chain = MagicMock()
    meeting_chain.select.return_value = meeting_chain
    meeting_chain.eq.return_value = meeting_chain
    meeting_chain.maybe_single.return_value = meeting_chain
    meeting_chain.single.return_value = meeting_chain
    meeting_chain.execute.return_value = _result(meeting)

    prefs_chain = MagicMock()
    prefs_chain.select.return_value = prefs_chain
    prefs_chain.eq.return_value = prefs_chain
    prefs_chain.maybe_single.return_value = prefs_chain
    prefs_chain.execute.return_value = _result({"action_item_reminders_enabled": True})

    def _table(name: str) -> MagicMock:
        if name == "notification_preferences":
            return prefs_chain
        return meeting_chain

    job_template = {
        "id": "job-X",
        "tenant_id": "tenant-1",
        "twin_id": "11111111-1111-1111-1111-111111111111",
        "operation": "send_action_item_reminder",
        "payload": {
            "meeting_id": "meet-1",
            "recipient_email": "owner@example.com",
            "user_id": "user-1",
        },
    }

    with patch("modules.graph_outbox_worker.supabase") as mock_sb, \
         patch("services.lifecycle_email_service.is_email_suppressed", return_value=False), \
         patch("services.email_service.send_email", new_callable=AsyncMock, return_value="msg-X") as mock_send:
        mock_sb.table.side_effect = _table

        # First item — must send.
        job_a = {**job_template, "id": "job-A",
                 "payload": {**job_template["payload"], "action_item_index": 0,
                             "idempotency_key": "action_item_reminder:meet-1:0"}}
        ok_a = await _process_send_action_item_reminder(job_a)

        # Second item on the same meeting — must ALSO send (this is the bug).
        job_b = {**job_template, "id": "job-B",
                 "payload": {**job_template["payload"], "action_item_index": 1,
                             "idempotency_key": "action_item_reminder:meet-1:1"}}
        ok_b = await _process_send_action_item_reminder(job_b)

    assert ok_a is True
    assert ok_b is True
    # Critical: BOTH reminders sent. Before F2.3, only the first would.
    assert mock_send.await_count == 2


@pytest.mark.asyncio
async def test_action_item_reminder_worker_skips_cross_tenant_meeting() -> None:
    """Regression for review blocker #9: SELECT on meetings filters by
    tenant_id, so a cross-tenant meeting_id in the payload returns 0 rows
    and the worker short-circuits with True (done) without calling
    notification_preferences, suppression, claim_notification_slot, or
    send_email.
    """
    from modules.graph_outbox_worker import _process_send_action_item_reminder

    meeting_chain = MagicMock()
    meeting_chain.select.return_value = meeting_chain
    meeting_chain.eq.return_value = meeting_chain
    meeting_chain.maybe_single.return_value = meeting_chain
    meeting_chain.single.return_value = meeting_chain
    meeting_chain.execute.return_value = _result(None)

    with patch("modules.graph_outbox_worker.supabase") as mock_sb, \
         patch("services.notification_service.claim_notification_slot") as mock_claim, \
         patch("services.lifecycle_email_service.is_email_suppressed") as mock_suppress, \
         patch("services.email_service.send_email", new_callable=AsyncMock) as mock_send:
        mock_sb.table.return_value = meeting_chain
        ok = await _process_send_action_item_reminder({
            "id": "job-cross-tenant",
            "tenant_id": "tenant-A",
            "operation": "send_action_item_reminder",
            "payload": {
                "meeting_id": "meet-belongs-to-tenant-B",
                "action_item_index": 0,
                "recipient_email": "owner@example.com",
                "user_id": "user-1",
                "tenant_id": "tenant-A",
            },
        })

    assert ok is True
    # Critical: no downstream side effects.
    mock_claim.assert_not_called()
    mock_suppress.assert_not_called()
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_action_item_reminder_worker_refuses_send_when_user_id_empty() -> None:
    """Regression for F6.1 (BLOCKER P1): an outbox payload with empty
    user_id MUST NOT proceed past the early refuse-send guard. The prior
    code did `user_id or tenant_id` when looking up
    notification_preferences and the suppression list — silently
    substituting tenant_id as a user_id (it never matches a real row,
    so the opt-out gate evaluated to "no opt-out" and the reminder
    fired regardless of user preference).
    """
    from modules.graph_outbox_worker import _process_send_action_item_reminder

    with patch("modules.graph_outbox_worker.supabase") as mock_sb, \
         patch("services.lifecycle_email_service.is_email_suppressed") as mock_suppress, \
         patch("services.email_service.send_email", new_callable=AsyncMock) as mock_send:
        ok = await _process_send_action_item_reminder({
            "id": "job-no-user",
            "tenant_id": "tenant-1",
            "operation": "send_action_item_reminder",
            "payload": {
                "meeting_id": "11111111-1111-1111-1111-111111111111",
                "action_item_index": 0,
                "recipient_email": "owner@example.com",
                "user_id": "",  # empty — the bug condition
                "tenant_id": "tenant-1",
            },
        })

    assert ok is True
    # Critical: no preferences lookup, no suppression check, no send.
    mock_sb.table.assert_not_called()
    mock_suppress.assert_not_called()
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_action_item_reminder_worker_refuses_invalid_recipient_email() -> None:
    """Regression for F6.3 (HIGH H2): defense-in-depth — the worker
    re-validates recipient_email even though the router validates at
    enqueue. A corrupt outbox row or a future enqueue path missing the
    guard would otherwise relay to whatever string the job carried.
    """
    from modules.graph_outbox_worker import _process_send_action_item_reminder

    with patch("modules.graph_outbox_worker.supabase") as mock_sb, \
         patch("services.lifecycle_email_service.is_email_suppressed") as mock_suppress, \
         patch("services.email_service.send_email", new_callable=AsyncMock) as mock_send:
        ok = await _process_send_action_item_reminder({
            "id": "job-bad-email",
            "tenant_id": "tenant-1",
            "operation": "send_action_item_reminder",
            "payload": {
                "meeting_id": "11111111-1111-1111-1111-111111111111",
                "action_item_index": 0,
                "recipient_email": "not-a-valid-email",
                "user_id": "user-1",
                "tenant_id": "tenant-1",
            },
        })

    assert ok is True
    mock_sb.table.assert_not_called()
    mock_suppress.assert_not_called()
    mock_send.assert_not_called()
