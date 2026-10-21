from modules.profile_selection import (
    build_creator_candidates,
    normalize_twin_status_shape,
    select_profile_twin_from_rows,
)


def test_select_profile_prefers_owner_match_over_newer_legacy_row():
    user_id = "user-1"
    tenant_id = "tenant-1"
    candidates = build_creator_candidates(user_id=user_id, tenant_id=tenant_id)

    rows = [
        {
            "id": "legacy-newer",
            "creator_id": f"tenant_{tenant_id}",
            "settings": {},
            "created_at": "2026-02-26T10:00:00+00:00",
            "status": "draft",
        },
        {
            "id": "owned-older",
            "creator_id": user_id,
            "settings": {"owner_user_id": user_id},
            "created_at": "2026-02-26T09:00:00+00:00",
            "status": "active",
        },
    ]

    selected = select_profile_twin_from_rows(
        rows=rows,
        user_id=user_id,
        creator_candidates=candidates,
    )
    assert selected is not None
    assert selected["id"] == "owned-older"


def test_select_profile_returns_none_for_ambiguous_legacy_candidates():
    user_id = "user-1"
    tenant_id = "tenant-1"
    candidates = build_creator_candidates(user_id=user_id, tenant_id=tenant_id)

    rows = [
        {
            "id": "legacy-1",
            "creator_id": f"tenant_{tenant_id}",
            "settings": {},
            "created_at": "2026-02-26T09:00:00+00:00",
        },
        {
            "id": "legacy-2",
            "creator_id": f"tenant_{tenant_id}",
            "settings": {},
            "created_at": "2026-02-26T10:00:00+00:00",
        },
    ]

    selected = select_profile_twin_from_rows(
        rows=rows,
        user_id=user_id,
        creator_candidates=candidates,
    )
    assert selected is None


def test_select_profile_allows_single_legacy_fallback():
    user_id = "user-1"
    tenant_id = "tenant-1"
    candidates = build_creator_candidates(user_id=user_id, tenant_id=tenant_id)

    rows = [
        {
            "id": "legacy-only",
            "creator_id": f"tenant_{tenant_id}",
            "settings": {},
            "created_at": "2026-02-26T10:00:00+00:00",
        }
    ]

    selected = select_profile_twin_from_rows(
        rows=rows,
        user_id=user_id,
        creator_candidates=candidates,
    )
    assert selected is not None
    assert selected["id"] == "legacy-only"


def test_normalize_status_falls_back_to_is_active():
    twin = {"id": "t1", "is_active": True, "settings": {}}
    normalized = normalize_twin_status_shape(twin)
    assert normalized["status"] == "active"

