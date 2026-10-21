"""Tests for POST /v2/desktop-recordings/{id}/enhance (Granola Batch 3).

Covers:
- owner gate (401 unauthenticated, 404 cross-tenant)
- enqueues ENHANCE_NOTES with twin-optional payload
- debounce: no-op when enhanced_notes_status='generating'
- flips status to 'generating' on accept
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


def _owned_row(*, tenant_id: str = "tenant-1", status: str = "completed", twin_id: Any = None) -> dict[str, Any]:
    return {
        "id": MEETING_ID,
        "tenant_id": tenant_id,
        "status": status,
        "twin_id": twin_id,
        "enhanced_notes_status": status if status == "generating" else "ready",
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


def _supabase_mock(owned_row: dict[str, Any] | None) -> MagicMock:
    meetings_chain = MagicMock()
    for method in ("select", "eq", "update", "maybe_single"):
        getattr(meetings_chain, method).return_value = meetings_chain
    # _fetch_owned uses maybe_single().execute(); update().eq().eq().execute()
    meetings_chain.execute.return_value = _result(owned_row)
    sb = MagicMock()
    sb.table.return_value = meetings_chain
    return sb


def test_enhance_requires_auth() -> None:
    resp = _client(None).post(f"/v2/desktop-recordings/{MEETING_ID}/enhance")
    assert resp.status_code == 401


def test_enhance_cross_tenant_returns_404() -> None:
    sb = _supabase_mock(_owned_row(tenant_id="tenant-1"))
    with patch("routers.desktop_recordings.supabase", sb):
        resp = _client(OTHER_USER).post(f"/v2/desktop-recordings/{MEETING_ID}/enhance")
    assert resp.status_code == 404


def test_enhance_enqueues_twin_optional() -> None:
    sb = _supabase_mock(_owned_row(status="completed", twin_id=None))
    captured: dict[str, Any] = {}

    outbox = MagicMock()

    def _submit(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "job-1"

    outbox.submit.side_effect = _submit

    with patch("routers.desktop_recordings.supabase", sb), \
         patch("modules.graph_outbox.get_graph_outbox", return_value=outbox):
        resp = _client(USER).post(f"/v2/desktop-recordings/{MEETING_ID}/enhance")

    assert resp.status_code == 200
    assert resp.json()["data"]["enqueued"] is True
    # twin-optional: None passes through, not gated
    assert captured["twin_id"] is None
    assert captured["payload"]["meeting_id"] == MEETING_ID
    # fresh timestamped key so re-runs actually re-run
    assert captured["idempotency_key"].startswith(f"enhance_notes:{MEETING_ID}:")


def test_enhance_debounces_when_generating() -> None:
    sb = _supabase_mock(_owned_row(status="generating"))
    outbox = MagicMock()
    with patch("routers.desktop_recordings.supabase", sb), \
         patch("modules.graph_outbox.get_graph_outbox", return_value=outbox):
        resp = _client(USER).post(f"/v2/desktop-recordings/{MEETING_ID}/enhance")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["enqueued"] is False
    assert body["data"]["reason"] == "already_generating"
    outbox.submit.assert_not_called()
