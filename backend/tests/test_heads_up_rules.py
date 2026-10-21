"""W9b — Rule candidate generator unit tests (sync rules).

Async kb_private_hit lives in test_heads_up_rules_async.py to keep
fixture overhead minimal for these pure functions.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# rule_open_commitments
# ---------------------------------------------------------------------------

def test_open_commitment_above_threshold_emits():
    from adk_core.services.persona_core.heads_up_rules import (
        rule_open_commitments,
        OPEN_COMMITMENT_DAYS_THRESHOLD,
    )
    commitments = [{
        "description": "Send Q2 doc",
        "days_open": OPEN_COMMITMENT_DAYS_THRESHOLD + 6,
        "from_meeting_id": "m1",
    }]
    candidates = rule_open_commitments(commitments)
    assert len(candidates) == 1
    c = candidates[0]
    assert c["kind"] == "open_commitment"
    assert c["description"] == "Send Q2 doc"
    assert c["source_meeting_id"] == "m1"


def test_open_commitment_at_or_below_threshold_skipped():
    from adk_core.services.persona_core.heads_up_rules import (
        rule_open_commitments,
        OPEN_COMMITMENT_DAYS_THRESHOLD,
    )
    commitments = [
        {"description": "Recent ask", "days_open": OPEN_COMMITMENT_DAYS_THRESHOLD - 1, "from_meeting_id": "m1"},
        {"description": "Boundary", "days_open": OPEN_COMMITMENT_DAYS_THRESHOLD, "from_meeting_id": "m2"},
    ]
    candidates = rule_open_commitments(commitments)
    assert candidates == []


def test_open_commitment_skips_missing_description():
    from adk_core.services.persona_core.heads_up_rules import rule_open_commitments
    commitments = [
        {"description": "", "days_open": 30, "from_meeting_id": "m1"},
        {"description": "Real one", "days_open": 30, "from_meeting_id": "m2"},
    ]
    candidates = rule_open_commitments(commitments)
    assert len(candidates) == 1
    assert candidates[0]["description"] == "Real one"


def test_open_commitment_empty_input():
    from adk_core.services.persona_core.heads_up_rules import rule_open_commitments
    assert rule_open_commitments(None) == []
    assert rule_open_commitments([]) == []


# ---------------------------------------------------------------------------
# rule_action_items_pending
# ---------------------------------------------------------------------------

def test_action_items_pending_from_previous_interactions():
    from adk_core.services.persona_core.heads_up_rules import rule_action_items_pending
    prior = [
        {
            "date": "2026-05-08",
            "meeting_title": "Q1 review",
            "open_items": ["Send legal review by May 15", "Schedule next sync"],
        }
    ]
    candidates = rule_action_items_pending(prior)
    assert len(candidates) == 2
    assert candidates[0]["kind"] == "action_item_pending"
    assert "legal review" in candidates[0]["description"]
    assert candidates[0]["from_meeting_title"] == "Q1 review"
    assert candidates[0]["from_meeting_date"] == "2026-05-08"


def test_action_items_pending_skips_empty_items():
    from adk_core.services.persona_core.heads_up_rules import rule_action_items_pending
    prior = [
        {"date": "x", "meeting_title": "y", "open_items": ["", "  ", "real one"]},
    ]
    candidates = rule_action_items_pending(prior)
    assert len(candidates) == 1
    assert candidates[0]["description"] == "real one"


def test_action_items_pending_empty_input():
    from adk_core.services.persona_core.heads_up_rules import rule_action_items_pending
    assert rule_action_items_pending(None) == []
    assert rule_action_items_pending([]) == []
    assert rule_action_items_pending([{"date": "x", "meeting_title": "y"}]) == []


# ---------------------------------------------------------------------------
# rule_agenda_signal
# ---------------------------------------------------------------------------

def test_agenda_signal_only_when_organizer_is_other():
    from adk_core.services.persona_core.heads_up_rules import rule_agenda_signal
    candidates = rule_agenda_signal(
        organizer_email="other@host.com",
        self_email="me@self.com",
        prior_interactions=[{"date": "2026-05-01", "meeting_title": "Roadmap chat"}],
    )
    assert len(candidates) == 1
    c = candidates[0]
    assert c["kind"] == "agenda_signal_other_organizer"
    assert c["organizer_email"] == "other@host.com"
    assert c["prior_topic"] == "Roadmap chat"


def test_agenda_signal_skipped_when_self_organized():
    from adk_core.services.persona_core.heads_up_rules import rule_agenda_signal
    candidates = rule_agenda_signal(
        organizer_email="me@self.com",
        self_email="me@self.com",
        prior_interactions=[{"date": "2026-05-01", "meeting_title": "x"}],
    )
    assert candidates == []


def test_agenda_signal_case_insensitive_email_match():
    from adk_core.services.persona_core.heads_up_rules import rule_agenda_signal
    candidates = rule_agenda_signal(
        organizer_email="ME@Self.com",
        self_email="me@self.COM",
        prior_interactions=[{"date": "x", "meeting_title": "y"}],
    )
    assert candidates == []  # case-insensitive match → same person


def test_agenda_signal_empty_when_no_prior_history():
    from adk_core.services.persona_core.heads_up_rules import rule_agenda_signal
    candidates = rule_agenda_signal(
        organizer_email="other@x.com",
        self_email="me@x.com",
        prior_interactions=[],
    )
    assert candidates == []


def test_agenda_signal_empty_when_emails_missing():
    from adk_core.services.persona_core.heads_up_rules import rule_agenda_signal
    candidates = rule_agenda_signal(
        organizer_email=None,
        self_email=None,
        prior_interactions=[{"date": "x", "meeting_title": "y"}],
    )
    assert candidates == []


# ---------------------------------------------------------------------------
# rule_pdl_change
# ---------------------------------------------------------------------------

def test_pdl_change_emits_when_company_differs():
    from adk_core.services.persona_core.heads_up_rules import rule_pdl_change
    candidates = rule_pdl_change(
        attendee="Sarah Chen",
        current={"company": "Beta", "role": "CRO"},
        previous={"company": "Acme", "role": "VP Sales"},
        last_met="2026-01-15",
    )
    assert len(candidates) == 1
    c = candidates[0]
    assert c["kind"] == "pdl_change"
    assert c["old_value"]["company"] == "Acme"
    assert c["new_value"]["company"] == "Beta"
    assert c["last_met"] == "2026-01-15"


def test_pdl_change_emits_when_role_differs_same_company():
    from adk_core.services.persona_core.heads_up_rules import rule_pdl_change
    candidates = rule_pdl_change(
        attendee="Sarah",
        current={"company": "Acme", "role": "Director"},
        previous={"company": "Acme", "role": "Senior Director"},
        last_met=None,
    )
    assert len(candidates) == 1


def test_pdl_change_empty_when_no_baseline():
    """Cold-start exclusion — first encounter has no prev_snapshot."""
    from adk_core.services.persona_core.heads_up_rules import rule_pdl_change
    candidates = rule_pdl_change(
        attendee="Sarah",
        current={"company": "Beta", "role": "CRO"},
        previous=None,
        last_met=None,
    )
    assert candidates == []


def test_pdl_change_empty_when_no_change():
    from adk_core.services.persona_core.heads_up_rules import rule_pdl_change
    candidates = rule_pdl_change(
        attendee="Sarah",
        current={"company": "Acme", "role": "VP"},
        previous={"company": "Acme", "role": "VP"},
        last_met="2026-01-15",
    )
    assert candidates == []


def test_pdl_change_case_insensitive_company_match():
    """Whitespace/case differences should NOT trigger a change."""
    from adk_core.services.persona_core.heads_up_rules import rule_pdl_change
    candidates = rule_pdl_change(
        attendee="Sarah",
        current={"company": "  ACME  ", "role": "VP"},
        previous={"company": "acme", "role": "vp"},
        last_met=None,
    )
    assert candidates == []
