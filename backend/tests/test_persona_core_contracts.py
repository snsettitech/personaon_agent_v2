"""Tests for the RecapContract type and related dataclasses.

These contracts define the post-meeting recap shape. They must be frozen
(immutable) per CLAUDE.md, and RecapContract must carry all 11 fields including
`my_positions[]` so the correction router can route position-edits deterministically.
"""

from dataclasses import FrozenInstanceError

import pytest

from adk_core.services.persona_core.contracts import (
    ActionItem,
    Commitment,
    IntentVsOutcome,
    Position,
    RecapContract,
)


def test_recap_contract_has_all_eleven_fields():
    r = RecapContract(
        recap="Brief narrative of what happened.",
        intent_vs_outcome=IntentVsOutcome(
            intent="Discuss pricing.", outcome="Agreed on tier 2."
        ),
        action_items=[ActionItem(owner="me", description="Send proposal", due=None)],
        commitments=[Commitment(by="me", to="Alex", what="Send proposal", due=None)],
        decisions=["Move to tier 2 pricing"],
        topics=["pricing", "timeline"],
        unanswered_questions=["What's their security review process?"],
        people_observed=[{"name": "Alex Chen", "role_hint": "VP Sales"}],
        my_positions=[
            Position(
                subject="enterprise tier pricing",
                stance="comfortable with $50k/yr floor",
                supersedes=None,
            ),
        ],
        style_sample="I usually open with a casual 'so what brings you to this?'",
        twin_id="twin_123",
    )
    assert r.my_positions[0].subject == "enterprise tier pricing"


def test_recap_contract_is_frozen():
    r = RecapContract(
        recap="r",
        intent_vs_outcome=IntentVsOutcome(intent="", outcome=""),
        action_items=[],
        commitments=[],
        decisions=[],
        topics=[],
        unanswered_questions=[],
        people_observed=[],
        my_positions=[],
        style_sample="s",
        twin_id="twin_123",
    )
    with pytest.raises(FrozenInstanceError):
        r.recap = "mutated"  # type: ignore[misc]  # intentional mutation of frozen dataclass to assert FrozenInstanceError


def test_position_is_frozen():
    p = Position(subject="pricing", stance="firm at $50k", supersedes=None)
    with pytest.raises(FrozenInstanceError):
        p.stance = "flexible"  # type: ignore[misc]  # intentional mutation of frozen dataclass to assert FrozenInstanceError


def test_action_item_and_commitment_are_frozen():
    a = ActionItem(owner="me", description="d", due=None)
    c = Commitment(by="me", to="Alex", what="w", due=None)
    with pytest.raises(FrozenInstanceError):
        a.owner = "them"  # type: ignore[misc]  # intentional mutation of frozen dataclass to assert FrozenInstanceError
    with pytest.raises(FrozenInstanceError):
        c.to = "Bob"  # type: ignore[misc]  # intentional mutation of frozen dataclass to assert FrozenInstanceError
