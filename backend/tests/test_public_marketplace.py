from modules.share_links import (
    build_public_share_path,
    is_marketplace_public_twin_record,
    is_publicly_accessible_twin_record,
)

_MEANINGFUL_BIO = (
    "Founder and builder working on AI-powered products for small teams "
    "who want a persona that actually sounds like them."
)

_WORK_EXPERIENCE = [
    {"company": "Acme Robotics", "role": "Founder", "description": "Building AI products."}
]


def _marketplace_ready_twin(*, is_public: bool = True) -> dict:
    return {
        "status": "active",
        "is_active": True,
        "settings": {
            "is_public": is_public,
            "public_profile": {
                "display_name": "Test Persona",
                "occupation": "Founder",
                "short_description": "Building AI products",
                "bio": _MEANINGFUL_BIO,
                "work_experience": _WORK_EXPERIENCE,
            },
        },
    }


def test_marketplace_public_rule_ignores_is_public_flag():
    """After the 100k-unlock cleanup: every live persona with a complete
    profile is in the marketplace dataset. The settings.is_public flag is
    no longer part of the gate."""
    # Flag true → in
    assert is_marketplace_public_twin_record(_marketplace_ready_twin(is_public=True)) is True

    # Flag false → still in (live + profile complete is enough)
    assert is_marketplace_public_twin_record(_marketplace_ready_twin(is_public=False)) is True

    # Flag missing entirely → still in
    twin_without_flag = _marketplace_ready_twin(is_public=True)
    twin_without_flag["settings"].pop("is_public")
    assert is_marketplace_public_twin_record(twin_without_flag) is True


def test_marketplace_public_rule_requires_active_profile_with_required_fields():
    twin = _marketplace_ready_twin(is_public=True)
    assert is_marketplace_public_twin_record(twin) is True

    twin["settings"]["public_profile"]["occupation"] = ""
    assert is_marketplace_public_twin_record(twin) is False

    twin["settings"]["public_profile"]["occupation"] = "Founder"
    twin["settings"]["deleted_at"] = "2026-03-16T00:00:00Z"
    assert is_marketplace_public_twin_record(twin) is False


def test_marketplace_public_rule_requires_meaningful_bio():
    """Execution-board 0.1 (PRD R1): a twin with all the old scalar fields
    populated but a meaningless bio (the "nill" root-cause case) must NOT
    pass the gate, even though display_name/occupation/short_description
    are all non-empty."""
    twin = _marketplace_ready_twin(is_public=True)
    twin["settings"]["public_profile"]["bio"] = "nill"
    assert is_marketplace_public_twin_record(twin) is False

    twin["settings"]["public_profile"]["headline"] = "software engineer"
    assert is_marketplace_public_twin_record(twin) is False


def test_marketplace_public_rule_requires_populated_section():
    """Execution-board 0.1 (PRD R1): a meaningful bio alone is not enough —
    the profile must also have at least one real work_experience or
    education entry (the sections that actually render publicly)."""
    twin = _marketplace_ready_twin(is_public=True)
    twin["settings"]["public_profile"]["work_experience"] = []
    assert is_marketplace_public_twin_record(twin) is False

    # An empty-content entry (all key fields blank) must not count either —
    # normalize_public_profile's dedupe drops it.
    twin["settings"]["public_profile"]["work_experience"] = [{"company": "", "role": "", "description": ""}]
    assert is_marketplace_public_twin_record(twin) is False

    # A real education entry alone is sufficient.
    twin["settings"]["public_profile"]["education"] = [
        {"institution": "State University", "degree": "BS", "field": "Computer Science"}
    ]
    assert is_marketplace_public_twin_record(twin) is True


def test_marketplace_public_rule_rejects_garbage_occupation_and_short_description():
    """Phase-0 review fix: occupation/short_description previously only got
    a truthiness check (any non-empty string cleared the gate). A garbage
    single-character value must now fail, while legitimate short values
    ("Founder", "Building AI products") continue to pass."""
    twin = _marketplace_ready_twin(is_public=True)
    twin["settings"]["public_profile"]["short_description"] = "x"
    assert is_marketplace_public_twin_record(twin) is False

    twin = _marketplace_ready_twin(is_public=True)
    twin["settings"]["public_profile"]["occupation"] = "x"
    assert is_marketplace_public_twin_record(twin) is False

    # Legitimate short values (the common case) must still pass.
    assert is_marketplace_public_twin_record(_marketplace_ready_twin(is_public=True)) is True


def test_marketplace_public_rule_rejects_name_only_work_experience_entry():
    """Phase-0 review fix: a work_experience/education entry with only a
    company/institution name and blank role/description/degree/field must
    NOT count as a populated section — it renders as no real content."""
    twin = _marketplace_ready_twin(is_public=True)
    twin["settings"]["public_profile"]["work_experience"] = [
        {"company": "Acme Robotics", "role": "", "description": ""}
    ]
    assert is_marketplace_public_twin_record(twin) is False

    # A name-only education entry must not count either.
    twin["settings"]["public_profile"]["education"] = [
        {"institution": "State University", "degree": "", "field": ""}
    ]
    assert is_marketplace_public_twin_record(twin) is False

    # But a real degree/field entry does count.
    twin["settings"]["public_profile"]["education"] = [
        {"institution": "State University", "degree": "BS", "field": "Computer Science"}
    ]
    assert is_marketplace_public_twin_record(twin) is True


def test_public_access_requires_marketplace_quality_gate():
    """Execution-board 0.1 (PRD R1): the OR-bypass that let
    `widget_settings.public_share_enabled=True` alone make an incomplete
    profile publicly reachable has been removed. Public accessibility now
    always requires the marketplace-quality gate to pass — there is no
    quality-free path."""
    # Marketplace path: live + profile complete → accessible (regardless of is_public)
    assert is_publicly_accessible_twin_record(_marketplace_ready_twin(is_public=True)) is True
    assert is_publicly_accessible_twin_record(_marketplace_ready_twin(is_public=False)) is True

    # Incomplete profile + public_share_enabled=True → still NOT accessible.
    # This is the exact bypass this fix closes: flipping the share toggle
    # used to be sufficient on its own, with zero content validation.
    incomplete_twin = _marketplace_ready_twin(is_public=False)
    incomplete_twin["settings"]["public_profile"]["occupation"] = ""
    assert is_marketplace_public_twin_record(incomplete_twin) is False
    incomplete_twin["settings"]["widget_settings"] = {"public_share_enabled": True}
    assert is_publicly_accessible_twin_record(incomplete_twin) is False

    # Incomplete profile + no share-link: private
    private_twin = _marketplace_ready_twin(is_public=False)
    private_twin["settings"]["public_profile"]["occupation"] = ""
    assert is_publicly_accessible_twin_record(private_twin) is False


def test_build_public_share_path_prefers_handle_before_token():
    path = build_public_share_path(
        "twin-123",
        {
            "handle": "jane-doe",
            "widget_settings": {"share_token": "token-123"},
        },
    )

    assert path == "/p/jane-doe"
