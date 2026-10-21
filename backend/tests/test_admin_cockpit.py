"""Tests for the admin cockpit endpoints (/admin/cockpit/*)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import modules.cockpit_metrics as cm
import modules.posthog_query as pq
import modules.revenue_metrics as rm
from modules.auth_guard import require_admin
from routers.admin import router as admin_router

ADMIN = {"user_id": "a1", "tenant_id": "a1", "email": "a@personaon.com", "actual_role": "owner"}


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router)
    app.dependency_overrides[require_admin] = lambda: ADMIN
    return app


def test_cockpit_summary_aggregates(monkeypatch) -> None:
    monkeypatch.setattr(cm, "get_summary", lambda: {"users": {"total": 3}})
    monkeypatch.setattr(cm, "get_plan_distribution", lambda: {"free": 3})
    monkeypatch.setattr(rm, "get_revenue_summary", lambda: {"mrr": 44.97})
    monkeypatch.setattr(pq, "get_dau", lambda: 2)
    monkeypatch.setattr(pq, "get_mau", lambda: 5)

    client = TestClient(_app())
    resp = client.get("/admin/cockpit/summary")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ops"]["users"]["total"] == 3
    assert body["plans"] == {"free": 3}
    assert body["revenue"]["mrr"] == 44.97
    assert body["engagement"] == {"dau": 2, "mau": 5}


def test_cockpit_timeseries_zero_filled(monkeypatch) -> None:
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date().isoformat()
    chain = MagicMock()
    for m in ("select", "gte", "limit"):
        getattr(chain, m).return_value = chain
    chain.execute.return_value = SimpleNamespace(
        data=[{"created_at": f"{today}T10:00:00Z"}, {"created_at": f"{today}T11:00:00Z"}]
    )
    sb = MagicMock()
    sb.table.return_value = chain
    monkeypatch.setattr(cm, "get_supabase_client", lambda: sb)

    client = TestClient(_app())
    resp = client.get("/admin/cockpit/timeseries?metric=signups&days=7")
    assert resp.status_code == 200
    series = resp.json()
    assert len(series) == 7
    assert series[-1]["date"] == today
    assert series[-1]["count"] == 2
