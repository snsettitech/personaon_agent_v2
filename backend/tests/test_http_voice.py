"""Integration tests for voice HTTP endpoints.

Tests the full HTTP request/response cycle through FastAPI for
voice clone, TTS, status, and delete endpoints with mocked ElevenLabs.
"""

import io
import pytest
from unittest.mock import patch, MagicMock

from elevenlabs.types.add_voice_ivc_response_model import AddVoiceIvcResponseModel
from fastapi.testclient import TestClient

TWIN_ID = "test-twin-voice"
FAKE_USER = {"user_id": "test-user", "tenant_id": "test-tenant"}


def _make_supabase_mock(twin_data=None):
    """Build a mock Supabase client that supports chained .eq() calls."""
    mock_sb = MagicMock()
    resp = MagicMock()
    resp.data = twin_data

    # Support chained .eq().eq()... by making eq() return a queryish mock
    select_query = MagicMock()
    select_query.eq.return_value = select_query  # .eq() returns itself for chaining
    select_query.single.return_value.execute.return_value = resp
    mock_sb.table.return_value.select.return_value = select_query

    update_query = MagicMock()
    update_query.eq.return_value = update_query  # chaining support
    update_query.execute.return_value = MagicMock()
    mock_sb.table.return_value.update.return_value = update_query
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


# ── Voice Status Tests ────────────────────────────────────────────────


class TestVoiceStatus:
    """GET /v2/voice/{id}/status tests."""

    def test_status_with_voice_cloned(self, client):
        twin_data = {
            "id": TWIN_ID,
            "name": "Test",
            "settings": {"voice_id": "v-abc-123", "voice_name": "My Voice"},
        }
        mock_sb = _make_supabase_mock(twin_data)

        with patch("routers.voice.get_supabase_client", return_value=mock_sb), \
             patch("routers.voice.verify_twin_ownership", return_value=True):
            resp = client.get(f"/v2/voice/{TWIN_ID}/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["cloned"] is True
        assert body["voice_id"] == "v-abc-123"
        assert body["voice_name"] == "My Voice"

    def test_status_without_voice(self, client):
        twin_data = {
            "id": TWIN_ID,
            "name": "Test",
            "settings": {},
        }
        mock_sb = _make_supabase_mock(twin_data)

        with patch("routers.voice.get_supabase_client", return_value=mock_sb), \
             patch("routers.voice.verify_twin_ownership", return_value=True):
            resp = client.get(f"/v2/voice/{TWIN_ID}/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["cloned"] is False
        assert body["voice_id"] is None


# ── Clone Tests ───────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _no_gcs_upload(monkeypatch):
    """The clone route also archives the sample to GCS (non-fatal, 5s budget).
    Unmocked, google-api-core keeps retrying the refused upload in a worker
    thread for up to 120s and the TestClient loop shutdown waits on it."""
    monkeypatch.setattr(
        "modules.gcs_storage.upload_file_bytes",
        lambda **kwargs: "gs://test-bucket/" + kwargs["filename"],
    )


class TestVoiceClone:
    """POST /v2/voice/{id}/clone tests."""

    def _make_audio_bytes(self, size: int = 50_000) -> bytes:
        """Create fake audio bytes of given size."""
        return b"\x00" * size

    def test_clone_success(self, client):
        twin_data = {
            "id": TWIN_ID,
            "name": "Test Persona",
            "settings": {},
        }
        mock_sb = _make_supabase_mock(twin_data)

        mock_el_client = MagicMock()
        mock_el_client.voices.ivc.create.return_value = AddVoiceIvcResponseModel(
            voice_id="v-new-123",
            requires_verification=False,
        )

        audio_bytes = self._make_audio_bytes()

        with patch("routers.voice.get_supabase_client", return_value=mock_sb), \
             patch("routers.voice.verify_twin_ownership", return_value=True), \
             patch("routers.voice._get_client", return_value=mock_el_client):

            resp = client.post(
                f"/v2/voice/{TWIN_ID}/clone",
                files={"audio": ("test.mp3", io.BytesIO(audio_bytes), "audio/mpeg")},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "cloned"
        assert body["voice_id"] == "v-new-123"
        assert body["voice_name"] == "PersonaOn - Test Persona"
        mock_el_client.voices.ivc.create.assert_called_once()

    def test_clone_500_keeps_cors_headers(self, app_with_auth):
        from main import asgi_app

        twin_data = {
            "id": TWIN_ID,
            "name": "Test Persona",
            "settings": {},
        }
        mock_sb = _make_supabase_mock(twin_data)
        mock_el_client = MagicMock()
        mock_el_client.voices.ivc.create.return_value = AddVoiceIvcResponseModel(
            voice_id="v-new-123",
            requires_verification=False,
        )

        runtime_client = TestClient(asgi_app, raise_server_exceptions=False)

        with patch("routers.voice.get_supabase_client", return_value=mock_sb), \
             patch("routers.voice.verify_twin_ownership", return_value=True), \
             patch("routers.voice._get_client", return_value=mock_el_client), \
             patch("routers.voice._update_twin_settings", side_effect=RuntimeError("db write failed")):

            resp = runtime_client.post(
                f"/v2/voice/{TWIN_ID}/clone",
                headers={"Origin": "https://personaon.com"},
                files={"audio": ("test.mp3", io.BytesIO(self._make_audio_bytes()), "audio/mpeg")},
            )

        assert resp.status_code == 500
        assert resp.headers["access-control-allow-origin"] == "https://personaon.com"
        assert resp.headers["access-control-allow-credentials"] == "true"

    def test_clone_file_too_small(self, client):
        twin_data = {
            "id": TWIN_ID,
            "name": "Test",
            "settings": {},
        }
        mock_sb = _make_supabase_mock(twin_data)

        with patch("routers.voice.get_supabase_client", return_value=mock_sb), \
             patch("routers.voice.verify_twin_ownership", return_value=True), \
             patch("routers.voice._get_client", return_value=MagicMock()):

            # File too small (< 10KB)
            small_audio = b"\x00" * 100
            resp = client.post(
                f"/v2/voice/{TWIN_ID}/clone",
                files={"audio": ("test.mp3", io.BytesIO(small_audio), "audio/mpeg")},
            )

        assert resp.status_code == 400
        assert "too short" in resp.json()["detail"].lower()

    def test_clone_wrong_file_type(self, client):
        twin_data = {
            "id": TWIN_ID,
            "name": "Test",
            "settings": {},
        }
        mock_sb = _make_supabase_mock(twin_data)

        with patch("routers.voice.get_supabase_client", return_value=mock_sb), \
             patch("routers.voice.verify_twin_ownership", return_value=True), \
             patch("routers.voice._get_client", return_value=MagicMock()):

            audio_bytes = self._make_audio_bytes()
            resp = client.post(
                f"/v2/voice/{TWIN_ID}/clone",
                files={"audio": ("test.txt", io.BytesIO(audio_bytes), "text/plain")},
            )

        assert resp.status_code == 400
        assert "unsupported" in resp.json()["detail"].lower()


# ── TTS Tests ─────────────────────────────────────────────────────────


class TestVoiceTTS:
    """POST /v2/voice/{id}/tts tests."""

    def test_tts_returns_audio(self, client):
        twin_data = {
            "id": TWIN_ID,
            "name": "Test",
            "settings": {"voice_id": "v-abc-123"},
        }
        mock_sb = _make_supabase_mock(twin_data)
        mock_el_client = MagicMock()
        mock_el_client.text_to_speech.convert.return_value = [b"fake-audio-data"]

        with patch("routers.voice.get_supabase_client", return_value=mock_sb), \
             patch("routers.voice.verify_twin_ownership", return_value=True), \
             patch("routers.voice._get_client", return_value=mock_el_client):

            resp = client.post(
                f"/v2/voice/{TWIN_ID}/tts",
                json={"text": "Hello world"},
            )

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/mpeg"
        assert resp.content == b"fake-audio-data"

    def test_tts_no_voice_cloned(self, client):
        twin_data = {
            "id": TWIN_ID,
            "name": "Test",
            "settings": {},  # No voice_id
        }
        mock_sb = _make_supabase_mock(twin_data)

        with patch("routers.voice.get_supabase_client", return_value=mock_sb), \
             patch("routers.voice.verify_twin_ownership", return_value=True):

            resp = client.post(
                f"/v2/voice/{TWIN_ID}/tts",
                json={"text": "Hello world"},
            )

        assert resp.status_code == 400
        assert "no voice" in resp.json()["detail"].lower()


# ── Delete Tests ──────────────────────────────────────────────────────


class TestPublicVoiceTTS:
    """POST /v2/voice/{id}/tts/public tests."""

    def test_public_tts_returns_audio(self, client):
        twin_data = {
            "id": TWIN_ID,
            "name": "Test",
            "settings": {"voice_id": "v-abc-123"},
        }
        mock_sb = _make_supabase_mock(twin_data)
        mock_el_client = MagicMock()
        mock_el_client.text_to_speech.convert.return_value = [b"public-audio-data"]

        with patch("routers.voice.get_supabase_client", return_value=mock_sb), \
             patch("routers.voice._get_client", return_value=mock_el_client):

            resp = client.post(
                f"/v2/voice/{TWIN_ID}/tts/public",
                json={"text": "Hello world"},
            )

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/mpeg"
        assert resp.content == b"public-audio-data"


class TestVoiceDelete:
    """DELETE /v2/voice/{id}/clone tests."""

    def test_delete_voice(self, client):
        twin_data = {
            "id": TWIN_ID,
            "name": "Test",
            "settings": {"voice_id": "v-del-123", "voice_name": "Old Voice"},
        }
        mock_sb = _make_supabase_mock(twin_data)
        mock_el_client = MagicMock()

        with patch("routers.voice.get_supabase_client", return_value=mock_sb), \
             patch("routers.voice.verify_twin_ownership", return_value=True), \
             patch("routers.voice._get_client", return_value=mock_el_client):

            resp = client.delete(f"/v2/voice/{TWIN_ID}/clone")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "deleted"
        assert body["voice_id"] == "v-del-123"
        mock_el_client.voices.delete.assert_called_once_with("v-del-123")
        # Verify settings update was called
        mock_sb.table.return_value.update.assert_called()

    def test_delete_no_voice(self, client):
        twin_data = {
            "id": TWIN_ID,
            "name": "Test",
            "settings": {},
        }
        mock_sb = _make_supabase_mock(twin_data)

        with patch("routers.voice.get_supabase_client", return_value=mock_sb), \
             patch("routers.voice.verify_twin_ownership", return_value=True):

            resp = client.delete(f"/v2/voice/{TWIN_ID}/clone")

        assert resp.status_code == 200
        assert resp.json()["status"] == "no_voice"


# ── Auth Tests ────────────────────────────────────────────────────────


class TestVoiceAuth:
    """Auth enforcement for voice endpoints."""

    def test_status_401_without_auth(self):
        from main import app
        app.dependency_overrides.clear()
        no_auth_client = TestClient(app, raise_server_exceptions=False)
        resp = no_auth_client.get(f"/v2/voice/{TWIN_ID}/status")
        assert resp.status_code == 401

    def test_clone_401_without_auth(self):
        from main import app
        app.dependency_overrides.clear()
        no_auth_client = TestClient(app, raise_server_exceptions=False)
        resp = no_auth_client.post(
            f"/v2/voice/{TWIN_ID}/clone",
            files={"audio": ("test.mp3", io.BytesIO(b"\x00" * 50000), "audio/mpeg")},
        )
        assert resp.status_code == 401
