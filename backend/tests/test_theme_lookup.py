"""Execution-board 0.3: keyword→theme lookup used at twin-creation time.

Verification scenario (plans/personaon-execution-board.md, 0.3): three fresh
signups with headlines "Software Engineer," "Marketing Consultant," and
"Founder & CEO" must each land on a different, role-appropriate, non-Classic
theme; an unmatched headline must fall back to a non-Classic default.
"""

from __future__ import annotations

from modules.theme_lookup import (
    DEFAULT_FALLBACK_THEME_ID,
    infer_default_theme_id,
)


def test_software_engineer_maps_to_technical_shell():
    assert infer_default_theme_id("Software Engineer") == "site"


def test_marketing_consultant_maps_to_business_shell():
    assert infer_default_theme_id("Marketing Consultant") == "conversion-warm"


def test_founder_and_ceo_maps_to_founder_shell():
    assert infer_default_theme_id("Founder & CEO") == "founder-site"


def test_no_keyword_match_falls_back_to_non_classic_default():
    result = infer_default_theme_id("Professional Juggler")
    assert result == DEFAULT_FALLBACK_THEME_ID
    assert result != "classic"


def test_empty_input_falls_back_to_non_classic_default():
    result = infer_default_theme_id(None)
    assert result == DEFAULT_FALLBACK_THEME_ID
    assert result != "classic"


def test_the_three_verification_headlines_land_on_three_different_themes():
    # Task 0.3's "Expected" clause: each of the 3 test headlines must land on
    # a DIFFERENT theme (not all funneled to one fallback).
    results = {
        infer_default_theme_id("Software Engineer"),
        infer_default_theme_id("Marketing Consultant"),
        infer_default_theme_id("Founder & CEO"),
    }
    assert len(results) == 3
    assert "classic" not in results


def test_context_is_considered_when_headline_is_absent():
    assert infer_default_theme_id(None, context="Freelance UX Designer") == "split"


def test_headline_keyword_match_is_whole_word_not_substring():
    # "ceo" must not falsely match as a substring inside an unrelated word
    # (e.g. "danceoff"). Without a word-boundary match this would incorrectly
    # resolve to "founder-site"; the correct behavior is the generic fallback.
    assert infer_default_theme_id("Danceoff Enthusiast") == DEFAULT_FALLBACK_THEME_ID
    assert infer_default_theme_id("Danceoff Enthusiast") != "founder-site"


def test_earliest_mentioned_role_wins_over_fixed_group_priority():
    # "photographer" (split) is the headline's primary, first-mentioned
    # identity; "consultant" (conversion-warm) is secondary. A fixed
    # group-priority scan would incorrectly return conversion-warm here
    # because that group is checked before split, regardless of position.
    result = infer_default_theme_id("Freelance photographer and part-time consultant")
    assert result == "split"
    assert result != "conversion-warm"


def test_earliest_mentioned_role_wins_technical_over_advisory():
    result = infer_default_theme_id("Software engineer and startup advisor")
    assert result == "site"
    assert result != "conversion-warm"


def test_turned_marker_prefers_current_role_over_former_role():
    # "CEO turned software developer": the person's CURRENT profession is
    # software developer, not CEO. The word "turned" marks everything before
    # it as a past identity that should not win just for appearing first.
    result = infer_default_theme_id("CEO turned software developer")
    assert result == "site"
    assert result != "founder-site"


def test_former_role_marker_is_demoted():
    result = infer_default_theme_id("Former CEO, now full-time photographer")
    assert result == "split"
    assert result != "founder-site"
