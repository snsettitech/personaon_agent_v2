"""Tests for the Recall.ai Calendar V2 webhook handler (Task P1.1.D)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_request(body: bytes, headers: dict | None = None) -> MagicMock:
    request = MagicMock()
    request.body = AsyncMock(return_value=body)
    request.headers = headers or {
        "webhook-id": "wh_1",
        "webhook-timestamp": "1",
        "webhook-signature": "v1,ok",
    }
    return request


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_signature() -> None:
    from fastapi import HTTPException

    from routers.recall_calendar_webhook import recall_calendar_webhook

    request = _make_request(
        b'{"event": "calendar.sync_events", "data": {}}',
        headers={
            "webhook-id": "wh_1",
            "webhook-timestamp": "1",
            "webhook-signature": "v1,bad",
        },
    )

    with patch(
        "routers.recall_calendar_webhook.verify_recall_webhook",
        return_value=False,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await recall_calendar_webhook(request)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_sync_events_enqueues_outbox_job() -> None:
    from routers.recall_calendar_webhook import recall_calendar_webhook

    body = json.dumps({
        "event": "calendar.sync_events",
        "data": {
            "calendar_id": "cal_abc",
            "last_updated_ts": "2026-05-19T10:00:00Z",
        },
    }).encode()
    request = _make_request(body)

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[{
            "twin_id": "twin-xyz",
            "tenant_id": "tenant-1",
            "is_active": True,
        }])
    )

    mock_outbox = MagicMock()

    with (
        patch(
            "routers.recall_calendar_webhook.verify_recall_webhook",
            return_value=True,
        ),
        patch("routers.recall_calendar_webhook.supabase", mock_sb),
        patch(
            "routers.recall_calendar_webhook.get_graph_outbox",
            return_value=mock_outbox,
        ),
    ):
        result = await recall_calendar_webhook(request)

    assert result["status"] == "sync_enqueued"
    mock_outbox.submit.assert_called_once()
    kwargs = mock_outbox.submit.call_args.kwargs
    assert kwargs["twin_id"] == "twin-xyz"
    assert kwargs["tenant_id"] == "tenant-1"
    assert kwargs["payload"]["recall_calendar_id"] == "cal_abc"
    assert kwargs["payload"]["last_updated_ts"] == "2026-05-19T10:00:00Z"
    assert kwargs["payload"]["twin_id"] == "twin-xyz"
    # Idempotency key includes both calendar and timestamp to dedupe Recall retries
    assert "cal_abc" in kwargs["idempotency_key"]
    assert "2026-05-19T10:00:00Z" in kwargs["idempotency_key"]


@pytest.mark.asyncio
async def test_calendar_update_disconnected_deactivates_connector() -> None:
    from routers.recall_calendar_webhook import recall_calendar_webhook

    body = json.dumps({
        "event": "calendar.update",
        "data": {
            "calendar_id": "cal_abc",
            "calendar": {"status": "disconnected"},
        },
    }).encode()
    request = _make_request(body)

    update_payloads: list[dict] = []
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[{
            "twin_id": "twin-xyz",
            "tenant_id": "tenant-1",
            "is_active": True,
        }])
    )

    def capture_update(payload: dict) -> MagicMock:
        update_payloads.append(payload)
        m = MagicMock()
        m.eq.return_value.execute.return_value = MagicMock()
        return m

    mock_sb.table.return_value.update = capture_update

    with (
        patch(
            "routers.recall_calendar_webhook.verify_recall_webhook",
            return_value=True,
        ),
        patch("routers.recall_calendar_webhook.supabase", mock_sb),
    ):
        result = await recall_calendar_webhook(request)

    assert result["status"] == "calendar_update_processed"
    assert any(p.get("is_active") is False for p in update_payloads), (
        f"deactivation payload must include is_active=False; got {update_payloads}"
    )


@pytest.mark.asyncio
async def test_calendar_update_non_disconnected_status_is_noop() -> None:
    """A calendar.update with status=connected should NOT deactivate anything."""
    from routers.recall_calendar_webhook import recall_calendar_webhook

    body = json.dumps({
        "event": "calendar.update",
        "data": {
            "calendar_id": "cal_abc",
            "calendar": {"status": "connected"},
        },
    }).encode()
    request = _make_request(body)

    update_payloads: list[dict] = []
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[{
            "twin_id": "twin-xyz",
            "tenant_id": "tenant-1",
            "is_active": True,
        }])
    )

    def capture_update(payload: dict) -> MagicMock:
        update_payloads.append(payload)
        m = MagicMock()
        m.eq.return_value.execute.return_value = MagicMock()
        return m

    mock_sb.table.return_value.update = capture_update

    with (
        patch(
            "routers.recall_calendar_webhook.verify_recall_webhook",
            return_value=True,
        ),
        patch("routers.recall_calendar_webhook.supabase", mock_sb),
    ):
        result = await recall_calendar_webhook(request)

    assert result["status"] == "calendar_update_processed"
    assert update_payloads == [], (
        f"connected status must not trigger an update; got {update_payloads}"
    )


@pytest.mark.asyncio
async def test_orphan_calendar_id_returns_ignored() -> None:
    """Webhook for a calendar_id not in tool_connectors should ack but not enqueue."""
    from routers.recall_calendar_webhook import recall_calendar_webhook

    body = json.dumps({
        "event": "calendar.sync_events",
        "data": {
            "calendar_id": "cal_orphan",
            "last_updated_ts": "2026-05-19T10:00:00Z",
        },
    }).encode()
    request = _make_request(body)

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[])
    )

    mock_outbox = MagicMock()

    with (
        patch(
            "routers.recall_calendar_webhook.verify_recall_webhook",
            return_value=True,
        ),
        patch("routers.recall_calendar_webhook.supabase", mock_sb),
        patch(
            "routers.recall_calendar_webhook.get_graph_outbox",
            return_value=mock_outbox,
        ),
    ):
        result = await recall_calendar_webhook(request)

    assert result["status"] == "ignored_orphan"
    mock_outbox.submit.assert_not_called()


@pytest.mark.asyncio
async def test_missing_calendar_id_returns_ignored() -> None:
    """Webhook payload missing calendar_id should ack without DB lookup."""
    from routers.recall_calendar_webhook import recall_calendar_webhook

    body = json.dumps({
        "event": "calendar.sync_events",
        "data": {"last_updated_ts": "2026-05-19T10:00:00Z"},
    }).encode()
    request = _make_request(body)

    mock_sb = MagicMock()

    with (
        patch(
            "routers.recall_calendar_webhook.verify_recall_webhook",
            return_value=True,
        ),
        patch("routers.recall_calendar_webhook.supabase", mock_sb),
    ):
        result = await recall_calendar_webhook(request)

    assert result["status"] == "ignored_no_calendar_id"
    mock_sb.table.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_event_type_is_acknowledged() -> None:
    """Future Recall event types should be acknowledged, not 500."""
    from routers.recall_calendar_webhook import recall_calendar_webhook

    body = json.dumps({
        "event": "calendar.something_new",
        "data": {"calendar_id": "cal_abc"},
    }).encode()
    request = _make_request(body)

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[{
            "twin_id": "twin-xyz",
            "tenant_id": "tenant-1",
            "is_active": True,
        }])
    )

    with (
        patch(
            "routers.recall_calendar_webhook.verify_recall_webhook",
            return_value=True,
        ),
        patch("routers.recall_calendar_webhook.supabase", mock_sb),
    ):
        result = await recall_calendar_webhook(request)

    assert result["status"] == "ignored_unknown_event"


@pytest.mark.asyncio
async def test_enqueue_failure_returns_deferred_200() -> None:
    """If outbox.submit raises, we must still return 200 so Recall does not retry forever."""
    from routers.recall_calendar_webhook import recall_calendar_webhook

    body = json.dumps({
        "event": "calendar.sync_events",
        "data": {
            "calendar_id": "cal_abc",
            "last_updated_ts": "2026-05-19T10:00:00Z",
        },
    }).encode()
    request = _make_request(body)

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[{
            "twin_id": "twin-xyz",
            "tenant_id": "tenant-1",
            "is_active": True,
        }])
    )

    mock_outbox = MagicMock()
    mock_outbox.submit.side_effect = RuntimeError("queue is down")

    with (
        patch(
            "routers.recall_calendar_webhook.verify_recall_webhook",
            return_value=True,
        ),
        patch("routers.recall_calendar_webhook.supabase", mock_sb),
        patch(
            "routers.recall_calendar_webhook.get_graph_outbox",
            return_value=mock_outbox,
        ),
    ):
        result = await recall_calendar_webhook(request)

    assert result["status"] == "deferred_enqueue_error"


@pytest.mark.asyncio
async def test_sync_events_skipped_for_inactive_connector() -> None:
    """L24: a sync_events webhook for a connector that's been disconnected
    (is_active=False) must NOT enqueue a sync job. Otherwise a late-arriving
    webhook upserts meetings into a calendar the user already disconnected."""
    from routers.recall_calendar_webhook import recall_calendar_webhook

    body = json.dumps({
        "event": "calendar.sync_events",
        "data": {
            "calendar_id": "cal_inactive",
            "last_updated_ts": "2026-05-19T10:00:00Z",
        },
    }).encode()
    request = _make_request(body)

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[{
            "twin_id": "twin-xyz",
            "tenant_id": "tenant-1",
            "is_active": False,  # connector was disconnected
        }])
    )

    mock_outbox = MagicMock()

    with (
        patch(
            "routers.recall_calendar_webhook.verify_recall_webhook",
            return_value=True,
        ),
        patch("routers.recall_calendar_webhook.supabase", mock_sb),
        patch(
            "routers.recall_calendar_webhook.get_graph_outbox",
            return_value=mock_outbox,
        ),
    ):
        result = await recall_calendar_webhook(request)

    assert result["status"] == "ignored_inactive"
    mock_outbox.submit.assert_not_called()


@pytest.mark.asyncio
async def test_sync_events_uses_initial_sentinel_when_last_updated_ts_missing() -> None:
    """L25: when last_updated_ts is missing (initial sync or odd Recall payload),
    the idempotency key must use the literal sentinel 'initial' rather than the
    string 'None' -- otherwise the first None-keyed sync's job permanently
    dedupes every future None-keyed call to the completed state."""
    from routers.recall_calendar_webhook import recall_calendar_webhook

    body = json.dumps({
        "event": "calendar.sync_events",
        "data": {
            "calendar_id": "cal_initial",
            # last_updated_ts deliberately omitted
        },
    }).encode()
    request = _make_request(body)

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[{
            "twin_id": "twin-xyz",
            "tenant_id": "tenant-1",
            "is_active": True,
        }])
    )

    mock_outbox = MagicMock()

    with (
        patch(
            "routers.recall_calendar_webhook.verify_recall_webhook",
            return_value=True,
        ),
        patch("routers.recall_calendar_webhook.supabase", mock_sb),
        patch(
            "routers.recall_calendar_webhook.get_graph_outbox",
            return_value=mock_outbox,
        ),
    ):
        result = await recall_calendar_webhook(request)

    assert result["status"] == "sync_enqueued"
    mock_outbox.submit.assert_called_once()
    key = mock_outbox.submit.call_args.kwargs["idempotency_key"]
    assert "initial" in key, (
        f"idempotency_key must use 'initial' sentinel when last_updated_ts is "
        f"missing; got {key!r}"
    )
    assert "None" not in key, (
        f"idempotency_key must not literally contain 'None'; got {key!r}"
    )


@pytest.mark.asyncio
async def test_db_lookup_failure_returns_deferred_200() -> None:
    """If the tool_connectors lookup raises, we must still return 200 (deferred)."""
    from routers.recall_calendar_webhook import recall_calendar_webhook

    body = json.dumps({
        "event": "calendar.sync_events",
        "data": {
            "calendar_id": "cal_abc",
            "last_updated_ts": "2026-05-19T10:00:00Z",
        },
    }).encode()
    request = _make_request(body)

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.side_effect = (
        RuntimeError("supabase is down")
    )

    with (
        patch(
            "routers.recall_calendar_webhook.verify_recall_webhook",
            return_value=True,
        ),
        patch("routers.recall_calendar_webhook.supabase", mock_sb),
    ):
        result = await recall_calendar_webhook(request)

    assert result["status"] == "deferred_db_error"
