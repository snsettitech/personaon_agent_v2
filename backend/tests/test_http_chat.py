"""Integration tests for chat HTTP endpoints.

Tests the full HTTP request/response cycle through FastAPI for
chat streaming, conversations, and promote-to-knowledge endpoints.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

TWIN_ID = "test-twin-chat"
FAKE_USER = {"user_id": "test-user", "tenant_id": "test-tenant"}


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


def _make_supabase_mock(twin_data=None):
    """Build a mock Supabase client."""
    mock_sb = MagicMock()
    resp = MagicMock()
    resp.data = twin_data
    mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = resp
    return mock_sb


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


# ── Chat Stream Tests ─────────────────────────────────────────────────


class TestOwnerChatStream:
    """POST /v2/chat/owner/{id}/stream tests."""

    def test_stream_returns_sse(self, client):
        twin_data = {
            "id": TWIN_ID,
            "name": "Test",
            "status": "active",
            "settings": {"persona_profile": {"name": "Test Person"}},
        }
        mock_sb = _make_supabase_mock(twin_data)

        async def fake_chat_stream(**kwargs):
            yield "Hello, "
            yield "how can I help?"

        mock_conv_repo = MagicMock()
        mock_conv_repo.get_conversation.return_value = None
        mock_conv_repo.create_conversation.return_value = {"id": "conv-1"}
        mock_conv_repo.add_message.return_value = {"id": "msg-1"}

        with patch("routers.chat.get_supabase_client", return_value=mock_sb), \
             patch("routers.chat.verify_twin_ownership", return_value=True), \
             patch("routers.chat.ensure_twin_active", return_value=True), \
             patch("routers.chat.chat_stream", side_effect=fake_chat_stream), \
             patch("routers.chat.get_conversation_repository", return_value=mock_conv_repo):

            resp = client.post(
                f"/v2/chat/owner/{TWIN_ID}/stream",
                json={"message": "Tell me about yourself"},
            )

        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)

        event_types = [e["type"] for e in events]
        assert "session" in event_types
        assert "message" in event_types
        assert "done" in event_types

        # Verify message content
        messages = [e for e in events if e["type"] == "message"]
        texts = [m["data"]["text"] for m in messages]
        assert "Hello, " in texts
        assert "how can I help?" in texts


# ── Conversations List Tests ──────────────────────────────────────────


class TestConversationsList:
    """GET /v2/chat/conversations tests."""

    def test_list_conversations(self, client):
        mock_conv_repo = MagicMock()
        mock_conv_repo.list_conversations.return_value = [
            {"id": "conv-1", "twin_id": TWIN_ID, "surface": "owner"},
            {"id": "conv-2", "twin_id": TWIN_ID, "surface": "public"},
        ]

        with patch("routers.chat.get_conversation_repository", return_value=mock_conv_repo):
            resp = client.get("/v2/chat/conversations")

        assert resp.status_code == 200
        body = resp.json()
        assert "conversations" in body
        assert "count" in body
        assert body["count"] == 2

    def test_list_conversations_empty(self, client):
        mock_conv_repo = MagicMock()
        mock_conv_repo.list_conversations.return_value = []

        with patch("routers.chat.get_conversation_repository", return_value=mock_conv_repo):
            resp = client.get("/v2/chat/conversations")

        assert resp.status_code == 200
        assert resp.json()["count"] == 0


# ── Conversation Messages Tests ───────────────────────────────────────


class TestConversationMessages:
    """GET /v2/chat/conversations/{id}/messages tests."""

    def test_get_messages(self, client):
        mock_conv_repo = MagicMock()
        mock_conv_repo.get_conversation_for_tenant.return_value = {
            "id": "conv-1",
            "twin_id": TWIN_ID,
            "tenant_id": FAKE_USER["tenant_id"],
        }
        mock_conv_repo.list_messages.return_value = [
            {"id": "msg-1", "role": "user", "content": "Hello"},
            {"id": "msg-2", "role": "assistant", "content": "Hi there!"},
        ]

        with patch("routers.chat.get_conversation_repository", return_value=mock_conv_repo):
            resp = client.get("/v2/chat/conversations/conv-1/messages")

        assert resp.status_code == 200
        body = resp.json()
        assert body["conversation_id"] == "conv-1"
        assert len(body["messages"]) == 2

    def test_get_messages_not_found(self, client):
        mock_conv_repo = MagicMock()
        mock_conv_repo.get_conversation_for_tenant.return_value = None

        with patch("routers.chat.get_conversation_repository", return_value=mock_conv_repo):
            resp = client.get("/v2/chat/conversations/nonexistent/messages")

        assert resp.status_code == 404


# ── Promote to Knowledge Tests ────────────────────────────────────────


class TestPromoteToKnowledge:
    """POST /v2/chat/conversations/{id}/promote tests."""

    def test_promote_success(self, client):
        mock_conv_repo = MagicMock()
        mock_conv_repo.get_conversation_for_tenant.return_value = {
            "id": "conv-1",
            "twin_id": TWIN_ID,
            "tenant_id": FAKE_USER["tenant_id"],
        }

        with patch("routers.chat.get_conversation_repository", return_value=mock_conv_repo), \
             patch("adk_core.services.vector_store.upsert_faq", return_value="point-99") as mock_upsert, \
             patch("adk_core.services.agent_service.invalidate_agent") as mock_invalidate:

            resp = client.post(
                "/v2/chat/conversations/conv-1/promote",
                json={
                    "question": "What is your approach to hiring?",
                    "answer": "I look for curiosity and grit above credentials.",
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "promoted"
        assert body["point_id"] == "point-99"
        assert body["twin_id"] == TWIN_ID
        mock_upsert.assert_called_once()
        mock_invalidate.assert_called_once_with(TWIN_ID)

    def test_promote_missing_fields(self, client):
        mock_conv_repo = MagicMock()
        mock_conv_repo.get_conversation_for_tenant.return_value = {
            "id": "conv-1",
            "twin_id": TWIN_ID,
            "tenant_id": FAKE_USER["tenant_id"],
        }

        with patch("routers.chat.get_conversation_repository", return_value=mock_conv_repo):
            resp = client.post(
                "/v2/chat/conversations/conv-1/promote",
                json={"question": "something", "answer": ""},
            )

        assert resp.status_code == 400
        assert "required" in resp.json()["detail"].lower()

    def test_promote_conversation_not_found(self, client):
        mock_conv_repo = MagicMock()
        mock_conv_repo.get_conversation_for_tenant.return_value = None

        with patch("routers.chat.get_conversation_repository", return_value=mock_conv_repo):
            resp = client.post(
                "/v2/chat/conversations/nonexistent/promote",
                json={"question": "Q", "answer": "A"},
            )

        assert resp.status_code == 404


# ── Auth Tests ────────────────────────────────────────────────────────


class TestChatAuth:
    """Auth enforcement for chat endpoints."""

    def test_stream_401_without_auth(self):
        from main import app
        app.dependency_overrides.clear()
        no_auth_client = TestClient(app, raise_server_exceptions=False)
        resp = no_auth_client.post(
            f"/v2/chat/owner/{TWIN_ID}/stream",
            json={"message": "Hello"},
        )
        assert resp.status_code == 401

    def test_conversations_401_without_auth(self):
        from main import app
        app.dependency_overrides.clear()
        no_auth_client = TestClient(app, raise_server_exceptions=False)
        resp = no_auth_client.get("/v2/chat/conversations")
        assert resp.status_code == 401

    def test_messages_401_without_auth(self):
        from main import app
        app.dependency_overrides.clear()
        no_auth_client = TestClient(app, raise_server_exceptions=False)
        resp = no_auth_client.get("/v2/chat/conversations/conv-1/messages")
        assert resp.status_code == 401

    def test_promote_401_without_auth(self):
        from main import app
        app.dependency_overrides.clear()
        no_auth_client = TestClient(app, raise_server_exceptions=False)
        resp = no_auth_client.post(
            "/v2/chat/conversations/conv-1/promote",
            json={"question": "Q", "answer": "A"},
        )
        assert resp.status_code == 401
