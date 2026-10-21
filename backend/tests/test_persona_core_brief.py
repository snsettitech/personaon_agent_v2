"""Tests for the pre-meeting brief engine (persona_core.brief).

Covers:
  - generate_brief happy path with PDL hit + prior recap + open commitment
  - PDL miss → person.bio/role/company/signals are empty strings/list
  - Gemini failure → fallback hooks (deterministic, derived from commitments)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


SAMPLE_PDL_RECORD = {
    "full_name": "Alex Chen",
    "job_title": "VP Sales",
    "job_company_name": "Acme",
    "summary": "Joined Acme in 2024 from Stripe (5 yrs, enterprise sales).",
    "headline": "VP Sales @ Acme",
    "experience": [
        {"company": {"name": "Acme"}, "title": {"name": "VP Sales"}},
    ],
    "location_name": "San Francisco",
}

SAMPLE_MEETING = {
    "id": "mtg-2",
    "title": "Pricing follow-up",
    "meeting_start": "2026-05-20T14:30:00Z",
    "meeting_end": "2026-05-20T15:00:00Z",
    "attendees_json": [
        {"email": "alex@acme.com", "displayName": "Alex Chen"},
    ],
    "organizer_email": "owner@example.com",
    "user_goal": "Lock in tier 2 pricing.",
    "user_context": None,
    "twin_id": "twin-1",
    "tenant_id": "tenant-1",
}


@pytest.mark.asyncio
async def test_generate_brief_with_pdl_and_prior_recap():
    """End-to-end happy path: PDL hits, prior recap exists with a 'me' commitment,
    Gemini returns hooks. The brief should contain all sections populated."""
    from adk_core.services.persona_core import brief as brief_module

    prior_recaps = [
        {
            "meeting_id": "mtg-1",
            "date": "2026-05-03",
            "title": "Numbers review",
            "summary": "Walked Alex through Q1 numbers. He asked for cohort data.",
            "commitments": [
                {"by": "me", "to": "Alex", "what": "Send cohort data", "due": None},
            ],
            "action_items": [],
        },
    ]

    sample_hooks = [
        {"label": "Bring", "text": "Cohort data — he asked for it on May 3."},
        {"label": "Probe", "text": "Their security review timeline."},
    ]

    with patch.object(
        brief_module,
        "_fetch_prior_recaps_for_brief",
        new=AsyncMock(return_value=prior_recaps),
    ), patch(
        "services.enrichment.pdl_client.enrich_by_email",
        new=AsyncMock(return_value=SAMPLE_PDL_RECORD),
    ), patch.object(
        brief_module,
        "_generate_hooks",
        new=AsyncMock(return_value=sample_hooks),
    ):
        result = await brief_module.generate_brief(
            twin_id="twin-1",
            meeting_id="mtg-2",
            meeting=SAMPLE_MEETING,
        )

    assert result["meeting_id"] == "mtg-2"
    assert result["meeting_title"] == "Pricing follow-up"
    assert result["your_goal"] == "Lock in tier 2 pricing."

    # PDL-populated person block
    assert result["person"]["name"] == "Alex Chen"
    assert result["person"]["role"] == "VP Sales"
    assert result["person"]["company"] == "Acme"
    assert "Stripe" in result["person"]["bio"]
    assert len(result["person"]["signals"]) >= 1

    # Prior meetings carried through (trimmed shape)
    assert len(result["prior_meetings"]) == 1
    assert result["prior_meetings"][0]["title"] == "Numbers review"
    assert result["prior_meetings"][0]["date"] == "2026-05-03"

    # Open commitment surfaced
    assert len(result["open_commitments"]) == 1
    assert result["open_commitments"][0]["description"] == "Send cohort data"
    assert result["open_commitments"][0]["days_open"] >= 0

    # Hooks come from the (mocked) generator
    assert result["hooks"] == sample_hooks
    assert "generated_at" in result


@pytest.mark.asyncio
async def test_generate_brief_pdl_miss_keeps_empty_person_fields():
    """PDL returning None should not crash; person.bio/role/company are empty."""
    from adk_core.services.persona_core import brief as brief_module

    with patch.object(
        brief_module,
        "_fetch_prior_recaps_for_brief",
        new=AsyncMock(return_value=[]),
    ), patch(
        "services.enrichment.pdl_client.enrich_by_email",
        new=AsyncMock(return_value=None),
    ), patch.object(
        brief_module,
        "_generate_hooks",
        new=AsyncMock(return_value=[{"label": "Probe", "text": "Ask about priority."}]),
    ):
        result = await brief_module.generate_brief(
            twin_id="twin-1",
            meeting_id="mtg-2",
            meeting=SAMPLE_MEETING,
        )

    assert result["person"]["name"] == "Alex Chen"  # from attendees_json
    assert result["person"]["bio"] == ""
    assert result["person"]["role"] == ""
    assert result["person"]["company"] == ""
    assert result["person"]["signals"] == []
    assert result["open_commitments"] == []
    # Hooks are still returned even with no enrichment
    assert len(result["hooks"]) == 1


@pytest.mark.asyncio
async def test_generate_brief_falls_back_when_gemini_fails():
    """If the Gemini hook generator raises, we should still get hooks (fallback)
    derived from open commitments."""
    from adk_core.services.persona_core import brief as brief_module

    prior_recaps = [
        {
            "meeting_id": "mtg-1",
            "date": "2026-05-03",
            "title": "Numbers review",
            "summary": "Q1 review.",
            "commitments": [
                {"by": "me", "to": "Alex", "what": "Send cohort data", "due": None},
            ],
            "action_items": [],
        },
    ]

    # Make the *underlying* client raise — exercise the real fallback path
    # inside _generate_hooks.
    def _boom_client(api_key):  # noqa: ARG001
        raise RuntimeError("simulated Gemini outage")

    with patch.object(
        brief_module,
        "_fetch_prior_recaps_for_brief",
        new=AsyncMock(return_value=prior_recaps),
    ), patch(
        "services.enrichment.pdl_client.enrich_by_email",
        new=AsyncMock(return_value=None),
    ), patch.object(brief_module, "_get_genai_client", side_effect=_boom_client):
        result = await brief_module.generate_brief(
            twin_id="twin-1",
            meeting_id="mtg-2",
            meeting=SAMPLE_MEETING,
        )

    # Fallback must still produce at least one hook tied to the open commitment.
    assert len(result["hooks"]) >= 1
    assert any("cohort" in h["text"].lower() for h in result["hooks"])


@pytest.mark.asyncio
async def test_generate_brief_skips_organizer_in_attendees():
    """If only attendee equals organizer (twin owner), person.name should be empty
    rather than the owner's display name."""
    from adk_core.services.persona_core import brief as brief_module

    meeting = {
        **SAMPLE_MEETING,
        "attendees_json": [
            {"email": "owner@example.com", "displayName": "Owner Self"},
        ],
    }

    with patch.object(
        brief_module,
        "_fetch_prior_recaps_for_brief",
        new=AsyncMock(return_value=[]),
    ), patch(
        "services.enrichment.pdl_client.enrich_by_email",
        new=AsyncMock(return_value=None),
    ), patch.object(
        brief_module,
        "_generate_hooks",
        new=AsyncMock(return_value=[]),
    ):
        result = await brief_module.generate_brief(
            twin_id="twin-1",
            meeting_id="mtg-2",
            meeting=meeting,
        )

    assert result["person"]["name"] == ""
    assert result["person"]["email"] == ""


@pytest.mark.asyncio
async def test_generate_brief_suppresses_slop_when_no_signal(monkeypatch):
    """No prior meetings, no PDL enrichment, no stated goal → the brief must NOT
    fabricate hooks/talking_points/agenda. With nothing real to say those arrays
    come back empty, so the UI shows the honest 'new contact' state instead of
    generic filler ('ask what outcomes they're hoping to achieve')."""
    monkeypatch.setenv("BRIEF_SCHEMA_V2_ENABLED", "true")
    from adk_core.services.persona_core import brief as brief_module

    no_goal_meeting = {**SAMPLE_MEETING, "user_goal": None, "user_context": None}

    with patch.object(
        brief_module,
        "_fetch_prior_recaps_for_brief",
        new=AsyncMock(return_value=[]),
    ), patch(
        "services.enrichment.pdl_client.enrich_by_email",
        new=AsyncMock(return_value=None),
    ), patch.object(
        brief_module,
        "_generate_hooks",
        new=AsyncMock(return_value=[
            {"label": "Probe", "text": "Ask what outcomes they're hoping to achieve."},
        ]),
    ):
        result = await brief_module.generate_brief(
            twin_id="twin-1",
            meeting_id="mtg-2",
            meeting=no_goal_meeting,
        )

    # Slop gate: no real signal → no fabricated content.
    assert result["hooks"] == []
    assert result["talking_points"] == []
    assert result["suggested_agenda"] == []
    # Person block still renders (name from attendees) — we just don't invent advice.
    assert result["person"]["name"] == "Alex Chen"


@pytest.mark.asyncio
async def test_generate_brief_keeps_hooks_when_goal_present(monkeypatch):
    """A user-stated goal is real signal — hooks/talking_points survive even with
    no prior meetings and no PDL. Guards against the slop gate over-suppressing."""
    monkeypatch.setenv("BRIEF_SCHEMA_V2_ENABLED", "true")
    from adk_core.services.persona_core import brief as brief_module

    sample_hooks = [{"label": "Lead", "text": "Open with the tier-2 pricing ask."}]
    with patch.object(
        brief_module,
        "_fetch_prior_recaps_for_brief",
        new=AsyncMock(return_value=[]),
    ), patch(
        "services.enrichment.pdl_client.enrich_by_email",
        new=AsyncMock(return_value=None),
    ), patch.object(
        brief_module,
        "_generate_hooks",
        new=AsyncMock(return_value=sample_hooks),
    ):
        result = await brief_module.generate_brief(
            twin_id="twin-1",
            meeting_id="mtg-2",
            meeting=SAMPLE_MEETING,  # carries a real user_goal
        )

    assert result["hooks"] == sample_hooks
    assert len(result["talking_points"]) >= 1
