"""W9a — Brief schema v2 contract tests.

Locks the additive schema_version=2 shape. The v1 fields stay for one
release cycle so older brief_json rows still render in the UI.

The schema-v2 flag is read from env at call time (function-based, not
module-level constant) so tests use a fixture instead of importlib.reload.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def schema_v2_on(monkeypatch):
    """Enable the v2 schema flag for this test only."""
    monkeypatch.setenv("BRIEF_SCHEMA_V2_ENABLED", "true")


@pytest.fixture
def schema_v2_off(monkeypatch):
    """Force the v2 schema flag off — covers the prod-soak path."""
    monkeypatch.setenv("BRIEF_SCHEMA_V2_ENABLED", "false")


def test_empty_contract_has_schema_version_2(schema_v2_on):
    from adk_core.services.persona_core.brief import _empty_brief_contract

    brief = _empty_brief_contract(
        meeting_id="m_test", title="Sync", start="2026-05-21T15:00:00Z"
    )
    assert brief["schema_version"] == 2


def test_empty_contract_has_v2_fields(schema_v2_on):
    from adk_core.services.persona_core.brief import _empty_brief_contract

    brief = _empty_brief_contract(
        meeting_id="m_test", title="Sync", start="2026-05-21T15:00:00Z"
    )
    # All v2 arrays default to empty (frontend reads without null-checks)
    assert brief["participant_insights"] == []
    assert brief["talking_points"] == []
    assert brief["previous_interactions"] == []
    assert brief["suggested_agenda"] == []
    assert brief["caution_notes"] == []
    assert brief["sources_used"] == {
        "kb_chunks": 0,
        "web_results": 0,
        "past_meetings": 0,
    }


def test_v1_backward_compat_fields_present(schema_v2_on):
    from adk_core.services.persona_core.brief import _empty_brief_contract

    brief = _empty_brief_contract(
        meeting_id="m_test", title="Sync", start="2026-05-21T15:00:00Z"
    )
    # v1 keys remain so unupdated readers don't crash
    assert "person" in brief
    assert "hooks" in brief
    assert "prior_meetings" in brief
    assert "open_commitments" in brief
    assert "your_goal" in brief
    assert "your_context" in brief


def test_meeting_identifiers_carry_through(schema_v2_on):
    from adk_core.services.persona_core.brief import _empty_brief_contract

    brief = _empty_brief_contract(
        meeting_id="m_abc",
        title="Investor pitch",
        start="2026-05-21T15:00:00Z",
    )
    assert brief["meeting_id"] == "m_abc"
    assert brief["meeting_title"] == "Investor pitch"
    assert brief["meeting_start"] == "2026-05-21T15:00:00Z"


def test_flag_disabled_returns_v1_only(schema_v2_off):
    """When BRIEF_SCHEMA_V2_ENABLED is false, only v1 fields ship.

    Production safety net — defaults false; staging sets true; promote
    to prod after 24h soak.
    """
    from adk_core.services.persona_core.brief import _empty_brief_contract

    brief = _empty_brief_contract(
        meeting_id="m_test", title="Sync", start="2026-05-21T15:00:00Z"
    )
    assert brief["schema_version"] == 1
    assert "participant_insights" not in brief
    assert "talking_points" not in brief
    assert "caution_notes" not in brief


def test_flag_default_is_off(monkeypatch):
    """When BRIEF_SCHEMA_V2_ENABLED is unset, v1 ships (prod-safe default).

    Uses monkeypatch.delenv so the unset state is restored after this test
    runs — leaving os.environ mutated would break tests in subsequent
    sessions or under pytest-xdist.
    """
    monkeypatch.delenv("BRIEF_SCHEMA_V2_ENABLED", raising=False)
    from adk_core.services.persona_core.brief import _schema_v2_enabled

    assert _schema_v2_enabled() is False


# ---------------------------------------------------------------------------
# Task 2 — participant_insights[]
# ---------------------------------------------------------------------------


def test_participant_insights_single_attendee():
    from adk_core.services.persona_core.brief import _extract_participant_insights

    attendees = [{"email": "sarah@acme.com", "displayName": "Sarah Chen"}]
    insights = _extract_participant_insights(attendees, organizer_email="me@self.com")
    assert len(insights) == 1
    assert insights[0]["name"] == "Sarah Chen"
    assert insights[0]["email"] == "sarah@acme.com"
    # Defaults present so frontend can read without null-checks
    assert insights[0]["role"] is None
    assert insights[0]["background"] is None
    assert insights[0]["recent_activities"] == []
    assert insights[0]["web_sources"] == []


def test_participant_insights_caps_at_four():
    attendees = [
        {"email": f"p{i}@x.com", "displayName": f"Person {i}"} for i in range(7)
    ]
    from adk_core.services.persona_core.brief import _extract_participant_insights

    insights = _extract_participant_insights(attendees, organizer_email="me@self.com")
    assert len(insights) == 4


def test_participant_insights_excludes_self_by_email():
    """Self-exclusion is a privacy guard — don't surface the user to themselves."""
    from adk_core.services.persona_core.brief import _extract_participant_insights

    attendees = [
        {"email": "me@self.com", "displayName": "Me"},
        {"email": "Sarah@Acme.com", "displayName": "Sarah Chen"},  # case-insensitive match below
    ]
    insights = _extract_participant_insights(
        attendees,
        organizer_email="other@host.com",
        self_email="ME@self.COM",
    )
    assert len(insights) == 1
    assert insights[0]["name"] == "Sarah Chen"


def test_participant_insights_empty_input():
    from adk_core.services.persona_core.brief import _extract_participant_insights

    assert _extract_participant_insights(None, organizer_email=None) == []
    assert _extract_participant_insights([], organizer_email=None) == []


def test_participant_insights_carries_pdl_snapshot_field():
    """W9b Task 6: each insight has a pdl_snapshot slot.

    Default None. generate_brief() populates it for the primary attendee
    after a successful PDL enrich, so the NEXT brief can diff via
    rule_pdl_change.
    """
    from adk_core.services.persona_core.brief import _extract_participant_insights

    insights = _extract_participant_insights(
        [{"email": "sarah@acme.com", "displayName": "Sarah Chen"}],
        organizer_email="me@self.com",
    )
    assert "pdl_snapshot" in insights[0]
    assert insights[0]["pdl_snapshot"] is None


def test_participant_insights_string_attendees_handled():
    """attendees_json sometimes contains plain strings — handle gracefully."""
    from adk_core.services.persona_core.brief import _extract_participant_insights

    insights = _extract_participant_insights(
        ["alice@x.com", "bob@y.com"], organizer_email="me@self.com"
    )
    assert len(insights) == 2
    assert insights[0]["name"] == "alice@x.com"  # falls back to string itself
    assert insights[0]["email"] == ""  # no parseable email when input is a bare string


# ---------------------------------------------------------------------------
# Task 3 — talking_points[]
# ---------------------------------------------------------------------------


def test_talking_points_mirror_hooks():
    """v2 talking_points should mirror v1 hooks under the new field names."""
    from adk_core.services.persona_core.brief import _hooks_to_talking_points

    hooks = [
        {"label": "Bring", "text": "Q2 strategy doc draft"},
        {"label": "Probe", "text": "Their renewal date"},
    ]
    points = _hooks_to_talking_points(hooks)
    assert len(points) == 2
    assert points[0] == {"topic": "Q2 strategy doc draft", "rationale": "Bring"}
    assert points[1] == {"topic": "Their renewal date", "rationale": "Probe"}


def test_talking_points_skip_empty_text():
    from adk_core.services.persona_core.brief import _hooks_to_talking_points

    hooks = [
        {"label": "Bring", "text": ""},
        {"label": "Probe", "text": "Real topic"},
        {"label": "Probe"},  # missing text key
    ]
    points = _hooks_to_talking_points(hooks)
    assert len(points) == 1
    assert points[0]["topic"] == "Real topic"


def test_talking_points_empty_input():
    from adk_core.services.persona_core.brief import _hooks_to_talking_points

    assert _hooks_to_talking_points([]) == []
    assert _hooks_to_talking_points(None) == []


# ---------------------------------------------------------------------------
# Task 4 — previous_interactions[] with open_items[]
# ---------------------------------------------------------------------------


def test_previous_interactions_includes_open_items():
    """action_items[] from prior recaps must surface as open_items[]."""
    from adk_core.services.persona_core.brief import _prior_recaps_to_interactions

    prior = [
        {
            "meeting_id": "m1",
            "date": "2026-04-22",
            "title": "Q1 review",
            "summary": "Talked about Q2 plan",
            "action_items": ["Send Q2 doc by Friday", "Schedule legal review"],
        }
    ]
    out = _prior_recaps_to_interactions(prior)
    assert len(out) == 1
    assert out[0]["date"] == "2026-04-22"
    assert out[0]["meeting_title"] == "Q1 review"
    assert out[0]["summary"] == "Talked about Q2 plan"
    assert out[0]["open_items"] == ["Send Q2 doc by Friday", "Schedule legal review"]


def test_previous_interactions_string_action_items():
    """When action_items is a single string (legacy shape), wrap in a list."""
    from adk_core.services.persona_core.brief import _prior_recaps_to_interactions

    prior = [
        {
            "meeting_id": "m1",
            "date": "2026-04-22",
            "title": "Sync",
            "summary": "...",
            "action_items": "Send the doc",
        }
    ]
    out = _prior_recaps_to_interactions(prior)
    assert out[0]["open_items"] == ["Send the doc"]


def test_previous_interactions_missing_action_items():
    """No action_items field — should default to empty list."""
    from adk_core.services.persona_core.brief import _prior_recaps_to_interactions

    prior = [{"meeting_id": "m1", "date": "2026-04-22", "title": "x", "summary": "y"}]
    out = _prior_recaps_to_interactions(prior)
    assert out[0]["open_items"] == []


def test_previous_interactions_empty_input():
    from adk_core.services.persona_core.brief import _prior_recaps_to_interactions

    assert _prior_recaps_to_interactions([]) == []
    assert _prior_recaps_to_interactions(None) == []


# ---------------------------------------------------------------------------
# Task 5 — suggested_agenda[]
# ---------------------------------------------------------------------------


def test_suggested_agenda_orders_warmup_main_wrap():
    from adk_core.services.persona_core.brief import _generate_agenda

    agenda = _generate_agenda(
        your_goal="Close on Series A term sheet",
        talking_points=[
            {"topic": "Term sheet pricing", "rationale": "Bring"},
            {"topic": "Renewal date", "rationale": "Probe"},
        ],
        open_commitments=[{"description": "Send Q2 strategy doc", "days_open": 13}],
        prior_count=3,
    )
    # 1 warmup + 1 commitment status + 1 goal + 2 talking points + 1 wrap = 6
    assert 2 <= len(agenda) <= 6
    # Warm-up comes first when prior_count > 0
    assert "catch-up" in agenda[0].lower() or "since last" in agenda[0].lower()
    # Wrap is always last when there's any content
    assert "next" in agenda[-1].lower() or "wrap" in agenda[-1].lower()


def test_suggested_agenda_includes_commitments_before_goal():
    from adk_core.services.persona_core.brief import _generate_agenda

    agenda = _generate_agenda(
        your_goal="Discuss roadmap",
        talking_points=[],
        open_commitments=[{"description": "Send pricing memo", "days_open": 10}],
        prior_count=1,
    )
    # warm-up, commitment, goal, wrap
    commit_idx = next(i for i, a in enumerate(agenda) if "pricing memo" in a.lower())
    goal_idx = next(i for i, a in enumerate(agenda) if "roadmap" in a.lower())
    assert commit_idx < goal_idx


def test_suggested_agenda_empty_when_no_signals():
    from adk_core.services.persona_core.brief import _generate_agenda

    agenda = _generate_agenda(
        your_goal="",
        talking_points=[],
        open_commitments=[],
        prior_count=0,
    )
    assert agenda == []


def test_suggested_agenda_caps_at_six():
    from adk_core.services.persona_core.brief import _generate_agenda

    agenda = _generate_agenda(
        your_goal="Goal",
        talking_points=[{"topic": f"Topic {i}", "rationale": "Bring"} for i in range(10)],
        open_commitments=[{"description": f"Item {i}"} for i in range(5)],
        prior_count=2,
    )
    assert len(agenda) <= 6


def test_suggested_agenda_skips_duplicates():
    """If goal text matches a talking point topic, don't list it twice."""
    from adk_core.services.persona_core.brief import _generate_agenda

    agenda = _generate_agenda(
        your_goal="Pricing memo review",
        talking_points=[{"topic": "Pricing memo review", "rationale": "Bring"}],
        open_commitments=[],
        prior_count=0,
    )
    pricing_count = sum(1 for item in agenda if "pricing memo review" in item.lower())
    assert pricing_count == 1


# ---------------------------------------------------------------------------
# Task 6 — sources_used{}
# ---------------------------------------------------------------------------


def test_sources_used_counts_past_meetings(schema_v2_on):
    """sources_used.past_meetings reflects prior_meetings count."""
    from adk_core.services.persona_core.brief import _empty_brief_contract

    brief = _empty_brief_contract(meeting_id="m", title="t", start="2026-05-21")
    # Simulate the wiring generate_brief() does
    brief["prior_meetings"] = [{"meeting_id": "m1"}, {"meeting_id": "m2"}, {"meeting_id": "m3"}]
    brief["sources_used"]["past_meetings"] = len(brief["prior_meetings"])

    assert brief["sources_used"]["past_meetings"] == 3
    # kb_chunks + web_results stay 0 in W9a; W9d populates them via brief_agent
    assert brief["sources_used"]["kb_chunks"] == 0
    assert brief["sources_used"]["web_results"] == 0


def test_sources_used_defaults_zero_when_no_priors(schema_v2_on):
    from adk_core.services.persona_core.brief import _empty_brief_contract

    brief = _empty_brief_contract(meeting_id="m", title="t", start="2026-05-21")
    assert brief["sources_used"] == {
        "kb_chunks": 0,
        "web_results": 0,
        "past_meetings": 0,
    }
