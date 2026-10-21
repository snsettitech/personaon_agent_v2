"""Tests for POST /v2/desktop-recordings/{id}/stop (Granola — Stop → summary).

Covers:
- owner gate (401 unauthenticated, 404 cross-tenant)
- flips status recording → processing (scoped by id AND tenant_id)
- enqueues ENHANCE_NOTES (stable key) off live segments + notes, twin-optional
- arms recap_timeout_check watchdog (independent of enhance enqueue)
- idempotent no-op when already terminal/processing
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from modules.auth_guard import verify_owner
from routers.desktop_recordings import router

USER = {"user_id": "user-1", "tenant_id": "tenant-1", "email": "u1@example.com"}
OTHER_USER = {"user_id": "user-2", "tenant_id": "tenant-2", "email": "u2@example.com"}
MEETING_ID = "11111111-1111-1111-1111-111111111111"


def _result(data: Any) -> SimpleNamespace:
    return SimpleNamespace(data=data)


def _owned_row(*, tenant_id: str = "tenant-1", status: str = "recording", twin_id: Any = None) -> dict[str, Any]:
    return {
        "id": MEETING_ID,
        "tenant_id": tenant_id,
        "status": status,
        "twin_id": twin_id,
    }


def _client(user: dict[str, Any] | None) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    if user is not None:
        app.dependency_overrides[verify_owner] = lambda: user
    else:
        app.dependency_overrides[verify_owner] = lambda: (_ for _ in ()).throw(
            HTTPException(status_code=401, detail="Authentication required")
        )
    return TestClient(app, raise_server_exceptions=False)


def _supabase_mock(owned_row: dict[str, Any] | None, *, update_returns: Any = None) -> MagicMock:
    """Mock supabase chain.

    _fetch_owned does select().eq().maybe_single().execute() -> owned_row.
    stop_recording does update().eq().eq().execute() -> update_returns.
    Both run through the same chain mock; execute() returns owned_row first
    (the fetch) then update_returns (the flip). Use side_effect to sequence.
    """
    chain = MagicMock()
    for method in ("select", "eq", "update", "maybe_single"):
        getattr(chain, method).return_value = chain
    # First execute(): _fetch_owned select. Second: the UPDATE flip.
    update_rows = update_returns if update_returns is not None else [owned_row]
    chain.execute.side_effect = [_result(owned_row), _result(update_rows)]
    sb = MagicMock()
    sb.table.return_value = chain
    return sb


def test_stop_requires_auth() -> None:
    resp = _client(None).post(f"/v2/desktop-recordings/{MEETING_ID}/stop")
    assert resp.status_code == 401


def test_stop_cross_tenant_returns_404() -> None:
    sb = _supabase_mock(_owned_row(tenant_id="tenant-1"))
    with patch("routers.desktop_recordings.supabase", sb):
        resp = _client(OTHER_USER).post(f"/v2/desktop-recordings/{MEETING_ID}/stop")
    assert resp.status_code == 404


def test_stop_flips_status_enqueues_and_arms() -> None:
    sb = _supabase_mock(_owned_row(status="recording", twin_id=None))
    submitted: list[dict[str, Any]] = []

    outbox = MagicMock()

    def _submit(**kwargs: Any) -> str:
        submitted.append(kwargs)
        return f"job-{len(submitted)}"

    outbox.submit.side_effect = _submit

    with patch("routers.desktop_recordings.supabase", sb), \
         patch("modules.graph_outbox.get_graph_outbox", return_value=outbox):
        resp = _client(USER).post(f"/v2/desktop-recordings/{MEETING_ID}/stop")

    assert resp.status_code == 200
    assert resp.json()["data"]["stopped"] is True

    # Status flip happened with id + tenant scoping.
    update_args = next(
        c for c in sb.table.return_value.update.call_args_list
    )
    flip = update_args.args[0]
    assert flip["status"] == "processing"
    assert flip["recap_stage"] == "enhancing"
    # id AND tenant scoping on the UPDATE.
    eq_calls = {c.args for c in sb.table.return_value.eq.call_args_list}
    assert ("id", MEETING_ID) in eq_calls
    assert ("tenant_id", "tenant-1") in eq_calls

    # Two jobs: ENHANCE_NOTES then RECAP_TIMEOUT_CHECK.
    ops = [s["operation"].value for s in submitted]
    assert "enhance_notes" in ops
    assert "recap_timeout_check" in ops

    enhance = next(s for s in submitted if s["operation"].value == "enhance_notes")
    # Stable key (NOT timestamped) so a webhook redelivery dedupes.
    assert enhance["idempotency_key"] == f"enhance_notes:{MEETING_ID}"
    assert enhance["payload"]["meeting_id"] == MEETING_ID
    # twin-optional: None passes through, not gated.
    assert enhance["twin_id"] is None

    watchdog = next(s for s in submitted if s["operation"].value == "recap_timeout_check")
    assert watchdog["idempotency_key"] == f"recap_timeout_check:{MEETING_ID}"
    assert watchdog["next_attempt_after"] is not None


def test_stop_arms_watchdog_even_if_enhance_enqueue_fails() -> None:
    """The watchdog arm is an INDEPENDENT try/except — a failed enhance enqueue
    must not prevent the row from ever being flipped to a terminal state."""
    sb = _supabase_mock(_owned_row(status="recording"))
    submitted: list[dict[str, Any]] = []

    outbox = MagicMock()

    def _submit(**kwargs: Any) -> str:
        if kwargs["operation"].value == "enhance_notes":
            raise RuntimeError("outbox down for enhance")
        submitted.append(kwargs)
        return "job-watchdog"

    outbox.submit.side_effect = _submit

    with patch("routers.desktop_recordings.supabase", sb), \
         patch("modules.graph_outbox.get_graph_outbox", return_value=outbox):
        resp = _client(USER).post(f"/v2/desktop-recordings/{MEETING_ID}/stop")

    # Stop still succeeds (the row was flipped); the watchdog still armed.
    assert resp.status_code == 200
    assert resp.json()["data"]["stopped"] is True
    ops = [s["operation"].value for s in submitted]
    assert "recap_timeout_check" in ops


def test_stop_is_idempotent_when_already_processing() -> None:
    sb = _supabase_mock(_owned_row(status="processing"))
    outbox = MagicMock()
    with patch("routers.desktop_recordings.supabase", sb), \
         patch("modules.graph_outbox.get_graph_outbox", return_value=outbox):
        resp = _client(USER).post(f"/v2/desktop-recordings/{MEETING_ID}/stop")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["stopped"] is False
    assert body["data"]["reason"] == "not_active"
    # No re-enqueue, no re-arm.
    outbox.submit.assert_not_called()


def test_stop_idempotent_when_already_completed() -> None:
    sb = _supabase_mock(_owned_row(status="completed"))
    outbox = MagicMock()
    with patch("routers.desktop_recordings.supabase", sb), \
         patch("modules.graph_outbox.get_graph_outbox", return_value=outbox):
        resp = _client(USER).post(f"/v2/desktop-recordings/{MEETING_ID}/stop")

    assert resp.status_code == 200
    assert resp.json()["data"]["stopped"] is False
    outbox.submit.assert_not_called()
