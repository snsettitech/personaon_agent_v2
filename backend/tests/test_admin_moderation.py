"""Tests for admin moderation endpoints (/admin/moderation/*, takedown/restore)."""
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


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router)
    app.dependency_overrides[require_admin] = lambda: OWNER
    return app


def test_list_personas_public_flag(monkeypatch) -> None:
    sb = MagicMock()
    sb.table.return_value = fluent([{"id": "t1", "status": "active", "is_active": True, "settings": {}}])
    monkeypatch.setattr(admin_common, "get_supabase_client", lambda: sb)
    resp = TestClient(_app()).get("/admin/moderation/twins")
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["public"] is True
    assert body[0]["taken_down"] is False


def test_takedown_sets_deleted_at(monkeypatch) -> None:
    select_chain = fluent([{"id": "t1", "name": "X", "status": "active", "is_active": True, "settings": {}}])
    update_chain = fluent([{"id": "t1"}])
    cap: dict = {}
    update_chain.update.side_effect = lambda payload: (cap.update(payload) or update_chain)
    sb = MagicMock()
    sb.table.side_effect = [select_chain, update_chain]
    monkeypatch.setattr(admin_common, "get_supabase_client", lambda: sb)
    monkeypatch.setattr(aa, "record_admin_action", lambda **kw: True)

    resp = TestClient(_app()).post("/admin/twins/t1/takedown", json={"reason": "spam"})
    assert resp.status_code == 200, resp.text
    assert cap["is_active"] is False
    assert cap["settings"]["deleted_at"]
    assert cap["settings"]["moderation_takedown"]["reason"] == "spam"


def test_restore_clears_markers(monkeypatch) -> None:
    select_chain = fluent([
        {"id": "t1", "settings": {"deleted_at": "x", "moderation_takedown": {"a": 1}, "keep": 2}}
    ])
    update_chain = fluent([{"id": "t1"}])
    cap: dict = {}
    update_chain.update.side_effect = lambda payload: (cap.update(payload) or update_chain)
    sb = MagicMock()
    sb.table.side_effect = [select_chain, update_chain]
    monkeypatch.setattr(admin_common, "get_supabase_client", lambda: sb)
    monkeypatch.setattr(aa, "record_admin_action", lambda **kw: True)

    resp = TestClient(_app()).post("/admin/twins/t1/restore")
    assert resp.status_code == 200, resp.text
    assert "deleted_at" not in cap["settings"]
    assert "moderation_takedown" not in cap["settings"]
    assert cap["settings"]["keep"] == 2
    assert cap["is_active"] is True
