"""Tests for voice_call.py helpers and edge-case fixes.

Covers:
  - _verify_voice_exists: 200/404/401/403/5xx/network-error behaviour
  - _clear_stale_voice_id: TOCTOU guard, tenant_id scoping, missing twin
  - sentinel regex: greedy strip handles ] inside citations JSON
  - orphan delete in clone_voice: old voice_id deleted before re-clone
"""

import json
import re
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx


# ---------------------------------------------------------------------------
# _verify_voice_exists
# ---------------------------------------------------------------------------

class TestVerifyVoiceExists:
    """Unit tests for the async _verify_voice_exists helper."""

    @pytest.mark.asyncio
    async def test_200_returns_true(self):
        from routers.voice_call import _verify_voice_exists

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("routers.voice_call.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _verify_voice_exists("voice-abc", "api-key-xyz")

        assert result is True

    @pytest.mark.asyncio
    async def test_404_returns_false(self):
        from routers.voice_call import _verify_voice_exists

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("routers.voice_call.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _verify_voice_exists("voice-abc", "api-key-xyz")

        assert result is False

    @pytest.mark.asyncio
    async def test_401_raises_503(self):
        from fastapi import HTTPException
        from routers.voice_call import _verify_voice_exists

        mock_resp = MagicMock()
        mock_resp.status_code = 401

        with patch("routers.voice_call.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(HTTPException) as exc_info:
                await _verify_voice_exists("voice-abc", "bad-key")

        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_403_raises_503(self):
        from fastapi import HTTPException
        from routers.voice_call import _verify_voice_exists

        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch("routers.voice_call.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(HTTPException) as exc_info:
                await _verify_voice_exists("voice-abc", "api-key-xyz")

        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_500_fails_open(self):
        """5xx from ElevenLabs should not block call issuance."""
        from routers.voice_call import _verify_voice_exists

        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with patch("routers.voice_call.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _verify_voice_exists("voice-abc", "api-key-xyz")

        assert result is True

    @pytest.mark.asyncio
    async def test_network_error_fails_open(self):
        """Network failure should not block call issuance."""
        from routers.voice_call import _verify_voice_exists

        with patch("routers.voice_call.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _verify_voice_exists("voice-abc", "api-key-xyz")

        assert result is True


# ---------------------------------------------------------------------------
# _clear_stale_voice_id
# ---------------------------------------------------------------------------

class TestClearStaleVoiceId:
    """Unit tests for the sync _clear_stale_voice_id helper."""

    def _make_supabase_mock(self, settings_data, tenant_id="tenant-1"):
        mock_sb = MagicMock()
        resp = MagicMock()
        resp.data = {"settings": settings_data, "tenant_id": tenant_id}

        select_query = MagicMock()
        select_query.eq.return_value = select_query
        select_query.single.return_value.execute.return_value = resp
        mock_sb.table.return_value.select.return_value = select_query

        update_query = MagicMock()
        update_query.eq.return_value = update_query
        update_query.execute.return_value = MagicMock()
        mock_sb.table.return_value.update.return_value = update_query
        return mock_sb

    def test_clears_matching_stale_voice_id(self):
        from routers.voice_call import _clear_stale_voice_id

        settings = {"voice_id": "old-voice", "voice_name": "Old Voice", "other": "keep"}
        mock_sb = self._make_supabase_mock(settings)

        with patch("routers.voice_call.get_supabase_client", return_value=mock_sb):
            _clear_stale_voice_id("twin-123", "old-voice")

        # Verify UPDATE was called
        mock_sb.table.return_value.update.assert_called_once()
        updated_settings = mock_sb.table.return_value.update.call_args[0][0]["settings"]
        assert "voice_id" not in updated_settings
        assert "voice_name" not in updated_settings
        assert updated_settings.get("other") == "keep"

    def test_toctou_guard_skips_clear_when_voice_id_changed(self):
        """If owner re-cloned between verify and clear, new voice_id must be preserved."""
        from routers.voice_call import _clear_stale_voice_id

        # Settings now has a NEW voice_id (re-clone happened between verify and clear)
        settings = {"voice_id": "new-voice", "voice_name": "New Voice"}
        mock_sb = self._make_supabase_mock(settings)

        with patch("routers.voice_call.get_supabase_client", return_value=mock_sb):
            _clear_stale_voice_id("twin-123", "old-voice")  # stale_voice_id differs

        # UPDATE must NOT be called
        mock_sb.table.return_value.update.assert_not_called()

    def test_scopes_update_with_tenant_id(self):
        """UPDATE must include tenant_id eq() to prevent cross-tenant mutation."""
        from routers.voice_call import _clear_stale_voice_id

        settings = {"voice_id": "stale-voice"}
        mock_sb = self._make_supabase_mock(settings, tenant_id="tenant-abc")

        with patch("routers.voice_call.get_supabase_client", return_value=mock_sb):
            _clear_stale_voice_id("twin-123", "stale-voice")

        update_query = mock_sb.table.return_value.update.return_value
        # eq() should have been called with tenant_id
        eq_calls = [str(c) for c in update_query.eq.call_args_list]
        assert any("tenant-abc" in c for c in eq_calls)

    def test_missing_twin_returns_silently(self):
        """No twin found should not raise."""
        from routers.voice_call import _clear_stale_voice_id

        mock_sb = MagicMock()
        resp = MagicMock()
        resp.data = None
        select_query = MagicMock()
        select_query.eq.return_value = select_query
        select_query.single.return_value.execute.return_value = resp
        mock_sb.table.return_value.select.return_value = select_query

        with patch("routers.voice_call.get_supabase_client", return_value=mock_sb):
            _clear_stale_voice_id("twin-missing", "voice-x")  # must not raise

        mock_sb.table.return_value.update.assert_not_called()

    def test_supabase_error_does_not_raise(self):
        """Supabase failure must be swallowed — self-healing is non-fatal."""
        from routers.voice_call import _clear_stale_voice_id

        mock_sb = MagicMock()
        mock_sb.table.side_effect = Exception("Supabase connection refused")

        with patch("routers.voice_call.get_supabase_client", return_value=mock_sb):
            _clear_stale_voice_id("twin-123", "voice-x")  # must not raise


# ---------------------------------------------------------------------------
# _load_twin_settings
# ---------------------------------------------------------------------------

class TestLoadTwinSettings:
    """Unit tests for the _load_twin_settings helper (single Supabase read)."""

    def _make_sb(self, data):
        mock_sb = MagicMock()
        resp = MagicMock()
        resp.data = data
        select_query = MagicMock()
        select_query.eq.return_value = select_query
        select_query.single.return_value.execute.return_value = resp
        mock_sb.table.return_value.select.return_value = select_query
        return mock_sb

    def test_returns_settings_dict(self):
        """Returns the settings dict from the twin row."""
        from routers.voice_call import _load_twin_settings

        settings = {"voice_id": "v-abc", "elevenlabs_agent_id": "agent_xyz"}
        mock_sb = self._make_sb({"settings": settings})

        with patch("routers.voice_call.get_supabase_client", return_value=mock_sb):
            result = _load_twin_settings("twin-1")

        assert result == settings

    def test_returns_empty_dict_when_not_found(self):
        """Returns empty dict when twin row has no data."""
        from routers.voice_call import _load_twin_settings

        mock_sb = self._make_sb(None)

        with patch("routers.voice_call.get_supabase_client", return_value=mock_sb):
            result = _load_twin_settings("twin-missing")

        assert result == {}

    def test_returns_empty_dict_on_supabase_exception(self):
        """Returns empty dict when Supabase raises (network error etc.)."""
        from routers.voice_call import _load_twin_settings

        mock_sb = MagicMock()
        mock_sb.table.side_effect = Exception("connection refused")

        with patch("routers.voice_call.get_supabase_client", return_value=mock_sb):
            result = _load_twin_settings("twin-1")

        assert result == {}


# ---------------------------------------------------------------------------
# _get_twin_agent_id
# ---------------------------------------------------------------------------

class TestGetTwinAgentId:
    """Unit tests for _get_twin_agent_id — per-persona agent lookup with fallback."""

    def test_returns_settings_agent_id(self):
        """When settings has elevenlabs_agent_id, return it."""
        from routers.voice_call import _get_twin_agent_id

        settings = {"elevenlabs_agent_id": "agent_xyz", "voice_id": "v-abc"}
        result = _get_twin_agent_id("twin-1", settings=settings)
        assert result == "agent_xyz"

    def test_fallback_to_env(self, monkeypatch):
        """When settings has no elevenlabs_agent_id, fall back to env var."""
        from routers.voice_call import _get_twin_agent_id

        monkeypatch.setenv("ELEVENLABS_AGENT_ID", "shared_agent_id")
        settings = {"voice_id": "v-abc"}  # no elevenlabs_agent_id
        result = _get_twin_agent_id("twin-1", settings=settings)
        assert result == "shared_agent_id"

    def test_raises_503_when_unconfigured(self, monkeypatch):
        """When neither settings agent_id nor env var is set, raise 503."""
        from fastapi import HTTPException
        from routers.voice_call import _get_twin_agent_id

        monkeypatch.delenv("ELEVENLABS_AGENT_ID", raising=False)
        settings = {"voice_id": "v-abc"}  # no elevenlabs_agent_id

        with pytest.raises(HTTPException) as exc_info:
            _get_twin_agent_id("twin-1", settings=settings)

        assert exc_info.value.status_code == 503

    def test_calls_load_twin_settings_when_settings_none(self, monkeypatch):
        """When settings=None, calls _load_twin_settings to fetch them."""
        from routers.voice_call import _get_twin_agent_id

        monkeypatch.setenv("ELEVENLABS_AGENT_ID", "shared_fallback")

        with patch("routers.voice_call._load_twin_settings", return_value={}) as mock_load:
            result = _get_twin_agent_id("twin-1", settings=None)

        mock_load.assert_called_once_with("twin-1")
        assert result == "shared_fallback"


# ---------------------------------------------------------------------------
# Sentinel regex
# ---------------------------------------------------------------------------

class TestSentinelRegex:
    """Verify the greedy sentinel strip handles ] characters inside citations JSON."""

    PATTERN = re.compile(r'\n?\[CITATIONS_JSON:.+\]$', re.DOTALL)

    def _strip(self, text: str) -> str:
        return self.PATTERN.sub('', text).rstrip()

    def test_strips_simple_sentinel(self):
        citations = json.dumps([{"id": "src1", "filename": "bio.txt"}])
        text = f"Here is my answer.\n[CITATIONS_JSON:{citations}]"
        assert self._strip(text) == "Here is my answer."

    def test_strips_sentinel_with_bracket_in_json_value(self):
        """JSON values containing ] must not cause premature match termination."""
        citations = json.dumps([{"id": "src1", "chunk_preview": "He said [hello] there."}])
        text = f"Answer text.\n[CITATIONS_JSON:{citations}]"
        result = self._strip(text)
        assert result == "Answer text."
        assert "[CITATIONS_JSON" not in result
        assert "[hello]" not in result  # whole sentinel gone, not partially stripped

    def test_strips_sentinel_with_nested_array_in_json(self):
        citations = json.dumps([{"id": "s1", "tags": ["a", "b]c", "d"]}])
        text = f"Some text.\n[CITATIONS_JSON:{citations}]"
        result = self._strip(text)
        assert result == "Some text."

    def test_no_sentinel_leaves_text_unchanged(self):
        text = "Just a plain response with no citations."
        assert self._strip(text) == text

    def test_strips_sentinel_spanning_newlines(self):
        citations = json.dumps([{"id": "s1"}])
        text = f"Line one.\nLine two.\n[CITATIONS_JSON:{citations}]"
        result = self._strip(text)
        assert result == "Line one.\nLine two."


# ---------------------------------------------------------------------------
# Orphan delete in clone_voice
# ---------------------------------------------------------------------------

class TestOrphanDeleteOnReclone:
    """voice.py: old voice_id must be deleted from ElevenLabs before re-cloning."""

    def _make_audio(self, size: int = 20_000) -> bytes:
        return b"0" * size

    def test_deletes_old_voice_before_cloning(self):
        """When voice_id already exists in settings, it must be deleted first."""
        from fastapi.testclient import TestClient
        from main import app
        from modules.auth_guard import require_tenant

        FAKE_USER = {"user_id": "u1", "tenant_id": "t1"}
        app.dependency_overrides[require_tenant] = lambda: FAKE_USER

        twin_data = {
            "id": "twin-1",
            "name": "Alice",
            "settings": {"voice_id": "old-voice-id", "voice_name": "Old"},
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

        mock_client = MagicMock()
        new_voice = MagicMock()
        new_voice.voice_id = "new-voice-id"
        mock_client.voices.ivc.create.return_value = new_voice
        mock_client.voices.get_all.return_value = MagicMock(voices=[])

        deleted_ids = []
        def fake_delete(vid):
            deleted_ids.append(vid)
        mock_client.voices.delete.side_effect = fake_delete

        try:
            with patch("routers.voice.get_supabase_client", return_value=mock_sb), \
                 patch("routers.voice.verify_twin_ownership", return_value=True), \
                 patch("routers.voice._get_client", return_value=mock_client), \
                 patch("modules.gcs_storage.upload_file_bytes", side_effect=Exception("gcs skip")):

                client = TestClient(app)
                import io
                audio = io.BytesIO(self._make_audio())
                resp_http = client.post(
                    "/v2/voice/twin-1/clone",
                    files={"audio": ("sample.mp3", audio, "audio/mpeg")},
                )

            assert resp_http.status_code == 200
            assert "old-voice-id" in deleted_ids, "old voice_id was not deleted before re-clone"
        finally:
            app.dependency_overrides.clear()

    def test_first_time_clone_skips_delete(self):
        """No existing voice_id means no delete call — must not crash."""
        from fastapi.testclient import TestClient
        from main import app
        from modules.auth_guard import require_tenant

        FAKE_USER = {"user_id": "u1", "tenant_id": "t1"}
        app.dependency_overrides[require_tenant] = lambda: FAKE_USER

        twin_data = {
            "id": "twin-2",
            "name": "Bob",
            "settings": {},  # no voice_id
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

        mock_client = MagicMock()
        new_voice = MagicMock()
        new_voice.voice_id = "brand-new-voice"
        mock_client.voices.ivc.create.return_value = new_voice
        mock_client.voices.get_all.return_value = MagicMock(voices=[])

        try:
            with patch("routers.voice.get_supabase_client", return_value=mock_sb), \
                 patch("routers.voice.verify_twin_ownership", return_value=True), \
                 patch("routers.voice._get_client", return_value=mock_client), \
                 patch("modules.gcs_storage.upload_file_bytes", side_effect=Exception("gcs skip")):

                client = TestClient(app)
                import io
                audio = io.BytesIO(self._make_audio())
                resp_http = client.post(
                    "/v2/voice/twin-2/clone",
                    files={"audio": ("sample.mp3", audio, "audio/mpeg")},
                )

            assert resp_http.status_code == 200
            mock_client.voices.delete.assert_not_called()
        finally:
            app.dependency_overrides.clear()
