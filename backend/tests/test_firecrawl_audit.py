"""Unit tests for the deterministic work_experience audit.

These tests exercise ``audit_work_experience`` only — a pure, no-I/O function.
No network, no Supabase, no Firecrawl calls. The guarded LLM repair path
(``_repair_work_experience``) hits the live model and is exercised only in prod.
"""

from datetime import datetime, timezone

from adk_core.services.firecrawl_service import audit_work_experience


def _issue_prefixes(issues: list[str]) -> list[str]:
    return [i.split(":", 1)[0] for i in issues]


def test_collapsed_microsoft_flags_single_year_and_understated() -> None:
    """The real failure: 6-7y Microsoft tenure collapsed to one 2023-2023 role."""
    profile = {
        "bio": "Brings 6+ years of enterprise cloud and AI experience at Microsoft to the team.",
        "work_experience": [
            {
                "company": "Microsoft",
                "role": "Senior Escalation Engineer",
                "start_year": 2023,
                "end_year": 2023,
            }
        ],
    }
    issues = audit_work_experience(profile)
    prefixes = _issue_prefixes(issues)
    assert "single_year_span" in prefixes
    assert "understated_tenure" in prefixes
    # Sanity: the understated message names Microsoft.
    assert any("Microsoft" in i for i in issues if i.startswith("understated_tenure"))


def test_correct_multi_role_microsoft_no_understated() -> None:
    """A correctly granular 3-role Microsoft history must NOT flag understated_tenure."""
    profile = {
        "bio": "6+ years at Microsoft across multiple engineering roles.",
        "work_experience": [
            {"company": "Microsoft", "role": "Support Engineer", "start_year": 2018, "end_year": 2020},
            {"company": "Microsoft", "role": "Escalation Engineer", "start_year": 2021, "end_year": 2022},
            {"company": "Microsoft", "role": "Senior Escalation Engineer", "start_year": 2023, "end_year": 2023},
        ],
    }
    issues = audit_work_experience(profile)
    prefixes = _issue_prefixes(issues)
    # Span is 2018->2023 = 5; actual + 1 (6) is NOT < claimed (6), so no understatement.
    assert "understated_tenure" not in prefixes
    # The 2023-2023 entry MAY still trip single_year_span — that's acceptable.


def test_date_inverted_flagged() -> None:
    profile = {
        "work_experience": [
            {"company": "Acme", "role": "Engineer", "start_year": 2020, "end_year": 2018},
        ],
    }
    issues = audit_work_experience(profile)
    assert "date_inverted" in _issue_prefixes(issues)


def test_clean_profile_returns_empty() -> None:
    """Good dates and no contradicting bio claim → no issues."""
    profile = {
        "bio": "A software engineer who has worked across several companies.",
        "short_description": "Engineer and builder.",
        "occupation": "Software Engineer",
        "work_experience": [
            {"company": "Acme", "role": "Engineer", "start_year": 2015, "end_year": 2019},
            {"company": "Globex", "role": "Senior Engineer", "start_year": 2019, "end_year": 2023},
        ],
    }
    assert audit_work_experience(profile) == []


def test_missing_work_experience() -> None:
    assert audit_work_experience({"bio": "Some bio"}) == []


def test_empty_work_experience_list() -> None:
    assert audit_work_experience({"work_experience": []}) == []


def test_none_years_do_not_crash() -> None:
    profile = {
        "work_experience": [
            {"company": "Acme", "role": "Engineer", "start_year": None, "end_year": None},
            {"company": "Globex", "role": "Lead", "start_year": 2020, "end_year": None},
        ],
    }
    # No bio claim, no inverted/single-year dates → clean, and definitely no crash.
    assert audit_work_experience(profile) == []


def test_non_dict_entries_ignored() -> None:
    profile = {
        "work_experience": [
            "not a dict",
            None,
            42,
            {"company": "Acme", "role": "Engineer", "start_year": 2018, "end_year": 2022},
        ],
    }
    # The single valid entry is fine; junk entries are skipped without error.
    assert audit_work_experience(profile) == []


def test_non_dict_profile_returns_empty() -> None:
    assert audit_work_experience("not a profile") == []  # type: ignore[arg-type]
    assert audit_work_experience(None) == []  # type: ignore[arg-type]


def test_string_years_are_ignored_not_coerced() -> None:
    """String years must not be coerced into the span math (only genuine ints count)."""
    profile = {
        "bio": "10 years at Acme.",
        "work_experience": [
            # str years -> not counted; no aggregate span -> no understated flag, no crash
            {"company": "Acme", "role": "Engineer", "start_year": "2015", "end_year": "2016"},
        ],
    }
    assert audit_work_experience(profile) == []


def test_ongoing_role_uses_current_year_for_span() -> None:
    """A role with a missing end_year is treated as ongoing (ends 'now')."""
    now_year = datetime.now(timezone.utc).year
    start = now_year - 8
    profile = {
        "bio": "7+ years at Acme building things.",
        "work_experience": [
            {"company": "Acme", "role": "Engineer", "start_year": start, "end_year": None},
        ],
    }
    # actual span ~= 8 years (now - start); claim is 7 -> actual+1 (9) not < 7 -> no understatement.
    assert "understated_tenure" not in _issue_prefixes(audit_work_experience(profile))


def test_understated_tenure_case_insensitive_company_match() -> None:
    """Company match in bio is case-insensitive."""
    profile = {
        "short_description": "8 years at microsoft.",
        "work_experience": [
            {"company": "Microsoft", "role": "Engineer", "start_year": 2022, "end_year": 2023},
        ],
    }
    assert "understated_tenure" in _issue_prefixes(audit_work_experience(profile))


def test_understated_tenure_binds_to_nearest_company_not_far_one() -> None:
    """Regression: a years-claim must bind to the NEAREST company only.

    Real false positive: bio "...6+ years of enterprise cloud and AI experience
    at Microsoft, now building PersonaOn" caused understated_tenure to fire for
    PersonaOn because the proximity window happened to span both companies. The
    "6 years" sits right next to Microsoft and far from PersonaOn, so only
    Microsoft may be credited with the 6-year claim.
    """
    profile = {
        "bio": (
            "Sai brings 6+ years of enterprise cloud and AI experience at "
            "Microsoft, now building PersonaOn."
        ),
        "work_experience": [
            # Collapsed Microsoft tenure (single 2023-2023 role).
            {
                "company": "Microsoft",
                "role": "Senior Escalation Engineer",
                "start_year": 2023,
                "end_year": 2023,
            },
            # Current PersonaOn role — short, genuine, must NOT be flagged.
            {
                "company": "PersonaOn",
                "role": "Founder",
                "start_year": 2024,
                "end_year": None,
            },
        ],
    }
    issues = audit_work_experience(profile)

    understated = [i for i in issues if i.startswith("understated_tenure")]
    # Microsoft IS understated (6y claimed vs ~0y span) and must be flagged.
    assert any("Microsoft" in i for i in understated), (
        f"expected understated_tenure for Microsoft, got: {understated}"
    )
    # PersonaOn must NOT be flagged — the "6 years" belongs to Microsoft.
    assert not any("PersonaOn" in i for i in understated), (
        f"PersonaOn must NOT be flagged for understated_tenure, got: {understated}"
    )


def test_nearest_company_wins_when_two_companies_in_window() -> None:
    """When two companies fall in one window, only the closer one is credited."""
    profile = {
        # "8 years" hugs Globex; Acme is mentioned far earlier in the sentence.
        "short_description": (
            "Worked briefly at Acme before spending 8 years at Globex."
        ),
        "work_experience": [
            {"company": "Acme", "role": "Intern", "start_year": 2014, "end_year": 2015},
            {"company": "Globex", "role": "Engineer", "start_year": 2016, "end_year": 2017},
        ],
    }
    issues = audit_work_experience(profile)
    understated = [i for i in issues if i.startswith("understated_tenure")]
    # Globex (nearest to "8 years") is understated; Acme is not credited the claim.
    assert any("Globex" in i for i in understated)
    assert not any("Acme" in i for i in understated)


def test_date_inverted_with_bio_claim_does_not_understate() -> None:
    """Regression: an inverted-date role must not ALSO fire understated_tenure.

    With end < start the aggregate span is negative, so the old check
    ``actual + 1 < claimed`` was always true and double-fired understated_tenure
    on top of the legitimate date_inverted. The span guard suppresses the spurious flag.
    """
    profile = {
        "bio": "5+ years at Acme building things.",
        "work_experience": [
            {"company": "Acme", "role": "Engineer", "start_year": 2020, "end_year": 2018},
        ],
    }
    prefixes = _issue_prefixes(audit_work_experience(profile))
    assert "date_inverted" in prefixes
    assert "understated_tenure" not in prefixes


def test_bool_years_are_not_treated_as_integers() -> None:
    """bool is an int subclass; True/False must never be coerced into year math."""
    profile = {
        "bio": "8 years at Acme.",
        "work_experience": [
            {"company": "Acme", "role": "Engineer", "start_year": True, "end_year": False},
        ],
    }
    # No genuine int years -> no span -> no date_inverted/single_year_span/understated.
    assert audit_work_experience(profile) == []
