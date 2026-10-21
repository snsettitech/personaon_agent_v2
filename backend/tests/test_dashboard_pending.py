"""Tests for GET /v2/dashboard/pending composition endpoint (Phase E.1).

Verifies:
- Zero counts returned when all sub-queries return empty.
- recap_edits (to_review) count path.
- queued_questions (visitor_questions) count path.
- action_items JSONB walker (follow_ups) correctly filters by due_at + completed.
- Cross-tenant isolation (tenant_id always in query chain).
- Graceful degradation: one sub-query failure still returns 200 with zeros for
  that field.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.auth_guard import verify_owner
from routers import dashboard

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

OWNER_USER: dict[str, Any] = {
    "user_id": "user-1",
    "tenant_id": "tenant-1",
    "email": "owner@example.com",
}


def _count_resp(count: int) -> SimpleNamespace:
    """Simulates a Supabase response with .count attribute."""
    return SimpleNamespace(count=count, data=[])


def _data_resp(rows: list[dict[str, Any]]) -> SimpleNamespace:
    """Simulates a Supabase response with .data list."""
    return SimpleNamespace(count=len(rows), data=rows)


def _app(user: dict[str, Any] = OWNER_USER) -> FastAPI:
    app = FastAPI()
    app.include_router(dashboard.router)
    app.dependency_overrides[verify_owner] = lambda: user
    return app


def _fluent_count_chain(count: int) -> MagicMock:
    """Returns a mock chain: .select().eq().is_().limit().execute() → count resp."""
    m = MagicMock()
    m.select.return_value = m
    m.eq.return_value = m
    m.is_.return_value = m
    m.neq.return_value = m
    m.gte.return_value = m
    m.limit.return_value = m
    m.execute.return_value = _count_resp(count)
    return m


def _fluent_data_chain(rows: list[dict[str, Any]]) -> MagicMock:
    """Returns a mock chain ending in .data list."""
    m = MagicMock()
    m.select.return_value = m
    m.eq.return_value = m
    m.is_.return_value = m
    m.neq.return_value = m
    m.gte.return_value = m
    m.limit.return_value = m
    m.execute.return_value = _data_resp(rows)
    return m


# ---------------------------------------------------------------------------
# Test 1: zeros for empty tenant
# ---------------------------------------------------------------------------

def test_pending_zeros_for_empty_tenant() -> None:
    """All three sub-queries return 0 → response data is all zeros."""
    with patch("routers.dashboard.supabase") as mock_sb:
        chain = _fluent_count_chain(0)
        mock_sb.table.return_value = chain

        client = TestClient(_app(), raise_server_exceptions=False)
        resp = client.get("/v2/dashboard/pending")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["data"] == {"to_review": 0, "follow_ups": 0, "visitor_questions": 0}


# ---------------------------------------------------------------------------
# Test 2: recap_edits to_review count
# ---------------------------------------------------------------------------

def test_pending_counts_recap_edits_with_null_store_routing() -> None:
    """recap_edits query returning count=3 → to_review == 3."""
    call_results: dict[str, Any] = {}

    def _table_side_effect(name: str) -> MagicMock:
        if name == "recap_edits":
            chain = _fluent_count_chain(3)
            call_results["recap_edits_chain"] = chain
            return chain
        # meetings and queued_questions return zeros
        return _fluent_count_chain(0)

    with patch("routers.dashboard.supabase") as mock_sb:
        mock_sb.table.side_effect = _table_side_effect
        client = TestClient(_app(), raise_server_exceptions=False)
        resp = client.get("/v2/dashboard/pending")

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["to_review"] == 3
    assert data["visitor_questions"] == 0
    assert data["follow_ups"] == 0

    # Verify tenant scoping was applied
    chain = call_results["recap_edits_chain"]
    chain.eq.assert_called_with("tenant_id", "tenant-1")


# ---------------------------------------------------------------------------
# Test 3: queued_questions visitor_questions count
# ---------------------------------------------------------------------------

def test_pending_counts_queued_questions_pending() -> None:
    """queued_questions returning count=2 → visitor_questions == 2."""
    call_results: dict[str, Any] = {}

    def _table_side_effect(name: str) -> MagicMock:
        if name == "queued_questions":
            chain = _fluent_count_chain(2)
            call_results["qq_chain"] = chain
            return chain
        return _fluent_count_chain(0)

    with patch("routers.dashboard.supabase") as mock_sb:
        mock_sb.table.side_effect = _table_side_effect
        client = TestClient(_app(), raise_server_exceptions=False)
        resp = client.get("/v2/dashboard/pending")

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["visitor_questions"] == 2
    assert data["to_review"] == 0
    assert data["follow_ups"] == 0


# ---------------------------------------------------------------------------
# Test 4: action_items JSONB walker
# ---------------------------------------------------------------------------

def test_pending_counts_action_items_with_due_at_not_completed() -> None:
    """Walker counts only items where due_at is set AND completed is not True."""
    meetings_rows = [
        {
            "action_items": [
                # should count — has due_at, not completed
                {"text": "Send report", "due_at": "2026-06-01T12:00:00Z", "completed": False},
                # should count — has due_at, completed absent (None-ish)
                {"text": "Review PR", "due_at": "2026-06-03T09:00:00Z"},
                # should NOT count — completed=True
                {"text": "Done task", "due_at": "2026-05-20T10:00:00Z", "completed": True},
                # should NOT count — no due_at
                {"text": "No deadline"},
            ]
        },
        {
            "action_items": [
                # should count
                {"text": "Follow up call", "due_at": "2026-06-05T15:00:00Z", "completed": False},
            ]
        },
        # Row with null action_items — should not crash
        {"action_items": None},
        # Row with non-list action_items — should not crash
        {"action_items": "broken"},
    ]

    def _table_side_effect(name: str) -> MagicMock:
        if name == "meetings":
            return _fluent_data_chain(meetings_rows)
        return _fluent_count_chain(0)

    with patch("routers.dashboard.supabase") as mock_sb:
        mock_sb.table.side_effect = _table_side_effect
        client = TestClient(_app(), raise_server_exceptions=False)
        resp = client.get("/v2/dashboard/pending")

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["follow_ups"] == 3  # 2 from first row + 1 from second row
    assert data["to_review"] == 0
    assert data["visitor_questions"] == 0


# ---------------------------------------------------------------------------
# Test 5: cross-tenant isolation
# ---------------------------------------------------------------------------

def test_pending_cross_tenant_isolation() -> None:
    """tenant_id from the authenticated user is always applied to every query."""
    other_user = {**OWNER_USER, "tenant_id": "tenant-99"}
    observed_tenant_ids: list[str] = []

    def _table_side_effect(name: str) -> MagicMock:
        chain = MagicMock()
        chain.select.return_value = chain
        chain.is_.return_value = chain
        chain.neq.return_value = chain
        chain.gte.return_value = chain
        chain.limit.return_value = chain
        chain.execute.return_value = SimpleNamespace(count=0, data=[])

        def _eq_capture(field: str, value: Any) -> MagicMock:
            if field == "tenant_id":
                observed_tenant_ids.append(str(value))
            chain.eq.return_value = chain
            return chain

        chain.eq.side_effect = _eq_capture
        return chain

    with patch("routers.dashboard.supabase") as mock_sb:
        mock_sb.table.side_effect = _table_side_effect
        client = TestClient(_app(other_user), raise_server_exceptions=False)
        resp = client.get("/v2/dashboard/pending")

    assert resp.status_code == 200, resp.text
    # All three sub-queries must have scoped to tenant-99
    assert all(tid == "tenant-99" for tid in observed_tenant_ids), (
        f"Expected all tenant_id='tenant-99', got: {observed_tenant_ids}"
    )
    # There should be at least 3 tenant_id scoping calls (one per sub-query)
    assert len(observed_tenant_ids) >= 3


# ---------------------------------------------------------------------------
# Test 6: graceful degradation on sub-query error
# ---------------------------------------------------------------------------

def test_pending_handles_supabase_errors_gracefully() -> None:
    """If recap_edits sub-query raises, endpoint still returns 200 with to_review=0."""
    call_count = [0]

    def _table_side_effect(name: str) -> MagicMock:
        call_count[0] += 1
        if name == "recap_edits":
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.is_.return_value = chain
            chain.limit.return_value = chain
            chain.execute.side_effect = RuntimeError("DB exploded")
            return chain
        return _fluent_count_chain(0)

    with patch("routers.dashboard.supabase") as mock_sb:
        mock_sb.table.side_effect = _table_side_effect
        client = TestClient(_app(), raise_server_exceptions=False)
        resp = client.get("/v2/dashboard/pending")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    # to_review falls back to 0 after error
    assert body["data"]["to_review"] == 0
    # other fields are still present
    assert "visitor_questions" in body["data"]
    assert "follow_ups" in body["data"]
