"""Tests for admin team & roles endpoints (/admin/team, /admin/users/{id}/role, /admin/audit)."""
from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import modules.admin_audit as aa
import routers.admin._common as admin_common
from modules.auth_guard import require_admin
from routers.admin import router as admin_router
from tests._supabase_mock import fluent

OWNER = {"user_id": "owner1", "tenant_id": "owner1", "email": "o@personaon.com", "actual_role": "owner", "is_admin_email": True}
ADMIN = {"user_id": "admin1", "tenant_id": "admin1", "email": "ad@personaon.com", "actual_role": "admin", "is_admin_email": True}


def _app(actor: dict) -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router)
    app.dependency_overrides[require_admin] = lambda: actor
    return app


def test_change_role_happy(monkeypatch) -> None:
    select_chain = fluent([{"role": "viewer", "email": "u@e.com"}])
    update_chain = fluent([{"id": "u2"}])
    sb = MagicMock()
    sb.table.side_effect = [select_chain, update_chain]
    monkeypatch.setattr(admin_common, "get_supabase_client", lambda: sb)
    cap: dict = {}
    monkeypatch.setattr(aa, "record_admin_action", lambda **kw: cap.update(kw) or True)

    resp = TestClient(_app(OWNER)).put("/admin/users/u2/role", json={"role": "admin"})
    assert resp.status_code == 200, resp.text
    assert cap["action"] == aa.ACTION_ROLE_CHANGED
    assert cap["after"] == {"role": "admin"}


def test_change_role_rejects_invalid(monkeypatch) -> None:
    monkeypatch.setattr(admin_common, "get_supabase_client", lambda: MagicMock())
    resp = TestClient(_app(OWNER)).put("/admin/users/u2/role", json={"role": "king"})
    assert resp.status_code == 400


def test_only_owner_can_grant_owner(monkeypatch) -> None:
    monkeypatch.setattr(admin_common, "get_supabase_client", lambda: MagicMock())
    resp = TestClient(_app(ADMIN)).put("/admin/users/u2/role", json={"role": "owner"})
    assert resp.status_code == 403


def test_cannot_change_own_role(monkeypatch) -> None:
    monkeypatch.setattr(admin_common, "get_supabase_client", lambda: MagicMock())
    resp = TestClient(_app(OWNER)).put("/admin/users/owner1/role", json={"role": "admin"})
    assert resp.status_code == 400


def test_team_list(monkeypatch) -> None:
    sb = MagicMock()
    sb.table.return_value = fluent([{"id": "o1", "email": "o@e.com", "role": "owner"}])
    monkeypatch.setattr(admin_common, "get_supabase_client", lambda: sb)
    resp = TestClient(_app(OWNER)).get("/admin/team")
    assert resp.status_code == 200
    assert resp.json()["staff"][0]["role"] == "owner"


def test_audit_list(monkeypatch) -> None:
    sb = MagicMock()
    sb.table.return_value = fluent([{"id": "a1", "action": "user_plan_changed"}])
    monkeypatch.setattr(admin_common, "get_supabase_client", lambda: sb)
    resp = TestClient(_app(OWNER)).get("/admin/audit")
    assert resp.status_code == 200
    assert resp.json()[0]["action"] == "user_plan_changed"
