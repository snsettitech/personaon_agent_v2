"""C1 security: the anonymous public profile response must not leak the raw
scraped dossier / PII fields. redact_public_profile_pack_for_public_response()
starts from the full pack, so anything sensitive that isn't explicitly emptied
would pass through — these tests pin the default-deny behavior.

Portfolio update (2026-06): work_experience and education are deliberately
PUBLIC — they are the core of the portfolio page. They are emitted as
sub-field-whitelisted entries gated by section_visibility; the raw dossier
alias (employment_history) and true PII remain hard-denied.
"""

from modules.public_profile_pack import (
    _PUBLIC_PII_DENYLIST,
    redact_public_profile_pack_for_public_response,
)


def test_redaction_keeps_safe_fields_and_strips_pii():
    pack = {
        "name": "Avery Stone",
        "headline": "Founder, PersonaOn",
        "bio": "Public bio visitors should see.",
        "avatar_url": "https://example.com/a.png",
        "areas_of_expertise": ["AI"],
        "pinned_questions": ["What is PersonaOn?"],
        # portfolio sections — curated entries MUST survive redaction
        "work_experience": [{"company": "Acme", "role": "VP", "description": "Led org"}],
        "education": [{"institution": "MIT", "degree": "MS", "field": "CS"}],
        # sensitive — must NOT appear in the public response
        "birth_year": 1990,
        "nationality": "Canadian",
        "employment_history": [{"company": "Raw dossier Inc"}],
        "speaking_style": "casual",
        "public_response_seeds": [{"q": "x", "a": "a private prepared answer"}],
        "persona_profile": {"raw": "full scraped dossier"},
        "email": "avery@example.com",
        "phone": "555-1234",
    }

    out = redact_public_profile_pack_for_public_response(pack)

    # Curated, visitor-safe fields are preserved.
    assert out["name"] == "Avery Stone"
    assert out["bio"] == "Public bio visitors should see."
    assert out["pinned_questions"] == ["What is PersonaOn?"]
    assert out["work_experience"] == [
        {"company": "Acme", "role": "VP", "description": "Led org"}
    ]
    assert out["education"] == [
        {"institution": "MIT", "degree": "MS", "field": "CS"}
    ]

    # Every named PII / dossier field is stripped.
    for field in (
        "birth_year",
        "nationality",
        "employment_history",
        "speaking_style",
        "public_response_seeds",
        "persona_profile",
        "email",
        "phone",
    ):
        assert field not in out, f"{field} leaked into the anonymous public response"


def test_redaction_output_has_no_denylisted_keys():
    # Even if every sensitive key is present, none survive redaction.
    pack = {key: "x" for key in _PUBLIC_PII_DENYLIST}
    pack["name"] = "Avery"
    out = redact_public_profile_pack_for_public_response(pack)
    assert _PUBLIC_PII_DENYLIST.isdisjoint(out.keys())


def test_structured_sections_whitelist_subfields():
    # Unknown keys inside work/education entries (enrichment leftovers,
    # internal ids, contact info) must not survive.
    pack = {
        "name": "Avery",
        "work_experience": [
            {
                "company": "Acme",
                "role": "VP",
                "manager_email": "boss@acme.com",
                "internal_id": "x-123",
                "salary": "$400k",
            },
            "not-a-dict-entry",
        ],
        "education": [
            {"institution": "MIT", "student_id": "9001"},
        ],
    }
    out = redact_public_profile_pack_for_public_response(pack)
    assert out["work_experience"] == [{"company": "Acme", "role": "VP"}]
    assert out["education"] == [{"institution": "MIT"}]


def test_structured_sections_respect_visibility_toggle():
    pack = {
        "name": "Avery",
        "work_experience": [{"company": "Acme"}],
        "education": [{"institution": "MIT"}],
    }
    settings = {
        "section_visibility": {"work_experience": False, "education": False}
    }
    out = redact_public_profile_pack_for_public_response(pack, settings)
    assert out["work_experience"] == []
    assert out["education"] == []


def test_redaction_emits_valid_theme_id():
    out = redact_public_profile_pack_for_public_response(
        {"name": "Avery"},
        {"public_profile": {"theme_id": "founder-site"}},
    )
    assert out["settings"]["theme_id"] == "founder-site"


def test_redaction_drops_unknown_theme_id():
    # Default-deny: anything not in ALLOWED_THEME_IDS must not pass through.
    out = redact_public_profile_pack_for_public_response(
        {"name": "Avery"},
        {"public_profile": {"theme_id": "totally-made-up"}},
    )
    assert out["settings"]["theme_id"] is None


def test_redaction_theme_id_absent_is_none():
    out = redact_public_profile_pack_for_public_response({"name": "Avery"}, {})
    assert out["settings"]["theme_id"] is None


def test_redaction_drops_non_string_theme_id():
    # A non-string stored value (corrupt/legacy row) must not pass through.
    out = redact_public_profile_pack_for_public_response(
        {"name": "Avery"},
        {"public_profile": {"theme_id": 42}},
    )
    assert out["settings"]["theme_id"] is None


def test_redaction_drops_empty_theme_id():
    out = redact_public_profile_pack_for_public_response(
        {"name": "Avery"},
        {"public_profile": {"theme_id": ""}},
    )
    assert out["settings"]["theme_id"] is None


def test_redaction_emits_new_layout_ids():
    for theme in ("editorial", "split", "site"):
        pack = redact_public_profile_pack_for_public_response(
            {"settings": {"public_profile": {"theme_id": theme}}},
            {"public_profile": {"theme_id": theme}},
        )
        assert pack["settings"]["theme_id"] == theme


def test_redaction_emits_valid_accent_and_drops_unknown():
    ok = redact_public_profile_pack_for_public_response(
        {}, {"public_profile": {"accent": "orange"}})
    assert ok["settings"]["accent"] == "orange"
    bad = redact_public_profile_pack_for_public_response(
        {}, {"public_profile": {"accent": "neon-pink"}})
    assert bad["settings"]["accent"] is None


# ---------------------------------------------------------------------------
# P1.1 — owner-approved public_faq (leak-safe, default [])
# ---------------------------------------------------------------------------


def test_public_faq_whitelisted_to_question_answer_and_strips_source_refs():
    # Owner-approved FAQ survives redaction but ONLY as {question, answer};
    # extra keys are dropped and inline source refs are stripped from answers.
    pack = {
        "name": "Avery",
        "public_faq": [
            {
                "question": "What do you do?",
                "answer": "We build AI websites [a1b2c3d4-1111-2222-3333-444455556666].",
                "internal_note": "leak me",
                "citations": ["a1b2c3d4-1111-2222-3333-444455556666"],
            },
            {"question": "  ", "answer": "dropped: blank question"},
            {"question": "Blank answer?", "answer": "   "},
            "not-a-dict",
        ],
    }
    out = redact_public_profile_pack_for_public_response(pack)
    assert out["public_faq"] == [
        {"question": "What do you do?", "answer": "We build AI websites"}
    ]


def test_public_faq_respects_section_visibility_toggle():
    pack = {"name": "Avery", "public_faq": [{"question": "Q?", "answer": "A."}]}
    settings = {"section_visibility": {"faq": False}}
    out = redact_public_profile_pack_for_public_response(pack, settings)
    assert out["public_faq"] == []


def test_public_faq_defaults_to_empty_when_absent():
    # No owner FAQ in the pack => [] (never seeded, never un-redacted).
    out = redact_public_profile_pack_for_public_response({"name": "Avery"}, {})
    assert out["public_faq"] == []
