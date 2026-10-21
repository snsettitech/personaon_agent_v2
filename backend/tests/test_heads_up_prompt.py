"""W9b — Heads Up LLM rewriter prompt + schema unit tests."""

from __future__ import annotations


def test_system_prompt_contains_six_principles():
    """All 6 design principles are named in the prompt so the LLM has the contract."""
    from adk_core.services.persona_core.heads_up_prompt import SYSTEM_PROMPT
    text = SYSTEM_PROMPT.lower()
    assert "observable fact" in text or "observable" in text
    assert "first-person" in text or "first person" in text
    assert "cite" in text
    assert "worth knowing" in text
    assert "stop" in text
    assert "sbi" in text or "impact" in text


def test_system_prompt_lists_anti_patterns():
    """Anti-pattern blocklist phrases appear in the prompt."""
    from adk_core.services.persona_core.heads_up_prompt import SYSTEM_PROMPT
    text = SYSTEM_PROMPT.lower()
    assert "you should" in text
    assert "you forgot" in text or "you missed" in text


def test_system_prompt_names_restraint_cases():
    """LLM is told to emit empty for the 4 out-of-scope candidate kinds."""
    from adk_core.services.persona_core.heads_up_prompt import SYSTEM_PROMPT
    text = SYSTEM_PROMPT
    assert "persona_mismatch" in text
    assert "kb_public_bio" in text
    assert "title_correction" in text
    assert "user_self_critique" in text


def test_output_schema_requires_source_candidate_idx():
    """Citation pivot: LLM emits int idx; we synthesize ref/quote post-call."""
    from adk_core.services.persona_core.heads_up_prompt import OUTPUT_SCHEMA
    props = OUTPUT_SCHEMA["properties"]["caution_notes"]["items"]["properties"]
    assert "text" in props
    assert "source_candidate_idx" in props
    assert props["source_candidate_idx"]["type"] == "integer"


def test_user_prompt_formats_candidates_with_indices():
    """User prompt enumerates candidates [0], [1], ... so LLM can pick by idx."""
    from adk_core.services.persona_core.heads_up_prompt import build_user_prompt
    candidates = [
        {"kind": "open_commitment", "attendee": "Sarah", "description": "send doc"},
        {"kind": "kb_private_hit", "attendee": "Marcus", "topic": "pricing"},
    ]
    prompt = build_user_prompt(candidates=candidates, meeting_title="Sync")
    assert "[0]" in prompt and "[1]" in prompt
    assert "Sarah" in prompt and "Marcus" in prompt


def test_user_prompt_empty_candidates_returns_empty_marker():
    from adk_core.services.persona_core.heads_up_prompt import build_user_prompt
    prompt = build_user_prompt(candidates=[], meeting_title="Sync")
    lower = prompt.lower()
    assert "no candidate" in lower or "empty" in lower


def test_user_prompt_includes_meeting_title():
    from adk_core.services.persona_core.heads_up_prompt import build_user_prompt
    prompt = build_user_prompt(
        candidates=[{"kind": "open_commitment", "description": "x"}],
        meeting_title="Investor pitch",
    )
    assert "Investor pitch" in prompt


def test_user_prompt_includes_structured_fields():
    """For each candidate, the structured fields (days_open, source_meeting_id)
    are passed through so the LLM has the full signal."""
    from adk_core.services.persona_core.heads_up_prompt import build_user_prompt
    prompt = build_user_prompt(
        candidates=[{
            "kind": "open_commitment",
            "attendee": "Sarah",
            "description": "send doc",
            "days_open": 13,
            "source_meeting_id": "meet_abc",
        }],
        meeting_title="Sync",
    )
    assert "13" in prompt
    assert "meet_abc" in prompt
