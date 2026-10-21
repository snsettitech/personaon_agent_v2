"""Tests for the admin access gate: @personaon.com email OR explicit admin/support role.

The broad 'owner' role must NOT grant admin access.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import modules.observability as obs
from modules.auth_guard import _is_admin_email, require_admin, require_admin_write, require_tenant


def test_is_admin_email() -> None:
    assert _is_admin_email("jane@personaon.com")
    assert _is_admin_email("Jane@PersonaOn.Com")
    assert not _is_admin_email("jane@gmail.com")
    assert not _is_admin_email(None)
    assert not _is_admin_email("")


def _app(tenant_user: dict) -> FastAPI:
    app = FastAPI()

    @app.get("/r")
    def _read(u: dict = Depends(require_admin)) -> dict:
        return {"role": u.get("actual_role"), "domain": u.get("is_admin_email")}

    @app.post("/w")
    def _write(u: dict = Depends(require_admin_write)) -> dict:
        return {"ok": True}

    app.dependency_overrides[require_tenant] = lambda: tenant_user
    return app


def _mock_role(monkeypatch, role: str) -> None:
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
        SimpleNamespace(data=[{"role": role}])
    )
    monkeypatch.setattr(obs, "get_supabase_client", lambda: sb)


def test_personaon_email_grants_read_and_write(monkeypatch) -> None:
    _mock_role(monkeypatch, "viewer")  # role irrelevant; domain wins
    client = TestClient(_app({"user_id": "u1", "tenant_id": "u1", "email": "jane@personaon.com"}))
    assert client.get("/r").status_code == 200
    assert client.post("/w").status_code == 200


def test_gmail_viewer_denied(monkeypatch) -> None:
    _mock_role(monkeypatch, "viewer")
    client = TestClient(_app({"user_id": "u2", "tenant_id": "u2", "email": "bob@gmail.com"}))
    assert client.get("/r").status_code == 403


def test_owner_role_no_longer_grants_admin(monkeypatch) -> None:
    _mock_role(monkeypatch, "owner")
    client = TestClient(_app({"user_id": "u3", "tenant_id": "u3", "email": "someone@gmail.com"}))
    assert client.get("/r").status_code == 403


def test_explicit_admin_role_on_non_domain_allowed(monkeypatch) -> None:
    _mock_role(monkeypatch, "admin")
    client = TestClient(_app({"user_id": "u4", "tenant_id": "u4", "email": "contractor@gmail.com"}))
    assert client.get("/r").status_code == 200
    assert client.post("/w").status_code == 200


def test_support_role_read_only(monkeypatch) -> None:
    _mock_role(monkeypatch, "support")
    client = TestClient(_app({"user_id": "u5", "tenant_id": "u5", "email": "help@gmail.com"}))
    assert client.get("/r").status_code == 200
    assert client.post("/w").status_code == 403  # support cannot write
