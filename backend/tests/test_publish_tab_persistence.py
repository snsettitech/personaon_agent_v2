"""Persistence regression tests for the Publish tab (#228 + #229).

Root cause both bugs share: owner edits in the dashboard write to ``twins.settings``
via ``PATCH /profile`` (theme/layout, #229) and ``PATCH /twins/{id}``
(section-visibility, #228). A 0-row UPDATE — e.g. an RLS-filtered write when the
Supabase client is not service-role, because the twin's ``tenant_id`` != the
owner's ``auth.uid()`` — does NOT raise in supabase-py. The handler therefore
reported a phantom success and the edit was silently dropped.

These tests pin:
  * the settings-merge behavior for both write paths (the value lands and
    sibling keys are preserved), and
  * that a 0-row write now fails loudly instead of phantom-confirming the save.
"""
import pytest
from fastapi import HTTPException

import routers.profile as profile_mod
import routers.twins as twins_mod
from modules.schemas import TwinSettingsUpdate
from routers.profile import UpdateProfileRequest, update_profile, _safe_update_twin_row
from tests._supabase_mock import fluent, result


def _seq(monkeypatch, module, execute_returns):
    """Install a fluent Supabase mock whose .execute() yields the given sequence."""
    m = fluent(None)
    m.execute.side_effect = list(execute_returns)
    monkeypatch.setattr(module, "supabase", m)
    return m


# --------------------------------------------------------------------------
# The fix: _safe_update_twin_row must surface a 0-row write (#228/#229 cause)
# --------------------------------------------------------------------------

def test_safe_update_twin_row_raises_when_update_matches_zero_rows(monkeypatch):
    # An RLS-filtered (or twin-missing) UPDATE returns an empty data list, not an error.
    monkeypatch.setattr(profile_mod, "supabase", fluent([]))
    with pytest.raises(HTTPException) as exc:
        _safe_update_twin_row("twin-1", {"settings": {"public_profile": {"theme_id": "site"}}})
    assert exc.value.status_code == 500


def test_safe_update_twin_row_succeeds_when_one_row_updated(monkeypatch):
    monkeypatch.setattr(profile_mod, "supabase", fluent([{"id": "twin-1"}]))
    # Should not raise.
    _safe_update_twin_row("twin-1", {"settings": {"public_profile": {"theme_id": "site"}}})


# --------------------------------------------------------------------------
# #229: PATCH /profile persists theme_id into settings.public_profile
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_profile_persists_theme_id_preserving_siblings(monkeypatch):
    monkeypatch.setattr(
        profile_mod, "get_or_create_profile_for_user",
        lambda user: {"id": "twin-1", "name": "Avery"},
    )
    m = _seq(monkeypatch, profile_mod, [
        result({"settings": {"public_profile": {"bio": "existing bio"}}}),   # read current
        result([{"id": "twin-1"}]),                                          # update -> 1 row
        result({"id": "twin-1", "name": "Avery",
                "settings": {"public_profile": {"bio": "existing bio", "theme_id": "site"}}}),
    ])
    out = await update_profile(
        UpdateProfileRequest(theme_id="site"),
        user={"user_id": "u1", "tenant_id": "t1"},
    )
    assert out["theme_id"] == "site"
    # The settings payload written must merge theme_id without dropping the existing bio.
    written = m.update.call_args[0][0]["settings"]["public_profile"]
    assert written == {"bio": "existing bio", "theme_id": "site"}


@pytest.mark.asyncio
async def test_update_profile_raises_when_theme_write_is_dropped(monkeypatch):
    monkeypatch.setattr(
        profile_mod, "get_or_create_profile_for_user",
        lambda user: {"id": "twin-1", "name": "Avery"},
    )
    _seq(monkeypatch, profile_mod, [
        result({"settings": {"public_profile": {}}}),  # read current
        result([]),                                    # update -> 0 rows (RLS no-op)
    ])
    with pytest.raises(HTTPException) as exc:
        await update_profile(
            UpdateProfileRequest(theme_id="site"),
            user={"user_id": "u1", "tenant_id": "t1"},
        )
    assert exc.value.status_code == 500


# --------------------------------------------------------------------------
# #228: PATCH /twins/{id} persists section_visibility, preserving other settings
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_twin_merges_section_visibility_preserving_settings(monkeypatch):
    monkeypatch.setattr(twins_mod, "_require_authenticated_user", lambda u: u)
    monkeypatch.setattr(twins_mod, "verify_twin_ownership", lambda twin_id, user: None)
    monkeypatch.setattr(twins_mod, "invalidate_agent", lambda twin_id: None)
    m = _seq(monkeypatch, twins_mod, [
        result({"settings": {"public_profile": {"bio": "b"}, "handle": "avery"}}),  # read current
        result([{"id": "twin-1"}]),                                                 # update -> 1 row
    ])
    out = await twins_mod.patch_twin(
        "twin-1",
        TwinSettingsUpdate(settings={"section_visibility": {"social_links": False}}),
        user={"user_id": "u1", "tenant_id": "t1"},
    )
    assert out  # truthy response.data
    written = m.update.call_args[0][0]["settings"]
    assert written["section_visibility"] == {"social_links": False}
    assert written["handle"] == "avery"                 # sibling key preserved
    assert written["public_profile"] == {"bio": "b"}    # sibling key preserved


@pytest.mark.asyncio
async def test_patch_twin_raises_when_settings_write_is_dropped(monkeypatch):
    # Parity with _safe_update_twin_row on the /profile path: by the time we UPDATE,
    # ownership + existence are already proven, so a 0-row write is an RLS-filtered
    # persistence failure — NOT a missing twin. It must fail loud with 500
    # (TWIN_WRITE_NO_ROWS), not the old misleading 404 that hid dropped saves. (#228)
    monkeypatch.setattr(twins_mod, "_require_authenticated_user", lambda u: u)
    monkeypatch.setattr(twins_mod, "verify_twin_ownership", lambda twin_id, user: None)
    monkeypatch.setattr(twins_mod, "invalidate_agent", lambda twin_id: None)
    _seq(monkeypatch, twins_mod, [
        result({"settings": {"public_profile": {"bio": "b"}, "handle": "avery"}}),  # read current
        result([]),                                                                 # update -> 0 rows (RLS no-op)
    ])
    with pytest.raises(HTTPException) as exc:
        await twins_mod.patch_twin(
            "twin-1",
            TwinSettingsUpdate(settings={"section_visibility": {"social_links": False}}),
            user={"user_id": "u1", "tenant_id": "t1"},
        )
    assert exc.value.status_code == 500
    assert exc.value.detail["code"] == "TWIN_WRITE_NO_ROWS"   # structured body, not a bare 500
