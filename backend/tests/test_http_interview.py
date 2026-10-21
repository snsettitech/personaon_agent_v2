"""Integration tests for interview HTTP endpoints.

Tests the full HTTP request/response cycle through FastAPI for
POST /v2/interview/{id}/stream and GET /v2/interview/{id}/stats
with mocked external services.
"""

import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from fastapi.testclient import TestClient

TWIN_ID = "test-twin-interview"
FAKE_USER = {"user_id": "test-user", "tenant_id": "test-tenant"}


def _make_supabase_mock(twin_data=None, msg_count=0):
    """Build a mock Supabase client."""
    mock_sb = MagicMock()

    # twins table
    twin_resp = MagicMock()
    twin_resp.data = twin_data
    mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = twin_resp

    # adk_messages count
    msg_resp = MagicMock()
    msg_resp.count = msg_count
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = msg_resp

    return mock_sb


def _parse_sse_events(text: str):
    """Parse SSE text into a list of {type, data} dicts."""
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_type = None
        data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_type = line[7:]
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    data = line[6:]
        if event_type and data is not None:
            events.append({"type": event_type, "data": data})
    return events


@pytest.fixture()
def app_with_auth():
    from modules.auth_guard import require_tenant
    from main import app

    app.dependency_overrides[require_tenant] = lambda: FAKE_USER
    yield app
    app.dependency_overrides.clear()


@pytest.fixture()
def client(app_with_auth):
    return TestClient(app_with_auth)


# ── Streaming Tests ───────────────────────────────────────────────────


class TestInterviewStream:
    """POST /v2/interview/{id}/stream tests."""

    def _mock_runner_class(self, message_text="What is your biggest achievement?"):
        """Create a mock Runner that yields text events."""
        mock_runner_cls = MagicMock()
        mock_runner_instance = MagicMock()
        mock_runner_cls.return_value = mock_runner_instance

        # run_async returns an async generator
        async def fake_run_async(**kwargs):
            if message_text is None:
                return

            mock_event = MagicMock()
            mock_part = MagicMock()
            mock_part.text = message_text
            mock_part.function_call = None
            mock_part.function_response = None
            mock_event.content.parts = [mock_part]
            yield mock_event

        mock_runner_instance.run_async = fake_run_async
        return mock_runner_cls, mock_runner_instance

    def test_stream_returns_sse_events(self, client):
        twin_data = {
            "id": TWIN_ID,
            "name": "Test",
            "settings": {"persona_profile": {"name": "Test Person"}},
        }
        mock_sb = _make_supabase_mock(twin_data)
        mock_runner_cls, _ = self._mock_runner_class()

        # Mock session service
        mock_session_svc = MagicMock()
        mock_session = MagicMock()
        mock_session.id = "sess-123"
        mock_session_svc.get_session = AsyncMock(return_value=None)
        mock_session_svc.create_session = AsyncMock(return_value=mock_session)

        with patch("routers.interview.get_supabase_client", return_value=mock_sb), \
             patch("routers.interview.verify_twin_ownership", return_value=True), \
             patch("routers.interview.ensure_twin_active", return_value=True), \
             patch("routers.interview.upsert_faq", return_value="point-1"), \
             patch("routers.interview.invalidate_agent"), \
             patch("google.adk.runners.Runner", mock_runner_cls), \
             patch("google.adk.agents.Agent", MagicMock()), \
             patch("google.adk.sessions.DatabaseSessionService", return_value=mock_session_svc), \
             patch("adk_core.services.agent_service._get_session_service", return_value=mock_session_svc):

            resp = client.post(
                f"/v2/interview/{TWIN_ID}/stream",
                json={"message": "I built a company", "last_question": "Tell me about yourself"},
            )

        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)

        # Should have session, message, and done events
        event_types = [e["type"] for e in events]
        assert "session" in event_types
        assert "done" in event_types

        # Session event
        session_event = next(e for e in events if e["type"] == "session")
        assert "session_id" in session_event["data"]

    def test_auto_save_calls_upsert_faq(self, client):
        """When last_question is provided, upsert_faq should be called."""
        twin_data = {
            "id": TWIN_ID,
            "name": "Test",
            "settings": {"persona_profile": {"name": "Test"}},
        }
        mock_sb = _make_supabase_mock(twin_data)
        mock_runner_cls, _ = self._mock_runner_class()

        mock_session_svc = MagicMock()
        mock_session = MagicMock()
        mock_session.id = "sess-456"
        mock_session_svc.get_session = AsyncMock(return_value=None)
        mock_session_svc.create_session = AsyncMock(return_value=mock_session)

        with patch("routers.interview.get_supabase_client", return_value=mock_sb), \
             patch("routers.interview.verify_twin_ownership", return_value=True), \
             patch("routers.interview.ensure_twin_active", return_value=True), \
             patch("routers.interview.upsert_faq", return_value="point-1") as mock_upsert, \
             patch("routers.interview.invalidate_agent") as mock_invalidate, \
             patch("google.adk.runners.Runner", mock_runner_cls), \
             patch("google.adk.agents.Agent", MagicMock()), \
             patch("google.adk.sessions.DatabaseSessionService", return_value=mock_session_svc), \
             patch("adk_core.services.agent_service._get_session_service", return_value=mock_session_svc):

            resp = client.post(
                f"/v2/interview/{TWIN_ID}/stream",
                json={
                    "message": "I love building systems",
                    "last_question": "What do you enjoy most about your work?",
                },
            )

        assert resp.status_code == 200
        mock_upsert.assert_called_once_with(
            question="What do you enjoy most about your work?",
            answer="I love building systems",
            twin_id=TWIN_ID,
            origin="interview",
        )
        mock_invalidate.assert_called_once_with(TWIN_ID)

        # Verify SSE session event shows saved_qa=True
        events = _parse_sse_events(resp.text)
        session_event = next(e for e in events if e["type"] == "session")
        assert session_event["data"]["saved_qa"] is True

    def test_no_auto_save_without_last_question(self, client):
        twin_data = {
            "id": TWIN_ID,
            "name": "Test",
            "settings": {"persona_profile": {"name": "Test"}},
        }
        mock_sb = _make_supabase_mock(twin_data)
        mock_runner_cls, _ = self._mock_runner_class()

        mock_session_svc = MagicMock()
        mock_session = MagicMock()
        mock_session.id = "sess-789"
        mock_session_svc.get_session = AsyncMock(return_value=None)
        mock_session_svc.create_session = AsyncMock(return_value=mock_session)

        with patch("routers.interview.get_supabase_client", return_value=mock_sb), \
             patch("routers.interview.verify_twin_ownership", return_value=True), \
             patch("routers.interview.ensure_twin_active", return_value=True), \
             patch("routers.interview.upsert_faq") as mock_upsert, \
             patch("routers.interview.invalidate_agent") as mock_invalidate, \
             patch("google.adk.runners.Runner", mock_runner_cls), \
             patch("google.adk.agents.Agent", MagicMock()), \
             patch("google.adk.sessions.DatabaseSessionService", return_value=mock_session_svc), \
             patch("adk_core.services.agent_service._get_session_service", return_value=mock_session_svc):

            resp = client.post(
                f"/v2/interview/{TWIN_ID}/stream",
                json={"message": "Hello"},
            )

        assert resp.status_code == 200
        mock_upsert.assert_not_called()
        mock_invalidate.assert_not_called()

        events = _parse_sse_events(resp.text)
        session_event = next(e for e in events if e["type"] == "session")
        assert session_event["data"]["saved_qa"] is False

    def test_stream_emits_error_event_when_model_returns_no_text(self, client):
        twin_data = {
            "id": TWIN_ID,
            "name": "Test",
            "settings": {"persona_profile": {"name": "Test"}},
        }
        mock_sb = _make_supabase_mock(twin_data)
        _, mock_runner_instance = self._mock_runner_class(message_text=None)

        mock_session_svc = MagicMock()
        mock_session = MagicMock()
        mock_session.id = "sess-empty"
        mock_session_svc.get_session = AsyncMock(return_value=None)
        mock_session_svc.create_session = AsyncMock(return_value=mock_session)

        with patch("routers.interview.get_supabase_client", return_value=mock_sb), \
             patch("routers.interview.verify_twin_ownership", return_value=True), \
             patch("routers.interview.ensure_twin_active", return_value=True), \
             patch("routers.interview._build_runner", return_value=mock_runner_instance), \
             patch("routers.interview._get_session_service", return_value=mock_session_svc):

            resp = client.post(
                f"/v2/interview/{TWIN_ID}/stream",
                json={"message": "Hello"},
            )

        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        error_event = next(e for e in events if e["type"] == "error")
        assert error_event["data"] == {
            "code": "empty_response",
            "message": "The interview model returned no question.",
            "recoverable": True,
        }


class TestInterviewStreamAuth:
    """Auth enforcement for interview stream."""

    def test_401_without_auth(self):
        from main import app
        app.dependency_overrides.clear()
        no_auth_client = TestClient(app, raise_server_exceptions=False)
        resp = no_auth_client.post(
            f"/v2/interview/{TWIN_ID}/stream",
            json={"message": "Hello"},
        )
        assert resp.status_code == 401


class TestInterviewStats:
    """GET /v2/interview/{id}/stats tests."""

    def test_returns_exchange_count(self, client):
        mock_count = AsyncMock(return_value=12)

        with patch("routers.interview_stats.count_faqs", mock_count), \
             patch("routers.interview_stats.verify_twin_ownership", return_value=True) as mock_owner:
            resp = client.get(f"/v2/interview/{TWIN_ID}/stats")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["data"]["twin_id"] == TWIN_ID
        assert body["data"]["exchange_count"] == 12
        mock_owner.assert_called_once()
        mock_count.assert_awaited_once_with(TWIN_ID, origin="interview")

    def test_stats_zero_when_no_exchanges(self, client):
        with patch("routers.interview_stats.count_faqs", AsyncMock(return_value=0)), \
             patch("routers.interview_stats.verify_twin_ownership", return_value=True):
            resp = client.get(f"/v2/interview/{TWIN_ID}/stats")

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "data": {"twin_id": TWIN_ID, "exchange_count": 0}}

    def test_stats_forbidden_for_non_owner(self, client):
        from fastapi import HTTPException

        mock_count = AsyncMock(return_value=5)
        with patch("routers.interview_stats.count_faqs", mock_count), \
             patch(
                 "routers.interview_stats.verify_twin_ownership",
                 side_effect=HTTPException(status_code=403, detail="Forbidden"),
             ):
            resp = client.get(f"/v2/interview/{TWIN_ID}/stats")

        assert resp.status_code == 403
        mock_count.assert_not_awaited()

    def test_stats_503_when_count_fails(self, client):
        with patch("routers.interview_stats.count_faqs", AsyncMock(side_effect=RuntimeError("db down"))), \
             patch("routers.interview_stats.verify_twin_ownership", return_value=True):
            resp = client.get(f"/v2/interview/{TWIN_ID}/stats")

        assert resp.status_code == 503
        assert "db down" not in resp.text
