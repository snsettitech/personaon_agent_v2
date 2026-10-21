"""Regression tests for _dedupe_object_rows guarding against malformed
(non-dict) work_experience/education rows.

Root cause: PATCH /twins/{id} accepts settings.public_profile as an
unvalidated Dict[str, Any] (routers/twins.py patch_twin). An owner can set
work_experience/education to a list containing non-dict items (e.g. bare
strings), and normalize_public_profile / build_public_profile_pack must not
crash when that malformed data is later read (e.g. by
GET /twins/{id}/profile-insights, which has no surrounding try/except).
"""

from modules.profile_research import _dedupe_object_rows
from modules.public_profile_pack import normalize_public_profile


def test_dedupe_object_rows_skips_non_dict_entries():
    rows = [
        "garbage",
        {"company": "Acme", "role": "Founder", "description": "Building things."},
        123,
        None,
        ["nested", "list"],
    ]
    result = _dedupe_object_rows(rows, ("company", "role", "description"))
    assert result == [{"company": "Acme", "role": "Founder", "description": "Building things."}]


def test_dedupe_object_rows_handles_all_non_dict_rows():
    assert _dedupe_object_rows(["a", "b", 1, None], ("company", "role")) == []


def test_normalize_public_profile_does_not_crash_on_malformed_work_experience():
    """Reproduces the PATCH /twins/{id} -> profile-insights crash scenario."""
    twin = {
        "name": "Test Persona",
        "settings": {
            "public_profile": {
                "display_name": "Test Persona",
                "work_experience": ["garbage"],
                "education": ["also garbage"],
            }
        },
    }

    normalized = normalize_public_profile(twin)

    assert normalized["work_experience"] == []
    assert normalized["education"] == []
