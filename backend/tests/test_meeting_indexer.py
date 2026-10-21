"""Tests for meeting_indexer service — Plan 27-01.

Covers:
  - chunk_transcript_by_turns: chunking logic, edge cases, char limit flush
  - normalize_entity: lowercase + strip
  - extract_entities: structured output, deduplication, short-transcript skip
  - index_meeting_chunks: upsert_text_chunks called per chunk with correct args
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(speaker: str, text: str, start: float = 0.0, end: float = 1.0) -> dict:
    """Build a minimal Recall.ai transcript entry."""
    words = []
    parts = text.split()
    for i, part in enumerate(parts):
        word_start = start + i * 0.1
        word_end = word_start + 0.05
        words.append({
            "text": part,
            "start_timestamp": {"relative": word_start},
            "end_timestamp": {"relative": word_end},
        })
    return {"participant": {"name": speaker}, "words": words}


# ---------------------------------------------------------------------------
# chunk_transcript_by_turns
# ---------------------------------------------------------------------------


def test_chunk_three_entries_single_chunk():
    """3 entries with turns_per_chunk=3 → 1 chunk containing all 3 speakers."""
    from services.meeting_indexer import chunk_transcript_by_turns

    entries = [
        _make_entry("Alice", "Hello everyone", 0.0),
        _make_entry("Bob", "Good morning", 2.0),
        _make_entry("Alice", "Let us start", 4.0),
    ]
    chunks = chunk_transcript_by_turns(entries, turns_per_chunk=3)
    assert len(chunks) == 1
    chunk = chunks[0]
    assert "Alice" in chunk["speakers"]
    assert "Bob" in chunk["speakers"]
    assert chunk["chunk_index"] == 0
    assert "Alice: Hello everyone" in chunk["text"]
    assert "Bob: Good morning" in chunk["text"]


def test_chunk_eight_entries_two_chunks():
    """8 entries with turns_per_chunk=4 → 2 chunks of 4 each."""
    from services.meeting_indexer import chunk_transcript_by_turns

    entries = [_make_entry(f"Speaker{i}", f"Word{i} spoken here", float(i)) for i in range(8)]
    chunks = chunk_transcript_by_turns(entries, turns_per_chunk=4)
    assert len(chunks) == 2
    assert chunks[0]["chunk_index"] == 0
    assert chunks[1]["chunk_index"] == 1


def test_chunk_empty_transcript_returns_empty():
    """Empty transcript returns []."""
    from services.meeting_indexer import chunk_transcript_by_turns

    chunks = chunk_transcript_by_turns([])
    assert chunks == []


def test_chunk_skips_empty_words_entries():
    """Entries with empty words list are skipped."""
    from services.meeting_indexer import chunk_transcript_by_turns

    entries = [
        {"participant": {"name": "Ghost"}, "words": []},
        _make_entry("Alice", "Real text here", 0.0),
        {"participant": {"name": "Ghost2"}, "words": None},
    ]
    chunks = chunk_transcript_by_turns(entries, turns_per_chunk=4)
    assert len(chunks) == 1
    assert "Alice" in chunks[0]["speakers"]
    assert "Ghost" not in chunks[0]["speakers"]


def test_chunk_char_limit_flush():
    """Flush early when accumulated chars exceed max_chunk_chars."""
    from services.meeting_indexer import chunk_transcript_by_turns

    # Each entry is ~30 chars: "Alice: Word Word Word Word" = ~26 chars
    # max_chunk_chars=50 should flush after 2 entries
    entries = [
        _make_entry("Alice", "Word Word Word Word", 0.0),
        _make_entry("Bob", "Word Word Word Word", 1.0),
        _make_entry("Alice", "Word Word Word Word", 2.0),
        _make_entry("Bob", "Word Word Word Word", 3.0),
    ]
    chunks = chunk_transcript_by_turns(entries, turns_per_chunk=10, max_chunk_chars=50)
    assert len(chunks) >= 2  # should have flushed before reaching 10 turns


def test_chunk_dict_keys():
    """Each chunk dict has required keys: text, speakers, start_time, end_time, chunk_index."""
    from services.meeting_indexer import chunk_transcript_by_turns

    entries = [_make_entry("Alice", "Hello there", 5.0, 7.0)]
    chunks = chunk_transcript_by_turns(entries)
    assert len(chunks) == 1
    chunk = chunks[0]
    assert "text" in chunk
    assert "speakers" in chunk
    assert "start_time" in chunk
    assert "end_time" in chunk
    assert "chunk_index" in chunk


def test_chunk_text_format():
    """Chunk text is newline-joined 'Speaker: words' lines."""
    from services.meeting_indexer import chunk_transcript_by_turns

    entries = [
        _make_entry("Alice", "Hello", 0.0),
        _make_entry("Bob", "World", 1.0),
    ]
    chunks = chunk_transcript_by_turns(entries, turns_per_chunk=4)
    assert len(chunks) == 1
    lines = chunks[0]["text"].split("\n")
    assert any(l.startswith("Alice:") for l in lines)
    assert any(l.startswith("Bob:") for l in lines)


# ---------------------------------------------------------------------------
# normalize_entity
# ---------------------------------------------------------------------------


def test_normalize_strips_and_lowercases():
    from services.meeting_indexer import normalize_entity

    assert normalize_entity("  Apple Inc  ") == "apple inc"


def test_normalize_empty_string():
    from services.meeting_indexer import normalize_entity

    assert normalize_entity("") == ""


def test_normalize_already_lowercase():
    from services.meeting_indexer import normalize_entity

    assert normalize_entity("google") == "google"


# ---------------------------------------------------------------------------
# extract_entities
# ---------------------------------------------------------------------------


def test_extract_entities_short_transcript_returns_empty():
    """Transcripts shorter than 500 chars return empty arrays (no Gemini call)."""
    from services.meeting_indexer import extract_entities

    result = asyncio.run(extract_entities("too short"))
    assert result == {"people": [], "companies": [], "topics": []}


def test_extract_entities_schema_keys():
    """extract_entities returns dict with people, companies, topics keys."""
    from services.meeting_indexer import extract_entities

    # Mock Gemini to return a valid response
    mock_response = MagicMock()
    mock_response.text = '{"people": ["Tim Cook"], "companies": ["Apple", "apple"], "topics": ["iphone"]}'

    with patch("services.meeting_indexer._get_genai_client") as mock_client_fn:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_fn.return_value = mock_client

        long_text = "x" * 600
        result = asyncio.run(extract_entities(long_text))

    assert "people" in result
    assert "companies" in result
    assert "topics" in result


def test_extract_entities_deduplicates():
    """Duplicate entity names (different case) are collapsed to single normalized form."""
    from services.meeting_indexer import extract_entities

    mock_response = MagicMock()
    mock_response.text = '{"people": [], "companies": ["Apple", "apple", "APPLE"], "topics": []}'

    with patch("services.meeting_indexer._get_genai_client") as mock_client_fn:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_fn.return_value = mock_client

        long_text = "x" * 600
        result = asyncio.run(extract_entities(long_text))

    assert result["companies"] == ["apple"]


def test_extract_entities_normalizes_values():
    """All returned entity values are lowercased."""
    from services.meeting_indexer import extract_entities

    mock_response = MagicMock()
    mock_response.text = '{"people": ["Tim Cook"], "companies": ["Microsoft"], "topics": ["AI Strategy"]}'

    with patch("services.meeting_indexer._get_genai_client") as mock_client_fn:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_fn.return_value = mock_client

        long_text = "x" * 600
        result = asyncio.run(extract_entities(long_text))

    assert all(v == v.lower() for v in result["people"])
    assert all(v == v.lower() for v in result["companies"])
    assert all(v == v.lower() for v in result["topics"])


def test_extract_entities_fails_open_on_exception():
    """On Gemini exception, returns empty arrays (fail-open)."""
    from services.meeting_indexer import extract_entities

    with patch("services.meeting_indexer._get_genai_client") as mock_client_fn:
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("API error")
        mock_client_fn.return_value = mock_client

        long_text = "x" * 600
        result = asyncio.run(extract_entities(long_text))

    assert result == {"people": [], "companies": [], "topics": []}


# ---------------------------------------------------------------------------
# index_meeting_chunks
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_supabase_for_indexing(request):
    """index_meeting_chunks now upserts a `sources` row via Supabase first; stub it."""
    if not request.node.name.startswith("test_index_meeting_chunks"):
        yield
        return
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={"title": "Test meeting"}
    )
    with patch("services.meeting_indexer.get_supabase_client", return_value=sb):
        yield


def test_index_meeting_chunks_calls_upsert_per_chunk():
    """index_meeting_chunks calls upsert_text_chunks once per chunk."""
    from services.meeting_indexer import index_meeting_chunks

    chunks = [
        {"text": "Alice: Hello", "speakers": ["Alice"], "start_time": 0.0, "end_time": 5.0, "chunk_index": 0},
        {"text": "Bob: World", "speakers": ["Bob"], "start_time": 5.0, "end_time": 10.0, "chunk_index": 1},
    ]

    with patch("services.meeting_indexer.upsert_text_chunks", new_callable=AsyncMock) as mock_upsert:
        mock_upsert.return_value = 1

        result = asyncio.run(
            index_meeting_chunks("mtg-123", "twin-456", chunks)
        )

    assert mock_upsert.call_count == 2
    assert result == 2


def test_index_meeting_chunks_source_key_format():
    """Source key follows 'meeting:{id}:chunk:{i}' format."""
    from services.meeting_indexer import index_meeting_chunks

    chunks = [
        {"text": "Alice: Hello there", "speakers": ["Alice"], "start_time": 0.0, "end_time": 5.0, "chunk_index": 0},
    ]

    with patch("services.meeting_indexer.upsert_text_chunks", new_callable=AsyncMock) as mock_upsert:
        mock_upsert.return_value = 1

        asyncio.run(
            index_meeting_chunks("mtg-xyz", "twin-abc", chunks)
        )

    call_kwargs = mock_upsert.call_args
    source_arg = call_kwargs[1].get("source") or call_kwargs[0][2]
    assert source_arg == "meeting:mtg-xyz:chunk:0"


def test_index_meeting_chunks_metadata_source_type():
    """Metadata contains source_type='meeting'."""
    from services.meeting_indexer import index_meeting_chunks

    chunks = [
        {"text": "Alice: Test", "speakers": ["Alice"], "start_time": 0.0, "end_time": 3.0, "chunk_index": 0},
    ]

    with patch("services.meeting_indexer.upsert_text_chunks", new_callable=AsyncMock) as mock_upsert:
        mock_upsert.return_value = 1

        asyncio.run(
            index_meeting_chunks("meeting-1", "twin-1", chunks)
        )

    call_kwargs = mock_upsert.call_args
    metadata = call_kwargs[1].get("metadata") or call_kwargs[0][3]
    assert metadata["source_type"] == "meeting"
    assert metadata["meeting_id"] == "meeting-1"


def test_index_meeting_chunks_empty_list():
    """Empty chunks list returns 0."""
    from services.meeting_indexer import index_meeting_chunks

    with patch("services.meeting_indexer.upsert_text_chunks", new_callable=AsyncMock) as mock_upsert:
        result = asyncio.run(
            index_meeting_chunks("mtg-1", "twin-1", [])
        )

    assert result == 0
    mock_upsert.assert_not_called()


# ---------------------------------------------------------------------------
# Stubs for later plans (kept so the file structure is consistent)
# ---------------------------------------------------------------------------


def test_worker_handler():
    """Stub for graph_outbox_worker INDEX_MEETING_TRANSCRIPT handler — Plan 27-02."""
    pytest.skip("implement in Plan 27-02")


def test_source_type_weighting():
    """Stub for source_type weighting in search results — Plan 27-03."""
    pytest.skip("implement in Plan 27-03")
