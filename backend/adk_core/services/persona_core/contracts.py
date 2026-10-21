"""RecapContract and related dataclasses for post-meeting recaps.

These types define the structured shape produced by the recap engine. They
are immutable (frozen) per the PersonaOn immutability rule (CLAUDE.md): the
recap is a snapshot of one meeting and must not be mutated in-place.

The `my_positions[]` field on RecapContract is structurally important: it
lets the correction router distinguish position-edits (the user changed
their mind about something) from fact-edits (a recorded detail was wrong).
Position edits route to `person_claims` with `tense_status='present'` and
supersede the prior matching claim.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionItem:
    owner: str
    description: str
    due: str | None


@dataclass(frozen=True)
class Commitment:
    """A commitment made during the meeting.

    `by` is the committing party (who is on the hook); `to` is the
    recipient/beneficiary (who the commitment is owed to).
    """

    by: str
    to: str
    what: str
    due: str | None


@dataclass(frozen=True)
class IntentVsOutcome:
    intent: str
    outcome: str


@dataclass(frozen=True)
class Position:
    """A first-person position/opinion/preference the user stated.

    Distinct from a fact: facts are what happened; positions are what the user
    thinks. Position edits route to person_claims with tense_status='present'
    and supersede prior positions on the same subject.
    """

    subject: str
    stance: str
    supersedes: str | None  # claim_id of prior position superseded by this one


@dataclass(frozen=True)
class RecapContract:
    recap: str
    intent_vs_outcome: IntentVsOutcome
    action_items: list[ActionItem]
    commitments: list[Commitment]
    decisions: list[str]
    topics: list[str]
    unanswered_questions: list[str]
    people_observed: list[dict[str, str]]
    my_positions: list[Position]
    style_sample: str
    twin_id: str
