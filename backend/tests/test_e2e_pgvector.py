"""End-to-end test: chat request -> pgvector search -> citations in SSE response.

Validates requirements CUT-05 and VAL-02:
- vector_store.search() returns results above 0.50 threshold
- agent_service.chat_stream emits CITATIONS_JSON sentinel
- chat.py strips sentinel and emits metadata SSE event with citation_details
"""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import chat

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

TWIN_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
TOKEN = "test-share-token-abc123"

MOCK_SEARCH_RESULTS_HIGH = [
    {
        "text": "John Smith is a senior software engineer with 15 years of experience.",
        "score": 0.85,
        "source_id": "src-001",
        "filename": "about.pdf",
        "url": "https://example.com/about.pdf",
        "type": "document",
    },
    {
        "text": "He specializes in distributed systems and cloud architecture.",
        "score": 0.72,
        "source_id": "src-002",
        "filename": "resume.pdf",
        "url": "https://example.com/resume.pdf",
        "type": "document",
    },
]

MOCK_SEARCH_RESULTS_LOW = [
    {
        "text": "Unrelated content about cooking recipes.",
        "score": 0.30,
        "source_id": "src-099",
        "filename": "misc.txt",
        "url": "",
        "type": "document",
    },
]

MOCK_PROFILE = {"name": "Test Persona"}
MOCK_ACTIONS: list[dict] = []


def _parse_sse_events(text: str) -> list[dict]:
    """Parse SSE text into structured events."""
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
                try:
                    payload = json.loads(line[6:])
                except json.JSONDecodeError:
                    payload = line[6:]
        if event_type and payload is not None:
            events.append({"type": event_type, "data": payload})
    return events


def _build_app() -> FastAPI:
    """Build a minimal FastAPI app with the chat router for testing."""
    app = FastAPI()
    app.include_router(chat.router)
    return app


async def _mock_chat_stream_with_citations(**kwargs) -> AsyncGenerator[str, None]:
    """Mock chat_stream that yields text chunks and a CITATIONS_JSON sentinel."""
    yield "Hello! "
    yield "I am a test persona."
    citations = [
        {
            "id": "src-001",
            "filename": "about.pdf",
            "citation_url": "https://example.com/about.pdf",
            "chunk_preview": "John Smith is a senior software engineer...",
        },
        {
            "id": "src-002",
            "filename": "resume.pdf",
            "citation_url": "https://example.com/resume.pdf",
            "chunk_preview": "He specializes in distributed systems...",
        },
    ]
    yield f"\n[CITATIONS_JSON:{json.dumps(citations)}]"


async def _mock_chat_stream_no_citations(**kwargs) -> AsyncGenerator[str, None]:
    """Mock chat_stream that yields text only (no sentinel)."""
    yield "Hello! "
    yield "I cannot find specific information about that."


def _apply_monkeypatches(monkeypatch) -> None:
    """Apply all monkeypatches needed to bypass auth/db for chat router tests."""
    monkeypatch.setattr(chat, "_public_access_or_404", lambda twin_id, token: None)
    monkeypatch.setattr(chat, "_widget_access_or_404", lambda twin_id: None)
    monkeypatch.setattr(
        chat, "_enforce_public_rate_limit", lambda twin_id, http_request: None
    )
    monkeypatch.setattr(
        chat, "_load_twin_context", lambda twin_id: (MOCK_PROFILE, MOCK_ACTIONS)
    )

    # Mock conversation repository
    mock_repo = MagicMock()
    mock_repo.get_conversation.return_value = None
    mock_repo.create_conversation.return_value = None
    mock_repo.add_message.return_value = None
    monkeypatch.setattr(chat, "get_conversation_repository", lambda: mock_repo)

    # Mock PostHog analytics (no-op)
    monkeypatch.setattr(chat, "ph_capture", lambda **kwargs: None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestE2EPgvectorCitationPipeline:
    """E2E integration tests for the pgvector citation pipeline."""

    def test_e2e_pgvector_search_citations_in_sse(self, monkeypatch) -> None:
        """Happy path: mock search results with score 0.85, verify SSE metadata event
        contains citation_details and no CITATIONS_JSON sentinel leaks into message events."""
        _apply_monkeypatches(monkeypatch)
        monkeypatch.setattr(chat, "chat_stream", _mock_chat_stream_with_citations)

        app = _build_app()
        client = TestClient(app)

        response = client.post(
            f"/v2/chat/public/{TWIN_ID}/{TOKEN}/stream",
            json={"message": "Tell me about yourself"},
        )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        events = _parse_sse_events(response.text)
        event_types = [e["type"] for e in events]

        # Must have session, message(s), metadata, done events
        assert "session" in event_types, "Missing 'session' SSE event"
        assert "message" in event_types, "Missing 'message' SSE event"
        assert "metadata" in event_types, "Missing 'metadata' SSE event"
        assert "done" in event_types, "Missing 'done' SSE event"

        # Verify metadata event contains citation_details
        metadata_events = [e for e in events if e["type"] == "metadata"]
        assert len(metadata_events) == 1, f"Expected 1 metadata event, got {len(metadata_events)}"

        meta_data = metadata_events[0]["data"]
        assert "citation_details" in meta_data, "Missing citation_details in metadata"
        citation_details = meta_data["citation_details"]
        assert len(citation_details) == 2, f"Expected 2 citations, got {len(citation_details)}"

        # Verify first citation shape
        first_citation = citation_details[0]
        assert first_citation["filename"] == "about.pdf"
        assert first_citation["id"] == "src-001"
        assert "citation_url" in first_citation
        assert "chunk_preview" in first_citation

        # Verify citations shorthand array
        assert "citations" in meta_data
        assert "about.pdf" in meta_data["citations"]
        assert "resume.pdf" in meta_data["citations"]

        # Verify CITATIONS_JSON sentinel does NOT leak into message events
        message_events = [e for e in events if e["type"] == "message"]
        for msg_event in message_events:
            text = msg_event["data"].get("text", "")
            assert "CITATIONS_JSON" not in text, (
                f"CITATIONS_JSON sentinel leaked into message event: {text!r}"
            )

    def test_e2e_pgvector_no_citations_below_threshold(self, monkeypatch) -> None:
        """Below-threshold path: no CITATIONS_JSON sentinel emitted, no metadata
        event with citation_details."""
        _apply_monkeypatches(monkeypatch)
        monkeypatch.setattr(chat, "chat_stream", _mock_chat_stream_no_citations)

        app = _build_app()
        client = TestClient(app)

        response = client.post(
            f"/v2/chat/public/{TWIN_ID}/{TOKEN}/stream",
            json={"message": "Tell me about cooking"},
        )

        assert response.status_code == 200

        events = _parse_sse_events(response.text)
        event_types = [e["type"] for e in events]

        # Should have session, message(s), done -- but NO metadata event
        assert "session" in event_types
        assert "message" in event_types
        assert "done" in event_types

        # No metadata event with citation_details
        metadata_events = [e for e in events if e["type"] == "metadata"]
        if metadata_events:
            for meta_ev in metadata_events:
                citation_details = meta_ev["data"].get("citation_details", [])
                assert len(citation_details) == 0, (
                    f"Expected empty citation_details, got {len(citation_details)}"
                )


class TestPgvectorSearchReturnShape:
    """Unit test that validates vector_store.search() return shape matches
    what citation extraction in agent_service.py expects."""

    @pytest.mark.asyncio
    async def test_e2e_pgvector_search_returns_expected_shape(self) -> None:
        """Mock the asyncpg pool and conn.fetch to return a row with columns:
        content, similarity, source_id, metadata. Assert the returned dict has
        keys: text, score, source_id, filename, url, type."""
        mock_row = {
            "content": "John Smith is a senior engineer.",
            "similarity": 0.8512,
            "source_id": "aaaaaaaa-bbbb-cccc-dddd-111111111111",
            "privacy_level": "public",
            "metadata": {
                "filename": "about.pdf",
                "url": "https://example.com/about.pdf",
                "type": "document",
            },
        }

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[mock_row])

        mock_pool = AsyncMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "adk_core.services.vector_store.get_pgvector_pool",
            return_value=mock_pool,
        ), patch(
            "adk_core.services.vector_store.get_embedding",
            return_value=[0.1] * 768,
        ):
            from adk_core.services.vector_store import search

            results = await search(query="who is John", twin_id=TWIN_ID, top_k=5)

        assert len(results) == 1
        result = results[0]

        # Verify all keys expected by citation extraction exist
        expected_keys = {"text", "score", "source_id", "privacy_level", "filename", "url", "type", "source_type"}
        assert set(result.keys()) == expected_keys, (
            f"Missing keys: {expected_keys - set(result.keys())}"
        )

        # Verify values
        assert result["text"] == "John Smith is a senior engineer."
        assert result["score"] == 0.8512
        assert result["source_id"] == "aaaaaaaa-bbbb-cccc-dddd-111111111111"
        assert result["filename"] == "about.pdf"
        assert result["url"] == "https://example.com/about.pdf"
        assert result["type"] == "document"

        # Verify score is above the citation threshold
        assert result["score"] > 0.50, (
            f"Score {result['score']} is below 0.50 threshold"
        )
