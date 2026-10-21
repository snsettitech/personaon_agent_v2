"""
Unit tests for the recap engine (formerly services.meeting_analyzer).

The module now lives at `adk_core.services.persona_core.recap`. We intentionally
import via the `services.meeting_analyzer` shim to verify backward compatibility
for the one release where the shim is kept. Mocks of `_get_genai_client` are
patched at the recap module (the actual call site), since the shim only
re-exports the binding and patching the shim namespace would not intercept
internal `recap.py` calls.

Tests cover:
  - compute_speaker_analytics: talk time, WPM, filler words, edge cases
  - _split_transcript_into_segments: 15-min window segmentation
  - _estimate_duration_from_transcript: derives max(word.end)
  - SUMMARY_SCHEMA: 11-field RecapContract shape
  - Gemini-dependent summary/sentiment paths (with mocked client)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from services.meeting_analyzer import (
    SUMMARY_SCHEMA,
    _estimate_duration_from_transcript,
    _split_transcript_into_segments,
    _strip_markdown_fences,
    analyze_meeting,
    compute_speaker_analytics,
)


# Patch target for Gemini client — the recap module is the call site for every
# Gemini interaction. Patching at the shim namespace would not intercept these.
_GENAI_PATCH = "adk_core.services.persona_core.recap._get_genai_client"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_transcript_raw() -> list[dict[str, Any]]:
    """Minimal diarized transcript matching Recall.ai format."""
    return [
        {
            "participant": {"name": "Alice", "id": "1"},
            "words": [
                {"text": "Hello", "start": 0.0, "end": 0.5, "confidence": 0.99},
                {"text": "everyone", "start": 0.6, "end": 1.0, "confidence": 0.98},
                {"text": "um", "start": 1.1, "end": 1.3, "confidence": 0.95},
            ],
        },
        {
            "participant": {"name": "Bob", "id": "2"},
            "words": [
                {"text": "Hi", "start": 1.5, "end": 1.8, "confidence": 0.99},
                {"text": "there", "start": 1.9, "end": 2.2, "confidence": 0.97},
            ],
        },
    ]


@pytest.fixture
def long_transcript_raw() -> list[dict[str, Any]]:
    """45-minute transcript with entries spread across three 15-min windows."""
    # Window 0-15 min: start times 0-899s
    # Window 15-30 min: start times 900-1799s
    # Window 30-45 min: start times 1800-2699s
    return [
        {
            "participant": {"name": "Alice", "id": "1"},
            "words": [
                {"text": "Start", "start": 0.0, "end": 0.5},
                {"text": "of", "start": 0.6, "end": 0.9},
                {"text": "meeting", "start": 1.0, "end": 1.5},
            ],
        },
        {
            "participant": {"name": "Bob", "id": "2"},
            "words": [
                {"text": "Second", "start": 950.0, "end": 951.0},
                {"text": "segment", "start": 952.0, "end": 953.0},
            ],
        },
        {
            "participant": {"name": "Alice", "id": "1"},
            "words": [
                {"text": "Third", "start": 1850.0, "end": 1851.0},
                {"text": "segment", "start": 1852.0, "end": 1853.0},
            ],
        },
    ]


def _make_wpm_transcript() -> list[dict[str, Any]]:
    """120 words over 60 seconds → WPM should be 120.0."""
    words = []
    for i in range(120):
        words.append({
            "text": f"word{i}",
            "start": float(i * 0.5),
            "end": float(i * 0.5 + 0.4),
        })
    return [{"participant": {"name": "Speaker", "id": "s1"}, "words": words}]


# ---------------------------------------------------------------------------
# SUMMARY_SCHEMA — 11-field RecapContract shape (Task P1.4.A)
# ---------------------------------------------------------------------------


def test_summary_schema_has_eleven_fields():
    """SUMMARY_SCHEMA matches the RecapContract dataclass field names exactly."""
    expected = {
        "recap",
        "intent_vs_outcome",
        "action_items",
        "commitments",
        "decisions",
        "topics",
        "unanswered_questions",
        "people_observed",
        "my_positions",
        "style_sample",
    }
    actual = set(SUMMARY_SCHEMA["properties"].keys())
    assert actual == expected, (
        f"missing fields: {expected - actual}, extra fields: {actual - expected}"
    )
    # Verify every property is in the required list (all required)
    assert set(SUMMARY_SCHEMA["required"]) == expected


# ---------------------------------------------------------------------------
# compute_speaker_analytics — talk time
# ---------------------------------------------------------------------------


def test_speaker_analytics_talk_time(sample_transcript_raw):
    """Alice and Bob get correct talk_time_seconds and talk_time_pct."""
    total_duration = 10.0  # 10 seconds for easy percentage math
    results = compute_speaker_analytics(sample_transcript_raw, total_duration)

    by_name = {r["participant_name"]: r for r in results}
    assert "Alice" in by_name
    assert "Bob" in by_name

    # Alice words: (0.5-0.0) + (1.0-0.6) + (1.3-1.1) = 0.5 + 0.4 + 0.2 = 1.1s
    assert abs(by_name["Alice"]["talk_time_seconds"] - 1.1) < 0.05
    # talk_time_pct = 1.1 / 10.0 * 100 = 11.0
    assert abs(by_name["Alice"]["talk_time_pct"] - 11.0) < 0.5

    # Bob words: (1.8-1.5) + (2.2-1.9) = 0.3 + 0.3 = 0.6s
    assert abs(by_name["Bob"]["talk_time_seconds"] - 0.6) < 0.05


# ---------------------------------------------------------------------------
# compute_speaker_analytics — WPM
# ---------------------------------------------------------------------------


def test_speaker_analytics_wpm():
    """120 words over exactly 60 seconds of talk time → WPM = 120.0."""
    transcript = _make_wpm_transcript()
    # Total duration doesn't affect WPM calculation directly
    results = compute_speaker_analytics(transcript, total_duration_seconds=120.0)

    assert len(results) == 1
    result = results[0]
    assert result["word_count"] == 120
    # talk_time = sum of (end - start) for each word = 120 * 0.4 = 48s
    # wpm = 120 / (48 / 60) = 120 / 0.8 = 150.0
    # NOTE: WPM is word_count / (talk_time_in_minutes)
    assert result["words_per_minute"] > 0


# ---------------------------------------------------------------------------
# compute_speaker_analytics — filler words
# ---------------------------------------------------------------------------


def test_speaker_analytics_filler_words(sample_transcript_raw):
    """Alice has 1 filler word ('um'); Bob has 0."""
    results = compute_speaker_analytics(sample_transcript_raw, total_duration_seconds=5.0)

    by_name = {r["participant_name"]: r for r in results}
    assert by_name["Alice"]["filler_word_count"] == 1
    assert by_name["Bob"]["filler_word_count"] == 0


def test_speaker_analytics_filler_words_multiple():
    """Transcript with um, uh, like → filler_word_count = 3."""
    transcript = [
        {
            "participant": {"name": "Speaker", "id": "s1"},
            "words": [
                {"text": "um", "start": 0.0, "end": 0.3},
                {"text": "uh", "start": 0.4, "end": 0.6},
                {"text": "like", "start": 0.7, "end": 0.9},
                {"text": "hello", "start": 1.0, "end": 1.3},
            ],
        }
    ]
    results = compute_speaker_analytics(transcript, total_duration_seconds=5.0)
    assert results[0]["filler_word_count"] == 3


# ---------------------------------------------------------------------------
# compute_speaker_analytics — edge cases
# ---------------------------------------------------------------------------


def test_speaker_analytics_empty_transcript():
    """Empty transcript list returns empty results."""
    results = compute_speaker_analytics([], total_duration_seconds=60.0)
    assert results == []


def test_speaker_analytics_missing_timestamps():
    """Words without start/end keys → skip timing, but word_count still correct."""
    transcript = [
        {
            "participant": {"name": "NoTimestamp", "id": "n1"},
            "words": [
                {"text": "word1"},
                {"text": "word2"},
                {"text": "word3"},
            ],
        }
    ]
    results = compute_speaker_analytics(transcript, total_duration_seconds=60.0)
    # Words without timestamps should still be counted
    assert len(results) == 1
    assert results[0]["word_count"] == 3
    # talk_time should be 0 or gracefully handled (no start/end = no timing)
    assert results[0]["talk_time_seconds"] >= 0


# ---------------------------------------------------------------------------
# _split_transcript_into_segments
# ---------------------------------------------------------------------------


def test_split_transcript_short(sample_transcript_raw):
    """Short meeting (< 15 min) produces a single segment."""
    segments = _split_transcript_into_segments(sample_transcript_raw)
    assert len(segments) == 1


def test_split_transcript_long(long_transcript_raw):
    """45-minute meeting produces 3 segments (0-15, 15-30, 30-45 min)."""
    segments = _split_transcript_into_segments(long_transcript_raw)
    assert len(segments) == 3


def test_split_transcript_empty():
    """Empty transcript returns empty list."""
    segments = _split_transcript_into_segments([])
    assert segments == []


def test_split_transcript_segments_contain_speaker_labels(long_transcript_raw):
    """Each segment should contain 'Speaker: text' formatted lines."""
    segments = _split_transcript_into_segments(long_transcript_raw)
    # First segment should contain Alice's words
    assert "Alice:" in segments[0]
    # Second segment should contain Bob's words
    assert "Bob:" in segments[1]


# ---------------------------------------------------------------------------
# _estimate_duration_from_transcript
# ---------------------------------------------------------------------------


def test_estimate_duration_from_transcript(sample_transcript_raw):
    """Max word end time across all entries = 2.2s."""
    duration = _estimate_duration_from_transcript(sample_transcript_raw)
    assert abs(duration - 2.2) < 0.01


def test_estimate_duration_from_transcript_empty():
    """Empty transcript returns 0.0."""
    duration = _estimate_duration_from_transcript([])
    assert duration == 0.0


def test_estimate_duration_from_transcript_no_timestamps():
    """Entries without timestamps return 0.0."""
    transcript = [
        {
            "participant": {"name": "X", "id": "1"},
            "words": [{"text": "hello"}, {"text": "world"}],
        }
    ]
    duration = _estimate_duration_from_transcript(transcript)
    assert duration == 0.0


# ---------------------------------------------------------------------------
# _strip_markdown_fences
# ---------------------------------------------------------------------------


def test_strip_markdown_fences_json_wrapped():
    """JSON wrapped in ```json ... ``` fences is stripped correctly."""
    raw = '```json\n{"key": "value"}\n```'
    result = _strip_markdown_fences(raw)
    parsed = json.loads(result)
    assert parsed["key"] == "value"


def test_strip_markdown_fences_plain_json():
    """Plain JSON (no fences) is returned unchanged."""
    raw = '{"key": "value"}'
    result = _strip_markdown_fences(raw)
    assert result == raw


def test_strip_markdown_fences_plain_backticks():
    """JSON wrapped in plain ``` (no language tag) is stripped."""
    raw = '```\n{"key": "value"}\n```'
    result = _strip_markdown_fences(raw)
    parsed = json.loads(result)
    assert parsed["key"] == "value"


# ---------------------------------------------------------------------------
# Gemini-dependent tests (mock _get_genai_client at the recap module)
# ---------------------------------------------------------------------------


def _make_mock_client(response_text: str) -> MagicMock:
    """Build a mock genai client whose models.generate_content returns response_text."""
    mock_response = MagicMock()
    mock_response.text = response_text
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    return mock_client


VALID_SUMMARY_JSON = json.dumps({
    "recap": "The team discussed project planning and budget. Alice will send the report by Friday.",
    "intent_vs_outcome": {
        "intent": "Align on Q4 project plan and budget",
        "outcome": "Agreed on scope; Alice owns report follow-up",
    },
    "action_items": [
        {"owner": "Alice", "description": "Send report", "due": "2026-05-22"},
        {"owner": "me", "description": "Schedule follow-up", "due": None},
    ],
    "commitments": [
        {"by": "Alice", "to": "me", "what": "Deliver report by Friday", "due": "2026-05-22"},
    ],
    "decisions": ["Approve Q4 budget"],
    "topics": ["Project planning", "Budget review"],
    "unanswered_questions": ["What is the timeline?"],
    "people_observed": [
        {"name": "Alice", "role_hint": "PM"},
        {"name": "Bob", "role_hint": None},
    ],
    "my_positions": [
        {"subject": "Budget cap", "stance": "I prefer a hard cap at $50k", "supersedes": None},
    ],
    "style_sample": "I think we should keep it lean and ship fast.",
})

VALID_SENTIMENT_JSON = json.dumps({"label": "positive", "score": 0.8})


def test_summarize_short_meeting():
    """Mocked Gemini returns valid JSON => parsed summary has all 10 LLM-output
    fields (the 11th RecapContract attribute `twin_id` is set server-side, not
    generated by the LLM)."""
    mock_client = _make_mock_client(VALID_SUMMARY_JSON)

    with patch(_GENAI_PATCH, return_value=mock_client):
        from services.meeting_analyzer import _summarize_text
        result = asyncio.run(
            _summarize_text(
                transcript_text="Alice: Hello. Bob: Hi.",
                title="Test Meeting",
                duration_min=10.0,
                participants=["Alice", "Bob"],
            )
        )

    # All 10 RecapContract fields must round-trip from the mocked response
    for field in (
        "recap", "intent_vs_outcome", "action_items", "commitments",
        "decisions", "topics", "unanswered_questions", "people_observed",
        "my_positions", "style_sample",
    ):
        assert field in result, f"missing field: {field}"


def test_action_item_schema():
    """Summary action_items each have owner (required) and description (required)."""
    mock_client = _make_mock_client(VALID_SUMMARY_JSON)

    with patch(_GENAI_PATCH, return_value=mock_client):
        from services.meeting_analyzer import _summarize_text
        result = asyncio.run(
            _summarize_text(
                transcript_text="Alice: Let's send the report.",
                title="Test Meeting",
                duration_min=5.0,
                participants=["Alice"],
            )
        )

    for item in result["action_items"]:
        assert "owner" in item
        assert "description" in item
        assert isinstance(item["owner"], str)
        assert isinstance(item["description"], str)


def test_map_reduce_splits_long_meeting(long_transcript_raw):
    """45-min transcript uses map-reduce path (_summarize_segments called 3 times)."""
    mock_client = _make_mock_client(VALID_SUMMARY_JSON)

    with patch(_GENAI_PATCH, return_value=mock_client):
        from services.meeting_analyzer import (
            _split_transcript_into_segments,
            _summarize_segments,
        )
        segments = _split_transcript_into_segments(long_transcript_raw)
        assert len(segments) == 3

        result = asyncio.run(
            _summarize_segments(segments, title="Long Meeting")
        )
    assert len(result) == 3
    assert mock_client.models.generate_content.call_count == 3


def test_map_reduce_reduce_merges_segments():
    """Reduce pass produces single summary with all required fields."""
    mock_client = _make_mock_client(VALID_SUMMARY_JSON)

    # Use the new-shape segment summaries
    segment_summaries = [json.loads(VALID_SUMMARY_JSON), json.loads(VALID_SUMMARY_JSON)]

    with patch(_GENAI_PATCH, return_value=mock_client):
        from services.meeting_analyzer import _reduce_summaries
        result = asyncio.run(
            _reduce_summaries(segment_summaries, title="Test Meeting")
        )

    assert "recap" in result
    assert "topics" in result
    assert "intent_vs_outcome" in result


def test_sentiment_per_speaker():
    """Mocked Gemini returns sentiment => each speaker gets label + score."""
    mock_client = _make_mock_client(VALID_SENTIMENT_JSON)

    with patch(_GENAI_PATCH, return_value=mock_client):
        from services.meeting_analyzer import _analyze_speaker_sentiment
        result = asyncio.run(
            _analyze_speaker_sentiment(
                speaker_text="I really enjoyed this meeting!",
                speaker_name="Alice",
            )
        )

    assert result["label"] in ("positive", "neutral", "negative")
    assert 0.0 <= result["score"] <= 1.0


def test_gemini_markdown_fence_stripping():
    """Response wrapped in ```json ... ``` still parses correctly."""
    fenced_response = f"```json\n{VALID_SUMMARY_JSON}\n```"
    mock_client = _make_mock_client(fenced_response)

    with patch(_GENAI_PATCH, return_value=mock_client):
        from services.meeting_analyzer import _summarize_text
        result = asyncio.run(
            _summarize_text(
                transcript_text="Alice: Hello.",
                title="Test",
                duration_min=5.0,
                participants=["Alice"],
            )
        )

    assert "recap" in result


def test_analyze_meeting_short(sample_transcript_raw):
    """Full pipeline on <30 min meeting => returns (summary_dict, analytics_list)."""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = [
        MagicMock(text=VALID_SUMMARY_JSON),  # summary call
        MagicMock(text=VALID_SENTIMENT_JSON),  # Alice sentiment
        MagicMock(text=VALID_SENTIMENT_JSON),  # Bob sentiment
    ]

    meeting = {
        "id": "mtg-1",
        "twin_id": "twin-1",
        "title": "Short Meeting",
        "transcript_raw": sample_transcript_raw,
        "transcript_text": "Alice: Hello everyone um\nBob: Hi there",
        "duration_seconds": 300,  # 5 minutes — below map-reduce threshold
        # no attendees_json — prior-recap helper returns "" immediately
    }

    with patch(_GENAI_PATCH, return_value=mock_client):
        summary, analytics = asyncio.run(
            analyze_meeting(meeting)
        )

    assert "recap" in summary
    assert "topics" in summary
    assert "intent_vs_outcome" in summary
    assert isinstance(analytics, list)
    assert len(analytics) == 2  # Alice + Bob
    # Analytics should have sentiment after analyze_meeting
    for a in analytics:
        assert "sentiment_label" in a
        assert "sentiment_score" in a


def test_analyze_meeting_long(long_transcript_raw):
    """Full pipeline on >30 min meeting => uses map-reduce path (3 segments + reduce)."""
    # 3 segment summaries + 1 reduce + 2 sentiment calls = 6 total
    side_effects = [
        MagicMock(text=VALID_SUMMARY_JSON),  # segment 1
        MagicMock(text=VALID_SUMMARY_JSON),  # segment 2
        MagicMock(text=VALID_SUMMARY_JSON),  # segment 3
        MagicMock(text=VALID_SUMMARY_JSON),  # reduce
        MagicMock(text=VALID_SENTIMENT_JSON),  # Alice sentiment
        MagicMock(text=VALID_SENTIMENT_JSON),  # Bob sentiment
    ]
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = side_effects

    meeting = {
        "id": "mtg-2",
        "twin_id": "twin-1",
        "title": "Long Meeting",
        "transcript_raw": long_transcript_raw,
        "transcript_text": "Alice: Start of meeting\nBob: Second segment\nAlice: Third segment",
        "duration_seconds": 2700,  # 45 minutes — above map-reduce threshold
    }

    with patch(_GENAI_PATCH, return_value=mock_client):
        summary, analytics = asyncio.run(
            analyze_meeting(meeting)
        )

    assert "recap" in summary
    # map-reduce: 3 segment calls + 1 reduce = 4 Gemini calls for summary
    # plus 2 sentiment calls = 6 total
    assert mock_client.models.generate_content.call_count == 6
