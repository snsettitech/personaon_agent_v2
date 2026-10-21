"""Tests for the commitments router (Phase A — Commitments surface).

Coverage:
- GET  /v2/twins/{twin_id}/commitments  → groups rows into you_owe / they_owe / counts
- PATCH /v2/twins/{twin_id}/commitments/{id} → 200 on match, 404 when no rows returned
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.auth_guard import verify_owner
from routers import twins_commitments
from tests._supabase_mock import fluent


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OWNER = {
    "user_id": "00000000-0000-0000-0000-000000000001",
    "tenant_id": "00000000-0000-0000-0000-000000000002",
}
TWIN_ID = "00000000-0000-0000-0000-000000000003"
COMMITMENT_ID = "00000000-0000-0000-0000-000000000010"

_BASE_COMMITMENT = {
    "id": COMMITMENT_ID,
    "meeting_id": "00000000-0000-0000-0000-000000000020",
    "contact_id": "00000000-0000-0000-0000-000000000030",
    "direction": "you_owe",
    "text": "Send follow-up email",
    "assignee_name": "Sooraj",
    "due_at": None,
    "status": "open",
    "created_at": "2026-05-27T10:00:00+00:00",
    "twin_id": TWIN_ID,
    "tenant_id": OWNER["tenant_id"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _app(user: dict[str, Any]) -> FastAPI:
    app = FastAPI()
    app.include_router(twins_commitments.router)
    app.dependency_overrides[verify_owner] = lambda: user
    return app


def _make_twin_ownership_mock() -> MagicMock:
    """Returns a mock that passes verify_twin_ownership (returns a twin row)."""
    twin_row = {
        "id": TWIN_ID,
        "tenant_id": OWNER["tenant_id"],
        "creator_id": None,
        "settings": {},
    }
    chain = MagicMock()
    chain.table.return_value = chain
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.single.return_value = chain
    chain.maybe_single.return_value = chain  # verify_twin_ownership uses maybe_single()
    chain.execute.return_value = SimpleNamespace(data=twin_row)
    return chain


@contextmanager
def _patched_ownership():
    with patch("modules.observability.get_supabase_client") as mock_client:
        mock_client.return_value = _make_twin_ownership_mock()
        yield mock_client


# ---------------------------------------------------------------------------
# GET — list_commitments
# ---------------------------------------------------------------------------

def test_list_empty():
    """No rows → empty you_owe and they_owe with zero counts."""
    app = _app(OWNER)
    client = TestClient(app)
    mock_sb = fluent([])

    with _patched_ownership(), patch("routers.twins_commitments.supabase") as sb:
        sb.table.return_value = mock_sb
        resp = client.get(f"/v2/twins/{TWIN_ID}/commitments")

    assert resp.status_code == 200
    body = resp.json()
    assert body["you_owe"] == []
    assert body["they_owe"] == []
    assert body["counts"] == {"you_owe": 0, "they_owe": 0, "total": 0}


def test_list_grouped():
    """Two rows with different directions are split into the correct buckets."""
    rows = [
        {**_BASE_COMMITMENT, "direction": "you_owe"},
        {
            **_BASE_COMMITMENT,
            "id": "00000000-0000-0000-0000-000000000011",
            "direction": "they_owe",
            "text": "Send contract",
        },
    ]
    app = _app(OWNER)
    client = TestClient(app)
    mock_sb = fluent(rows)

    with _patched_ownership(), patch("routers.twins_commitments.supabase") as sb:
        sb.table.return_value = mock_sb
        resp = client.get(f"/v2/twins/{TWIN_ID}/commitments?status=all")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["you_owe"]) == 1
    assert body["you_owe"][0]["text"] == "Send follow-up email"
    assert len(body["they_owe"]) == 1
    assert body["they_owe"][0]["text"] == "Send contract"
    assert body["counts"] == {"you_owe": 1, "they_owe": 1, "total": 2}


# ---------------------------------------------------------------------------
# PATCH — update_commitment
# ---------------------------------------------------------------------------

def test_patch_not_found():
    """Supabase returns empty data → 404."""
    app = _app(OWNER)
    client = TestClient(app)
    mock_sb = fluent([])

    with _patched_ownership(), patch("routers.twins_commitments.supabase") as sb:
        sb.table.return_value = mock_sb
        resp = client.patch(
            f"/v2/twins/{TWIN_ID}/commitments/{COMMITMENT_ID}",
            json={"status": "done"},
        )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Commitment not found"


def test_patch_updates_status():
    """Supabase returns updated row → 200 with CommitmentOut fields."""
    updated_row = {**_BASE_COMMITMENT, "status": "done"}
    app = _app(OWNER)
    client = TestClient(app)
    mock_sb = fluent([updated_row])

    with _patched_ownership(), patch("routers.twins_commitments.supabase") as sb:
        sb.table.return_value = mock_sb
        resp = client.patch(
            f"/v2/twins/{TWIN_ID}/commitments/{COMMITMENT_ID}",
            json={"status": "done"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == COMMITMENT_ID
    assert body["status"] == "done"
    assert body["direction"] == "you_owe"
