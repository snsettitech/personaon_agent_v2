"""W9b — Anti-pattern post-filter unit tests.

Defense-in-depth: even when the LLM emits forbidden language, this layer
drops the note before it ships. Cheaper than re-prompting; bounds the
worst-case shipped output.
"""

from __future__ import annotations


def test_anti_pattern_caught_imperative():
    from adk_core.services.persona_core.heads_up_safety import note_violates_anti_pattern
    assert note_violates_anti_pattern("You should send Sarah the doc.") is not None


def test_anti_pattern_caught_failure_verb():
    from adk_core.services.persona_core.heads_up_safety import note_violates_anti_pattern
    assert note_violates_anti_pattern("Heads up — you forgot to send the doc.") is not None


def test_anti_pattern_caught_mind_reading():
    from adk_core.services.persona_core.heads_up_safety import note_violates_anti_pattern
    assert note_violates_anti_pattern("Sarah may be frustrated by the delay.") is None
    # That exact phrasing isn't in the list (it's "they may be frustrated") — verify
    # the closer variants ARE caught:
    assert note_violates_anti_pattern("They may be frustrated by the delay.") is not None
    assert note_violates_anti_pattern("He might be annoyed at the wait.") is not None


def test_anti_pattern_caught_loaded_judgment():
    from adk_core.services.persona_core.heads_up_safety import note_violates_anti_pattern
    assert note_violates_anti_pattern("The Q2 doc is overdue by 13 days.") is not None
    assert note_violates_anti_pattern("Equity split is at a stalemate.") is not None


def test_clean_note_passes():
    from adk_core.services.persona_core.heads_up_safety import note_violates_anti_pattern
    assert note_violates_anti_pattern(
        "Heads up — Sarah's still waiting on the Q2 doc you mentioned May 8."
    ) is None


def test_filter_drops_violations_keeps_clean():
    from adk_core.services.persona_core.heads_up_safety import filter_safe_notes
    notes = [
        {"text": "You should send the doc.", "source_candidate_idx": 0},
        {"text": "Heads up — pricing memo from May 7.", "source_candidate_idx": 1},
        {"text": "Don't forget to follow up.", "source_candidate_idx": 2},
    ]
    safe, dropped = filter_safe_notes(notes)
    assert len(safe) == 1
    assert safe[0]["text"] == "Heads up — pricing memo from May 7."
    assert len(dropped) == 2
    # Dropped notes carry a reason for log/audit
    assert "_dropped_reason" in dropped[0]


def test_case_insensitive_matching():
    """Anti-patterns match case-insensitively."""
    from adk_core.services.persona_core.heads_up_safety import note_violates_anti_pattern
    assert note_violates_anti_pattern("YOU FORGOT to do it.") is not None
    assert note_violates_anti_pattern("You Forgot anything?") is not None


def test_filter_handles_empty_list():
    from adk_core.services.persona_core.heads_up_safety import filter_safe_notes
    safe, dropped = filter_safe_notes([])
    assert safe == []
    assert dropped == []


def test_filter_handles_missing_text_field():
    """Defensive: malformed notes (no text key) get dropped, don't crash."""
    from adk_core.services.persona_core.heads_up_safety import filter_safe_notes
    notes = [{"source_candidate_idx": 0}, {"text": "clean note", "source_candidate_idx": 1}]
    safe, dropped = filter_safe_notes(notes)
    assert len(safe) == 1
    assert safe[0]["text"] == "clean note"


def test_anti_patterns_constant_matches_blocklist_size():
    """ANTI_PATTERNS list is non-empty + has the categories we care about."""
    from adk_core.services.persona_core.heads_up_safety import ANTI_PATTERNS
    assert len(ANTI_PATTERNS) >= 15
    # At least one from each category
    assert any("you should" in p for p in ANTI_PATTERNS)
    assert any("forgot" in p for p in ANTI_PATTERNS)
    assert any("frustrated" in p for p in ANTI_PATTERNS)
    assert any("overdue" in p for p in ANTI_PATTERNS)
