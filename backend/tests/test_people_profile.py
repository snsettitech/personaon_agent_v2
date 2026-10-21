"""Tests for GET /v2/people/{twin_id}/{person_node_id} (routers/people.py).

Staging-verification fix (finding #12, low severity): requesting a
non-existent person_node_id previously raised an unhandled exception from
Supabase's `.single()` (which errors on zero rows) and surfaced as an
HTTP 500. It must return a clean 404 instead, matching every other
"not found" endpoint in this codebase (see test_contacts.py::
test_get_contact_404_if_missing for the established pattern).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import people
from routers.meetings import _require_meeting_intelligence

OWNER = {
    "user_id": "00000000-0000-0000-0000-000000000001",
    "tenant_id": "00000000-0000-0000-0000-000000000002",
}
TWIN_ID = "00000000-0000-0000-0000-000000000003"
PERSON_ID = "00000000-0000-0000-0000-000000000004"


def _result(data: Any) -> SimpleNamespace:
    return SimpleNamespace(data=data)


def _fluent_chain(return_data: Any) -> MagicMock:
    """Chained MagicMock where every builder call returns itself."""
    m = MagicMock()
    for name in (
        "select", "eq", "neq", "in_", "order", "limit", "filter",
        "single", "maybe_single",
    ):
        getattr(m, name).return_value = m
    m.execute.return_value = _result(return_data)
    return m


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(people.router)
    # Bypass the MEETING_INTELLIGENCE_ENABLED flag gate for this test.
    app.dependency_overrides[_require_meeting_intelligence] = lambda: None
    return app


def test_get_person_profile_404_when_node_missing():
    """No matching row in `nodes` -> 404 'Person not found', not a 500.

    Regression test: `.maybe_single()` must be used (not `.single()`) so a
    zero-row result resolves to `data=None` instead of raising.
    """
    app = _app()
    client = TestClient(app)

    twin_chain = _fluent_chain([{"id": TWIN_ID}])
    node_chain = _fluent_chain(None)

    def table_side_effect(name: str) -> MagicMock:
        if name == "twins":
            return twin_chain
        if name == "nodes":
            return node_chain
        return MagicMock()

    mock_supabase = MagicMock()
    mock_supabase.table.side_effect = table_side_effect

    with patch("routers.people._get_current_user", return_value=OWNER), \
         patch("routers.people.supabase", mock_supabase):
        resp = client.get(f"/v2/people/{TWIN_ID}/{PERSON_ID}")

    assert resp.status_code == 404
    assert "Person not found" in resp.json()["detail"]
    node_chain.maybe_single.assert_called_once()
    node_chain.single.assert_not_called()


def test_get_person_profile_403_when_twin_not_owned():
    """Twin ownership check fails (`twins` query returns no row) -> 403."""
    app = _app()
    client = TestClient(app)

    twin_chain = _fluent_chain([])
    node_chain = _fluent_chain(None)

    def table_side_effect(name: str) -> MagicMock:
        if name == "twins":
            return twin_chain
        if name == "nodes":
            return node_chain
        return MagicMock()

    mock_supabase = MagicMock()
    mock_supabase.table.side_effect = table_side_effect

    with patch("routers.people._get_current_user", return_value=OWNER), \
         patch("routers.people.supabase", mock_supabase):
        resp = client.get(f"/v2/people/{TWIN_ID}/{PERSON_ID}")

    assert resp.status_code == 403
