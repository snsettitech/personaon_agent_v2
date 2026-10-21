"""Wave 0 test stubs for handle system endpoints.

These tests define the expected contract for /handles/claim, /handles/check,
and /handles/resolve. They will fail RED until Task 1 implements the endpoints.
"""
import pytest


class TestHandleClaim:
    """POST /handles/claim"""

    def test_claim_returns_handle_and_url(self):
        """Claiming a handle returns the claimed handle and /p/{handle} URL."""
        pytest.skip("Wave 0 stub -- implement in Task 1")

    def test_claim_sanitizes_handle(self):
        """Handle is lowercased, diacritics stripped, non-alphanumeric removed."""
        pytest.skip("Wave 0 stub -- implement in Task 1")

    def test_claim_rejects_reserved_handles(self):
        """Reserved handles (admin, api, app, etc.) are rejected."""
        pytest.skip("Wave 0 stub -- implement in Task 1")

    def test_claim_resolves_collision(self):
        """When handle is taken, appends -2, -3, etc. until available."""
        pytest.skip("Wave 0 stub -- implement in Task 1")

    def test_claim_requires_twin_ownership(self):
        """Claiming a handle for a twin you don't own raises 403."""
        pytest.skip("Wave 0 stub -- implement in Task 1")


class TestHandleCheck:
    """GET /handles/check"""

    def test_check_available_returns_true(self):
        """Available handle returns { available: true }."""
        pytest.skip("Wave 0 stub -- implement in Task 1")

    def test_check_taken_returns_suggestion(self):
        """Taken handle returns { available: false, suggestion: '...' }."""
        pytest.skip("Wave 0 stub -- implement in Task 1")


class TestHandleResolve:
    """GET /handles/resolve"""

    def test_resolve_returns_twin_id_and_token(self):
        """Valid handle returns { twin_id, share_token }."""
        pytest.skip("Wave 0 stub -- implement in Task 1")

    def test_resolve_404_for_unknown_handle(self):
        """Unknown handle returns 404."""
        pytest.skip("Wave 0 stub -- implement in Task 1")

    def test_resolve_404_for_inactive_twin(self):
        """Handle pointing to inactive twin returns 404."""
        pytest.skip("Wave 0 stub -- implement in Task 1")
