import json
import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request


async def _list_to_agen(items: list[str]):
    for item in items:
        yield item


def _request_with_headers(headers: list[tuple[bytes, bytes]], scheme: str = "http") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v2/voice/twin-1/call-session/public",
            "scheme": scheme,
            "server": ("internal", 8080),
            "headers": headers,
            "query_string": b"",
        }
    )


def test_session_token_round_trips_and_expires(monkeypatch):
    from routers.voice_call import _sign_call_session_token, _verify_call_session_token

    monkeypatch.setenv("VOICE_CALL_SESSION_SECRET", "test-secret")

    token = _sign_call_session_token(
        session_id="session-123",
        twin_id="11111111-1111-1111-1111-111111111111",
        is_public=True,
        expires_at=int(time.time()) + 60,
    )

    payload = _verify_call_session_token(token)

    assert payload["session_id"] == "session-123"
    assert payload["twin_id"] == "11111111-1111-1111-1111-111111111111"
    assert payload["is_public"] is True

    expired = _sign_call_session_token(
        session_id="session-expired",
        twin_id="11111111-1111-1111-1111-111111111111",
        is_public=False,
        expires_at=int(time.time()) - 1,
    )

    with pytest.raises(HTTPException) as exc_info:
        _verify_call_session_token(expired)

    assert exc_info.value.status_code == 401


def test_voice_runtime_secrets_are_stripped(monkeypatch):
    from routers.voice_call import (
        _get_api_key,
        _get_deepgram_api_key,
        _get_voice_llm_secret,
        _get_voice_session_secret,
    )

    monkeypatch.setenv("ELEVENLABS_API_KEY", " eleven-key\r\n")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "deepgram-key\r\n")
    monkeypatch.setenv("VOICE_LLM_WEBHOOK_SECRET", " llm-secret\n")
    monkeypatch.setenv("VOICE_CALL_SESSION_SECRET", " session-secret\r\n")

    assert _get_api_key() == "eleven-key"
    assert _get_deepgram_api_key() == "deepgram-key"
    assert _get_voice_llm_secret() == "llm-secret"
    assert _get_voice_session_secret() == "session-secret"

    monkeypatch.delenv("VOICE_LLM_WEBHOOK_SECRET")
    monkeypatch.setenv("ELEVENLABS_WEBHOOK_SECRET", " fallback-secret\r\n")

    assert _get_voice_llm_secret() == "fallback-secret"


def test_build_deepgram_settings_uses_persona_voice_and_backend_llm(monkeypatch):
    from routers.voice_call import _build_deepgram_settings

    monkeypatch.setenv("ELEVENLABS_API_KEY", "eleven-key")
    monkeypatch.setenv("VOICE_LLM_WEBHOOK_SECRET", "llm-secret")
    monkeypatch.setenv("DEEPGRAM_VOICE_LISTEN_MODEL", "flux-general-en")
    monkeypatch.setenv("DEEPGRAM_VOICE_LISTEN_VERSION", "v2")
    monkeypatch.setenv("ELEVENLABS_TTS_MODEL_ID", "eleven_flash_v2_5")

    settings = _build_deepgram_settings(
        twin_id="11111111-1111-1111-1111-111111111111",
        voice_id="voice-abc",
        backend_url="https://api.personaon.example",
    )

    assert settings["type"] == "Settings"
    assert settings["audio"]["input"] == {"encoding": "linear16", "sample_rate": 16000}
    assert settings["audio"]["output"] == {
        "encoding": "linear16",
        "sample_rate": 24000,
        "container": "none",
    }
    assert settings["agent"]["listen"]["provider"] == {
        "type": "deepgram",
        "model": "flux-general-en",
        "version": "v2",
    }
    think = settings["agent"]["think"]
    assert think["provider"]["type"] == "open_ai"
    assert "twin_id=11111111-1111-1111-1111-111111111111" in think["endpoint"]["url"]
    assert think["endpoint"]["headers"]["X-PersonaOn-Token"] == "llm-secret"
    speak = settings["agent"]["speak"]
    assert speak["provider"]["type"] == "eleven_labs"
    assert speak["provider"]["model_id"] == "eleven_flash_v2_5"
    assert "/voice-abc/multi-stream-input" in speak["endpoint"]["url"]
    assert speak["endpoint"]["headers"]["xi-api-key"] == "eleven-key"


def test_websocket_url_uses_forwarded_https_scheme(monkeypatch):
    from routers.voice_call import _websocket_url_from_request

    monkeypatch.delenv("VOICE_CALL_WS_BASE_URL", raising=False)
    request = _request_with_headers(
        [
            (b"host", b"personaon-api-v2-s4xem3bf3q-uc.a.run.app"),
            (b"x-forwarded-proto", b"https"),
        ]
    )

    url = _websocket_url_from_request(request, "session-123", "token-abc")

    assert url == (
        "wss://personaon-api-v2-s4xem3bf3q-uc.a.run.app"
        "/ws/voice-call/session-123?token=token-abc"
    )


def test_backend_url_uses_forwarded_https_scheme(monkeypatch):
    from routers.voice_call import _backend_url_from_request

    monkeypatch.delenv("BACKEND_API_URL", raising=False)
    monkeypatch.delenv("PUBLIC_BACKEND_URL", raising=False)
    request = _request_with_headers(
        [
            (b"host", b"personaon-api-v2-s4xem3bf3q-uc.a.run.app"),
            (b"x-forwarded-proto", b"https,http"),
        ]
    )

    assert _backend_url_from_request(request) == "https://personaon-api-v2-s4xem3bf3q-uc.a.run.app"


@pytest.mark.asyncio
async def test_visible_voice_chunks_strip_citation_sentinel_across_chunks():
    from routers.voice_call import _iter_visible_voice_chunks

    citations = json.dumps([{"id": "src1", "chunk_preview": "keep private"}])
    chunks = [
        "Here is the spoken answer.",
        "\n[CIT",
        f"ATIONS_JSON:{citations}]",
    ]

    visible = []
    async for chunk in _iter_visible_voice_chunks(_list_to_agen(chunks)):
        visible.append(chunk)

    joined = "".join(visible)
    assert joined == "Here is the spoken answer."
    assert "CITATIONS_JSON" not in joined
    assert "keep private" not in joined


def test_voice_capabilities_require_provider_config(monkeypatch):
    from modules import public_profile_pack
    from modules.public_profile_pack import build_public_profile_pack

    # The pack also reads score/claims/topics from Supabase; those lookups are
    # irrelevant to voice capabilities and otherwise retry against the dummy DB.
    monkeypatch.setattr(public_profile_pack, "_fetch_answerability_score", lambda twin_id: 0.0)
    monkeypatch.setattr(public_profile_pack, "_fetch_verified_claim_count", lambda twin_id: 0)
    monkeypatch.setattr(public_profile_pack, "_fetch_public_topics", lambda twin_id, **_: [])

    twin = {
        "id": "twin-1",
        "name": "Ada",
        "settings": {
            "voice_id": "voice-secret",
            "voice_name": "PersonaOn - Ada",
            "persona_profile": {
                "name": "Ada",
                "headline": "Computer scientist",
                "bio": "Ada builds analytical engines.",
            },
        },
    }

    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    pack = build_public_profile_pack(twin)
    assert pack["has_voice"] is True
    assert pack["voice_capabilities"] == {
        "tts": True,
        "live_call": False,
        "provider": "none",
        "voice_name": "PersonaOn - Ada",
    }

    monkeypatch.setenv("DEEPGRAM_API_KEY", "deepgram-key")
    monkeypatch.setenv("VOICE_CALL_PROVIDER", "deepgram")
    pack = build_public_profile_pack(twin)
    assert pack["voice_capabilities"] == {
        "tts": True,
        "live_call": False,
        "provider": "none",
        "voice_name": "PersonaOn - Ada",
    }

    monkeypatch.setenv("ELEVENLABS_API_KEY", "eleven-key")
    monkeypatch.setenv("VOICE_CALL_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("VOICE_LLM_WEBHOOK_SECRET", "llm-secret")
    pack = build_public_profile_pack(twin)
    assert pack["voice_capabilities"] == {
        "tts": True,
        "live_call": True,
        "provider": "deepgram",
        "voice_name": "PersonaOn - Ada",
    }
