"""Tests for Phase 4 polish: cockpit engagement + CSV export."""
from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import modules.posthog_query as pq
import routers.admin._common as admin_common
from modules.auth_guard import require_admin
from routers.admin import router as admin_router
from tests._supabase_mock import fluent

ADMIN = {"user_id": "a1", "tenant_id": "a1", "email": "a@personaon.com", "actual_role": "owner"}


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router)
    app.dependency_overrides[require_admin] = lambda: ADMIN
    return app


def test_engagement_builds_funnel(monkeypatch) -> None:
    monkeypatch.setattr(
        pq, "get_event_counts",
        lambda events, days=30: {"user_signup": 10, "onboarding_started": 6, "onboarding_published": 4, "chat_message_sent": 3},
    )
    monkeypatch.setattr(pq, "get_weekly_active", lambda weeks=8: [{"date": "2026-06-01", "count": 5}])

    resp = TestClient(_app()).get("/admin/cockpit/engagement")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["funnel"][0] == {"step": "Signed up", "event": "user_signup", "count": 10}
    assert body["weekly_active"][0]["count"] == 5


def test_engagement_null_without_key(monkeypatch) -> None:
    monkeypatch.setattr(pq, "get_event_counts", lambda events, days=30: None)
    monkeypatch.setattr(pq, "get_weekly_active", lambda weeks=8: None)
    resp = TestClient(_app()).get("/admin/cockpit/engagement")
    assert resp.status_code == 200
    assert resp.json()["funnel"] is None


def test_users_export_csv(monkeypatch) -> None:
    sb = MagicMock()
    sb.table.return_value = fluent([
        {"id": "u1", "email": "u@e.com", "full_name": "U", "role": "viewer", "plan": "free", "created_at": "2026-01-01", "last_active_at": None},
    ])
    monkeypatch.setattr(admin_common, "get_supabase_client", lambda: sb)

    resp = TestClient(_app()).get("/admin/users/export")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert resp.text.startswith("id,email")
    assert "u@e.com" in resp.text
