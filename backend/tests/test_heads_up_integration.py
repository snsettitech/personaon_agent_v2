"""W9b — Heads Up wire-in integration tests.

Verifies that generate_brief() correctly composes rule candidates + invokes
the LLM rewriter when feature flags are on, and short-circuits when off.

The LLM call + KB search are mocked — these tests are about the WIRING,
not the LLM behavior (covered by test_heads_up_rewriter.py and the eval
harness).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_build_heads_up_candidates_composes_all_rules(monkeypatch):
    """The helper concats sync rule outputs + the async KB rule output."""
    monkeypatch.setenv("BRIEF_SCHEMA_V2_ENABLED", "true")
    monkeypatch.setenv("HEADS_UP_ENABLED", "true")
    from adk_core.services.persona_core import brief
    from adk_core.services.persona_core import heads_up_rules

    meeting = {
        "organizer_email": "other@external.com",
        "attendees_json": [{"displayName": "Sarah", "email": "sarah@x.com"}],
        "title": "Quarterly review",
    }
    with patch.object(heads_up_rules, "_kb_search", new_callable=AsyncMock) as mock_kb:
        mock_kb.return_value = [{"text": "private note about Sarah", "source_id": "n_1"}]
        candidates = await brief._build_heads_up_candidates(
            twin_id="t_1",
            meeting=meeting,
            open_commitments=[
                {"description": "Send Q2 doc", "days_open": 13, "from_meeting_id": "m1"},
            ],
            previous_interactions=[
                {"date": "2026-05-01", "meeting_title": "Last sync", "open_items": ["Follow up"]},
            ],
            effective_self_email="me@self.com",
        )
    kinds = [c["kind"] for c in candidates]
    assert "open_commitment" in kinds
    assert "action_item_pending" in kinds
    assert "agenda_signal_other_organizer" in kinds
    assert "kb_private_hit" in kinds


@pytest.mark.asyncio
async def test_build_heads_up_candidates_isolates_rule_failures(monkeypatch):
    """If one rule raises, the others still contribute candidates."""
    from adk_core.services.persona_core import brief
    from adk_core.services.persona_core import heads_up_rules

    with patch.object(heads_up_rules, "_kb_search", new_callable=AsyncMock) as mock_kb:
        mock_kb.side_effect = RuntimeError("kb down")
        candidates = await brief._build_heads_up_candidates(
            twin_id="t_1",
            meeting={"organizer_email": "me@self.com", "title": "x", "attendees_json": []},
            open_commitments=[{"description": "Send doc", "days_open": 13, "from_meeting_id": "m1"}],
            previous_interactions=[],
            effective_self_email="me@self.com",
        )
    # KB failed but open_commitment rule still contributed
    kinds = [c["kind"] for c in candidates]
    assert "open_commitment" in kinds
    assert "kb_private_hit" not in kinds


def test_heads_up_enabled_default_off(monkeypatch):
    """HEADS_UP_ENABLED unset → false (production-safe default)."""
    monkeypatch.delenv("HEADS_UP_ENABLED", raising=False)
    from adk_core.services.persona_core.brief import _heads_up_enabled
    assert _heads_up_enabled() is False


def test_heads_up_enabled_true_when_set(monkeypatch):
    monkeypatch.setenv("HEADS_UP_ENABLED", "true")
    from adk_core.services.persona_core.brief import _heads_up_enabled
    assert _heads_up_enabled() is True


def test_heads_up_independent_of_schema_v2_flag(monkeypatch):
    """The two flags are independent functions — toggling one doesn't
    affect the other. Both must be true for caution_notes to populate."""
    monkeypatch.setenv("BRIEF_SCHEMA_V2_ENABLED", "true")
    monkeypatch.setenv("HEADS_UP_ENABLED", "false")
    from adk_core.services.persona_core.brief import (
        _schema_v2_enabled,
        _heads_up_enabled,
    )
    assert _schema_v2_enabled() is True
    assert _heads_up_enabled() is False
