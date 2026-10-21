"""Tests for the outcome-based persona readiness scorer.

Covers the pure scoring logic and the DB/retrieval-backed dimensions with the
external calls mocked. See
docs/superpowers/specs/2026-05-30-persona-readiness-algorithm-design.md.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from routers import persona_readiness as pr


# ── labels ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "score,label",
    [
        (0, "Needs setup"),
        (24, "Needs setup"),
        (25, "Getting useful"),
        (44, "Getting useful"),
        (45, "Reliable"),
        (64, "Reliable"),
        (65, "Sharp"),
        (84, "Sharp"),
        (85, "Expert"),
        (100, "Expert"),
    ],
)
def test_label_boundaries(score, label):
    assert pr._label_for(score) == label


# ── identity ─────────────────────────────────────────────────────────

def test_identity_empty():
    result = pr._score_identity({})
    assert result["score"] == 0
    assert result["status"] == "empty"
    assert result["max"] == 20


def test_identity_complete():
    settings = {
        "persona_profile": {
            "name": "Ada",
            "occupation": "Engineer",
            "short_description": "Builds things",
            "areas_of_expertise": ["systems", "ml"],
            "bio": "x" * 80,
        }
    }
    result = pr._score_identity(settings)
    assert result["score"] == 20
    assert result["status"] == "complete"
    assert all(result["fields"].values())


def test_identity_partial_flags_missing_bio():
    settings = {
        "persona_profile": {
            "name": "Ada",
            "occupation": "Engineer",
            "short_description": "Builds things",
            "areas_of_expertise": ["systems"],
            "bio": "too short",  # < 80 chars
        }
    }
    result = pr._score_identity(settings)
    assert result["score"] == 16  # 3+4+4+5, bio (4) missing
    assert result["status"] == "partial"
    assert result["fields"]["bio"] is False
    assert "bio" in result["hint"]


def test_identity_handles_json_string_profile():
    # persona_profile sometimes persists as a JSON string.
    settings = {"persona_profile": '{"name": "Ada"}'}
    result = pr._score_identity(settings)
    assert result["fields"]["name"] is True
    assert result["score"] == 3


# ── coverage ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_coverage_breadth_and_depth():
    with patch("adk_core.services.vector_store.namespace_stats", new_callable=AsyncMock) as stats, \
         patch.object(pr, "_distinct_source_types", return_value=["document", "web", "meeting"]):
        stats.return_value = {"vector_count": 30}
        result = await pr._score_coverage("twin-1")
    # breadth = 8*min(3,3)=24 ; depth = min(16, round(4*log2(31)))=16 ; capped at 40
    assert result["score"] == 40
    assert result["status"] == "strong"
    assert result["chunk_count"] == 30
    assert result["source_types"] == ["document", "web", "meeting"]


@pytest.mark.asyncio
async def test_coverage_single_type_is_growing():
    with patch("adk_core.services.vector_store.namespace_stats", new_callable=AsyncMock) as stats, \
         patch.object(pr, "_distinct_source_types", return_value=["document"]):
        stats.return_value = {"vector_count": 5}
        result = await pr._score_coverage("twin-1")
    # breadth = 8 ; depth = min(16, round(4*log2(6)))=10 ; total=18
    assert result["score"] == 18
    assert result["status"] == "growing"


@pytest.mark.asyncio
async def test_coverage_empty():
    with patch("adk_core.services.vector_store.namespace_stats", new_callable=AsyncMock) as stats, \
         patch.object(pr, "_distinct_source_types", return_value=[]):
        stats.return_value = {"vector_count": 0}
        result = await pr._score_coverage("twin-1")
    assert result["score"] == 0
    assert result["status"] == "empty"


# ── answerability ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_answerability_no_questions_uses_capped_proxy():
    with patch.object(pr, "_question_set", return_value=[]):
        result = await pr._score_answerability("twin-1", {}, chunk_count=100)
    # proxy capped at half (15) when no real questions exist
    assert result["score"] == 15
    assert result["asked"] == 0
    assert result["status"] == "unmeasured"


@pytest.mark.asyncio
async def test_answerability_no_questions_no_chunks_is_empty():
    with patch.object(pr, "_question_set", return_value=[]):
        result = await pr._score_answerability("twin-1", {}, chunk_count=0)
    assert result["score"] == 0
    assert result["status"] == "empty"


@pytest.mark.asyncio
async def test_answerability_partial_from_retrieval():
    questions = ["q1", "q2", "q3"]

    async def fake_search(q, twin_id, top_k=1):
        # q1 and q2 land above tau; q3 does not.
        scores = {"q1": 0.6, "q2": 0.4, "q3": 0.1}
        return [{"score": scores[q]}]

    with patch.object(pr, "_question_set", return_value=questions), \
         patch("adk_core.services.vector_store.search", side_effect=fake_search):
        result = await pr._score_answerability("twin-1", {}, chunk_count=50)

    assert result["asked"] == 3
    assert result["answerable"] == 2  # 0.6 and 0.4 >= 0.35
    assert result["score"] == 20  # round(30 * 2/3)
    assert result["status"] == "partial"
    assert len(result["sampled_questions"]) == 3


@pytest.mark.asyncio
async def test_answerability_none_answerable():
    async def fake_search(q, twin_id, top_k=1):
        return [{"score": 0.05}]

    with patch.object(pr, "_question_set", return_value=["q1", "q2"]), \
         patch("adk_core.services.vector_store.search", side_effect=fake_search):
        result = await pr._score_answerability("twin-1", {}, chunk_count=10)

    assert result["answerable"] == 0
    assert result["score"] == 0
    assert result["status"] == "empty"


# ── freshness ────────────────────────────────────────────────────────

def test_freshness_recent_is_full():
    from datetime import datetime, timezone, timedelta
    recent = datetime.now(timezone.utc) - timedelta(days=3)
    with patch.object(pr, "_newest_source_at", return_value=recent):
        result = pr._score_freshness("twin-1", chunk_count=10)
    assert result["score"] == 10
    assert result["status"] == "fresh"


def test_freshness_old_decays():
    from datetime import datetime, timezone, timedelta
    old = datetime.now(timezone.utc) - timedelta(days=120)
    with patch.object(pr, "_newest_source_at", return_value=old):
        result = pr._score_freshness("twin-1", chunk_count=10)
    assert result["score"] == 3  # 90 < 120 <= 180
    assert result["status"] == "stale"


def test_freshness_no_sources_no_chunks_is_zero():
    with patch.object(pr, "_newest_source_at", return_value=None):
        result = pr._score_freshness("twin-1", chunk_count=0)
    assert result["score"] == 0
    assert result["status"] == "empty"


def test_parse_ts_handles_z_suffix_and_naive():
    from datetime import timezone
    dt = pr._parse_ts("2026-05-01T12:00:00Z")
    assert dt is not None and dt.tzinfo is not None
    naive = pr._parse_ts("2026-05-01T12:00:00")
    assert naive is not None and naive.tzinfo == timezone.utc
    assert pr._parse_ts(None) is None
    assert pr._parse_ts("garbage") is None
