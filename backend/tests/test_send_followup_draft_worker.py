"""Tests for the send_followup_draft graph_outbox handler (Phase B3).

Requires the full backend import chain (google-adk etc.); runs in CI. The
handler sends an owner-approved follow-up draft via Resend, off the request
path, with defense-in-depth tenant scoping + recipient validation.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from tests._supabase_mock import fluent


def _job(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "job-1",
        "tenant_id": "tenant-1",
        "operation": "send_followup_draft",
        "idempotency_key": "send_followup:draft-1",
        "payload": payload,
    }


def _draft(**over: Any) -> dict[str, Any]:
    base = {
        "id": "draft-1",
        "tenant_id": "tenant-1",
        "twin_id": "twin-1",
        "status": "approved",
        "proposed_action": {
            "action_type": "draft_email",
            "params": {"to": "lead@example.com", "subject": "Following up", "body": "Hi there"},
        },
    }
    base.update(over)
    return base


async def _fake_run_db(fn):
    """Run the handler's DB lambda so the fluent supabase mock drives results."""
    return fn()


@pytest.mark.asyncio
async def test_dispatch_routes_send_followup_draft() -> None:
    from modules import graph_outbox_worker
    from modules.graph_outbox import GraphOperationType

    job = _job({"draft_id": "draft-1", "tenant_id": "tenant-1"})
    job["operation"] = GraphOperationType.SEND_FOLLOWUP_DRAFT.value
    with patch.object(
        graph_outbox_worker, "_process_send_followup_draft",
        new_callable=AsyncMock, return_value=True,
    ) as handler:
        result = await graph_outbox_worker._dispatch(job)
    assert result is True
    handler.assert_awaited_once_with(job)


@pytest.mark.asyncio
async def test_send_followup_draft_sends_and_marks_executed() -> None:
    from modules import graph_outbox_worker as w

    send_mock = AsyncMock(return_value="msg-1")
    with patch.object(w, "_run_db", _fake_run_db), \
            patch.object(w, "supabase", fluent(_draft())), \
            patch("services.email_service.send_email", send_mock), \
            patch("modules.email_validation.is_valid_email", lambda e: "@" in (e or "")):
        ok = await w._process_send_followup_draft(_job({"draft_id": "draft-1", "tenant_id": "tenant-1"}))

    assert ok is True
    send_mock.assert_awaited_once()
    kwargs = send_mock.await_args.kwargs
    assert kwargs["to"] == "lead@example.com"
    assert kwargs["subject"] == "Following up"
    assert kwargs["idempotency_key"] == "send_followup:draft-1"


@pytest.mark.asyncio
async def test_send_followup_draft_bad_payload_noop() -> None:
    from modules import graph_outbox_worker as w

    send_mock = AsyncMock(return_value="msg-1")
    with patch.object(w, "_run_db", _fake_run_db), \
            patch.object(w, "supabase", fluent(_draft())), \
            patch("services.email_service.send_email", send_mock), \
            patch("modules.email_validation.is_valid_email", lambda e: True):
        ok = await w._process_send_followup_draft(_job({}))  # no draft_id

    assert ok is True
    send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_followup_draft_missing_or_cross_tenant_noop() -> None:
    from modules import graph_outbox_worker as w

    send_mock = AsyncMock(return_value="msg-1")
    with patch.object(w, "_run_db", _fake_run_db), \
            patch.object(w, "supabase", fluent(None)), \
            patch("services.email_service.send_email", send_mock), \
            patch("modules.email_validation.is_valid_email", lambda e: True):
        ok = await w._process_send_followup_draft(_job({"draft_id": "draft-1", "tenant_id": "tenant-1"}))

    assert ok is True
    send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_followup_draft_rejects_invalid_recipient() -> None:
    from modules import graph_outbox_worker as w

    bad = _draft(proposed_action={"action_type": "draft_email", "params": {"to": "not-an-email", "body": "x"}})
    send_mock = AsyncMock(return_value="msg-1")
    with patch.object(w, "_run_db", _fake_run_db), \
            patch.object(w, "supabase", fluent(bad)), \
            patch("services.email_service.send_email", send_mock), \
            patch("modules.email_validation.is_valid_email", lambda e: "@" in (e or "")):
        ok = await w._process_send_followup_draft(_job({"draft_id": "draft-1", "tenant_id": "tenant-1"}))

    assert ok is True  # bad data is terminal, not retried
    send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_followup_draft_returns_false_on_send_error() -> None:
    from modules import graph_outbox_worker as w

    with patch.object(w, "_run_db", _fake_run_db), \
            patch.object(w, "supabase", fluent(_draft())), \
            patch("services.email_service.send_email", AsyncMock(side_effect=RuntimeError("resend down"))), \
            patch("modules.email_validation.is_valid_email", lambda e: True):
        ok = await w._process_send_followup_draft(_job({"draft_id": "draft-1", "tenant_id": "tenant-1"}))

    assert ok is False  # transient → retry
