"""Tests for POST /public/marketplace/ask — semantic cross-twin search."""

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


def _public_twin(twin_id: str, name: str, occupation: str) -> dict:
    """Build a marketplace-eligible twin row.

    Execution-board 0.1 (PRD R1): the marketplace gate now also requires a
    meaningful bio (40+ chars, 2+ words — modules.text_quality) and at least
    one populated work_experience/education entry, so this fixture needs
    real-looking content rather than a one-line placeholder bio.
    """
    return {
        "id": twin_id,
        "name": name,
        "status": "active",
        "is_active": True,
        "created_at": "2026-04-01T00:00:00Z",
        "settings": {
            "is_public": True,
            "handle": name.lower().replace(" ", "-"),
            "public_profile": {
                "display_name": name,
                "occupation": occupation,
                "short_description": f"{name} is an expert in {occupation}.",
                "bio": f"{name} has spent years working as a {occupation}, advising founders and building a track record in the space.",
                "work_experience": [
                    {"company": "Independent", "role": occupation, "description": f"Working as a {occupation}."}
                ],
            },
        },
    }


TWIN_A = _public_twin("aaaa-1111", "Alice Chen", "VC Partner")
TWIN_B = _public_twin("bbbb-2222", "Bob Smith", "Serial Founder")


@pytest.fixture()
def client():
    from main import app
    return TestClient(app)


# -- Helper: mock the entire vector search path --

def _mock_search_global(results: list[dict]):
    """Return an AsyncMock for search_global that yields given results."""
    mock = AsyncMock(return_value=results)
    return mock


class TestMarketplaceAsk:
    """POST /public/marketplace/ask tests."""

    @patch("routers.profile_public._fetch_marketplace_twin_rows")
    @patch("routers.profile_public._get_score_rows", return_value={})
    @patch("routers.profile_public._get_public_topics", return_value={})
    @patch("adk_core.services.vector_store.search_global")
    def test_returns_ranked_results(
        self,
        mock_search,
        mock_topics,
        mock_scores,
        mock_fetch_twins,
        client,
    ):
        mock_fetch_twins.return_value = [TWIN_A, TWIN_B]
        mock_search.return_value = [
            {"twin_id": "aaaa-1111", "text": "Series A requires strong metrics.", "score": 0.92, "source": "profile", "type": ""},
            {"twin_id": "bbbb-2222", "text": "I raised my first round in 2015.", "score": 0.85, "source": "profile", "type": ""},
        ]

        resp = client.post("/public/marketplace/ask", json={"question": "How do I raise a Series A?"})
        assert resp.status_code == 200

        data = resp.json()
        assert data["query"] == "How do I raise a Series A?"
        assert len(data["results"]) == 2

        # Best match first
        first = data["results"][0]
        assert first["persona"]["twin_id"] == "aaaa-1111"
        assert first["persona"]["display_name"] == "Alice Chen"
        assert first["relevance"] == 92.0
        assert "Series A" in first["snippet"]

        second = data["results"][1]
        assert second["persona"]["twin_id"] == "bbbb-2222"
        assert second["relevance"] == 85.0

    @patch("routers.profile_public._fetch_marketplace_twin_rows")
    @patch("adk_core.services.vector_store.search_global")
    def test_empty_results_when_no_public_twins(
        self,
        mock_search,
        mock_fetch_twins,
        client,
    ):
        mock_fetch_twins.return_value = []

        resp = client.post("/public/marketplace/ask", json={"question": "What is machine learning?"})
        assert resp.status_code == 200

        data = resp.json()
        assert data["results"] == []
        # search_global should not even be called
        mock_search.assert_not_called()

    @patch("routers.profile_public._fetch_marketplace_twin_rows")
    @patch("routers.profile_public._get_score_rows", return_value={})
    @patch("routers.profile_public._get_public_topics", return_value={})
    @patch("adk_core.services.vector_store.search_global")
    def test_deduplicates_by_twin_keeping_best_score(
        self,
        mock_search,
        mock_topics,
        mock_scores,
        mock_fetch_twins,
        client,
    ):
        mock_fetch_twins.return_value = [TWIN_A]
        # Two chunks from same twin — should keep only the best one
        mock_search.return_value = [
            {"twin_id": "aaaa-1111", "text": "Best answer about VC.", "score": 0.95, "source": "profile", "type": ""},
            {"twin_id": "aaaa-1111", "text": "Weaker answer about VC.", "score": 0.70, "source": "faq", "type": ""},
        ]

        resp = client.post("/public/marketplace/ask", json={"question": "Tell me about venture capital"})
        assert resp.status_code == 200

        data = resp.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["relevance"] == 95.0
        assert "Best answer" in data["results"][0]["snippet"]

    def test_rejects_short_question(self, client):
        resp = client.post("/public/marketplace/ask", json={"question": "Hi"})
        assert resp.status_code == 422  # Pydantic validation

    def test_rejects_missing_question(self, client):
        resp = client.post("/public/marketplace/ask", json={})
        assert resp.status_code == 422

    @patch("routers.profile_public._fetch_marketplace_twin_rows")
    @patch("adk_core.services.vector_store.search_global")
    def test_returns_503_on_vector_search_failure(
        self,
        mock_search,
        mock_fetch_twins,
        client,
    ):
        mock_fetch_twins.return_value = [TWIN_A]
        mock_search.side_effect = RuntimeError("pgvector connection failed")

        resp = client.post(
            "/public/marketplace/ask",
            json={"question": "How do I raise a Series A?"},
        )
        assert resp.status_code == 503

    @patch("routers.profile_public._fetch_marketplace_twin_rows")
    @patch("routers.profile_public._get_score_rows", return_value={})
    @patch("routers.profile_public._get_public_topics", return_value={})
    @patch("adk_core.services.vector_store.search_global")
    def test_respects_limit_parameter(
        self,
        mock_search,
        mock_topics,
        mock_scores,
        mock_fetch_twins,
        client,
    ):
        mock_fetch_twins.return_value = [TWIN_A, TWIN_B]
        mock_search.return_value = [
            {"twin_id": "aaaa-1111", "text": "Answer A.", "score": 0.9, "source": "", "type": ""},
            {"twin_id": "bbbb-2222", "text": "Answer B.", "score": 0.8, "source": "", "type": ""},
        ]

        resp = client.post(
            "/public/marketplace/ask",
            json={"question": "What about fundraising?", "limit": 1},
        )
        assert resp.status_code == 200
        assert len(resp.json()["results"]) == 1


class TestTruncateSnippet:
    """Unit tests for _truncate_snippet helper."""

    def test_extracts_first_two_sentences(self):
        from routers.profile_public import _truncate_snippet

        text = "First sentence. Second sentence. Third sentence."
        result = _truncate_snippet(text)
        assert "First sentence." in result
        assert "Second sentence." in result
        assert "Third" not in result

    def test_strips_markdown(self):
        from routers.profile_public import _truncate_snippet

        text = "**Bold** text ## heading here. Normal sentence."
        result = _truncate_snippet(text)
        assert "**" not in result
        assert "##" not in result

    def test_handles_empty_string(self):
        from routers.profile_public import _truncate_snippet

        assert _truncate_snippet("") == ""
        assert _truncate_snippet("   ") == ""

    def test_respects_max_length(self):
        from routers.profile_public import _truncate_snippet

        long_text = "A" * 500 + ". Second."
        result = _truncate_snippet(long_text)
        assert len(result) <= 300
