"""Integration tests for queued_questions router (Phase 19 — Three-Bucket Agent)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER = {"user_id": "u1", "tenant_id": "t1", "role": "owner"}

PENDING_ROW = {
    "id": "qid-1",
    "twin_id": "twin-1",
    "tenant_id": "t1",
    "question": "What is your pricing?",
    "topic": "pricing",
    "status": "pending",
    "ask_count": 5,
    "created_at": "2026-03-29T10:00:00Z",
    "updated_at": "2026-03-29T10:00:00Z",
    "owner_answer": None,
    "answered_at": None,
}


def _build_chain_mock(data: list | None = None) -> MagicMock:
    """Build a chainable Supabase mock that terminates with .execute()."""
    chain = MagicMock()
    execute_result = MagicMock()
    execute_result.data = data or []

    # Each method in the chain returns the same chain mock.
    for method in ("table", "select", "eq", "order", "range", "update", "limit", "insert"):
        getattr(chain, method).return_value = chain

    chain.execute.return_value = execute_result
    return chain


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """Create a TestClient with auth and Supabase fully mocked."""
    from fastapi import FastAPI
    from routers.queued_questions import router
    from modules.auth_guard import require_tenant

    app = FastAPI()
    app.include_router(router)

    # Override require_tenant dependency
    app.dependency_overrides[require_tenant] = lambda: FAKE_USER

    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests: list_queued_questions
# ---------------------------------------------------------------------------

class TestListQueuedQuestions:
    def test_list_queued_questions_returns_pending(self, client):
        chain = _build_chain_mock(data=[PENDING_ROW])

        with (
            patch("routers.queued_questions.get_supabase_client", return_value=chain),
            patch("routers.queued_questions.verify_twin_ownership", return_value=True),
        ):
            resp = client.get("/v2/queued-questions", params={"twin_id": "twin-1"})

        assert resp.status_code == 200
        body = resp.json()
        assert "questions" in body
        assert body["count"] == 1
        assert body["questions"][0]["question"] == "What is your pricing?"

    def test_list_queued_questions_requires_auth(self):
        """Without auth override, the endpoint should return 401."""
        from fastapi import FastAPI
        from routers.queued_questions import router

        app = FastAPI()
        app.include_router(router)
        # No dependency override — uses real require_tenant which checks auth

        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/v2/queued-questions", params={"twin_id": "twin-1"})

        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests: answer_queued_question
# ---------------------------------------------------------------------------

class TestAnswerQueuedQuestion:
    def test_answer_queued_question_ingests_to_vector_store(self, client):
        chain = _build_chain_mock(data=[PENDING_ROW])

        with (
            patch("routers.queued_questions.get_supabase_client", return_value=chain),
            patch("adk_core.services.vector_store.upsert_faq") as mock_upsert,
            patch("adk_core.services.agent_service.invalidate_agent") as mock_invalidate,
        ):
            resp = client.post(
                "/v2/queued-questions/qid-1/answer",
                json={"answer": "Our pricing starts at $10/month."},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "answered"
        assert body["question_id"] == "qid-1"

        mock_upsert.assert_called_once_with(
            question="What is your pricing?",
            answer="Our pricing starts at $10/month.",
            twin_id="twin-1",
        )
        mock_invalidate.assert_called_once_with("twin-1")

    def test_answer_queued_question_empty_answer_400(self, client):
        chain = _build_chain_mock(data=[PENDING_ROW])

        with (
            patch("routers.queued_questions.get_supabase_client", return_value=chain),
        ):
            resp = client.post(
                "/v2/queued-questions/qid-1/answer",
                json={"answer": ""},
            )

        assert resp.status_code == 400

    def test_answer_queued_question_not_found_404(self, client):
        chain = _build_chain_mock(data=[])  # empty result

        with (
            patch("routers.queued_questions.get_supabase_client", return_value=chain),
        ):
            resp = client.post(
                "/v2/queued-questions/nonexistent/answer",
                json={"answer": "Some answer"},
            )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: dismiss_queued_question
# ---------------------------------------------------------------------------

class TestDismissQueuedQuestion:
    def test_dismiss_queued_question(self, client):
        chain = _build_chain_mock(data=[PENDING_ROW])

        with (
            patch("routers.queued_questions.get_supabase_client", return_value=chain),
        ):
            resp = client.post("/v2/queued-questions/qid-1/dismiss")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "dismissed"
        assert body["question_id"] == "qid-1"

    def test_dismiss_queued_question_not_found_404(self, client):
        chain = _build_chain_mock(data=[])

        with (
            patch("routers.queued_questions.get_supabase_client", return_value=chain),
        ):
            resp = client.post("/v2/queued-questions/nonexistent/dismiss")

        assert resp.status_code == 404
