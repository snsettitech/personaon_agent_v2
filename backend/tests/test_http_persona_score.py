"""Integration tests for persona score HTTP endpoints.

Tests the full HTTP request/response cycle through FastAPI for
GET /v2/twins/{id}/score with mocked external services.
"""

import pytest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

TWIN_ID = "test-twin-001"
FAKE_USER = {"user_id": "test-user", "tenant_id": "test-tenant"}


def _make_supabase_mock(twin_data=None):
    """Build a mock Supabase client that returns twin_data for twins table."""
    mock_sb = MagicMock()
    resp = MagicMock()
    resp.data = twin_data
    mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = resp

    # For adk_messages count query (interview scoring)
    msg_resp = MagicMock()
    msg_resp.count = 0
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = msg_resp

    return mock_sb


@pytest.fixture()
def app_with_auth():
    """Create app with auth overrides and cleanup."""
    from modules.auth_guard import require_tenant
    from main import app

    app.dependency_overrides[require_tenant] = lambda: FAKE_USER
    yield app
    app.dependency_overrides.clear()


@pytest.fixture()
def client(app_with_auth):
    return TestClient(app_with_auth)


# ── Tests ─────────────────────────────────────────────────────────────


class TestPersonaScore200:
    """GET /v2/twins/{id}/score returns 200 with valid breakdown."""

    def test_returns_valid_breakdown(self, client):
        twin_data = {
            "id": TWIN_ID,
            "name": "Test Persona",
            "settings": {
                "persona_profile": {
                    "name": "Test Persona",
                    "occupation": "Engineer",
                    "education": "MIT",
                    "work_experience": "10 years",
                    "achievements": "Award winner",
                },
                "voice_id": "v-123",
            },
        }
        mock_sb = _make_supabase_mock(twin_data)

        with patch("routers.persona_score.get_supabase_client", return_value=mock_sb), \
             patch("routers.persona_score.verify_twin_ownership", return_value=True), \
             patch("adk_core.services.vector_store.namespace_stats", return_value={"vector_count": 60}):

            resp = client.get(f"/v2/twins/{TWIN_ID}/score")

        assert resp.status_code == 200
        body = resp.json()
        assert "score" in body
        assert "max" in body
        assert "label" in body
        assert "breakdown" in body
        assert body["max"] == 100

    def test_response_schema_fields(self, client):
        twin_data = {
            "id": TWIN_ID,
            "name": "Test",
            "settings": {"persona_profile": {"name": "Test"}},
        }
        mock_sb = _make_supabase_mock(twin_data)

        with patch("routers.persona_score.get_supabase_client", return_value=mock_sb), \
             patch("routers.persona_score.verify_twin_ownership", return_value=True), \
             patch("adk_core.services.vector_store.namespace_stats", return_value={"vector_count": 0}):

            resp = client.get(f"/v2/twins/{TWIN_ID}/score")

        body = resp.json()
        breakdown = body["breakdown"]
        for section in ("profile", "knowledge", "interview", "voice"):
            assert section in breakdown, f"Missing breakdown section: {section}"
            assert "score" in breakdown[section]
            assert "max" in breakdown[section]
            assert "status" in breakdown[section]


class TestPersonaScoreEmpty:
    """Empty profile returns a low score."""

    def test_empty_profile_low_score(self, client):
        twin_data = {
            "id": TWIN_ID,
            "name": "Empty Twin",
            "settings": {},
        }
        mock_sb = _make_supabase_mock(twin_data)

        with patch("routers.persona_score.get_supabase_client", return_value=mock_sb), \
             patch("routers.persona_score.verify_twin_ownership", return_value=True), \
             patch("adk_core.services.vector_store.namespace_stats", return_value={"vector_count": 0}):

            resp = client.get(f"/v2/twins/{TWIN_ID}/score")

        assert resp.status_code == 200
        body = resp.json()
        assert body["score"] == 0
        assert body["label"] == "Early"
        assert body["breakdown"]["profile"]["status"] == "empty"
        assert body["breakdown"]["knowledge"]["status"] == "empty"
        assert body["breakdown"]["voice"]["status"] == "missing"


class TestPersonaScoreFullProfile:
    """Full profile + vectors + voice returns a high score."""

    def test_full_profile_high_score(self, client):
        twin_data = {
            "id": TWIN_ID,
            "name": "Full Persona",
            "settings": {
                "persona_profile": {
                    "name": "Full Persona",
                    "occupation": "CTO",
                    "education": "Stanford PhD",
                    "work_experience": "20 years at Google",
                    "achievements": "Founded 3 startups",
                },
                "voice_id": "v-full-123",
                "voice_name": "Full voice",
            },
        }
        mock_sb = _make_supabase_mock(twin_data)
        # Override adk_messages to show 25 exchanges
        msg_resp = MagicMock()
        msg_resp.count = 25
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = msg_resp

        with patch("routers.persona_score.get_supabase_client", return_value=mock_sb), \
             patch("routers.persona_score.verify_twin_ownership", return_value=True), \
             patch("adk_core.services.vector_store.namespace_stats", return_value={"vector_count": 60}):

            resp = client.get(f"/v2/twins/{TWIN_ID}/score")

        assert resp.status_code == 200
        body = resp.json()
        # Profile: 25/25, Knowledge: 35/35, Interview: 25/25, Voice: 15/15 = 100
        assert body["score"] >= 75, f"Expected high score, got {body['score']}"
        assert body["label"] in ("Highly Trained", "Expert")
        assert body["breakdown"]["profile"]["status"] == "complete"
        assert body["breakdown"]["voice"]["status"] == "cloned"


class TestPersonaScoreAuth:
    """Auth enforcement tests."""

    def test_401_without_auth(self):
        """No auth override — require_tenant should reject."""
        from main import app

        # Ensure no overrides
        app.dependency_overrides.clear()
        no_auth_client = TestClient(app, raise_server_exceptions=False)
        resp = no_auth_client.get(f"/v2/twins/{TWIN_ID}/score")
        assert resp.status_code == 401
