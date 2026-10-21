"""
Tests for the citation sentinel ([CITATIONS_JSON:...]) emitted by agent_service.chat_stream.

Verifies that:
1. _handle_chat (chat.py) strips the sentinel and emits event: metadata with citation_details
2. widget_chat_stream (widget.py) strips the sentinel — it must NOT appear in any token event
3. widget_chat_turn (widget.py) strips the sentinel from the joined message

These tests guard against the production issue discovered during PR #4 review, where
widget.py bypasses _handle_chat and would have leaked the raw sentinel to consumers.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import chat, widget as widget_router


# ─── Helpers ────────────────────────────────────────────────────────────────

_CITATIONS = [
    {"id": "src-1", "filename": "resume.pdf", "citation_url": "https://example.com", "chunk_preview": "Relevant text."}
]
_SENTINEL = f"\n[CITATIONS_JSON:{json.dumps(_CITATIONS)}]"


def _parse_sse_events(text: str) -> list[dict]:
    events: list[dict] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_type = None
        payload = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event_type = line[7:]
            if line.startswith("data: "):
                payload = json.loads(line[6:])
        if event_type and payload is not None:
            events.append({"type": event_type, "data": payload})
    return events


def _build_app(*routers) -> FastAPI:
    app = FastAPI()
    for r in routers:
        app.include_router(r)
    return app


class _FakeConversationRepo:
    def __init__(self):
        self.conversations: dict = {}
        self.messages: list = []

    def get_conversation(self, conversation_id: str):
        return self.conversations.get(conversation_id)

    def create_conversation(self, **kwargs):
        self.conversations[kwargs["conversation_id"]] = kwargs
        return kwargs

    def add_message(self, **kwargs):
        self.messages.append(kwargs)
        return kwargs


# ─── chat.py / _handle_chat tests ───────────────────────────────────────────

def test_handle_chat_stream_emits_metadata_event_for_citations(monkeypatch):
    """Sentinel in chat_stream → stripped from message text, emitted as metadata event."""
    repo = _FakeConversationRepo()

    async def fake_chat_stream(**kwargs):
        yield "Hello, "
        yield "here is my answer."
        yield _SENTINEL

    monkeypatch.setattr(chat, "_public_access_or_404", lambda twin_id, token: None)
    monkeypatch.setattr(chat, "_enforce_public_rate_limit", lambda twin_id, http_request: None)
    monkeypatch.setattr(chat, "_load_twin_context", lambda twin_id: ({"name": "Ada"}, []))
    monkeypatch.setattr(chat, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(chat, "get_conversation_repository", lambda: repo)

    app = _build_app(chat.router)
    client = TestClient(app)

    response = client.post(
        "/v2/chat/public/twin-1/token-123/stream",
        json={"message": "Tell me about yourself"},
    )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)

    event_types = [e["type"] for e in events]
    assert "metadata" in event_types, f"Expected metadata event, got: {event_types}"
    assert event_types[-1] == "done"

    # metadata event must contain citation_details
    metadata_event = next(e for e in events if e["type"] == "metadata")
    assert metadata_event["data"]["citation_details"] == _CITATIONS
    assert metadata_event["data"]["citations"] == ["resume.pdf"]

    # sentinel must NOT appear in any message event text
    for event in events:
        if event["type"] == "message":
            assert "CITATIONS_JSON" not in event["data"].get("text", ""), (
                f"Sentinel leaked into message event: {event['data']}"
            )


def test_handle_chat_stream_no_metadata_when_no_citations(monkeypatch):
    """No sentinel in chat_stream → no metadata event emitted."""
    repo = _FakeConversationRepo()

    async def fake_chat_stream(**kwargs):
        yield "Plain answer with no citations."

    monkeypatch.setattr(chat, "_public_access_or_404", lambda twin_id, token: None)
    monkeypatch.setattr(chat, "_enforce_public_rate_limit", lambda twin_id, http_request: None)
    monkeypatch.setattr(chat, "_load_twin_context", lambda twin_id: ({"name": "Ada"}, []))
    monkeypatch.setattr(chat, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(chat, "get_conversation_repository", lambda: repo)

    app = _build_app(chat.router)
    client = TestClient(app)

    response = client.post(
        "/v2/chat/public/twin-1/token-123/stream",
        json={"message": "hi"},
    )

    events = _parse_sse_events(response.text)
    event_types = [e["type"] for e in events]
    assert "metadata" not in event_types


def test_handle_chat_sync_strips_sentinel_from_response_message(monkeypatch):
    """Sync (non-stream) endpoint must strip the sentinel from the joined message."""
    repo = _FakeConversationRepo()

    async def fake_chat_stream(**kwargs):
        yield "My answer."
        yield _SENTINEL

    monkeypatch.setattr(chat, "_public_access_or_404", lambda twin_id, token: None)
    monkeypatch.setattr(chat, "_enforce_public_rate_limit", lambda twin_id, http_request: None)
    monkeypatch.setattr(chat, "_load_twin_context", lambda twin_id: ({"name": "Ada"}, []))
    monkeypatch.setattr(chat, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(chat, "get_conversation_repository", lambda: repo)

    app = _build_app(chat.router)
    client = TestClient(app)

    response = client.post(
        "/v2/chat/public/twin-1/token-123",
        json={"message": "hi"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "CITATIONS_JSON" not in body["message"], (
        f"Sentinel leaked into sync response: {body['message']}"
    )


# ─── widget.py tests ────────────────────────────────────────────────────────

def _build_widget_app(monkeypatch, fake_stream) -> FastAPI:
    """Build widget app with all external dependencies stubbed."""
    monkeypatch.setattr(
        widget_router, "_fetch_twin_row",
        lambda twin_id: {"id": "twin-1", "name": "Ada", "settings": {"persona_profile": {"name": "Ada"}}},
    )
    monkeypatch.setattr(
        widget_router, "is_publicly_accessible_twin_record",
        lambda twin: True,
    )
    monkeypatch.setattr(widget_router, "chat_stream", fake_stream)

    app = FastAPI()
    app.include_router(widget_router.router)
    # Override the Depends so API key validation is bypassed
    app.dependency_overrides[widget_router._validate_widget_request] = lambda: {"id": "key-1", "twin_id": "twin-1"}
    return app


def test_widget_stream_strips_citation_sentinel(monkeypatch):
    """widget_chat_stream must not emit the sentinel as a token event."""
    async def fake_chat_stream(**kwargs):
        yield "Widget answer."
        yield _SENTINEL

    client = TestClient(_build_widget_app(monkeypatch, fake_chat_stream))
    response = client.post("/widget/chat/twin-1/stream", json={"message": "hello"})

    assert response.status_code == 200
    events = _parse_sse_events(response.text)

    for event in events:
        if event["type"] == "token":
            assert "CITATIONS_JSON" not in event["data"].get("token", ""), (
                f"Sentinel leaked into widget token event: {event['data']}"
            )


def test_widget_stream_only_clean_tokens_forwarded(monkeypatch):
    """widget_chat_stream: clean chunks forwarded; sentinel chunk skipped entirely."""
    async def fake_chat_stream(**kwargs):
        yield "first"
        yield "second"
        yield _SENTINEL

    client = TestClient(_build_widget_app(monkeypatch, fake_chat_stream))
    response = client.post("/widget/chat/twin-1/stream", json={"message": "hello"})

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    token_events = [e for e in events if e["type"] == "token"]

    # Exactly 2 clean tokens forwarded; sentinel chunk produces no token event
    assert len(token_events) == 2
    assert token_events[0]["data"]["token"] == "first"
    assert token_events[1]["data"]["token"] == "second"


def test_widget_turn_strips_citation_sentinel(monkeypatch):
    """widget_chat_turn (non-stream): sentinel must not appear in response message."""
    async def fake_chat_stream(**kwargs):
        yield "Widget sync answer."
        yield _SENTINEL

    client = TestClient(_build_widget_app(monkeypatch, fake_chat_stream))
    response = client.post("/widget/chat/twin-1", json={"message": "hello"})

    assert response.status_code == 200
    body = response.json()
    assert "CITATIONS_JSON" not in body["message"], (
        f"Sentinel leaked into widget_chat_turn message: {body['message']}"
    )
    assert "Widget sync answer." in body["message"]
