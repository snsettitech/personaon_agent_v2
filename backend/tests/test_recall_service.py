"""Tests for Recall.ai API client service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_format_bot_name_basic():
    from services.recall_service import format_bot_name
    assert format_bot_name("John Doe") == "John Doe's AI Assistant"


def test_format_bot_name_truncation():
    from services.recall_service import format_bot_name
    long_name = "A" * 90  # 90 + len("'s AI Assistant") = 105 chars, should truncate to 100
    result = format_bot_name(long_name)
    assert len(result) <= 100


def test_format_bot_name_empty():
    from services.recall_service import format_bot_name
    assert format_bot_name("") == "'s AI Assistant"


@pytest.mark.asyncio
async def test_create_bot_success():
    from services.recall_service import create_bot

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "bot-123", "status": "ready"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("services.recall_service.httpx.AsyncClient", return_value=mock_client):
        result = await create_bot(
            meeting_url="https://meet.google.com/abc-def",
            bot_name="Test Bot",
        )

    assert result["id"] == "bot-123"
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    assert "bot_name" in call_kwargs.kwargs["json"]
    assert call_kwargs.kwargs["json"]["bot_name"] == "Test Bot"


@pytest.mark.asyncio
async def test_create_bot_with_join_at():
    from services.recall_service import create_bot

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "bot-456"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("services.recall_service.httpx.AsyncClient", return_value=mock_client):
        result = await create_bot(
            meeting_url="https://zoom.us/j/123",
            bot_name="Test Bot",
            join_at="2026-04-15T14:00:00Z",
        )

    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["join_at"] == "2026-04-15T14:00:00Z"
    assert result["id"] == "bot-456"


@pytest.mark.asyncio
async def test_create_bot_uses_recallai_streaming_with_diarization():
    """create_bot must use recallai_streaming provider with explicit diarization
    sibling to provider (NOT nested inside the provider config)."""
    from services.recall_service import create_bot

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "bot-789"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("services.recall_service.httpx.AsyncClient", return_value=mock_client):
        await create_bot(meeting_url="https://meet.google.com/abc", bot_name="Twin")

    payload = mock_client.post.call_args.kwargs["json"]
    transcript_cfg = payload["recording_config"]["transcript"]

    # Provider config
    assert "recallai_streaming" in transcript_cfg["provider"], \
        "create_bot must use recallai_streaming (not meeting_captions)"
    assert transcript_cfg["provider"]["recallai_streaming"]["mode"] == "prioritize_accuracy"
    assert transcript_cfg["provider"]["recallai_streaming"]["language_code"] == "auto"
    assert "meeting_captions" not in transcript_cfg["provider"], \
        "meeting_captions must be removed from create_bot payload"

    # Diarization is a SIBLING to provider, not nested inside it
    assert transcript_cfg["diarization"]["use_separate_streams_when_available"] is True
    assert "diarization" not in transcript_cfg["provider"]["recallai_streaming"], \
        "diarization must be sibling to provider, not nested inside"


@pytest.mark.asyncio
async def test_get_bot_transcript():
    from services.recall_service import get_bot_transcript

    mock_transcript = [
        {"speaker": "Alice", "words": [{"text": "Hello"}, {"text": "world"}]},
        {"speaker": "Bob", "words": [{"text": "Hi"}]},
    ]

    # get_bot_transcript makes 2 GETs:
    # 1. GET /bot/{id}/ → returns bot object with recordings[].media_shortcuts.transcript
    # 2. GET download_url → returns transcript list (no auth header, pre-signed S3)
    mock_bot_resp = MagicMock()
    mock_bot_resp.json.return_value = {
        "id": "bot-123",
        "recordings": [{
            "media_shortcuts": {
                "transcript": {
                    "data": {"download_url": "https://s3.example.com/transcript.json"}
                }
            }
        }]
    }
    mock_bot_resp.raise_for_status = MagicMock()

    mock_transcript_resp = MagicMock()
    mock_transcript_resp.json.return_value = mock_transcript
    mock_transcript_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=[mock_bot_resp, mock_transcript_resp])

    with patch("services.recall_service.httpx.AsyncClient", return_value=mock_client):
        result = await get_bot_transcript("bot-123")

    assert len(result) == 2
    assert result[0]["speaker"] == "Alice"
    assert result[1]["speaker"] == "Bob"


# ---------------------------------------------------------------------------
# Phase 29: create_voice_bot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_voice_bot_output_media_payload():
    """create_voice_bot sends output_media.camera.kind='webpage' in payload."""
    from services.recall_service import create_voice_bot

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "bot-voice-1"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("services.recall_service.httpx.AsyncClient", return_value=mock_client):
        result = await create_voice_bot(
            meeting_url="https://meet.google.com/abc-def",
            bot_name="Twin Bot",
            twin_id="twin-123",
            meeting_id="mtg-456",
        )

    assert result["id"] == "bot-voice-1"
    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["output_media"]["camera"]["kind"] == "webpage"
    assert "twin_id=twin-123" in payload["output_media"]["camera"]["config"]["url"]
    assert "meeting_id=mtg-456" in payload["output_media"]["camera"]["config"]["url"]


@pytest.mark.asyncio
async def test_create_voice_bot_deepgram_streaming_config():
    """create_voice_bot includes deepgram_streaming nova-3 in recording_config."""
    from services.recall_service import create_voice_bot

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "bot-voice-2"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("services.recall_service.httpx.AsyncClient", return_value=mock_client):
        await create_voice_bot(
            meeting_url="https://zoom.us/j/111",
            bot_name="Twin Bot",
            twin_id="twin-abc",
            meeting_id="mtg-xyz",
        )

    payload = mock_client.post.call_args.kwargs["json"]
    transcript_provider = (
        payload["recording_config"]["transcript"]["provider"]
    )
    assert "deepgram_streaming" in transcript_provider
    assert transcript_provider["deepgram_streaming"]["model"] == "nova-3"


@pytest.mark.asyncio
async def test_create_voice_bot_web_4_core_variant():
    """create_voice_bot sets web_4_core for all meeting platforms."""
    from services.recall_service import create_voice_bot

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "bot-voice-3"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("services.recall_service.httpx.AsyncClient", return_value=mock_client):
        await create_voice_bot(
            meeting_url="https://teams.microsoft.com/l/meetup/123",
            bot_name="Twin Bot",
            twin_id="twin-t",
            meeting_id="mtg-t",
        )

    payload = mock_client.post.call_args.kwargs["json"]
    variant = payload["variant"]
    assert variant["zoom"] == "web_4_core"
    assert variant["google_meet"] == "web_4_core"
    assert variant["microsoft_teams"] == "web_4_core"


@pytest.mark.asyncio
async def test_create_voice_bot_with_join_at():
    """create_voice_bot passes join_at when provided."""
    from services.recall_service import create_voice_bot

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "bot-voice-4"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("services.recall_service.httpx.AsyncClient", return_value=mock_client):
        await create_voice_bot(
            meeting_url="https://meet.google.com/xyz",
            bot_name="Twin",
            twin_id="twin-j",
            meeting_id="mtg-j",
            join_at="2026-04-17T09:00:00Z",
        )

    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["join_at"] == "2026-04-17T09:00:00Z"


@pytest.mark.asyncio
async def test_create_voice_bot_without_join_at_omits_field():
    """join_at is not included in payload when not provided."""
    from services.recall_service import create_voice_bot

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "bot-voice-5"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("services.recall_service.httpx.AsyncClient", return_value=mock_client):
        await create_voice_bot(
            meeting_url="https://meet.google.com/xyz",
            bot_name="Twin",
            twin_id="twin-nj",
            meeting_id="mtg-nj",
        )

    payload = mock_client.post.call_args.kwargs["json"]
    assert "join_at" not in payload


@pytest.mark.asyncio
async def test_create_gemini_live_bot_output_media_payload():
    from services.recall_service import create_gemini_live_bot

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "bot-gemini-1"}
    mock_response.raise_for_status = MagicMock()
    mock_response.is_success = True

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("services.recall_service.httpx.AsyncClient", return_value=mock_client):
        result = await create_gemini_live_bot(
            meeting_url="https://meet.google.com/abc-def",
            bot_name="Twin Bot",
            twin_id="twin-123",
            meeting_id="mtg-456",
            voice_name="Aoede",
            api_key_token="signed-token",
        )

    assert result["id"] == "bot-gemini-1"
    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["output_media"]["camera"]["kind"] == "webpage"
    url = payload["output_media"]["camera"]["config"]["url"]
    assert "voice-agent-gemini.html" in url
    assert "twin_id=twin-123" in url
    assert "meeting_id=mtg-456" in url
    assert "voice=Aoede" in url
    assert "api_key_token=signed-token" in url


@pytest.mark.asyncio
async def test_create_gemini_live_bot_uses_deepgram_streaming_webhook():
    from services.recall_service import create_gemini_live_bot

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "bot-gemini-2"}
    mock_response.raise_for_status = MagicMock()
    mock_response.is_success = True

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("services.recall_service.httpx.AsyncClient", return_value=mock_client):
        await create_gemini_live_bot(
            meeting_url="https://zoom.us/j/123",
            bot_name="Twin Bot",
            twin_id="twin-abc",
            meeting_id="mtg-xyz",
        )

    payload = mock_client.post.call_args.kwargs["json"]
    recording_config = payload["recording_config"]
    assert "realtime_endpoints" in recording_config
    assert recording_config["realtime_endpoints"] == [
        {
            "type": "webhook",
            "url": "http://localhost:8006/v2/meetings/webhook/transcript",
            "events": ["transcript.data"],
        }
    ]
    transcript_provider = recording_config["transcript"]["provider"]
    assert "deepgram_streaming" in transcript_provider
    assert transcript_provider["deepgram_streaming"]["model"] == "nova-3"
    assert "meeting_captions" not in transcript_provider
    assert recording_config["include_bot_in_recording"]["audio"] is True


@pytest.mark.asyncio
async def test_create_gemini_live_bot_with_join_at():
    from services.recall_service import create_gemini_live_bot

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "bot-gemini-3"}
    mock_response.raise_for_status = MagicMock()
    mock_response.is_success = True

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("services.recall_service.httpx.AsyncClient", return_value=mock_client):
        await create_gemini_live_bot(
            meeting_url="https://meet.google.com/xyz",
            bot_name="Twin",
            twin_id="twin-j",
            meeting_id="mtg-j",
            join_at="2026-04-17T09:00:00Z",
        )

    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["join_at"] == "2026-04-17T09:00:00Z"


# ---------------------------------------------------------------------------
# Phase 29: start_output_media
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_output_media_sends_correct_payload():
    """start_output_media POSTs webpage camera config to /bot/{id}/output_media/."""
    from services.recall_service import start_output_media

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "om-1", "status": "active"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("services.recall_service.httpx.AsyncClient", return_value=mock_client):
        result = await start_output_media("bot-abc", "https://example.com/voice-agent.html")

    assert result["status"] == "active"
    call_url = mock_client.post.call_args.args[0]
    assert "bot-abc/output_media" in call_url
    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["camera"]["kind"] == "webpage"
    assert payload["camera"]["config"]["url"] == "https://example.com/voice-agent.html"


# ---------------------------------------------------------------------------
# Phase 29: stop_output_media
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_output_media_calls_delete():
    """stop_output_media sends DELETE to /bot/{id}/output_media/."""
    from services.recall_service import stop_output_media

    # raise_for_status is called synchronously (not awaited) — must be MagicMock
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    # Implementation uses client.request("DELETE", ...) not client.delete
    mock_client.request = AsyncMock(return_value=mock_response)

    with patch("services.recall_service.httpx.AsyncClient", return_value=mock_client):
        await stop_output_media("bot-xyz")

    mock_client.request.assert_called_once()
    call_args = mock_client.request.call_args
    assert call_args.args[0] == "DELETE"
    assert "bot-xyz/output_media" in call_args.args[1]
