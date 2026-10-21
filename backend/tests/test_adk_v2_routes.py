from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from adk_core.schemas.api import ChatTurnResponse
from routers import chat


def _build_app(router) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def test_owner_chat_turn_uses_v2_contract(monkeypatch):
    calls = {}

    async def fake_handle_chat(**kwargs):
        calls.update(kwargs)
        return ChatTurnResponse(
            conversation_id="conv-1",
            message="I think through first principles.",
            citations=["src-1"],
            persona_version="adk-v1",
            surface=kwargs["surface"],
        )

    monkeypatch.setattr(chat, "_handle_chat", fake_handle_chat)
    monkeypatch.setattr(chat, "verify_twin_ownership", lambda twin_id, user: True)
    monkeypatch.setattr(chat, "ensure_twin_active", lambda twin_id: True)

    app = _build_app(chat.router)
    app.dependency_overrides[chat.require_tenant] = lambda: {
        "tenant_id": "tenant-1",
        "user_id": "user-1",
    }
    client = TestClient(app)

    response = client.post(
        "/v2/chat/owner/twin-1",
        json={"message": "  Tell   me about your thinking  "},
    )

    assert response.status_code == 200
    assert response.json()["surface"] == "owner"
    assert calls["surface"] == "owner"
    assert calls["tenant_id"] == "tenant-1"
    assert calls["request"].message == "Tell me about your thinking"


def test_widget_chat_stream_emits_sse_events(monkeypatch):
    async def fake_chat_stream(**kwargs):
        del kwargs
        yield "Shipping matters."

    class FakeConversationRepo:
        def get_conversation(self, conversation_id):
            del conversation_id
            return

        def create_conversation(self, **kwargs):
            return kwargs

        def add_message(self, **kwargs):
            return kwargs

    monkeypatch.setattr(chat, "_widget_access_or_404", lambda twin_id: None)
    monkeypatch.setattr(chat, "_load_twin_context", lambda twin_id: ({"name": "Test"}, []))
    monkeypatch.setattr(chat, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(chat, "get_conversation_repository", lambda: FakeConversationRepo())

    app = _build_app(chat.router)
    client = TestClient(app)

    response = client.post("/v2/chat/widget/twin-1/stream", json={"message": "hello"})

    assert response.status_code == 200
    assert "event: session" in response.text
    assert "event: message" in response.text
    assert "event: done" in response.text


def test_public_chat_turn_routes_to_public_surface(monkeypatch):
    calls = {}

    async def fake_handle_chat(**kwargs):
        calls.update(kwargs)
        return ChatTurnResponse(
            conversation_id="conv-2",
            message="I would approach it methodically.",
            citations=[],
            persona_version="adk-v2",
            surface=kwargs["surface"],
        )

    monkeypatch.setattr(chat, "_handle_chat", fake_handle_chat)
    monkeypatch.setattr(chat, "_public_access_or_404", lambda twin_id, token: None)
    monkeypatch.setattr(chat, "_enforce_public_rate_limit", lambda twin_id, http_request: None)

    app = _build_app(chat.router)
    client = TestClient(app)

    response = client.post(
        "/v2/chat/public/twin-9/token-123",
        json={"message": "What matters most to you?"},
    )

    assert response.status_code == 200
    assert response.json()["surface"] == "public"
    assert calls["surface"] == "public"
    assert calls["share_token"] == "token-123"
