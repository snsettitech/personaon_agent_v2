"""Regression coverage for SIGNUPS_ENABLED / AGENT_EDITS_ENABLED kill switches.

execution-board 0.10 / PRD NFR-3 introduced three runtime kill switches
(modules/runtime_kill_switches.py). PUBLIC_CHAT_ENABLED already had dedicated
coverage (test_chat_resting.py); this file closes the gap for the other two.

The scenario these tests guard against: a future refactor of sync_user() or
update_persona() accidentally moves the kill-switch check to the wrong place
(e.g. before the existing-user early return in sync_user), which would
incorrectly block existing-user logins or persona edits instead of only
gating NEW signups / edits.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException, Response


class _Query:
    """Minimal fluent Supabase table() query stub keyed by table name."""

    def __init__(self, table_name, state):
        self._table_name = table_name
        self._state = state
        self._filters = {}

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self._filters[field] = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def upsert(self, payload):
        self._state["upsert_calls"].append((self._table_name, payload))
        return self

    def execute(self):
        if self._table_name == "users":
            user_id = self._filters.get("id")
            if user_id is not None:
                row = self._state["users_by_id"].get(user_id)
                return type("Resp", (), {"data": [row] if row else []})()
            return type("Resp", (), {"data": []})()

        if self._table_name == "twins":
            tenant_id = self._filters.get("tenant_id")
            twins = self._state["twins_by_tenant"].get(tenant_id, [])
            return type("Resp", (), {"data": twins})()

        return type("Resp", (), {"data": []})()


class _Supabase:
    def __init__(self, state):
        self._state = state

    def table(self, name):
        return _Query(name, self._state)


class _Request:
    def __init__(self):
        self.headers = {}


@pytest.mark.asyncio
async def test_sync_user_existing_user_not_blocked_by_signups_disabled(monkeypatch):
    """The signups_enabled() gate must sit AFTER the existing-user early
    return — an existing user logging in must never be paused by the
    new-signups kill switch."""
    from routers import auth as auth_router

    monkeypatch.setenv("SIGNUPS_ENABLED", "false")

    state = {
        "users_by_id": {
            "existing-user-id": {
                "id": "existing-user-id",
                "email": "owner@example.com",
                "tenant_id": "tenant-existing",
                "full_name": "Owner",
            }
        },
        "twins_by_tenant": {"tenant-existing": [{"id": "twin-1"}]},
        "upsert_calls": [],
    }
    monkeypatch.setattr(auth_router, "supabase", _Supabase(state))

    user = {
        "user_id": "existing-user-id",
        "email": "owner@example.com",
        "user_metadata": {},
    }

    result = await auth_router.sync_user(_Request(), Response(), user=user)

    assert result.status == "exists"
    assert result.user.tenant_id == "tenant-existing"


@pytest.mark.asyncio
async def test_sync_user_new_account_blocked_by_signups_disabled(monkeypatch):
    """A brand-new user (no row in `users`) must be rejected with 503 while
    SIGNUPS_ENABLED=false."""
    from routers import auth as auth_router

    monkeypatch.setenv("SIGNUPS_ENABLED", "false")

    state = {"users_by_id": {}, "twins_by_tenant": {}, "upsert_calls": []}
    monkeypatch.setattr(auth_router, "supabase", _Supabase(state))
    monkeypatch.setattr(auth_router, "resolve_tenant_id", lambda *_a, **_k: "tenant-new")

    user = {
        "user_id": "brand-new-user-id",
        "email": "newperson@example.com",
        "user_metadata": {},
    }

    with pytest.raises(HTTPException) as exc_info:
        await auth_router.sync_user(_Request(), Response(), user=user)

    assert exc_info.value.status_code == 503
    # Kill switch must reject before any user row is written.
    assert state["upsert_calls"] == []


@pytest.mark.asyncio
async def test_sync_user_new_account_allowed_when_signups_enabled(monkeypatch):
    """Sanity check: with the switch enabled (default), new-account creation
    proceeds and writes the user row."""
    from routers import auth as auth_router

    monkeypatch.setenv("SIGNUPS_ENABLED", "true")

    state = {"users_by_id": {}, "twins_by_tenant": {}, "upsert_calls": []}
    monkeypatch.setattr(auth_router, "supabase", _Supabase(state))
    monkeypatch.setattr(auth_router, "resolve_tenant_id", lambda *_a, **_k: "tenant-new")

    user = {
        "user_id": "brand-new-user-id",
        "email": "newperson@example.com",
        "user_metadata": {"full_name": "New Person"},
    }

    result = await auth_router.sync_user(_Request(), Response(), user=user)

    assert result.status == "created"
    assert any(table == "users" for table, _payload in state["upsert_calls"])


def test_auto_create_twin_blocked_by_signups_disabled(monkeypatch):
    """auto_create_twin (new-signups entrypoint) must short-circuit with 503
    before doing any auth/tenant resolution work."""
    import asyncio

    from routers import auto_create

    monkeypatch.setenv("SIGNUPS_ENABLED", "false")

    request = auto_create.AutoCreateRequest(name="Ada Lovelace")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(auto_create.auto_create_twin(request, user=None))

    assert exc_info.value.status_code == 503


def test_update_persona_declines_when_agent_edits_disabled(monkeypatch):
    """update_persona must reject in-character (not raise, not silently
    write) when AGENT_EDITS_ENABLED=false, and must never reach Supabase."""
    import asyncio

    from adk_core.tools.persona_edit_tools import _make_update_persona_tool

    monkeypatch.setenv("AGENT_EDITS_ENABLED", "false")

    calls = []

    def _fail_if_called():
        calls.append(True)
        raise AssertionError("get_supabase_client should not be called when edits are disabled")

    import adk_core.tools.persona_edit_tools as persona_edit_tools_module
    monkeypatch.setattr(persona_edit_tools_module, "get_supabase_client", _fail_if_called)

    tool = _make_update_persona_tool("twin-1")
    result = asyncio.run(tool.func(field="headline", value="New headline"))

    assert result["status"] == "rejected"
    assert calls == []


def test_update_persona_writes_when_agent_edits_enabled(monkeypatch):
    """Sanity check: with the switch enabled (default), a valid edit reaches
    the Supabase RPC and returns status=updated."""
    import asyncio
    from unittest.mock import MagicMock

    from adk_core.tools.persona_edit_tools import _make_update_persona_tool
    import adk_core.tools.persona_edit_tools as persona_edit_tools_module

    monkeypatch.setenv("AGENT_EDITS_ENABLED", "true")

    fake_client = MagicMock()
    monkeypatch.setattr(persona_edit_tools_module, "get_supabase_client", lambda: fake_client)

    tool = _make_update_persona_tool("twin-1")
    result = asyncio.run(tool.func(field="headline", value="New headline"))

    assert result["status"] == "updated"
    fake_client.rpc.assert_called_once_with(
        "update_persona_field",
        {"p_twin_id": "twin-1", "p_field": "headline", "p_value": "New headline"},
    )
