"""Tests for the GCP ops-alert ingestion webhook (POST /admin/ops/alerts/webhook/{source})
and the admin-authenticated listing endpoint (GET /admin/ops/alerts).
"""
from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.admin._common as admin_common
from modules.auth_guard import get_current_user, require_admin
from routers.admin import router as admin_router
from services import gcp_alert_auth
from tests._supabase_mock import fluent

OWNER = {"user_id": "owner1", "tenant_id": "owner1", "email": "o@personaon.com", "actual_role": "owner", "is_admin_email": True}


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router)
    app.dependency_overrides[require_admin] = lambda: OWNER
    return app


# ---------------------------------------------------------------------------
# services/gcp_alert_auth.py -- shared-secret verification
# ---------------------------------------------------------------------------


def test_gcp_alert_auth_rejects_when_secret_not_configured() -> None:
    with patch.object(gcp_alert_auth, "GCP_ALERT_WEBHOOK_SECRET", ""):
        assert gcp_alert_auth.verify_gcp_alert_webhook(secret_header="anything") is False


def test_gcp_alert_auth_rejects_when_no_carrier_supplied() -> None:
    with patch.object(gcp_alert_auth, "GCP_ALERT_WEBHOOK_SECRET", "s3cr3t"):
        assert gcp_alert_auth.verify_gcp_alert_webhook() is False


def test_gcp_alert_auth_accepts_matching_header() -> None:
    with patch.object(gcp_alert_auth, "GCP_ALERT_WEBHOOK_SECRET", "s3cr3t"):
        assert gcp_alert_auth.verify_gcp_alert_webhook(secret_header="s3cr3t") is True


def test_gcp_alert_auth_accepts_matching_query_param() -> None:
    with patch.object(gcp_alert_auth, "GCP_ALERT_WEBHOOK_SECRET", "s3cr3t"):
        assert gcp_alert_auth.verify_gcp_alert_webhook(secret_query_param="s3cr3t") is True


def test_gcp_alert_auth_accepts_matching_basic_auth_password() -> None:
    creds = base64.b64encode(b"gcp:s3cr3t").decode("utf-8")
    with patch.object(gcp_alert_auth, "GCP_ALERT_WEBHOOK_SECRET", "s3cr3t"):
        assert gcp_alert_auth.verify_gcp_alert_webhook(authorization_header=f"Basic {creds}") is True


def test_gcp_alert_auth_accepts_matching_bearer_token() -> None:
    # GCP's webhook_tokenauth channel type may send the configured token as
    # `Authorization: Bearer <token>` rather than Basic-Auth or a header —
    # the real behavior is unconfirmed (see gcp_alert_auth.py docstring), so
    # both shapes are accepted defensively.
    with patch.object(gcp_alert_auth, "GCP_ALERT_WEBHOOK_SECRET", "s3cr3t"):
        assert gcp_alert_auth.verify_gcp_alert_webhook(authorization_header="Bearer s3cr3t") is True


def test_gcp_alert_auth_rejects_wrong_secret() -> None:
    with patch.object(gcp_alert_auth, "GCP_ALERT_WEBHOOK_SECRET", "s3cr3t"):
        assert gcp_alert_auth.verify_gcp_alert_webhook(secret_header="wrong") is False


# ---------------------------------------------------------------------------
# POST /admin/ops/alerts/webhook/{source}
# ---------------------------------------------------------------------------


def test_webhook_rejects_unknown_source() -> None:
    with patch.object(gcp_alert_auth, "GCP_ALERT_WEBHOOK_SECRET", "s3cr3t"):
        resp = TestClient(_app()).post(
            "/admin/ops/alerts/webhook/not_a_real_source",
            headers={"x-ops-webhook-secret": "s3cr3t"},
            json={},
        )
    assert resp.status_code == 404


def test_webhook_rejects_missing_secret() -> None:
    with patch.object(gcp_alert_auth, "GCP_ALERT_WEBHOOK_SECRET", "s3cr3t"):
        resp = TestClient(_app()).post("/admin/ops/alerts/webhook/gcp_uptime", json={})
    assert resp.status_code == 401


def test_webhook_ingests_uptime_incident(monkeypatch) -> None:
    insert_chain = fluent([{
        "id": "a1", "source": "gcp_uptime", "severity": "critical",
        "title": "Uptime check failed", "detail": {}, "created_at": "now", "resolved_at": None,
    }])
    sb = MagicMock()
    sb.table.return_value = insert_chain
    monkeypatch.setattr(admin_common, "get_supabase_client", lambda: sb)

    payload = {
        "incident": {
            "incident_id": "0.abcdef",
            "resource_name": "personaon.com uptime",
            "state": "open",
            "summary": "Uptime check failed",
            "condition_name": "uptime-check",
        },
        "version": "1.2",
    }
    with patch.object(gcp_alert_auth, "GCP_ALERT_WEBHOOK_SECRET", "s3cr3t"):
        resp = TestClient(_app()).post(
            "/admin/ops/alerts/webhook/gcp_uptime",
            headers={"x-ops-webhook-secret": "s3cr3t"},
            json=payload,
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    insert_chain.insert.assert_called_once()
    inserted_row = insert_chain.insert.call_args[0][0]
    assert inserted_row["source"] == "gcp_uptime"
    assert inserted_row["severity"] == "critical"
    assert inserted_row["title"] == "Uptime check failed"


def test_webhook_ingests_uptime_incident_with_uppercase_state(monkeypatch) -> None:
    """Regression guard: severity computation must not be case-sensitive.
    GCP's real `incident.state` casing was never verified against a live
    payload (see GcpAlertIncidentPayload docstring) -- an exact-lowercase
    match would silently downgrade a genuinely open incident to 'info'."""
    insert_chain = fluent([{
        "id": "a3", "source": "gcp_billing", "severity": "critical",
        "title": "Budget exceeded", "detail": {}, "created_at": "now", "resolved_at": None,
    }])
    sb = MagicMock()
    sb.table.return_value = insert_chain
    monkeypatch.setattr(admin_common, "get_supabase_client", lambda: sb)

    payload = {
        "incident": {
            "incident_id": "0.ghijkl",
            "state": " OPEN ",
            "summary": "Budget exceeded",
        },
    }
    with patch.object(gcp_alert_auth, "GCP_ALERT_WEBHOOK_SECRET", "s3cr3t"):
        resp = TestClient(_app()).post(
            "/admin/ops/alerts/webhook/gcp_billing",
            headers={"x-ops-webhook-secret": "s3cr3t"},
            json=payload,
        )
    assert resp.status_code == 200, resp.text
    inserted_row = insert_chain.insert.call_args[0][0]
    assert inserted_row["severity"] == "critical"


def test_webhook_accepts_empty_body_permissively(monkeypatch) -> None:
    """Permissive-fallback contract: an unrecognized/empty body must not 422."""
    insert_chain = fluent([{"id": "a2"}])
    sb = MagicMock()
    sb.table.return_value = insert_chain
    monkeypatch.setattr(admin_common, "get_supabase_client", lambda: sb)

    with patch.object(gcp_alert_auth, "GCP_ALERT_WEBHOOK_SECRET", "s3cr3t"):
        resp = TestClient(_app()).post(
            "/admin/ops/alerts/webhook/gcp_billing",
            headers={"x-ops-webhook-secret": "s3cr3t"},
        )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# GET /admin/ops/alerts
# ---------------------------------------------------------------------------


def test_list_ops_alerts_returns_data_shape_for_admin(monkeypatch) -> None:
    """Happy-path response shape when require_admin is satisfied. This does NOT
    exercise admin enforcement -- _app() unconditionally overrides require_admin,
    so a caller reaching this branch is already assumed to be an admin. Actual
    enforcement is covered by test_list_ops_alerts_rejects_unauthenticated_request
    and test_list_ops_alerts_rejects_non_admin_user below, which exercise the
    real require_admin dependency instead of the test-harness override."""
    sb = MagicMock()
    sb.table.return_value = fluent([
        {"id": "a1", "source": "gcp_uptime", "severity": "critical", "title": "x", "detail": {}, "created_at": "now", "resolved_at": None},
    ])
    monkeypatch.setattr(admin_common, "get_supabase_client", lambda: sb)
    resp = TestClient(_app()).get("/admin/ops/alerts")
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["source"] == "gcp_uptime"


def test_list_ops_alerts_rejects_unauthenticated_request() -> None:
    """Regression guard for the finding that test_list_ops_alerts_requires_admin
    never exercised the real require_admin dependency (it was always bypassed
    via app.dependency_overrides). This test builds an app with NO override, so
    a request with no Authorization header must be rejected by the real
    get_current_user -> require_tenant -> require_admin chain."""
    app = FastAPI()
    app.include_router(admin_router)
    resp = TestClient(app).get("/admin/ops/alerts")
    assert resp.status_code == 401


def test_list_ops_alerts_surfaces_db_error_instead_of_empty_list(monkeypatch) -> None:
    """Regression guard: a DB error (e.g. ops_alerts table/migration missing)
    must NOT be silently swallowed into an empty 200 response -- that would be
    indistinguishable from a genuinely healthy 'no alerts' state on the admin
    page. Mirrors the POST webhook's existing 500-on-DB-error behavior."""
    sb = MagicMock()
    broken_chain = fluent([])
    broken_chain.execute.side_effect = RuntimeError("relation \"ops_alerts\" does not exist")
    sb.table.return_value = broken_chain
    monkeypatch.setattr(admin_common, "get_supabase_client", lambda: sb)

    resp = TestClient(_app()).get("/admin/ops/alerts")
    assert resp.status_code == 500


def test_list_ops_alerts_rejects_non_admin_user(monkeypatch) -> None:
    """An authenticated caller who is neither an @<ADMIN_EMAIL_DOMAIN> address nor
    an admin/support role must be rejected (403) by the real require_admin
    dependency, not merely accepted because the test harness overrode it."""
    role_lookup = fluent([{"role": "viewer"}])
    sb = MagicMock()
    sb.table.return_value = role_lookup
    monkeypatch.setattr("modules.observability.get_supabase_client", lambda: sb)

    non_admin_user = {"user_id": "u1", "tenant_id": "u1", "email": "someone@example.com"}
    app = FastAPI()
    app.include_router(admin_router)
    app.dependency_overrides[get_current_user] = lambda: non_admin_user
    resp = TestClient(app).get("/admin/ops/alerts")
    assert resp.status_code == 403
