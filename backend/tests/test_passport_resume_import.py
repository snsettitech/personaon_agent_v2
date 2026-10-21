"""PON-8 resume → proposed claims mapping tests."""

from __future__ import annotations

import pytest

from modules.passport_resume_import import (
    claims_from_extraction,
    parse_resume_extraction_json,
)


def test_parse_strips_fences():
    raw = '```json\n{"full_name": "Ada Lovelace"}\n```'
    data = parse_resume_extraction_json(raw)
    assert data["full_name"] == "Ada Lovelace"


def test_claims_from_extraction_maps_core_types():
    parsed = {
        "full_name": "Ada Lovelace",
        "headline": "Mathematician",
        "short_description": "Pioneer of computing.",
        "education": [
            {"institution": "Cambridge", "degree": "B.A.", "field": "Math"},
        ],
        "work_experience": [
            {"company": "Analytical Engine", "role": "Programmer", "start_year": 1842},
        ],
        "areas_of_expertise": ["algorithms", "notes"],
    }
    claims = claims_from_extraction(parsed)
    types = {c["claim_type"] for c in claims}
    assert "full_name" in types
    assert "headline" in types
    assert "bio" in types
    assert "education" in types
    assert "work_experience" in types
    assert "skill" in types
    assert all(c["value_text"] for c in claims)


def test_claims_from_extraction_skips_empty():
    assert claims_from_extraction({}) == []
    assert claims_from_extraction({"education": [{}], "work_experience": [None]}) == []


def test_parse_invalid_raises():
    with pytest.raises(ValueError):
        parse_resume_extraction_json("not-json")
