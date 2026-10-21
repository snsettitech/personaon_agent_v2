"""Tests for meeting_voice_service — Phase 29.

Covers:
- generate_meeting_response: deferral when <2 chunks, normal response, fallback on exception
- stream_tts: no-op when API key missing, audio decode, isFinal terminates loop
- warm_meeting_cache: happy path, twin not found, exception → False
- get_cached_context: hit, miss, TTL expiry
- clear_meeting_cache: removes entry
"""
from __future__ import annotations

import os
import base64
import json
import time
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _list_to_agen(items: list[str]) -> AsyncGenerator[str, None]:
    for item in items:
        yield item


# ---------------------------------------------------------------------------
# generate_meeting_response
# ---------------------------------------------------------------------------


class TestGenerateMeetingResponse:
    """generate_meeting_response — deferral and normal paths."""

    @pytest.mark.asyncio
    async def test_deferral_when_too_few_high_score_chunks(self):
        """Yields deferral template when <2 chunks score above 0.5."""
        from services.meeting_voice_service import DEFERRAL_TEMPLATE, generate_meeting_response

        low_score_chunks = [
            {"text": "some text", "score": 0.3},
        ]

        with patch("services.meeting_voice_service.kb_search", AsyncMock(return_value=low_score_chunks)):
            chunks = []
            async for chunk in generate_meeting_response(
                transcript_text="What is your take on climate change?",
                twin_id="twin-abc",
                user_name="Alice",
                persona_profile={},
            ):
                chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0] == DEFERRAL_TEMPLATE.format(user_name="Alice")

    @pytest.mark.asyncio
    async def test_deferral_zero_chunks(self):
        """Yields deferral when search returns no results."""
        from services.meeting_voice_service import DEFERRAL_TEMPLATE, generate_meeting_response

        with patch("services.meeting_voice_service.kb_search", AsyncMock(return_value=[])):
            chunks = []
            async for chunk in generate_meeting_response(
                transcript_text="Tell me about AI.",
                twin_id="twin-xyz",
                user_name="Bob",
                persona_profile={},
            ):
                chunks.append(chunk)

        assert chunks == [DEFERRAL_TEMPLATE.format(user_name="Bob")]

    @pytest.mark.asyncio
    async def test_normal_response_when_enough_chunks(self):
        """Yields LLM text when >=2 chunks score above 0.5."""
        from services.meeting_voice_service import generate_meeting_response

        high_chunks = [
            {"text": "Alice is an expert in AI", "score": 0.8},
            {"text": "Alice has published 5 papers on ML", "score": 0.75},
        ]

        mock_chunk_1 = MagicMock()
        mock_chunk_1.text = "I have extensive experience in AI research."
        mock_chunk_2 = MagicMock()
        mock_chunk_2.text = " Happy to elaborate."

        mock_response = [mock_chunk_1, mock_chunk_2]

        mock_client = MagicMock()
        mock_client.models.generate_content_stream.return_value = iter(mock_response)

        with (
            patch("services.meeting_voice_service.kb_search", AsyncMock(return_value=high_chunks)),
            patch("services.meeting_voice_service._get_genai_client", return_value=mock_client),
        ):
            chunks = []
            async for chunk in generate_meeting_response(
                transcript_text="What's your AI background?",
                twin_id="twin-abc",
                user_name="Alice",
                persona_profile={"name": "Alice"},
            ):
                chunks.append(chunk)

        assert "".join(chunks) == "I have extensive experience in AI research. Happy to elaborate."

    @pytest.mark.asyncio
    async def test_warm_chunks_merged_and_deduplicated(self):
        """Warm chunks are merged; duplicates (same text) are not included twice."""
        from services.meeting_voice_service import generate_meeting_response

        kb_chunks = [
            {"text": "Unique chunk A", "score": 0.9},
            {"text": "Shared chunk", "score": 0.8},
        ]
        warm_chunks = [
            {"text": "Shared chunk", "score": 0.7},   # duplicate — should be dropped
            {"text": "Unique warm B", "score": 0.6},  # new — should be added
        ]

        captured_chunks: list[dict] = []

        # We patch kb_search and Gemini; capture what system_instruction gets built from
        mock_client = MagicMock()

        def capture_and_return(*args, **kwargs):
            config = kwargs.get("config")
            if config:
                # Track that system prompt was built
                pass
            chunk = MagicMock()
            chunk.text = "ok"
            return iter([chunk])

        mock_client.models.generate_content_stream.side_effect = capture_and_return

        with (
            patch("services.meeting_voice_service.kb_search", AsyncMock(return_value=kb_chunks)),
            patch("services.meeting_voice_service._get_genai_client", return_value=mock_client),
        ):
            async for _ in generate_meeting_response(
                transcript_text="test",
                twin_id="twin-1",
                user_name="Test",
                persona_profile={},
                warm_chunks=warm_chunks,
            ):
                pass

        # Gemini was called (not deferred)
        mock_client.models.generate_content_stream.assert_called_once()
        _, call_kwargs = mock_client.models.generate_content_stream.call_args
        # system_instruction should include all 3 unique texts
        system_instruction = call_kwargs["config"].system_instruction
        assert "Unique chunk A" in system_instruction
        assert "Shared chunk" in system_instruction
        assert "Unique warm B" in system_instruction

    @pytest.mark.asyncio
    async def test_exception_yields_deferral(self):
        """Exception during KB search yields deferral template instead of crashing."""
        from services.meeting_voice_service import DEFERRAL_TEMPLATE, generate_meeting_response

        with patch("services.meeting_voice_service.kb_search", AsyncMock(side_effect=RuntimeError("timeout"))):
            chunks = []
            async for chunk in generate_meeting_response(
                transcript_text="What do you think?",
                twin_id="twin-err",
                user_name="Carol",
                persona_profile={},
            ):
                chunks.append(chunk)

        assert chunks == [DEFERRAL_TEMPLATE.format(user_name="Carol")]

    @pytest.mark.asyncio
    async def test_deferral_template_user_name_substituted(self):
        """DEFERRAL_TEMPLATE {user_name} is correctly substituted."""
        from services.meeting_voice_service import generate_meeting_response

        with patch("services.meeting_voice_service.kb_search", AsyncMock(return_value=[])):
            chunks = []
            async for chunk in generate_meeting_response(
                transcript_text="Q",
                twin_id="t",
                user_name="Dr. Smith",
                persona_profile={},
            ):
                chunks.append(chunk)

        assert "Dr. Smith" in chunks[0]
        assert "{user_name}" not in chunks[0]


# ---------------------------------------------------------------------------
# stream_tts
# ---------------------------------------------------------------------------


class _AsyncWsMock:
    """Async context manager + async iterator mock for websockets.connect."""

    def __init__(self, messages: list[str]):
        self._messages = messages
        self._index = 0
        self.send = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._messages):
            raise StopAsyncIteration
        msg = self._messages[self._index]
        self._index += 1
        return msg


class TestStreamTts:
    """stream_tts — audio yield and error handling."""

    @pytest.mark.asyncio
    async def test_no_op_when_api_key_missing(self):
        """Yields nothing when ELEVENLABS_API_KEY is empty."""
        from services.meeting_voice_service import stream_tts

        # stream_tts falls back to the env var, so clear both sources.
        env = {k: v for k, v in os.environ.items() if k != "ELEVENLABS_API_KEY"}
        with (
            patch("services.meeting_voice_service.ELEVENLABS_API_KEY", ""),
            patch.dict(os.environ, env, clear=True),
            patch("services.meeting_voice_service.websockets.connect") as mock_connect,
        ):
            audio_bytes = []
            async for chunk in stream_tts(_list_to_agen(["hello"]), voice_id="v123"):
                audio_bytes.append(chunk)

        assert audio_bytes == []
        mock_connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_yields_decoded_audio(self):
        """Decodes base64 audio from ElevenLabs WS messages."""
        from services.meeting_voice_service import stream_tts

        raw_audio = b"\x00\x01\x02\x03"
        b64_audio = base64.b64encode(raw_audio).decode("ascii")

        mock_ws = _AsyncWsMock([
            json.dumps({"status": "ready"}),                     # ignored
            json.dumps({"audio": b64_audio}),                    # yields bytes
            json.dumps({"audio": b64_audio, "isFinal": True}),  # yields bytes + terminates
        ])

        with (
            patch("services.meeting_voice_service.ELEVENLABS_API_KEY", "fake-key"),
            patch("services.meeting_voice_service.websockets.connect", return_value=mock_ws),
        ):
            audio_chunks = []
            async for chunk in stream_tts(_list_to_agen(["hello world"]), voice_id="v123"):
                audio_chunks.append(chunk)

        assert raw_audio in audio_chunks
        assert len(audio_chunks) == 2

    @pytest.mark.asyncio
    async def test_skips_non_audio_messages(self):
        """Messages without 'audio' key are silently skipped."""
        from services.meeting_voice_service import stream_tts

        raw_audio = b"\xAB\xCD"
        b64_audio = base64.b64encode(raw_audio).decode("ascii")

        mock_ws = _AsyncWsMock([
            json.dumps({"message": "connected"}),
            json.dumps({}),
            json.dumps({"audio": b64_audio, "isFinal": True}),
        ])

        with (
            patch("services.meeting_voice_service.ELEVENLABS_API_KEY", "fake-key"),
            patch("services.meeting_voice_service.websockets.connect", return_value=mock_ws),
        ):
            audio_chunks = []
            async for chunk in stream_tts(_list_to_agen(["test"]), voice_id="v456"):
                audio_chunks.append(chunk)

        assert audio_chunks == [raw_audio]

    @pytest.mark.asyncio
    async def test_ws_exception_yields_nothing(self):
        """WS connection error is caught; no crash, yields nothing."""
        from services.meeting_voice_service import stream_tts

        with (
            patch("services.meeting_voice_service.ELEVENLABS_API_KEY", "fake-key"),
            patch("services.meeting_voice_service.websockets.connect", side_effect=OSError("refused")),
        ):
            audio_chunks = []
            async for chunk in stream_tts(_list_to_agen(["test"]), voice_id="v789"):
                audio_chunks.append(chunk)

        assert audio_chunks == []


# ---------------------------------------------------------------------------
# warm_meeting_cache / get_cached_context / clear_meeting_cache
# ---------------------------------------------------------------------------


class TestMeetingCache:
    """Cache lifecycle: warm → hit → TTL expiry → clear."""

    def _mock_supabase_twin(self, twin_id: str, name: str, settings: dict):
        mock_sb = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = {"id": twin_id, "name": name, "settings": settings}
        mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_resp
        return mock_sb

    @pytest.mark.asyncio
    async def test_warm_cache_happy_path(self):
        """Warms cache with twin profile, voice_id, and KB chunks."""
        from services import meeting_voice_service as svc

        # Clear any stale state
        svc._meeting_cache.pop("mtg-1", None)

        mock_sb = self._mock_supabase_twin(
            "twin-1",
            "Alice",
            {
                "voice_id": "v-alice",
                "persona_profile": {"name": "Alice", "expertise": ["AI", "ML"]},
            },
        )
        mock_chunks = [{"text": "Alice knows AI", "score": 0.9}]

        with (
            patch("services.meeting_voice_service.get_supabase_client", return_value=mock_sb),
            patch("services.meeting_voice_service.kb_search", AsyncMock(return_value=mock_chunks)),
        ):
            result = await svc.warm_meeting_cache("twin-1", "mtg-1")

        assert result is True
        cached = svc._meeting_cache.get("mtg-1")
        assert cached is not None
        assert cached["voice_id"] == "v-alice"
        assert cached["twin_name"] == "Alice"
        assert cached["warm_chunks"] == mock_chunks
        assert "AI" in cached["expertise_keywords"]

        svc._meeting_cache.pop("mtg-1", None)

    @pytest.mark.asyncio
    async def test_warm_cache_twin_not_found_returns_false(self):
        """Returns False when twin does not exist in DB."""
        from services import meeting_voice_service as svc

        mock_sb = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = None
        mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_resp

        with patch("services.meeting_voice_service.get_supabase_client", return_value=mock_sb):
            result = await svc.warm_meeting_cache("twin-missing", "mtg-2")

        assert result is False
        assert "mtg-2" not in svc._meeting_cache

    @pytest.mark.asyncio
    async def test_warm_cache_db_exception_returns_false(self):
        """Returns False (not raise) when DB throws an exception."""
        from services import meeting_voice_service as svc

        mock_sb = MagicMock()
        mock_sb.table.side_effect = RuntimeError("DB down")

        with patch("services.meeting_voice_service.get_supabase_client", return_value=mock_sb):
            result = await svc.warm_meeting_cache("twin-3", "mtg-3")

        assert result is False

    def test_get_cached_context_hit(self):
        """Returns entry when cache is warm and within TTL."""
        from services import meeting_voice_service as svc

        svc._meeting_cache["mtg-hit"] = {
            "twin_id": "t-1",
            "cached_at": time.time(),
        }

        result = svc.get_cached_context("mtg-hit")
        assert result is not None
        assert result["twin_id"] == "t-1"

        svc._meeting_cache.pop("mtg-hit", None)

    def test_get_cached_context_miss(self):
        """Returns None for unknown meeting_id."""
        from services import meeting_voice_service as svc

        result = svc.get_cached_context("mtg-nonexistent-xyz-123")
        assert result is None

    def test_get_cached_context_expired(self):
        """Returns None and removes entry when TTL has elapsed."""
        from services import meeting_voice_service as svc

        svc._meeting_cache["mtg-expired"] = {
            "twin_id": "t-2",
            "cached_at": time.time() - 9000,  # 2.5 hours ago
        }

        result = svc.get_cached_context("mtg-expired")
        assert result is None
        assert "mtg-expired" not in svc._meeting_cache

    def test_clear_meeting_cache(self):
        """Removes existing cache entry."""
        from services import meeting_voice_service as svc

        svc._meeting_cache["mtg-clear"] = {"twin_id": "t-3", "cached_at": time.time()}
        svc.clear_meeting_cache("mtg-clear")
        assert "mtg-clear" not in svc._meeting_cache

    def test_clear_meeting_cache_nonexistent_is_noop(self):
        """Clearing a missing entry does not raise."""
        from services import meeting_voice_service as svc

        svc.clear_meeting_cache("mtg-does-not-exist-abc")  # must not raise
