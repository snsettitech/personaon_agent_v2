"""Tests for services/name_match.py — shared name-variant matching utility."""
from __future__ import annotations


from services.name_match import is_name_variant


# ---------------------------------------------------------------------------
# Exact match
# ---------------------------------------------------------------------------

def test_exact_match_same_case():
    assert is_name_variant("Sainath", "Sainath") is True


def test_exact_match_different_case():
    assert is_name_variant("sainath", "SAINATH") is True


def test_no_match_completely_different():
    assert is_name_variant("Jordan", "Sainath") is False


# ---------------------------------------------------------------------------
# Multi-token overlap
# ---------------------------------------------------------------------------

def test_multi_token_first_name_matches_full_name():
    """'Sainath' vs 'Sainath Setti' — token overlap on first name."""
    assert is_name_variant("Sainath", "Sainath Setti") is True


def test_multi_token_last_name_matches_full_name():
    """'Setti' vs 'Sainath Setti' — token overlap on last name."""
    assert is_name_variant("Setti", "Sainath Setti") is True


def test_multi_token_full_name_vs_full_name():
    assert is_name_variant("Sainath Setti", "Sainath Setti") is True


def test_multi_token_no_overlap():
    assert is_name_variant("Jordan Reyes", "Sainath Setti") is False


# ---------------------------------------------------------------------------
# Nickname / prefix matching
# ---------------------------------------------------------------------------

def test_nickname_prefix_short_candidate():
    """'Sai' (3 chars) is a prefix of 'sainath' → match."""
    assert is_name_variant("Sai", "Sainath") is True


def test_nickname_prefix_4_chars():
    """'Sain' (4 chars) is a prefix of 'sainath' → match."""
    assert is_name_variant("Sain", "Sainath") is True


def test_nickname_prefix_boundary_5_chars_no_match():
    """'Sainx' (5 chars) should NOT match via prefix rule — only <=4 chars trigger it."""
    assert is_name_variant("Sainx", "Sainath") is False


def test_nickname_reverse_short_reference():
    """Short reference 'Sai' is prefix of candidate token 'Sainath' → match."""
    assert is_name_variant("Sainath", "Sai") is True


def test_nickname_prefix_exact_token_no_false_match():
    """Candidate equals reference token exactly — prefix check must NOT fire
    ('sai' == 'sai', startswith checks `tok != cand_lc`)."""
    # Both sides the same — covered by exact-match rule
    assert is_name_variant("Sai", "Sai") is True


# ---------------------------------------------------------------------------
# Edge cases — empty / whitespace
# ---------------------------------------------------------------------------

def test_none_candidate_returns_false():
    assert is_name_variant(None, "Sainath") is False


def test_none_reference_returns_false():
    assert is_name_variant("Sainath", None) is False


def test_both_none_returns_false():
    assert is_name_variant(None, None) is False


def test_whitespace_only_candidate_returns_false():
    assert is_name_variant("   ", "Sainath") is False


def test_whitespace_only_reference_returns_false():
    assert is_name_variant("Sainath", "   ") is False


def test_empty_string_candidate_returns_false():
    assert is_name_variant("", "Sainath") is False


# ---------------------------------------------------------------------------
# Unicode / non-Latin
# ---------------------------------------------------------------------------

def test_non_latin_vs_latin_no_match():
    """A non-Latin name vs a Latin owner — no shared tokens, no prefix → False."""
    assert is_name_variant("李明", "Sainath") is False


def test_non_latin_vs_same_non_latin_exact_match():
    assert is_name_variant("李明", "李明") is True


# ---------------------------------------------------------------------------
# Assignee-role-specific regression cases (BUG-B)
# ---------------------------------------------------------------------------

def test_owner_full_name_assignee_first_name():
    """Owner 'Sainath Setti', assignee 'Sainath' → you."""
    assert is_name_variant("Sainath", "Sainath Setti") is True


def test_owner_full_name_assignee_last_name():
    """Owner 'Sainath Setti', assignee 'Setti' → you (token match)."""
    assert is_name_variant("Setti", "Sainath Setti") is True


def test_owner_full_name_assignee_nickname():
    """Owner 'Sainath Setti', assignee 'Sai' → you (prefix rule)."""
    assert is_name_variant("Sai", "Sainath Setti") is True


def test_owner_full_name_assignee_full_match():
    """Owner 'Sainath Setti', assignee 'Sainath Setti' → you (exact)."""
    assert is_name_variant("Sainath Setti", "Sainath Setti") is True


def test_conflict_both_named_alex():
    """Both owner and contact named 'Alex' — this util just sees two equal names.
    The endpoint handles the conflict; the util itself returns True for exact match."""
    assert is_name_variant("Alex", "Alex") is True
