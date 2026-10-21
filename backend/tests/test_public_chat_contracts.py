from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import chat, profile_public


def _build_app(router) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


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


def _public_twin(*, status: str = "active", public_share_enabled: bool = True) -> dict:
    return {
        "id": "twin-1",
        "status": status,
        "settings": {
            "widget_settings": {
                "share_token": "token-123",
                "public_share_enabled": public_share_enabled,
            }
        },
    }


class _FakeConversationRepo:
    def __init__(self):
        self.conversations: dict[str, dict] = {}
        self.created_conversations: list[dict] = []
        self.messages: list[dict] = []

    def get_conversation(self, conversation_id: str):
        return self.conversations.get(conversation_id)

    def create_conversation(self, **kwargs):
        self.conversations[kwargs["conversation_id"]] = kwargs
        self.created_conversations.append(kwargs)
        return kwargs

    def add_message(self, **kwargs):
        self.messages.append(kwargs)
        return kwargs


def test_sync_public_chat_persists_conversation_and_messages(monkeypatch):
    repo = _FakeConversationRepo()

    async def fake_chat_stream(**kwargs):
        yield f"reply:{kwargs['message']}"

    monkeypatch.setattr(chat, "_public_access_or_404", lambda twin_id, token: None)
    monkeypatch.setattr(chat, "_enforce_public_rate_limit", lambda twin_id, http_request: None)
    monkeypatch.setattr(chat, "_load_twin_context", lambda twin_id: ({"name": "Ada"}, []))
    monkeypatch.setattr(chat, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(chat, "get_conversation_repository", lambda: repo)

    app = _build_app(chat.router)
    client = TestClient(app)

    first_response = client.post(
        "/v2/chat/public/twin-1/token-123",
        json={"message": "hello", "client_context": {"source": "landing"}},
    )

    assert first_response.status_code == 200
    conversation_id = first_response.json()["conversation_id"]
    assert len(repo.created_conversations) == 1
    assert repo.created_conversations[0]["conversation_id"] == conversation_id
    assert repo.created_conversations[0]["share_token"] == "token-123"
    assert repo.created_conversations[0]["metadata"]["client_context"] == {"source": "landing"}
    assert [message["role"] for message in repo.messages] == ["user", "assistant"]
    assert repo.messages[0]["content"] == "hello"
    assert repo.messages[1]["content"] == "reply:hello"

    second_response = client.post(
        "/v2/chat/public/twin-1/token-123",
        json={"message": "again", "conversation_id": conversation_id},
    )

    assert second_response.status_code == 200
    assert second_response.json()["conversation_id"] == conversation_id
    assert len(repo.created_conversations) == 1
    assert [message["content"] for message in repo.messages[-2:]] == ["again", "reply:again"]


def test_stream_public_chat_persists_same_fields_as_sync(monkeypatch):
    repo = _FakeConversationRepo()

    async def fake_chat_stream(**kwargs):
        yield "chunk-one"
        yield "chunk-two"

    monkeypatch.setattr(chat, "_public_access_or_404", lambda twin_id, token: None)
    monkeypatch.setattr(chat, "_enforce_public_rate_limit", lambda twin_id, http_request: None)
    monkeypatch.setattr(chat, "_load_twin_context", lambda twin_id: ({"name": "Ada"}, []))
    monkeypatch.setattr(chat, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(chat, "get_conversation_repository", lambda: repo)

    app = _build_app(chat.router)
    client = TestClient(app)

    response = client.post(
        "/v2/chat/public/twin-1/token-123/stream",
        json={"message": "hello", "client_context": {"page": "share"}},
    )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert [event["type"] for event in events] == ["session", "message", "message", "done"]
    assert len(repo.created_conversations) == 1
    assert repo.created_conversations[0]["share_token"] == "token-123"
    assert repo.created_conversations[0]["metadata"]["client_context"] == {"page": "share"}
    assert [message["content"] for message in repo.messages] == ["hello", "chunk-onechunk-two"]


def test_public_chat_rejects_non_active_twin(monkeypatch):
    monkeypatch.setattr(chat, "_fetch_twin_row", lambda twin_id: _public_twin(status="draft"))
    monkeypatch.setattr(chat, "validate_share_token", lambda token, twin_id: True)

    app = _build_app(chat.router)
    client = TestClient(app)

    response = client.post(
        "/v2/chat/public/twin-1/token-123",
        json={"message": "hello"},
    )

    assert response.status_code == 404


def test_public_profile_rejects_non_active_twin(monkeypatch):
    monkeypatch.setattr(profile_public, "_fetch_public_twin", lambda twin_id: _public_twin(status="draft"))
    monkeypatch.setattr(profile_public, "validate_share_token", lambda token, twin_id: True)

    app = _build_app(profile_public.router)
    client = TestClient(app)

    response = client.get("/share/twin-1/token-123/profile")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PROFILE_NOT_PUBLISHED"


def test_public_profile_endpoint_redacts_hidden_fields_and_internal_voice_id(monkeypatch):
    class _EmptyPolicyQuery:
        data: list[dict] = []

        def select(self, *args, **kwargs):
            return self

        def eq(self, *args, **kwargs):
            return self

        def or_(self, *args, **kwargs):
            return self

        def order(self, *args, **kwargs):
            return self

        def limit(self, *args, **kwargs):
            return self

        def execute(self):
            return self

    twin = _public_twin()
    twin["settings"] = {
        **twin["settings"],
        "subscription_tier": "core",
        "section_visibility": {
            "areas_of_expertise": False,
            "featured_content": True,
            "social_links": True,
            "pinned_questions": False,
        },
        "show_branding": False,
        "voice_id": "voice-secret",
        "public_profile": {
            "social_link_visibility": {"website": True, "linkedin": False},
            # Execution-board 0.1 (PRD R1): is_publicly_accessible_twin_record
            # now always requires the marketplace-quality gate (meaningful
            # bio + a populated work_experience/education entry) — there is
            # no longer a quality-free path via public_share_enabled alone.
            # This test only cares about redaction (build_public_profile_pack
            # is mocked below), so this content just needs to clear the gate.
            "display_name": "Test Persona",
            "occupation": "Founder",
            "short_description": "Building AI products",
            "bio": "Founder and builder working on AI-powered products for small teams.",
            "work_experience": [
                {"company": "Acme Robotics", "role": "Founder", "description": "Building AI products."}
            ],
        },
    }
    full_profile = {
        "areas_of_expertise": ["AI Product Development"],
        "key_achievements": ["Built a company"],
        "personality_traits": ["Direct"],
        "contributions": ["Open-source work"],
        "pinned_questions": ["What do you do?"],
        "featured_content": [
            {"type": "youtube", "url": "https://youtu.be/visible"},
            {"type": "link", "url": "https://hidden.example.com", "hidden": True},
        ],
        "social_links": {
            "website": "https://example.com",
            "linkedin": "https://linkedin.com/in/private",
        },
        "social_link_visibility": {"website": True, "linkedin": False},
        "settings": {
            "subscription_tier": "core",
            "section_visibility": twin["settings"]["section_visibility"],
            "show_branding": False,
            "voice_id": "voice-secret",
        },
        "has_voice": True,
        "public_topics": [],
    }

    monkeypatch.setattr(profile_public, "_fetch_public_twin", lambda twin_id: twin)
    monkeypatch.setattr(profile_public, "validate_share_token", lambda token, twin_id: True)
    monkeypatch.setattr(profile_public, "build_public_profile_pack", lambda _twin: dict(full_profile))
    monkeypatch.setattr(profile_public, "supabase", type(
        "FakeSupabase",
        (),
        {"table": lambda self, _name: _EmptyPolicyQuery()},
    )())

    app = _build_app(profile_public.router)
    client = TestClient(app)

    response = client.get("/share/twin-1/token-123/profile")

    assert response.status_code == 200
    body = response.json()
    assert body["areas_of_expertise"] == []
    assert body["pinned_questions"] == []
    assert body["featured_content"] == [{"type": "youtube", "url": "https://youtu.be/visible"}]
    assert body["social_links"] == {"website": "https://example.com"}
    assert body["social_link_visibility"] == {"website": True}
    assert body["has_voice"] is True
    assert body["settings"] == {
        "subscription_tier": "core",
        "section_visibility": twin["settings"]["section_visibility"],
        "show_branding": False,
        # persona-themes: the redactor emits curated layout fields (default-deny →
        # None when the stored value isn't in the allow-list). Public-safe, not PII.
        "theme_id": None,
        "accent": None,
    }
    assert "voice_id" not in body["settings"]


def test_public_validate_share_endpoint_redacts_public_pack(monkeypatch):
    from modules import public_profile_pack as pack_module
    from modules import share_links
    from routers import auth

    class _TwinQuery:
        def __init__(self, data: dict):
            self.data = data

        def select(self, *args, **kwargs):
            return self

        def eq(self, *args, **kwargs):
            return self

        def single(self):
            return self

        def execute(self):
            return self

    class _Supabase:
        def __init__(self, twin: dict):
            self.twin = twin

        def table(self, name: str):
            assert name == "twins"
            return _TwinQuery(self.twin)

    twin = _public_twin()
    twin["name"] = "Ada"
    twin["settings"] = {
        **twin["settings"],
        "section_visibility": {
            "areas_of_expertise": False,
            "social_links": True,
        },
        "voice_id": "voice-secret",
        "public_profile": {
            "social_link_visibility": {"website": True, "linkedin": False},
        },
    }
    full_profile = {
        "name": "Ada",
        "areas_of_expertise": ["AI Product Development"],
        "social_links": {
            "website": "https://example.com",
            "linkedin": "https://linkedin.com/in/private",
        },
        "social_link_visibility": {"website": True, "linkedin": False},
        "settings": {
            "section_visibility": twin["settings"]["section_visibility"],
            "voice_id": "voice-secret",
        },
        "has_voice": True,
    }

    monkeypatch.setattr(share_links, "validate_share_token", lambda token, twin_id: True)
    monkeypatch.setattr(pack_module, "build_public_profile_pack", lambda _twin: dict(full_profile))
    monkeypatch.setattr(auth, "supabase", _Supabase(twin))

    app = _build_app(auth.router)
    client = TestClient(app)

    response = client.get("/public/validate-share/twin-1/token-123")

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["areas_of_expertise"] == []
    assert body["social_links"] == {"website": "https://example.com"}
    assert body["social_link_visibility"] == {"website": True}
    assert body["has_voice"] is True
    assert "voice_id" not in body["settings"]
