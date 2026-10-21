"""Tests for /v2/twins/{twin_id}/memory-candidates endpoints."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from tests._supabase_mock import fluent, result

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

TWIN_ID = "twin-abc"
CANDIDATE_ID = "cand-001"
USER = {"user_id": "user-xyz", "tenant_id": "tenant-xyz"}

CANDIDATE_ROW = {
    "id": CANDIDATE_ID,
    "meeting_id": "meet-1",
    "contact_id": "contact-1",
    "kind": "fact",
    "subject": "Alice",
    "predicate": "prefers",
    "text": "Alice prefers morning meetings",
    "confidence": 0.92,
    "status": "pending",
    "created_at": "2026-05-28T10:00:00Z",
    "twin_id": TWIN_ID,
    "tenant_id": "tenant-xyz",
}


def _make_client():
    """Build a TestClient with auth and ownership mocked out."""
    from fastapi import FastAPI
    from routers.twins_memory_candidates import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


def _auth_overrides(app, user=USER):
    """Patch verify_owner and verify_twin_ownership for the duration of a test."""
    from modules.auth_guard import verify_owner

    app.dependency_overrides[verify_owner] = lambda: user
    return app


# ---------------------------------------------------------------------------
# GET /v2/twins/{twin_id}/memory-candidates
# ---------------------------------------------------------------------------


class TestListCandidates:
    def test_returns_list_of_candidates(self):
        from fastapi import FastAPI
        from routers.twins_memory_candidates import router

        app = FastAPI()
        app.include_router(router)
        _auth_overrides(app)

        mock_sb = fluent([CANDIDATE_ROW])

        with (
            patch("routers.twins_memory_candidates.supabase", mock_sb),
            patch("routers.twins_memory_candidates.verify_twin_ownership"),
        ):
            client = TestClient(app)
            resp = client.get(f"/v2/twins/{TWIN_ID}/memory-candidates")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == CANDIDATE_ID
        assert data[0]["kind"] == "fact"
        assert data[0]["status"] == "pending"

    def test_returns_empty_list_when_no_candidates(self):
        from fastapi import FastAPI
        from routers.twins_memory_candidates import router

        app = FastAPI()
        app.include_router(router)
        _auth_overrides(app)

        mock_sb = fluent([])

        with (
            patch("routers.twins_memory_candidates.supabase", mock_sb),
            patch("routers.twins_memory_candidates.verify_twin_ownership"),
        ):
            client = TestClient(app)
            resp = client.get(f"/v2/twins/{TWIN_ID}/memory-candidates")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_status_filter_all_skips_eq(self):
        """When status=all, the query should NOT filter by status."""
        from fastapi import FastAPI
        from routers.twins_memory_candidates import router

        app = FastAPI()
        app.include_router(router)
        _auth_overrides(app)

        mock_sb = fluent([CANDIDATE_ROW])

        with (
            patch("routers.twins_memory_candidates.supabase", mock_sb),
            patch("routers.twins_memory_candidates.verify_twin_ownership"),
        ):
            client = TestClient(app)
            resp = client.get(
                f"/v2/twins/{TWIN_ID}/memory-candidates", params={"status": "all"}
            )

        assert resp.status_code == 200

    def test_contact_id_filter_applied(self):
        from fastapi import FastAPI
        from routers.twins_memory_candidates import router

        app = FastAPI()
        app.include_router(router)
        _auth_overrides(app)

        mock_sb = fluent([CANDIDATE_ROW])

        with (
            patch("routers.twins_memory_candidates.supabase", mock_sb),
            patch("routers.twins_memory_candidates.verify_twin_ownership"),
        ):
            client = TestClient(app)
            resp = client.get(
                f"/v2/twins/{TWIN_ID}/memory-candidates",
                params={"contact_id": "contact-1"},
            )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# PATCH /v2/twins/{twin_id}/memory-candidates/{candidate_id}
# ---------------------------------------------------------------------------


class TestDecideCandidate:
    def _make_approved_row(self):
        return {**CANDIDATE_ROW, "status": "approved", "approved_at": "2026-05-28T11:00:00Z"}

    def test_approve_returns_updated_candidate(self):
        from fastapi import FastAPI
        from routers.twins_memory_candidates import router

        app = FastAPI()
        app.include_router(router)
        _auth_overrides(app)

        approved_row = self._make_approved_row()
        mock_sb = fluent([approved_row])

        # audit insert also goes through mock_sb; second execute returns empty list (ok)
        with (
            patch("routers.twins_memory_candidates.supabase", mock_sb),
            patch("routers.twins_memory_candidates.verify_twin_ownership"),
        ):
            client = TestClient(app)
            resp = client.patch(
                f"/v2/twins/{TWIN_ID}/memory-candidates/{CANDIDATE_ID}",
                json={"decision": "approved"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"
        assert resp.json()["id"] == CANDIDATE_ID

    def test_dismiss_returns_updated_candidate(self):
        from fastapi import FastAPI
        from routers.twins_memory_candidates import router

        app = FastAPI()
        app.include_router(router)
        _auth_overrides(app)

        dismissed_row = {**CANDIDATE_ROW, "status": "dismissed", "dismissed_at": "2026-05-28T11:00:00Z"}
        mock_sb = fluent([dismissed_row])

        with (
            patch("routers.twins_memory_candidates.supabase", mock_sb),
            patch("routers.twins_memory_candidates.verify_twin_ownership"),
        ):
            client = TestClient(app)
            resp = client.patch(
                f"/v2/twins/{TWIN_ID}/memory-candidates/{CANDIDATE_ID}",
                json={"decision": "dismissed", "notes": "duplicate"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "dismissed"

    def test_404_when_candidate_not_found(self):
        from fastapi import FastAPI
        from routers.twins_memory_candidates import router

        app = FastAPI()
        app.include_router(router)
        _auth_overrides(app)

        # execute returns empty data → 404
        mock_sb = fluent([])

        with (
            patch("routers.twins_memory_candidates.supabase", mock_sb),
            patch("routers.twins_memory_candidates.verify_twin_ownership"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.patch(
                f"/v2/twins/{TWIN_ID}/memory-candidates/nonexistent",
                json={"decision": "approved"},
            )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Candidate not found"

    def test_audit_failure_does_not_break_response(self):
        """Even if the audit insert raises, the endpoint should still return 200."""
        from fastapi import FastAPI
        from routers.twins_memory_candidates import router

        app = FastAPI()
        app.include_router(router)
        _auth_overrides(app)

        approved_row = self._make_approved_row()

        # First execute (update) returns data; second execute (audit insert) raises
        mock_sb = MagicMock()
        for name in (
            "table", "select", "eq", "neq", "ilike", "in_", "is_", "not_",
            "order", "limit", "insert", "update", "delete", "single",
            "maybe_single", "upsert", "rpc",
        ):
            getattr(mock_sb, name).return_value = mock_sb

        call_count = {"n": 0}

        def execute_side_effect():
            call_count["n"] += 1
            if call_count["n"] == 1:
                # update call — success
                from types import SimpleNamespace
                return SimpleNamespace(data=[approved_row])
            raise RuntimeError("DB unavailable")

        mock_sb.execute.side_effect = execute_side_effect

        with (
            patch("routers.twins_memory_candidates.supabase", mock_sb),
            patch("routers.twins_memory_candidates.verify_twin_ownership"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.patch(
                f"/v2/twins/{TWIN_ID}/memory-candidates/{CANDIDATE_ID}",
                json={"decision": "approved"},
            )

        assert resp.status_code == 200
        assert resp.json()["id"] == CANDIDATE_ID
