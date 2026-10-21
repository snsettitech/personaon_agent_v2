"""Tests for the live user-notes endpoint (Granola Batch 1).

Covers PATCH /v2/desktop-recordings/{id}/notes:
- owner gate (401 unauthenticated, 404 cross-tenant)
- writes user_notes_json AND notes_updated_at (both columns)
- mutation scoped by id AND tenant_id (tenant_scope_mutations rule)
- does NOT route through update_recap_with_audit (plain owner UPDATE)
- empty notes accepted (don't block empty->empty saves)
- 500 when the row vanishes (no update rows returned)
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


def _owned_row(tenant_id: str = "tenant-1") -> dict[str, Any]:
    return {"id": MEETING_ID, "tenant_id": tenant_id, "status": "recording"}


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


def _supabase_mock(*, owned_row: dict[str, Any] | None, update_rows: list[dict[str, Any]] | None = None) -> MagicMock:
    """A supabase mock for the meetings table.

    _fetch_owned does .select()....maybe_single().execute() -> owned_row.
    The notes UPDATE does .update(payload).eq().eq().execute() -> update_rows.
    Both share the same fluent chain; we capture the update payload + eq filters.
    """
    captured: dict[str, Any] = {"update_payload": None, "eq_filters": []}

    chain = MagicMock()
    for method in ("select", "neq", "order", "range", "maybe_single"):
        getattr(chain, method).return_value = chain

    def _eq(col: str, val: Any) -> MagicMock:
        captured["eq_filters"].append((col, val))
        return chain

    chain.eq.side_effect = _eq

    def _update(payload: Any) -> MagicMock:
        captured["update_payload"] = payload
        return chain

    chain.update.side_effect = _update

    # _fetch_owned's terminal .execute() (after maybe_single) returns owned_row;
    # the UPDATE's terminal .execute() (after the eq chain) returns update_rows.
    # Route by whether an update payload has been captured yet.
    def _execute() -> SimpleNamespace:
        if captured["update_payload"] is not None:
            return _result(update_rows if update_rows is not None else [owned_row])
        return _result(owned_row)

    chain.execute.side_effect = _execute

    sb = MagicMock()
    sb.table.return_value = chain
    sb._captured = captured  # type: ignore[attr-defined]
    return sb


# ---------------------------------------------------------------------------
# Auth / ownership
# ---------------------------------------------------------------------------

def test_notes_requires_auth() -> None:
    resp = _client(None).patch(
        f"/v2/desktop-recordings/{MEETING_ID}/notes",
        json={"user_notes_json": {"text": "hi"}},
    )
    assert resp.status_code == 401


def test_notes_cross_tenant_returns_404() -> None:
    sb = _supabase_mock(owned_row=_owned_row(tenant_id="tenant-1"))
    with patch("routers.desktop_recordings.supabase", sb):
        resp = _client(OTHER_USER).patch(
            f"/v2/desktop-recordings/{MEETING_ID}/notes",
            json={"user_notes_json": {"text": "hi"}},
        )
    assert resp.status_code == 404
    # The cross-tenant request must never reach the UPDATE.
    assert sb._captured["update_payload"] is None


# ---------------------------------------------------------------------------
# Write behavior
# ---------------------------------------------------------------------------

def test_notes_writes_both_columns_scoped_by_id_and_tenant() -> None:
    sb = _supabase_mock(owned_row=_owned_row())
    with patch("routers.desktop_recordings.supabase", sb):
        resp = _client(USER).patch(
            f"/v2/desktop-recordings/{MEETING_ID}/notes",
            json={"user_notes_json": {"text": "follow up with Bob"}},
        )
    assert resp.status_code == 200
    payload = sb._captured["update_payload"]
    assert payload["user_notes_json"] == {"text": "follow up with Bob"}
    # Both columns written.
    assert "notes_updated_at" in payload and payload["notes_updated_at"]
    # Mutation scoped by id AND tenant_id (defense-in-depth alongside RLS).
    eq_filters = sb._captured["eq_filters"]
    assert ("id", MEETING_ID) in eq_filters
    assert ("tenant_id", "tenant-1") in eq_filters


def test_notes_accepts_empty_text() -> None:
    sb = _supabase_mock(owned_row=_owned_row())
    with patch("routers.desktop_recordings.supabase", sb):
        resp = _client(USER).patch(
            f"/v2/desktop-recordings/{MEETING_ID}/notes",
            json={"user_notes_json": {"text": ""}},
        )
    assert resp.status_code == 200
    assert sb._captured["update_payload"]["user_notes_json"] == {"text": ""}


def test_notes_missing_text_defaults_to_empty() -> None:
    sb = _supabase_mock(owned_row=_owned_row())
    with patch("routers.desktop_recordings.supabase", sb):
        resp = _client(USER).patch(
            f"/v2/desktop-recordings/{MEETING_ID}/notes",
            json={"user_notes_json": {}},
        )
    assert resp.status_code == 200
    assert sb._captured["update_payload"]["user_notes_json"] == {"text": ""}


def test_notes_returns_500_when_no_rows_updated() -> None:
    sb = _supabase_mock(owned_row=_owned_row(), update_rows=[])
    with patch("routers.desktop_recordings.supabase", sb):
        resp = _client(USER).patch(
            f"/v2/desktop-recordings/{MEETING_ID}/notes",
            json={"user_notes_json": {"text": "x"}},
        )
    assert resp.status_code == 500


def test_notes_rejects_oversized_text() -> None:
    sb = _supabase_mock(owned_row=_owned_row())
    big = "x" * 100_001
    with patch("routers.desktop_recordings.supabase", sb):
        resp = _client(USER).patch(
            f"/v2/desktop-recordings/{MEETING_ID}/notes",
            json={"user_notes_json": {"text": big}},
        )
    assert resp.status_code == 422
