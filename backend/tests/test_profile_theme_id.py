import pytest
from pydantic import ValidationError

from routers.profile import UpdateProfileRequest, map_twin_to_profile


def test_update_request_accepts_valid_theme_id():
    req = UpdateProfileRequest(theme_id="founder-site")
    assert req.theme_id == "founder-site"


def test_update_request_rejects_unknown_theme_id():
    with pytest.raises(ValidationError):
        UpdateProfileRequest(theme_id="not-a-theme")


def test_update_request_theme_id_optional():
    req = UpdateProfileRequest()
    assert req.theme_id is None


def test_map_twin_returns_theme_id():
    twin = {
        "id": "t1",
        "name": "Avery",
        "settings": {"public_profile": {"theme_id": "conversion-warm"}},
    }
    assert map_twin_to_profile(twin)["theme_id"] == "conversion-warm"


def test_map_twin_theme_id_absent_is_none():
    twin = {"id": "t1", "name": "Avery", "settings": {}}
    assert map_twin_to_profile(twin)["theme_id"] is None


def test_update_request_rejects_empty_theme_id():
    with pytest.raises(ValidationError):
        UpdateProfileRequest(theme_id="")


def test_update_request_accepts_new_layout_ids():
    for theme in ("editorial", "split", "site"):
        assert UpdateProfileRequest(theme_id=theme).theme_id == theme


def test_update_request_accepts_valid_accent_rejects_unknown():
    assert UpdateProfileRequest(accent="forest").accent == "forest"
    with pytest.raises(ValidationError):
        UpdateProfileRequest(accent="neon-pink")
