"""Tests for notification audience resolution."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests._supabase_mock import fluent


@pytest.mark.asyncio
async def test_resolve_all_active_filters_deleted_rows():
    from modules.audience import resolve_audience
    from modules.notification_flows import AudienceSpec

    sb = fluent([
        {"id": "user-1", "email": "one@example.com", "tenant_id": "tenant-1", "deleted_at": None},
        {"id": "user-2", "email": "two@example.com", "tenant_id": "tenant-2", "deleted_at": None},
    ])

    audience = await resolve_audience(sb, AudienceSpec(segment="all_active"))

    assert audience.count == 2
    assert [row.user_id for row in audience.recipients] == ["user-1", "user-2"]


@pytest.mark.asyncio
async def test_resolve_plan_uses_plan_or_metadata():
    from modules.audience import resolve_audience
    from modules.notification_flows import AudienceSpec

    sb = fluent([
        {"id": "user-1", "email": "one@example.com", "tenant_id": "tenant-1", "plan": "business"},
        {"id": "user-2", "email": "two@example.com", "tenant_id": "tenant-2", "user_metadata": {"plan": "free"}},
    ])

    audience = await resolve_audience(sb, AudienceSpec(segment="plan", plan="business"))

    assert audience.count == 1
    assert audience.recipients[0].user_id == "user-1"


@pytest.mark.asyncio
async def test_resolve_flag_not_used_uses_auth_pages(monkeypatch):
    from modules import audience as audience_module
    from modules.notification_flows import AudienceSpec
    from modules.audience import resolve_audience

    audience_module._flag_audience_cache.clear()
    audience_module._flag_used_cache.clear()

    page_one = [
        SimpleNamespace(
            id=f"user-{i}",
            email=f"user{i}@example.com",
            user_metadata={"flag_beta": i == 3},
        )
        for i in range(100)
    ]
    page_two = [
        SimpleNamespace(id="user-100", email="user100@example.com", user_metadata={}),
    ]
    calls: list[tuple[int, int]] = []

    class Admin:
        def list_users(self, *, page: int, per_page: int):
            calls.append((page, per_page))
            return SimpleNamespace(users=page_one if page == 1 else page_two)

    sb = SimpleNamespace(auth=SimpleNamespace(admin=Admin()))
    monkeypatch.setattr("modules.posthog_query.run_hogql", lambda _query: [["user-2"]])

    resolved = await resolve_audience(sb, AudienceSpec(segment="flag_not_used", flag="beta"))

    assert calls == [(1, 100), (2, 100)]
    assert resolved.count == 99
    assert "user-2" not in {row.user_id for row in resolved.recipients}
    assert "user-3" not in {row.user_id for row in resolved.recipients}


@pytest.mark.asyncio
async def test_resolve_user_list_dedupes_recipients():
    from modules.audience import resolve_audience
    from modules.notification_flows import AudienceSpec

    sb = fluent([
        {"id": "user-1", "email": "one@example.com", "tenant_id": "tenant-1"},
        {"id": "user-1", "email": "one@example.com", "tenant_id": "tenant-1"},
    ])

    audience = await resolve_audience(sb, AudienceSpec(segment="user_list", user_ids=["user-1"]))

    assert audience.count == 1
    assert audience.recipients[0].email == "one@example.com"
