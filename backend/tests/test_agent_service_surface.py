"""Unit tests for surface-keyed runner cache logic in agent_service."""

from unittest.mock import sentinel


def test_surface_class_owner():
    from adk_core.services.agent_service import _surface_class
    assert _surface_class("owner") == "owner"


def test_surface_class_widget():
    from adk_core.services.agent_service import _surface_class
    assert _surface_class("widget") == "visitor"


def test_surface_class_public():
    from adk_core.services.agent_service import _surface_class
    assert _surface_class("public") == "visitor"


def test_surface_class_unknown():
    from adk_core.services.agent_service import _surface_class
    assert _surface_class("embed") == "visitor"


def test_cache_key_format():
    from adk_core.services.agent_service import _cache_key
    assert _cache_key("twin-123", "owner") == "twin-123:owner"


def test_invalidate_agent_removes_both_keys():
    """After caching runners for both surfaces, invalidate_agent removes both."""
    import adk_core.services.agent_service as svc

    # Insert sentinel values for both surface variants
    svc._runner_cache["twin-123:owner"] = sentinel.owner_runner
    svc._runner_cache["twin-123:visitor"] = sentinel.visitor_runner

    # Verify both are present
    assert "twin-123:owner" in svc._runner_cache
    assert "twin-123:visitor" in svc._runner_cache

    svc.invalidate_agent("twin-123")

    # Both should be removed
    assert "twin-123:owner" not in svc._runner_cache
    assert "twin-123:visitor" not in svc._runner_cache


def test_invalidate_agent_no_error_when_missing():
    """invalidate_agent with nonexistent twin_id does not raise."""
    from adk_core.services.agent_service import invalidate_agent

    # Should not raise any exception
    invalidate_agent("nonexistent-twin-xyz")
