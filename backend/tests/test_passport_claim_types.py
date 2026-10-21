from modules.passport_claim_types import CLAIM_TYPES, is_allowed_claim_type


def test_allowlist_includes_sprint1_types():
    for t in ("full_name", "headline", "bio", "work_experience", "education", "skill"):
        assert is_allowed_claim_type(t)


def test_allowlist_includes_remaining_types():
    for t in ("project", "credential", "preference", "social_link"):
        assert is_allowed_claim_type(t)


def test_rejects_life_brain_types():
    assert not is_allowed_claim_type("belief")
    assert not is_allowed_claim_type("media_appearance")


def test_claim_types_frozen_set():
    assert isinstance(CLAIM_TYPES, frozenset)
