"""W9b — Async kb_private_hit rule unit tests.

Separated from test_heads_up_rules.py so pytest-asyncio fixtures don't
overhead the sync rule tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_kb_private_hit_returns_candidate_on_match():
    from adk_core.services.persona_core import heads_up_rules
    with patch.object(
        heads_up_rules, "_kb_search", new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = [
            {
                "text": "Marcus pushed back on enterprise pricing in March",
                "source_id": "note_42",
                "filename": "march_notes.md",
            },
        ]
        candidates = await heads_up_rules.rule_kb_private_hit(
            twin_id="t_1",
            meeting_title="Marcus Sync",
            attendees=[{"displayName": "Marcus Webb", "email": "marcus@x.com"}],
        )
    assert len(candidates) == 1
    c = candidates[0]
    assert c["kind"] == "kb_private_hit"
    assert c["tier"] == "private"
    assert c["attendee"] == "Marcus Webb"
    assert "Marcus" in c["note_quote"]
    assert c["note_source_id"] == "note_42"


@pytest.mark.asyncio
async def test_kb_private_hit_uses_private_tier_only():
    """Defensive: the KB call must pass allowed_tiers=['private'] —
    otherwise we'd surface public-tier hits as 'cautions', which is wrong."""
    from adk_core.services.persona_core import heads_up_rules
    with patch.object(
        heads_up_rules, "_kb_search", new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = []
        await heads_up_rules.rule_kb_private_hit(
            twin_id="t_1",
            meeting_title="Sync",
            attendees=[{"displayName": "Marcus", "email": "m@x.com"}],
        )
    # Inspect the call kwargs
    assert mock_search.called
    call_kwargs = mock_search.call_args.kwargs
    assert call_kwargs.get("allowed_tiers") == ["private"]
    assert call_kwargs.get("twin_id") == "t_1"


@pytest.mark.asyncio
async def test_kb_private_hit_empty_on_no_results():
    from adk_core.services.persona_core import heads_up_rules
    with patch.object(
        heads_up_rules, "_kb_search", new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = []
        candidates = await heads_up_rules.rule_kb_private_hit(
            twin_id="t_1",
            meeting_title="x",
            attendees=[],
        )
    assert candidates == []


@pytest.mark.asyncio
async def test_kb_private_hit_returns_empty_on_search_error():
    """KB outage must NOT block brief generation — return empty."""
    from adk_core.services.persona_core import heads_up_rules
    with patch.object(
        heads_up_rules, "_kb_search", new_callable=AsyncMock,
    ) as mock_search:
        mock_search.side_effect = RuntimeError("pgvector down")
        candidates = await heads_up_rules.rule_kb_private_hit(
            twin_id="t_1", meeting_title="x", attendees=[],
        )
    assert candidates == []


@pytest.mark.asyncio
async def test_kb_private_hit_skips_empty_text_chunks():
    """Malformed chunks (no text) don't create empty candidates."""
    from adk_core.services.persona_core import heads_up_rules
    with patch.object(
        heads_up_rules, "_kb_search", new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = [
            {"text": "", "source_id": "x"},
            {"text": "real content", "source_id": "y", "filename": "f.md"},
        ]
        candidates = await heads_up_rules.rule_kb_private_hit(
            twin_id="t_1",
            meeting_title="Sync",
            attendees=[{"displayName": "Marcus"}],
        )
    assert len(candidates) == 1
    assert candidates[0]["note_quote"] == "real content"


@pytest.mark.asyncio
async def test_kb_private_hit_empty_when_no_query_signal():
    """No title + no attendees → no query → empty result without DB call."""
    from adk_core.services.persona_core import heads_up_rules
    with patch.object(
        heads_up_rules, "_kb_search", new_callable=AsyncMock,
    ) as mock_search:
        candidates = await heads_up_rules.rule_kb_private_hit(
            twin_id="t_1", meeting_title="", attendees=None,
        )
    assert candidates == []
    # Crucially: no DB call when we have nothing to query for
    assert not mock_search.called


@pytest.mark.asyncio
async def test_kb_private_hit_truncates_long_quotes():
    """note_quote is bounded — long chunks don't bloat the LLM prompt."""
    from adk_core.services.persona_core import heads_up_rules
    long_text = "x" * 1000
    with patch.object(
        heads_up_rules, "_kb_search", new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = [{"text": long_text, "source_id": "x"}]
        candidates = await heads_up_rules.rule_kb_private_hit(
            twin_id="t_1",
            meeting_title="Sync",
            attendees=[{"displayName": "M"}],
        )
    assert len(candidates) == 1
    assert len(candidates[0]["note_quote"]) <= 280
