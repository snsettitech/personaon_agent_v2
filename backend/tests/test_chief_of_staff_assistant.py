"""Tests for the chief-of-staff Home assistant (surface_class='assistant').

The assistant is a distinct agent from the persona-embodiment chat: it speaks TO
the owner about their persona (improve/respond) and must NOT roleplay as them.
"""
from __future__ import annotations

from adk_core.services.agent_service import _surface_class
from adk_core.services.prompts import generate_system_prompt

PROFILE = {"name": "Sainath Setti", "occupation": "CEO at PersonaOn"}


def test_surface_class_maps_assistant() -> None:
    assert _surface_class("assistant") == "assistant"
    # existing surfaces unchanged
    assert _surface_class("owner") == "owner"
    assert _surface_class("widget") == "visitor"


def test_assistant_prompt_is_chief_of_staff_not_persona() -> None:
    prompt = generate_system_prompt(PROFILE, surface_class="assistant")
    # It is the chief of staff, addressing the owner...
    assert "CHIEF OF STAFF" in prompt
    assert "You are NOT the persona" in prompt or "NOT the persona" in prompt
    # ...and must NOT carry the persona-embodiment instruction.
    assert "roleplaying as the person" not in prompt
    assert "Embody the Persona" not in prompt


def test_assistant_prompt_is_improve_first_and_can_respond() -> None:
    prompt = generate_system_prompt(PROFILE, surface_class="assistant")
    # Improve is the #1 job: search then capture.
    assert "capture_knowledge" in prompt
    assert "search_knowledge_base" in prompt
    # Respond is in the toolkit but never auto-sends.
    assert "create_followup_draft" in prompt
    assert "NEVER sent automatically" in prompt or "never sent" in prompt.lower()
    # The persona's profile is included so it can find gaps.
    assert "Sainath Setti" in prompt


def test_owner_and_visitor_prompts_still_embody_persona() -> None:
    """Regression: the existing surfaces keep the embodiment template."""
    for sc in ("owner", "visitor"):
        prompt = generate_system_prompt(PROFILE, surface_class=sc)
        assert "roleplaying as the person" in prompt
        assert "CHIEF OF STAFF" not in prompt


def test_assistant_prompt_forbids_tech_recital_and_hallucination() -> None:
    """The chief-of-staff must never recite the tech stack or invent — this is the
    fix for the 'we use RAG and vector databases' answer."""
    prompt = generate_system_prompt(PROFILE, surface_class="assistant")
    lower = prompt.lower()
    assert "never invent" in lower
    assert "vector databases" in lower  # named in the forbidding rule
    assert "rag" in lower  # forbidden term is explicitly listed
    assert "how does it work" in lower  # explicit handling guidance present


def test_public_persona_prompt_forbids_tech_talk() -> None:
    """A public-facing persona must never expose AI/RAG/architecture to visitors."""
    for sc in ("visitor", "owner"):
        prompt = generate_system_prompt(PROFILE, surface_class=sc)
        lower = prompt.lower()
        assert "never describe how you technically work" in lower
        assert "vector databases" in lower


def test_assistant_first_message_only_names_shipped_editable_fields() -> None:
    """Execution board 0.11: the first-chat-message guidance must only promise the
    6 fields update_persona can actually write today, and must explicitly forbid
    mentioning theme/sections/blog/handle in that opening message — those tools
    don't exist yet."""
    prompt = generate_system_prompt(PROFILE, surface_class="assistant")
    lower = prompt.lower()
    assert "first message to a brand-new owner" in lower
    for field in (
        "headline",
        "role",
        "organization",
        "occupation",
        "bio",
        "short_description",
    ):
        assert field in lower
    # explicit anti-over-promise instruction for the opening message
    assert "never mention theme, layout, sections" in lower
    assert "blog" in lower
