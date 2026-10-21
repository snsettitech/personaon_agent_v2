"""Tests for admin user-management endpoints (/admin/users/*)."""
from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import modules.admin_audit as aa
import routers.admin._common as admin_common
from modules.auth_guard import require_admin
from routers.admin import router as admin_router
from tests._supabase_mock import fluent

ADMIN = {"user_id": "a1", "tenant_id": "a1", "email": "a@personaon.com", "actual_role": "owner", "is_admin_email": True}


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router)
    app.dependency_overrides[require_admin] = lambda: ADMIN
    return app


def test_entitlements_rejects_bad_plan(monkeypatch) -> None:
    monkeypatch.setattr(admin_common, "get_supabase_client", lambda: MagicMock())
    resp = TestClient(_app()).post("/admin/users/u2/entitlements", json={"plan": "galaxy"})
    assert resp.status_code == 400


def test_entitlements_updates_plan_and_audits(monkeypatch) -> None:
    select_chain = fluent([{"plan": "free", "email": "u@e.com"}])
    update_chain = fluent([{"id": "u2"}])
    sb = MagicMock()
    sb.table.side_effect = [select_chain, update_chain]
    monkeypatch.setattr(admin_common, "get_supabase_client", lambda: sb)
    captured: dict = {}
    monkeypatch.setattr(aa, "record_admin_action", lambda **kw: captured.update(kw) or True)

    resp = TestClient(_app()).post("/admin/users/u2/entitlements", json={"plan": "business"})
    assert resp.status_code == 200, resp.text
    assert captured["action"] == aa.ACTION_PLAN_CHANGED
    assert captured["after"] == {"plan": "business"}


def test_grant_all_sets_business_and_flags(monkeypatch) -> None:
    select_chain = fluent([{"plan": "free", "email": "u@e.com"}])
    update_chain = fluent([{"id": "u2"}])
    sb = MagicMock()
    sb.table.side_effect = [select_chain, update_chain]
    monkeypatch.setattr(admin_common, "get_supabase_client", lambda: sb)
    monkeypatch.setattr(aa, "record_admin_action", lambda **kw: True)

    resp = TestClient(_app()).post("/admin/users/u2/grant-all")
    assert resp.status_code == 200, resp.text
    sb.auth.admin.update_user_by_id.assert_called_once()
    meta = sb.auth.admin.update_user_by_id.call_args[0][1]["user_metadata"]
    assert meta["flag_persona_v1"] is True


def test_suspend_bans_user(monkeypatch) -> None:
    sb = MagicMock()
    monkeypatch.setattr(admin_common, "get_supabase_client", lambda: sb)
    monkeypatch.setattr(aa, "record_admin_action", lambda **kw: True)

    resp = TestClient(_app()).post("/admin/users/u2/suspend")
    assert resp.status_code == 200
    sb.auth.admin.update_user_by_id.assert_called_once()
    assert sb.auth.admin.update_user_by_id.call_args[0][1]["ban_duration"]
