from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.gemini_live as gemini_live


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(gemini_live.router)
    return TestClient(app, raise_server_exceptions=False)


def _token(monkeypatch, twin_id: str = "twin-1", meeting_id: str = "mtg-1", ttl_seconds: int = 300) -> str:
    monkeypatch.setattr(gemini_live, "_TOKEN_SECRET", "test-secret")
    monkeypatch.setattr(gemini_live, "_TOKEN_TTL_SECONDS", 300)
    return gemini_live.issue_meeting_token(twin_id, meeting_id, ttl_seconds=ttl_seconds)


def _mock_supabase(twin_row: dict) -> MagicMock:
    response = SimpleNamespace(data=twin_row)
    twins = MagicMock()
    twins.select.return_value = twins
    twins.eq.return_value = twins
    twins.single.return_value = twins
    twins.execute.return_value = response

    sb = MagicMock()
    sb.table.return_value = twins
    return sb


def test_search_knowledge_returns_chunks(monkeypatch):
    token = _token(monkeypatch)
    mock_search = AsyncMock(
        return_value=[
            {
                "text": "Private note",
                "score": 0.91,
                "source_id": "src-1",
                "source_type": "persona",
            }
        ]
    )

    with patch.object(gemini_live, "vector_search", mock_search):
        response = _client().post(
            f"/v2/gemini-live/twin-1/search_knowledge?api_key_token={token}",
            json={"query": "What do I know?", "top_k": 3},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["chunks"] == [
        {
            "text": "Private note",
            "score": 0.91,
            "source_id": "src-1",
            "source_type": "persona",
        }
    ]
    mock_search.assert_awaited_once_with(query="What do I know?", twin_id="twin-1", top_k=3)


def test_search_knowledge_enforces_twin_scope(monkeypatch):
    token = _token(monkeypatch, twin_id="twin-a", meeting_id="mtg-scope")

    response = _client().post(
        f"/v2/gemini-live/twin-b/search_knowledge?api_key_token={token}",
        json={"query": "scope check", "top_k": 5},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Token twin mismatch"


def test_ephemeral_token_rejects_malformed_token(monkeypatch):
    monkeypatch.setattr(gemini_live, "_TOKEN_SECRET", "test-secret")

    response = _client().get("/v2/gemini-live/twin-1/ephemeral-token?api_key_token=bad-token")

    assert response.status_code == 401
    assert response.json()["detail"] == "Malformed token"


def test_ephemeral_token_rejects_expired_token(monkeypatch):
    token = _token(monkeypatch, ttl_seconds=-1)

    response = _client().get(
        f"/v2/gemini-live/twin-1/ephemeral-token?api_key_token={token}"
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Token expired"


def test_ephemeral_token_rejects_tampered_token(monkeypatch):
    token = _token(monkeypatch)
    tampered = f"{token[:-1]}x"

    response = _client().get(
        f"/v2/gemini-live/twin-1/ephemeral-token?api_key_token={tampered}"
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token signature"


def test_ephemeral_token_returns_access_token_only(monkeypatch):
    token = _token(monkeypatch)

    with patch.object(gemini_live, "_create_auth_token", return_value="auth-token-123"):
        response = _client().get(
            f"/v2/gemini-live/twin-1/ephemeral-token?api_key_token={token}"
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["access_token"] == "auth-token-123"
    assert "api_key" not in body
    assert body["model"]


def test_ephemeral_token_creation_failure_fails_closed(monkeypatch):
    token = _token(monkeypatch)

    with patch.object(gemini_live, "_create_auth_token", side_effect=RuntimeError("boom")):
        response = _client().get(
            f"/v2/gemini-live/twin-1/ephemeral-token?api_key_token={token}"
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to create Gemini auth token"


def test_log_client_event_accepts_valid_payload(monkeypatch):
    token = _token(monkeypatch)

    response = _client().post(
        f"/v2/gemini-live/twin-1/log_client_event?api_key_token={token}",
        json={
            "event": "ws_open",
            "level": "info",
            "details": {"generation": 1},
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok"}


def test_log_client_event_enforces_twin_scope(monkeypatch):
    token = _token(monkeypatch, twin_id="twin-a", meeting_id="mtg-1")

    response = _client().post(
        f"/v2/gemini-live/twin-b/log_client_event?api_key_token={token}",
        json={"event": "ws_open", "details": {}},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Token twin mismatch"


def test_persona_config_defaults_voice_to_kore(monkeypatch):
    token = _token(monkeypatch)
    mock_sb = _mock_supabase(
        {
            "id": "twin-1",
            "name": "Alice",
            "settings": {"persona_profile": {"role": "Investor"}},
        }
    )

    with patch.object(gemini_live, "get_supabase_client", return_value=mock_sb):
        response = _client().get(
            f"/v2/gemini-live/twin-1/persona-config?api_key_token={token}"
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["voice_name"] == "Kore"
    assert "Alice" in body["system_instruction"]


def test_persona_config_returns_saved_voice(monkeypatch):
    token = _token(monkeypatch)
    mock_sb = _mock_supabase(
        {
            "id": "twin-1",
            "name": "Alice",
            "settings": {
                "gemini_voice": "Zephyr",
                "persona_profile": {"role": "Investor", "topics": ["fundraising"]},
            },
        }
    )

    with patch.object(gemini_live, "get_supabase_client", return_value=mock_sb):
        response = _client().get(
            f"/v2/gemini-live/twin-1/persona-config?api_key_token={token}"
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["voice_name"] == "Zephyr"
    assert "fundraising" in body["system_instruction"]
