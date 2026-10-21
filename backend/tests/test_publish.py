"""Wave 0 test stubs for POST /profile/publish endpoint.

These tests define the expected contract for the publish endpoint.
They will fail RED until Task 2 implements the endpoint.
"""
import pytest


class TestProfilePublish:
    """POST /profile/publish"""

    def test_publish_sets_twin_active(self):
        """Publishing sets is_active=True and status='active' on twins table."""
        pytest.skip("Wave 0 stub -- implement in Task 2")

    def test_publish_ensures_share_token(self):
        """Publishing ensures a share token exists for the twin."""
        pytest.skip("Wave 0 stub -- implement in Task 2")

    def test_publish_returns_url_with_handle(self):
        """If twin has a handle, publish returns /p/{handle} URL."""
        pytest.skip("Wave 0 stub -- implement in Task 2")

    def test_publish_returns_url_without_handle(self):
        """If twin has no handle, publish returns /share/{twin_id}/{token} URL."""
        pytest.skip("Wave 0 stub -- implement in Task 2")

    def test_publish_sets_default_subscription_tier(self):
        """Publishing sets subscription_tier to 'free' if not already set."""
        pytest.skip("Wave 0 stub -- implement in Task 2")

    def test_publish_requires_twin_ownership(self):
        """Publishing a twin you don't own raises 403."""
        pytest.skip("Wave 0 stub -- implement in Task 2")


class TestPublicProfileTier:
    """subscription_tier in public profile response"""

    def test_profile_pack_includes_subscription_tier(self):
        """build_public_profile_pack response includes subscription_tier field."""
        pytest.skip("Wave 0 stub -- implement in Task 2")

    def test_profile_pack_defaults_to_free_tier(self):
        """When subscription_tier is not set, defaults to 'free'."""
        pytest.skip("Wave 0 stub -- implement in Task 2")
