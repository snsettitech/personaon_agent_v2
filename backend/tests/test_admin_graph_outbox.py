"""Tests for the /admin/graph-outbox/* endpoints (Layer 4 of worker-smooth).

Operators use these to inspect failed/stuck jobs and retry without manual
DB intervention. Auth is via `require_admin` (owner/admin/support role).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.auth_guard import require_admin
from routers.admin import router as admin_router


ADMIN_USER = {"user_id": "admin-1", "tenant_id": "tenant-admin", "email": "admin@personaon.com"}


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router)
    app.dependency_overrides[require_admin] = lambda: ADMIN_USER
    return app


def _chain(rows: Any) -> MagicMock:
    """Build a fluent supabase chain that returns rows on .execute()."""
    m = MagicMock()
    for method in ("select", "eq", "lt", "order", "limit", "update"):
        getattr(m, method).return_value = m
    m.execute.return_value = SimpleNamespace(data=rows)
    return m


def test_retry_endpoint_resets_failed_job_to_pending() -> None:
    """POST /admin/graph-outbox/retry/{id} on a failed job resets it."""
    select_chain = _chain(
        [{"id": "job-1", "status": "failed", "operation": "generate_meeting_summary", "attempt_count": 5}]
    )
    update_chain = _chain([{"id": "job-1"}])
    captured_updates: list[dict[str, Any]] = []
    update_chain.update.side_effect = lambda payload: (
        captured_updates.append(payload) or update_chain
    )

    table_calls = [select_chain, update_chain]
    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda _name: table_calls.pop(0) if table_calls else update_chain

    with patch("routers.admin._common.get_supabase_client", return_value=mock_sb):
        client = TestClient(_app())
        resp = client.post("/admin/graph-outbox/retry/job-1")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["data"]["new_status"] == "pending"
    assert body["data"]["attempt_count"] == 0

    # The UPDATE included status=pending + attempt_count=0 + next_attempt_after.
    payload = captured_updates[0]
    assert payload["status"] == "pending"
    assert payload["attempt_count"] == 0
    assert "next_attempt_after" in payload
    assert "admin_retry by user=admin-1" in payload["error_message"]


def test_retry_endpoint_returns_404_when_job_missing() -> None:
    """A retry against an unknown job_id is 404, not a silent success."""
    mock_sb = MagicMock()
    mock_sb.table.return_value = _chain([])  # no rows

    with patch("routers.admin._common.get_supabase_client", return_value=mock_sb):
        client = TestClient(_app())
        resp = client.post("/admin/graph-outbox/retry/nonexistent")

    assert resp.status_code == 404


def test_retry_endpoint_noop_when_job_already_pending() -> None:
    """Retrying a 'pending' job is a no-op (already queued)."""
    select_chain = _chain([{"id": "job-2", "status": "pending", "operation": "x", "attempt_count": 0}])
    mock_sb = MagicMock()
    mock_sb.table.return_value = select_chain

    with patch("routers.admin._common.get_supabase_client", return_value=mock_sb):
        client = TestClient(_app())
        resp = client.post("/admin/graph-outbox/retry/job-2")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "noop"
    assert body["data"]["current_status"] == "pending"


def test_list_failed_returns_rows() -> None:
    rows = [
        {"id": "f1", "operation": "x", "status": "failed", "attempt_count": 5, "max_attempts": 5},
        {"id": "f2", "operation": "y", "status": "failed", "attempt_count": 5, "max_attempts": 5},
    ]
    mock_sb = MagicMock()
    mock_sb.table.return_value = _chain(rows)

    with patch("routers.admin._common.get_supabase_client", return_value=mock_sb):
        client = TestClient(_app())
        resp = client.get("/admin/graph-outbox/failed")

    assert resp.status_code == 200
    assert len(resp.json()) == 2
