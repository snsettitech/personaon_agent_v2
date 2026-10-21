"""W9b — Heads Up LLM rewriter unit tests.

Covers the Gemini call wrapper + JSON parser + citation synthesizer +
post-LLM safety filter integration. The actual LLM is mocked — see
test_heads_up_eval.py for live-Gemini integration runs.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _fake_gemini_response(payload: dict) -> SimpleNamespace:
    """Build a SimpleNamespace mimicking genai's response.text shape."""
    return SimpleNamespace(text=json.dumps(payload))


@pytest.mark.asyncio
async def test_rewriter_returns_empty_on_empty_candidates():
    """No candidates → no LLM call, empty result."""
    from adk_core.services.persona_core import heads_up_rewriter
    with patch.object(
        heads_up_rewriter, "_get_genai_client",
    ) as mock_client:
        result = await heads_up_rewriter.rewrite_to_caution_notes(
            candidates=[], meeting_title="Sync",
        )
        assert not mock_client.called  # no LLM call for empty input
    assert result == []


@pytest.mark.asyncio
async def test_rewriter_synthesizes_citation_from_candidate_idx():
    """LLM emits idx; rewriter mechanically builds source dict from candidate."""
    from adk_core.services.persona_core import heads_up_rewriter
    candidates = [{
        "kind": "open_commitment",
        "attendee": "Sarah",
        "description": "send Q2 doc",
        "days_open": 13,
        "source_meeting_id": "meet_abc",
        "source_quote": "I'll send it Friday",
    }]
    fake_resp = _fake_gemini_response({
        "caution_notes": [{
            "text": "Heads up — Sarah's still waiting on the Q2 doc you mentioned.",
            "source_candidate_idx": 0,
        }],
    })
    with patch.object(
        heads_up_rewriter, "_get_genai_client",
    ) as mock_client:
        mock_client.return_value.models.generate_content = MagicMock(return_value=fake_resp)
        notes = await heads_up_rewriter.rewrite_to_caution_notes(
            candidates=candidates, meeting_title="Sync",
        )
    assert len(notes) == 1
    note = notes[0]
    assert "Sarah" in note["text"]
    assert note["source"]["kind"] == "open_commitment"
    assert note["source"]["ref"] == "meet_abc"
    assert note["source"]["quote"] == "I'll send it Friday"


@pytest.mark.asyncio
async def test_rewriter_drops_anti_pattern_notes():
    """Notes containing forbidden language are dropped post-LLM."""
    from adk_core.services.persona_core import heads_up_rewriter
    candidates = [{
        "kind": "open_commitment",
        "description": "x",
        "source_meeting_id": "m",
        "source_quote": "q",
    }]
    fake_resp = _fake_gemini_response({
        "caution_notes": [
            {"text": "You should send the doc.", "source_candidate_idx": 0},
            {"text": "Heads up — pricing memo from May 7.", "source_candidate_idx": 0},
        ],
    })
    with patch.object(
        heads_up_rewriter, "_get_genai_client",
    ) as mock_client:
        mock_client.return_value.models.generate_content = MagicMock(return_value=fake_resp)
        notes = await heads_up_rewriter.rewrite_to_caution_notes(
            candidates=candidates, meeting_title="Sync",
        )
    # Imperative dropped; clean one survives
    assert len(notes) == 1
    assert "Heads up" in notes[0]["text"]


@pytest.mark.asyncio
async def test_rewriter_returns_empty_on_llm_error():
    """LLM timeout / network error → empty notes (NEVER raw rule output)."""
    from adk_core.services.persona_core import heads_up_rewriter
    candidates = [{"kind": "open_commitment", "description": "x", "source_meeting_id": "m"}]
    with patch.object(
        heads_up_rewriter, "_get_genai_client",
    ) as mock_client:
        mock_client.return_value.models.generate_content = MagicMock(
            side_effect=RuntimeError("timeout")
        )
        notes = await heads_up_rewriter.rewrite_to_caution_notes(
            candidates=candidates, meeting_title="Sync",
        )
    assert notes == []


@pytest.mark.asyncio
async def test_rewriter_returns_empty_on_parse_error():
    """Non-JSON LLM response → empty notes."""
    from adk_core.services.persona_core import heads_up_rewriter
    candidates = [{"kind": "open_commitment", "description": "x", "source_meeting_id": "m"}]
    fake_resp = SimpleNamespace(text="this is not json at all")
    with patch.object(
        heads_up_rewriter, "_get_genai_client",
    ) as mock_client:
        mock_client.return_value.models.generate_content = MagicMock(return_value=fake_resp)
        notes = await heads_up_rewriter.rewrite_to_caution_notes(
            candidates=candidates, meeting_title="Sync",
        )
    assert notes == []


@pytest.mark.asyncio
async def test_rewriter_caps_notes_at_three():
    """Even if LLM returns >3 notes, only top 3 ship."""
    from adk_core.services.persona_core import heads_up_rewriter
    candidates = [
        {"kind": "open_commitment", "description": f"item {i}", "source_meeting_id": "m", "source_quote": "q"}
        for i in range(5)
    ]
    fake_resp = _fake_gemini_response({
        "caution_notes": [
            {"text": f"Heads up — note {i}.", "source_candidate_idx": i}
            for i in range(5)
        ],
    })
    with patch.object(
        heads_up_rewriter, "_get_genai_client",
    ) as mock_client:
        mock_client.return_value.models.generate_content = MagicMock(return_value=fake_resp)
        notes = await heads_up_rewriter.rewrite_to_caution_notes(
            candidates=candidates, meeting_title="Sync",
        )
    assert len(notes) == 3


@pytest.mark.asyncio
async def test_rewriter_drops_note_with_invalid_idx():
    """Out-of-range source_candidate_idx → drop the note, don't crash."""
    from adk_core.services.persona_core import heads_up_rewriter
    candidates = [{"kind": "open_commitment", "description": "x", "source_meeting_id": "m"}]
    fake_resp = _fake_gemini_response({
        "caution_notes": [
            {"text": "Heads up — valid.", "source_candidate_idx": 0},
            {"text": "Heads up — invalid idx.", "source_candidate_idx": 99},
            {"text": "Heads up — negative.", "source_candidate_idx": -1},
        ],
    })
    with patch.object(
        heads_up_rewriter, "_get_genai_client",
    ) as mock_client:
        mock_client.return_value.models.generate_content = MagicMock(return_value=fake_resp)
        notes = await heads_up_rewriter.rewrite_to_caution_notes(
            candidates=candidates, meeting_title="Sync",
        )
    assert len(notes) == 1
    assert notes[0]["source"]["ref"] == "m"


@pytest.mark.asyncio
async def test_rewriter_invalid_idx_log_redacts_private_text(caplog):
    from adk_core.services.persona_core import heads_up_rewriter

    private_title = "Confidential acquisition review"
    private_note = "Heads up — PRIVATE CUSTOMER DATA about Project Falcon."
    candidates = [{"kind": "open_commitment", "description": "x", "source_meeting_id": "m"}]
    fake_resp = _fake_gemini_response({
        "caution_notes": [
            {"text": private_note, "source_candidate_idx": 99},
        ],
    })
    caplog.set_level(logging.WARNING, logger=heads_up_rewriter.logger.name)

    with patch.object(
        heads_up_rewriter, "_get_genai_client",
    ) as mock_client:
        mock_client.return_value.models.generate_content = MagicMock(return_value=fake_resp)
        notes = await heads_up_rewriter.rewrite_to_caution_notes(
            candidates=candidates, meeting_title=private_title,
        )

    assert notes == []
    assert "PRIVATE CUSTOMER DATA" not in caplog.text
    assert private_title not in caplog.text
    assert "meeting_hash=" in caplog.text
    assert "note_hash=" in caplog.text


@pytest.mark.asyncio
async def test_rewriter_strips_markdown_fences():
    """LLM sometimes wraps JSON in ```json fences; rewriter handles it."""
    from adk_core.services.persona_core import heads_up_rewriter
    candidates = [{"kind": "open_commitment", "description": "x", "source_meeting_id": "m"}]
    fake_resp = SimpleNamespace(text=(
        "```json\n"
        '{"caution_notes": [{"text": "Heads up — fenced.", "source_candidate_idx": 0}]}\n'
        "```"
    ))
    with patch.object(
        heads_up_rewriter, "_get_genai_client",
    ) as mock_client:
        mock_client.return_value.models.generate_content = MagicMock(return_value=fake_resp)
        notes = await heads_up_rewriter.rewrite_to_caution_notes(
            candidates=candidates, meeting_title="Sync",
        )
    assert len(notes) == 1
    assert "fenced" in notes[0]["text"]


@pytest.mark.asyncio
async def test_rewriter_source_ref_falls_back_to_kind_when_no_meeting_id():
    """For candidates without source_meeting_id (e.g. kb_private_hit),
    the source.ref falls back to a sensible identifier."""
    from adk_core.services.persona_core import heads_up_rewriter
    candidates = [{
        "kind": "kb_private_hit",
        "attendee": "Marcus",
        "topic": "pricing",
        "note_quote": "Marcus pushed back on pricing",
        "note_source_id": "note_42",
        "tier": "private",
    }]
    fake_resp = _fake_gemini_response({
        "caution_notes": [{
            "text": "Worth re-reading — your private note mentions Marcus pushed back on pricing.",
            "source_candidate_idx": 0,
        }],
    })
    with patch.object(
        heads_up_rewriter, "_get_genai_client",
    ) as mock_client:
        mock_client.return_value.models.generate_content = MagicMock(return_value=fake_resp)
        notes = await heads_up_rewriter.rewrite_to_caution_notes(
            candidates=candidates, meeting_title="Marcus Sync",
        )
    assert len(notes) == 1
    assert notes[0]["source"]["ref"] == "note_42"
    assert notes[0]["source"]["quote"] == "Marcus pushed back on pricing"
