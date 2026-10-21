"""Direct tests for the share-link public-reachability gate (issue #332).

`test_auth_comprehensive.py` stubs `is_publicly_accessible_twin_record` to
isolate token matching, and the router tests patch it too. These tests call
the real function (and the real `validate_share_token` / `get_share_link_info`
callers) so the active-status + marketplace-quality gate stays covered.
"""
from __future__ import annotations

import copy
from typing import Any
from unittest.mock import patch

import pytest

from modules.share_links import (
    get_share_link_info,
    is_marketplace_public_twin_record,
    is_publicly_accessible_twin_record,
    validate_share_token,
)
from tests._supabase_mock import fluent

_BIO = (
    "Founder and builder working on AI-powered products for small teams "
    "who want a persona that actually sounds like them."
)
_TOKEN = "valid-token-123"


def _twin(**overrides: Any) -> dict[str, Any]:
    twin: dict[str, Any] = {
        "id": "twin-1",
        "tenant_id": "tenant-1",
        "status": "active",
        "settings": {
            "widget_settings": {"share_token": _TOKEN},
            "public_profile": {
                "display_name": "Test Persona",
                "occupation": "Founder",
                "short_description": "Building AI products",
                "bio": _BIO,
                "work_experience": [
                    {"company": "Acme Robotics", "role": "Founder", "description": "Building."}
                ],
            },
        },
    }
    twin.update(overrides)
    return twin


def _failing_twin(*, public_share_enabled: bool = False) -> dict[str, Any]:
    twin = _twin()
    twin["settings"]["public_profile"]["bio"] = "nill"
    twin["settings"]["public_profile"]["work_experience"] = []
    twin["settings"]["widget_settings"]["public_share_enabled"] = public_share_enabled
    return twin


def test_active_passing_twin_is_accessible():
    assert is_publicly_accessible_twin_record(_twin()) is True


@pytest.mark.parametrize("status", ["draft", "archived", "pending", "", None])
def test_non_active_status_is_not_accessible_even_when_profile_passes(status):
    twin = _twin(status=status)
    assert is_marketplace_public_twin_record(twin) is False
    assert is_publicly_accessible_twin_record(twin) is False


def test_status_match_is_case_insensitive():
    assert is_publicly_accessible_twin_record(_twin(status="ACTIVE")) is True


def test_active_but_failing_quality_is_not_accessible():
    assert is_publicly_accessible_twin_record(_failing_twin()) is False


def test_public_share_enabled_does_not_bypass_failing_quality():
    twin = _failing_twin(public_share_enabled=True)
    assert is_publicly_accessible_twin_record(twin) is False


def test_deleted_twin_is_not_accessible():
    twin = _twin()
    twin["settings"]["deleted_at"] = "2026-03-16T00:00:00Z"
    assert is_publicly_accessible_twin_record(twin) is False


@pytest.mark.parametrize("twin", [None, {}])
def test_missing_twin_is_not_accessible(twin):
    assert is_publicly_accessible_twin_record(twin) is False


@pytest.mark.parametrize("settings", [None, {}, "not-a-dict", []])
def test_missing_or_malformed_settings_is_not_accessible(settings):
    twin = _twin()
    twin["settings"] = settings
    assert is_publicly_accessible_twin_record(twin) is False


@pytest.mark.parametrize("missing", ["occupation", "bio", "work_experience"])
def test_missing_required_profile_key_is_not_accessible(missing):
    twin = _twin()
    profile = twin["settings"]["public_profile"]
    del profile[missing]
    if missing == "bio":
        # `short_description` backs `bio`; drop it so no fallback remains.
        profile.pop("short_description")
    assert is_publicly_accessible_twin_record(twin) is False


def test_missing_short_description_falls_back_to_bio():
    twin = _twin()
    del twin["settings"]["public_profile"]["short_description"]
    assert is_publicly_accessible_twin_record(twin) is True


def test_gate_does_not_mutate_input():
    twin = _twin()
    snapshot = copy.deepcopy(twin)
    is_publicly_accessible_twin_record(twin)
    assert twin == snapshot


def test_normalize_failure_fails_closed():
    with patch(
        "modules.public_profile_pack.normalize_public_profile",
        side_effect=RuntimeError("boom"),
    ):
        assert is_publicly_accessible_twin_record(_twin()) is False


# --- real callers, no gate stub -------------------------------------------


def _validate(twin: dict[str, Any] | None, token: str = _TOKEN) -> bool:
    with patch("modules.share_links.supabase") as sb, patch(
        "modules.share_links.AuditLogger"
    ):
        sb.table.return_value = fluent(twin)
        return validate_share_token(token, "twin-1")


def test_validate_share_token_accepts_passing_twin_with_matching_token():
    assert _validate(_twin()) is True


def test_validate_share_token_rejects_wrong_token_on_passing_twin():
    assert _validate(_twin(), token="wrong") is False


def test_validate_share_token_rejects_failing_quality_even_with_matching_token():
    assert _validate(_failing_twin(public_share_enabled=True)) is False


def test_validate_share_token_rejects_draft_twin_with_matching_token():
    assert _validate(_twin(status="draft")) is False


def test_validate_share_token_rejects_missing_twin():
    assert _validate(None) is False


def test_get_share_link_info_mints_no_token_for_failing_twin():
    twin = _failing_twin()
    twin["settings"]["widget_settings"].pop("share_token")
    with patch("modules.share_links.supabase") as sb, patch(
        "modules.share_links.ensure_share_token"
    ) as ensure:
        sb.table.return_value = fluent(twin)
        info = get_share_link_info("twin-1")
    ensure.assert_not_called()
    assert info["share_token"] is None
    assert info["share_url"] is None


def test_get_share_link_info_mints_token_for_passing_twin():
    twin = _twin()
    twin["settings"]["widget_settings"].pop("share_token")
    with patch("modules.share_links.supabase") as sb, patch(
        "modules.share_links.ensure_share_token", return_value="minted"
    ) as ensure:
        sb.table.return_value = fluent(twin)
        info = get_share_link_info("twin-1")
    ensure.assert_called()
    assert info["share_token"] == "minted"
