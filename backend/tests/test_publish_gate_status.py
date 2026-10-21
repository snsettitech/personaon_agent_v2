"""Publish-gate status for the dashboard banner (execution-board 0.6).

`modules.share_links.get_publish_gate_status` must reuse the exact same
content-quality signals as `is_marketplace_public_twin_record` (execution-
board 0.1) so the dashboard banner can never diverge from what actually
decides public reachability. These tests pin: (1) a thin/garbage profile
reports specific, non-generic reasons; (2) a complete profile passes with
zero reasons; (3) `POST /profile/publish` itself enforces the same gate
(closing the OR-bypass this endpoint previously had — it flipped
status=active unconditionally with no content check at all).
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from modules.auth_guard import require_tenant
from modules.share_links import get_publish_gate_status
from tests._supabase_mock import fluent

client = TestClient(app)


def _thin_twin() -> dict:
    return {
        "id": "twin-1",
        "name": "Jordan Casey",
        "settings": {
            "public_profile": {
                "display_name": "Jordan Casey",
                "occupation": "Software Engineer",
                "bio": "nill",
                "work_experience": [],
                "education": [],
            }
        },
    }


def _complete_twin() -> dict:
    return {
        "id": "twin-1",
        "name": "Jordan Casey",
        "settings": {
            "public_profile": {
                "display_name": "Jordan Casey",
                "occupation": "Software Engineer",
                "bio": "I help early-stage teams design pricing and packaging that actually converts.",
                "work_experience": [
                    {"company": "Acme Corp", "role": "Senior Engineer", "description": "Led the platform team."}
                ],
                "education": [],
            }
        },
    }


def test_gate_status_none_twin_fails_closed():
    status = get_publish_gate_status(None)
    assert status["passed"] is False
    assert status["reasons"]


def test_gate_status_reports_specific_bio_reason_not_generic():
    status = get_publish_gate_status(_thin_twin())
    assert status["passed"] is False
    # Reason must name the actual failure, not a generic "profile incomplete".
    assert any("sentence" in reason.lower() or "bio" in reason.lower() for reason in status["reasons"])


def test_gate_status_reports_missing_work_experience_or_education():
    status = get_publish_gate_status(_thin_twin())
    assert any("work experience" in reason.lower() or "education" in reason.lower() for reason in status["reasons"])


def test_gate_status_passes_for_complete_profile():
    status = get_publish_gate_status(_complete_twin())
    assert status["passed"] is True
    assert status["reasons"] == []


def _owner_user():
    return {"user_id": "owner-1", "tenant_id": "tenant-1", "role": "owner"}


def test_publish_gate_endpoint_returns_specific_reasons():
    app.dependency_overrides[require_tenant] = _owner_user
    try:
        with patch("routers.profile.get_or_create_profile_for_user", return_value={"id": "twin-1"}), \
             patch("routers.profile.supabase") as mocked_supabase:
            mocked_supabase.table.return_value = fluent(_thin_twin())
            response = client.get("/profile/publish-gate")
            assert response.status_code == 200
            body = response.json()
            assert body["passed"] is False
            assert len(body["reasons"]) > 0
    finally:
        app.dependency_overrides = {}


def test_publish_rejects_thin_profile_with_reasons_not_silent_flip():
    """POST /profile/publish must not flip status=active for a gate-failing
    profile — this endpoint previously had zero content-quality check."""
    app.dependency_overrides[require_tenant] = _owner_user
    try:
        with patch("routers.profile.verify_twin_ownership"), \
             patch("routers.profile.supabase") as mocked_supabase:
            mocked_supabase.table.return_value = fluent(_thin_twin())
            response = client.post("/profile/publish", json={"twin_id": "twin-1"})
            assert response.status_code == 400
            detail = response.json().get("detail", {})
            assert detail.get("code") == "PUBLISH_GATE_FAILED"
            assert detail.get("reasons")
    finally:
        app.dependency_overrides = {}


def test_publish_allows_complete_profile():
    app.dependency_overrides[require_tenant] = _owner_user
    try:
        twin_query = fluent(_complete_twin())
        with patch("routers.profile.verify_twin_ownership"), \
             patch("routers.profile.supabase") as mocked_supabase, \
             patch("routers.profile.ensure_share_token", return_value="tok123"):
            mocked_supabase.table.return_value = twin_query
            response = client.post("/profile/publish", json={"twin_id": "twin-1"})
            assert response.status_code == 200
            body = response.json()
            assert body["share_token"] == "tok123"
    finally:
        app.dependency_overrides = {}
