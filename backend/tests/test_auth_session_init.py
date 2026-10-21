"""Tests for POST /auth/session-init, specifically the auth_provider field.

session_init() previously had no test coverage at all. This diff adds
auth_provider (derived from the Supabase JWT's app_metadata.provider) so the
frontend can label onboarding_started's input_source correctly instead of the
old LinkedIn-only identity.provider, which was null for Google/email signups.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from routers.onboarding import ConsentState


def _user(provider: str | None, *, has_linkedin: bool = False) -> dict:
    return {
        "user_id": "user-1",
        "email": "alice@example.com",
        "name": "Alice",
        "user_metadata": {},
        "app_metadata": {"provider": provider} if provider is not None else {},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider",
    ["google", "linkedin_oidc", "email"],
)
async def test_session_init_returns_actual_auth_provider(provider: str):
    """auth_provider must reflect the real Supabase auth method for every signup path."""
    with patch("routers.onboarding._consent_gate_enabled", return_value=False), \
         patch("routers.onboarding._consent_state", return_value=ConsentState(accepted=True)), \
         patch("routers.onboarding._fetch_profile_twin", return_value=None), \
         patch("routers.auth.user_has_linkedin_provider", return_value=False):
        from routers.auth import session_init

        result = await session_init(user=_user(provider))

    assert result["auth_provider"] == provider
    assert result["has_persona"] is False
    assert result["next_route"] == "/onboarding"


@pytest.mark.asyncio
async def test_session_init_auth_provider_null_when_app_metadata_missing():
    """Missing app_metadata.provider must return null, not raise or guess."""
    with patch("routers.onboarding._consent_gate_enabled", return_value=False), \
         patch("routers.onboarding._consent_state", return_value=ConsentState(accepted=True)), \
         patch("routers.onboarding._fetch_profile_twin", return_value=None), \
         patch("routers.auth.user_has_linkedin_provider", return_value=False):
        from routers.auth import session_init

        result = await session_init(user=_user(None))

    assert result["auth_provider"] is None


@pytest.mark.asyncio
async def test_session_init_auth_provider_independent_of_linkedin_identity():
    """auth_provider (real auth method) must stay correct even when the separate
    LinkedIn-identity block (identity.provider, used only for form pre-fill) is
    populated — the two fields must not be conflated."""
    with patch("routers.onboarding._consent_gate_enabled", return_value=False), \
         patch("routers.onboarding._consent_state", return_value=ConsentState(accepted=True)), \
         patch("routers.onboarding._fetch_profile_twin", return_value=None), \
         patch("routers.auth.user_has_linkedin_provider", return_value=True), \
         patch("routers.auth.select_best_linkedin_account", return_value=None), \
         patch("routers.auth.supabase") as mock_sb:
        mock_sb.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value = MagicMock(data=[])

        from routers.auth import session_init

        # A user who signed up via Google but has since connected LinkedIn
        # for identity verification — auth_provider must stay "google".
        result = await session_init(user=_user("google", has_linkedin=True))

    assert result["auth_provider"] == "google"
