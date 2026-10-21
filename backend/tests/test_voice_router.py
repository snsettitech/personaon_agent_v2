"""Tests for routers/voice.py — models and helper functions.

All external services (Supabase, ElevenLabs) are mocked.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


# ── VoiceStatusResponse model ─────────────────────────────────────

class TestVoiceStatusResponse:
    """Test VoiceStatusResponse Pydantic model."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from routers.voice import VoiceStatusResponse
        self.Model = VoiceStatusResponse

    def test_cloned_voice(self):
        resp = self.Model(cloned=True, voice_id="v-123", voice_name="My Voice")
        assert resp.cloned is True
        assert resp.voice_id == "v-123"
        assert resp.voice_name == "My Voice"

    def test_no_voice(self):
        resp = self.Model(cloned=False)
        assert resp.cloned is False
        assert resp.voice_id is None
        assert resp.voice_name is None

    def test_partial_fields(self):
        resp = self.Model(cloned=True, voice_id="v-1")
        assert resp.voice_name is None


# ── TTSRequest model ──────────────────────────────────────────────

class TestTTSRequest:
    """Test TTSRequest Pydantic model validation."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from routers.voice import TTSRequest
        self.Model = TTSRequest

    def test_valid_text(self):
        req = self.Model(text="Hello world")
        assert req.text == "Hello world"

    def test_empty_text_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self.Model(text="")

    def test_missing_text_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self.Model()

    def test_max_length_enforced(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self.Model(text="x" * 5001)

    def test_at_max_length(self):
        req = self.Model(text="x" * 5000)
        assert len(req.text) == 5000

    def test_min_length_single_char(self):
        req = self.Model(text="a")
        assert req.text == "a"


# ── _get_twin_settings ────────────────────────────────────────────

class TestGetTwinSettings:
    """Test loading twin settings from mocked Supabase."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from routers.voice import _get_twin_settings
        self._get = _get_twin_settings

    def _mock_sb(self, data):
        mock_sb = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = data
        select_query = MagicMock()
        select_query.eq.return_value = select_query
        select_query.single.return_value.execute.return_value = mock_resp
        mock_sb.table.return_value.select.return_value = select_query
        return mock_sb

    @patch("routers.voice.get_supabase_client")
    def test_returns_twin_data(self, mock_get_sb):
        twin_data = {"id": "twin-1", "name": "Alice", "settings": {"voice_id": "v1"}}
        mock_get_sb.return_value = self._mock_sb(twin_data)
        result = self._get("twin-1")
        assert result == twin_data

    @patch("routers.voice.get_supabase_client")
    def test_twin_not_found_raises_404(self, mock_get_sb):
        from fastapi import HTTPException
        mock_get_sb.return_value = self._mock_sb(None)
        with pytest.raises(HTTPException) as exc_info:
            self._get("nonexistent")
        assert exc_info.value.status_code == 404


# ── _get_client ────────────────────────────────────────────────────

class TestGetClient:
    """Test ElevenLabs client creation."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from routers.voice import _get_client
        self._get_client = _get_client

    def test_missing_api_key_raises_503(self, monkeypatch):
        from fastapi import HTTPException
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        with pytest.raises(HTTPException) as exc_info:
            self._get_client()
        assert exc_info.value.status_code == 503
        assert "ELEVENLABS_API_KEY" in exc_info.value.detail

    @patch("routers.voice.os.getenv")
    def test_with_api_key_creates_client(self, mock_getenv):
        mock_getenv.return_value = "test-key-123"
        # Mock the ElevenLabs import inside _get_client
        mock_elevenlabs_module = MagicMock()
        mock_client_instance = MagicMock()
        mock_elevenlabs_module.ElevenLabs.return_value = mock_client_instance

        import sys
        with patch.dict(sys.modules, {"elevenlabs.client": mock_elevenlabs_module}):
            client = self._get_client()
            assert client is mock_client_instance
            mock_elevenlabs_module.ElevenLabs.assert_called_once_with(api_key="test-key-123")

    @patch("routers.voice.os.getenv")
    def test_import_error_raises_503(self, mock_getenv):
        from fastapi import HTTPException
        mock_getenv.return_value = "test-key-123"

        # Simulate elevenlabs not installed
        import sys
        original = sys.modules.get("elevenlabs.client")
        sys.modules["elevenlabs.client"] = None  # force ImportError
        try:
            # We need to reload to clear any cached import
            # Instead, directly test with a patched import that raises
            with patch("builtins.__import__", side_effect=ImportError("no elevenlabs")):
                with pytest.raises(HTTPException) as exc_info:
                    self._get_client()
                assert exc_info.value.status_code == 503
        finally:
            if original is not None:
                sys.modules["elevenlabs.client"] = original
            else:
                sys.modules.pop("elevenlabs.client", None)


# ── _create_elevenlabs_agent ──────────────────────────────────────

class TestCreateElevenLabsAgent:
    """Unit tests for the async _create_elevenlabs_agent helper."""

    @pytest.mark.asyncio
    async def test_returns_agent_id(self):
        """200 response with agent_id in JSON → returns the agent_id string."""
        from routers.voice import _create_elevenlabs_agent

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"agent_id": "agent_abc"}

        with patch("backend.routers.voice.httpx.AsyncClient") as mock_cls:
            from unittest.mock import AsyncMock
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _create_elevenlabs_agent("voice-123", "Alice", "api-key")

        assert result == "agent_abc"

    @pytest.mark.asyncio
    async def test_payload_contains_tts_voice_id(self):
        """Payload sent to ElevenLabs must include tts.voice_id."""
        from routers.voice import _create_elevenlabs_agent

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"agent_id": "agent_xyz"}

        with patch("backend.routers.voice.httpx.AsyncClient") as mock_cls:
            from unittest.mock import AsyncMock
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await _create_elevenlabs_agent("voice-xyz", "Bob", "api-key")

        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json") or call_kwargs[0][1]
        tts_config = payload["conversation_config"]["tts"]
        assert tts_config["voice_id"] == "voice-xyz"

    @pytest.mark.asyncio
    async def test_non_200_returns_none(self):
        """Non-200 response → returns None (non-fatal)."""
        from routers.voice import _create_elevenlabs_agent

        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad request"

        with patch("backend.routers.voice.httpx.AsyncClient") as mock_cls:
            from unittest.mock import AsyncMock
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _create_elevenlabs_agent("voice-123", "Alice", "api-key")

        assert result is None

    @pytest.mark.asyncio
    async def test_exception_returns_none(self):
        """Network exception → returns None (non-fatal)."""
        import httpx
        from routers.voice import _create_elevenlabs_agent

        with patch("backend.routers.voice.httpx.AsyncClient") as mock_cls:
            from unittest.mock import AsyncMock
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("timeout"))
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _create_elevenlabs_agent("voice-123", "Alice", "api-key")

        assert result is None


# ── _delete_elevenlabs_agent ──────────────────────────────────────

class TestDeleteElevenLabsAgent:
    """Unit tests for the async _delete_elevenlabs_agent helper."""

    @pytest.mark.asyncio
    async def test_success_200(self):
        """200 response → completes without error."""
        from routers.voice import _delete_elevenlabs_agent

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("backend.routers.voice.httpx.AsyncClient") as mock_cls:
            from unittest.mock import AsyncMock
            mock_client = AsyncMock()
            mock_client.delete = AsyncMock(return_value=mock_resp)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            # Must not raise
            await _delete_elevenlabs_agent("agent_abc", "api-key")

        mock_client.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_200_logs_warning(self):
        """Non-200 response → logs warning, does not raise."""
        from routers.voice import _delete_elevenlabs_agent

        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with patch("backend.routers.voice.httpx.AsyncClient") as mock_cls:
            from unittest.mock import AsyncMock
            mock_client = AsyncMock()
            mock_client.delete = AsyncMock(return_value=mock_resp)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            # Must not raise even on error status
            await _delete_elevenlabs_agent("agent_abc", "api-key")

        mock_client.delete.assert_called_once()


# ── clone_voice() — agent lifecycle ──────────────────────────────

class TestCloneVoiceAgentLifecycle:
    """Tests for ElevenLabs agent creation in clone_voice()."""

    def _make_audio(self, size: int = 20_000) -> bytes:
        return b"0" * size

    def _setup_mocks(self, twin_data: dict):
        """Return a configured Supabase mock + ElevenLabs client mock."""
        mock_sb = MagicMock()
        resp = MagicMock()
        resp.data = twin_data
        select_query = MagicMock()
        select_query.eq.return_value = select_query
        select_query.single.return_value.execute.return_value = resp
        mock_sb.table.return_value.select.return_value = select_query
        update_query = MagicMock()
        update_query.eq.return_value = update_query
        update_query.execute.return_value = MagicMock()
        mock_sb.table.return_value.update.return_value = update_query

        mock_client = MagicMock()
        new_voice = MagicMock()
        new_voice.voice_id = "new-voice-id"
        mock_client.voices.ivc.create.return_value = new_voice
        mock_client.voices.get_all.return_value = MagicMock(voices=[])

        return mock_sb, mock_client

    def test_writes_agent_id(self):
        """clone_voice() must write elevenlabs_agent_id to settings in the same _update_twin_settings call."""
        from fastapi.testclient import TestClient
        from modules.auth_guard import require_tenant

        FAKE_USER = {"user_id": "u1", "tenant_id": "t1"}

        twin_data = {"id": "twin-1", "name": "Alice", "settings": {}, "tenant_id": "t1"}
        mock_sb, mock_elevenlabs_client = self._setup_mocks(twin_data)

        # Capture settings written to _update_twin_settings
        written_settings = {}

        def fake_update(twin_id, settings, tenant_id=""):
            written_settings.update(settings)

        try:
            with patch.dict("os.environ", {
                    "VOICE_CREATE_ELEVENLABS_AGENT": "true",
                    "JWT_SECRET": "test",
                    "STRIPE_SECRET_KEY": "sk_test",
                    "STRIPE_WEBHOOK_SECRET": "whsec_test",
                 }), \
                 patch("routers.voice.get_supabase_client", return_value=mock_sb), \
                 patch("routers.voice.verify_twin_ownership", return_value=True), \
                 patch("routers.voice._get_client", return_value=mock_elevenlabs_client), \
                 patch("routers.voice._update_twin_settings", side_effect=fake_update), \
                 patch("routers.voice._create_elevenlabs_agent", return_value="agent_new_id") as mock_create_agent, \
                 patch("modules.gcs_storage.upload_file_bytes", side_effect=Exception("gcs skip")):

                from main import app

                app.dependency_overrides[require_tenant] = lambda: FAKE_USER
                client = TestClient(app)
                import io
                audio = io.BytesIO(self._make_audio())
                resp_http = client.post(
                    "/v2/voice/twin-1/clone",
                    files={"audio": ("sample.mp3", audio, "audio/mpeg")},
                )

            assert resp_http.status_code == 200
            mock_create_agent.assert_called_once()
            assert written_settings.get("voice_id") == "new-voice-id"
            assert written_settings.get("elevenlabs_agent_id") == "agent_new_id"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_skips_agent_creation_by_default(self, monkeypatch):
        """Deepgram live calls use raw TTS, so clone must not require a ConvAI agent."""
        from routers.voice import clone_voice

        monkeypatch.delenv("VOICE_CREATE_ELEVENLABS_AGENT", raising=False)
        monkeypatch.setattr("routers.voice.verify_twin_ownership", lambda twin_id, user: None)
        monkeypatch.setattr("routers.voice._get_twin_settings", lambda twin_id, tenant_id="": {
            "id": twin_id,
            "name": "Alice",
            "settings": {},
        })

        new_voice = MagicMock()
        new_voice.voice_id = "new-voice-id"
        fake_client = MagicMock()
        fake_client.voices.ivc.create.return_value = new_voice
        fake_client.voices.get_all.return_value = MagicMock(voices=[])
        monkeypatch.setattr("routers.voice._get_client", lambda: fake_client)

        create_agent = AsyncMock(return_value="agent_new_id")
        monkeypatch.setattr("routers.voice._create_elevenlabs_agent", create_agent)

        written: dict = {}
        monkeypatch.setattr(
            "routers.voice._update_twin_settings",
            lambda twin_id, settings, tenant_id="": written.update(settings),
        )
        monkeypatch.setattr("routers.voice.get_supabase_client", lambda: MagicMock())

        upload = MagicMock()
        upload.content_type = "audio/webm"
        upload.filename = "voice.webm"
        upload.read = AsyncMock(return_value=b"x" * 20_000)

        result = await clone_voice("twin-1", upload, {"tenant_id": "tenant-1"})

        assert result["voice_id"] == "new-voice-id"
        assert written["voice_id"] == "new-voice-id"
        assert "elevenlabs_agent_id" not in written
        create_agent.assert_not_awaited()

    def test_reclone_deletes_old_agent(self):
        """Re-clone must call _delete_elevenlabs_agent with the old agent_id."""
        from fastapi.testclient import TestClient
        from main import app
        from modules.auth_guard import require_tenant

        FAKE_USER = {"user_id": "u1", "tenant_id": "t1"}
        app.dependency_overrides[require_tenant] = lambda: FAKE_USER

        twin_data = {
            "id": "twin-1",
            "name": "Alice",
            "settings": {"voice_id": "old-voice", "elevenlabs_agent_id": "old_agent_id"},
            "tenant_id": "t1",
        }
        mock_sb, mock_elevenlabs_client = self._setup_mocks(twin_data)

        deleted_agent_ids = []

        async def fake_delete_agent(agent_id, api_key):
            deleted_agent_ids.append(agent_id)

        try:
            with patch("routers.voice.get_supabase_client", return_value=mock_sb), \
                 patch("routers.voice.verify_twin_ownership", return_value=True), \
                 patch("routers.voice._get_client", return_value=mock_elevenlabs_client), \
                 patch("routers.voice._delete_elevenlabs_agent", side_effect=fake_delete_agent), \
                 patch("routers.voice._create_elevenlabs_agent", return_value="new_agent_id"), \
                 patch("routers.voice._update_twin_settings"), \
                 patch("modules.gcs_storage.upload_file_bytes", side_effect=Exception("gcs skip")):

                client = TestClient(app)
                import io
                audio = io.BytesIO(self._make_audio())
                resp_http = client.post(
                    "/v2/voice/twin-1/clone",
                    files={"audio": ("sample.mp3", audio, "audio/mpeg")},
                )

            assert resp_http.status_code == 200
            assert "old_agent_id" in deleted_agent_ids, "old agent_id must be deleted before re-clone"
        finally:
            app.dependency_overrides.clear()


# ── delete_voice() — agent cleanup ───────────────────────────────

class TestDeleteVoiceAgentCleanup:
    """Tests for ElevenLabs agent deletion in delete_voice()."""

    def test_deletes_agent(self):
        """delete_voice() must call _delete_elevenlabs_agent with the stored agent_id."""
        from fastapi.testclient import TestClient
        from main import app
        from modules.auth_guard import require_tenant

        FAKE_USER = {"user_id": "u1", "tenant_id": "t1"}
        app.dependency_overrides[require_tenant] = lambda: FAKE_USER

        twin_data = {
            "id": "twin-1",
            "name": "Alice",
            "settings": {"voice_id": "voice-abc", "elevenlabs_agent_id": "agent_xyz"},
            "tenant_id": "t1",
        }

        mock_sb = MagicMock()
        resp = MagicMock()
        resp.data = twin_data
        select_query = MagicMock()
        select_query.eq.return_value = select_query
        select_query.single.return_value.execute.return_value = resp
        mock_sb.table.return_value.select.return_value = select_query
        update_query = MagicMock()
        update_query.eq.return_value = update_query
        update_query.execute.return_value = MagicMock()
        mock_sb.table.return_value.update.return_value = update_query

        deleted_agent_ids = []

        async def fake_delete_agent(agent_id, api_key):
            deleted_agent_ids.append(agent_id)

        mock_elevenlabs_client = MagicMock()

        try:
            with patch("routers.voice.get_supabase_client", return_value=mock_sb), \
                 patch("routers.voice.verify_twin_ownership", return_value=True), \
                 patch("routers.voice._get_client", return_value=mock_elevenlabs_client), \
                 patch("routers.voice._delete_elevenlabs_agent", side_effect=fake_delete_agent):

                client = TestClient(app)
                resp_http = client.delete("/v2/voice/twin-1/clone")

            assert resp_http.status_code == 200
            assert "agent_xyz" in deleted_agent_ids, "_delete_elevenlabs_agent must be called with agent_xyz"
        finally:
            app.dependency_overrides.clear()

    def test_removes_agent_id_from_settings(self):
        """delete_voice() must pop elevenlabs_agent_id from settings."""
        from fastapi.testclient import TestClient
        from main import app
        from modules.auth_guard import require_tenant

        FAKE_USER = {"user_id": "u1", "tenant_id": "t1"}
        app.dependency_overrides[require_tenant] = lambda: FAKE_USER

        twin_data = {
            "id": "twin-1",
            "name": "Alice",
            "settings": {"voice_id": "voice-abc", "elevenlabs_agent_id": "agent_xyz", "other": "keep"},
            "tenant_id": "t1",
        }

        mock_sb = MagicMock()
        resp = MagicMock()
        resp.data = twin_data
        select_query = MagicMock()
        select_query.eq.return_value = select_query
        select_query.single.return_value.execute.return_value = resp
        mock_sb.table.return_value.select.return_value = select_query
        update_query = MagicMock()
        update_query.eq.return_value = update_query
        update_query.execute.return_value = MagicMock()
        mock_sb.table.return_value.update.return_value = update_query

        written_settings = {}

        def fake_update_call(data):
            written_settings.update(data.get("settings", {}))
            return update_query

        mock_sb.table.return_value.update.side_effect = fake_update_call

        mock_elevenlabs_client = MagicMock()

        try:
            with patch("routers.voice.get_supabase_client", return_value=mock_sb), \
                 patch("routers.voice.verify_twin_ownership", return_value=True), \
                 patch("routers.voice._get_client", return_value=mock_elevenlabs_client), \
                 patch("routers.voice._delete_elevenlabs_agent", return_value=None):

                client = TestClient(app)
                resp_http = client.delete("/v2/voice/twin-1/clone")

            assert resp_http.status_code == 200
            assert "elevenlabs_agent_id" not in written_settings
            assert "voice_id" not in written_settings
            assert written_settings.get("other") == "keep"
        finally:
            app.dependency_overrides.clear()
