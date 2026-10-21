"""Tests for meeting search — Plan 27-03.

Covers:
  - _apply_source_weights: meeting down-weighting, null source_type, empty list, boundary case
  - search_meetings: only returns source_type="meeting" results
  - /v2/meetings/{twin_id}/search endpoint: result shape, missing q param
"""
import pytest
from unittest.mock import AsyncMock, patch

from adk_core.services.agent_service import _apply_source_weights


# ---------------------------------------------------------------------------
# _apply_source_weights tests
# ---------------------------------------------------------------------------

def test_apply_source_weights_meeting_downweighted():
    """Meeting row at 0.8 is down-weighted to 0.56; persona row at 0.7 stays 0.7; persona sorts first."""
    results = [
        {"text": "meeting chunk", "score": 0.8, "source_type": "meeting"},
        {"text": "persona chunk", "score": 0.7, "source_type": "persona"},
    ]
    weighted = _apply_source_weights(results)
    # Persona row (0.7) should sort above meeting row (0.8 * 0.7 = 0.56)
    assert weighted[0]["source_type"] == "persona"
    assert abs(weighted[0]["score"] - 0.7) < 1e-9
    assert weighted[1]["source_type"] == "meeting"
    assert abs(weighted[1]["score"] - 0.56) < 1e-6


def test_apply_source_weights_null_source_type():
    """Row with no source_type is treated as persona and is NOT down-weighted."""
    results = [
        {"text": "unknown chunk", "score": 0.6},
    ]
    weighted = _apply_source_weights(results)
    assert len(weighted) == 1
    assert abs(weighted[0]["score"] - 0.6) < 1e-9


def test_apply_source_weights_empty_list():
    """Empty input returns empty list without error."""
    assert _apply_source_weights([]) == []


def test_chunk_score_boundary():
    """Meeting row at 0.72 raw score becomes 0.504 after 0.7x weight, which is > CITATION_SCORE_THRESHOLD 0.50.

    This verifies the boundary: a meeting chunk with raw similarity 0.72 will still appear
    in citations after weighting (0.72 * 0.7 = 0.504 > 0.50).
    """
    results = [
        {"text": "meeting chunk at boundary", "score": 0.72, "source_type": "meeting"},
    ]
    weighted = _apply_source_weights(results)
    weighted_score = weighted[0]["score"]
    assert abs(weighted_score - 0.504) < 1e-6, f"Expected 0.504 got {weighted_score}"
    # Must be above the CITATION_SCORE_THRESHOLD of 0.50
    assert weighted_score > 0.50


# ---------------------------------------------------------------------------
# search_meetings: only returns meeting chunks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_only_returns_meeting_chunks(mock_pgvector_pool):
    """search_meetings() must return only rows with source_type='meeting'."""
    pool, conn = mock_pgvector_pool

    mock_row = {
        "content": "Budget discussion at Q1 meeting",
        "similarity": 0.85,
        "metadata": {
            "meeting_id": "meet-123",
            "speakers": ["Alice", "Bob"],
            "start_time": 120.0,
            "end_time": 145.0,
        },
    }
    conn.fetch = AsyncMock(return_value=[mock_row])

    with patch("adk_core.services.vector_store.get_pgvector_pool", return_value=pool):
        with patch("adk_core.services.vector_store.get_embedding", return_value=[0.1] * 768):
            from adk_core.services.vector_store import search_meetings
            results = await search_meetings("budget", "twin-abc", top_k=5)

    assert len(results) == 1
    result = results[0]
    assert result["source_type"] == "meeting"
    assert result["meeting_id"] == "meet-123"
    assert result["speakers"] == ["Alice", "Bob"]
    assert result["text"] == "Budget discussion at Q1 meeting"


# ---------------------------------------------------------------------------
# /v2/meetings/{twin_id}/search endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_meetings_endpoint_returns_results():
    """GET /v2/meetings/{twin_id}/search?q= returns 200 with expected response shape."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI, Request

    # Minimal app wiring
    app = FastAPI()

    # Stub auth: inject user into request.state
    @app.middleware("http")
    async def inject_user(request: Request, call_next):
        request.state.user = {"id": "user-1", "tenant_id": "tenant-1"}
        return await call_next(request)

    mock_results = [
        {
            "text": "We discussed the Q2 budget",
            "score": 0.88,
            "meeting_id": "meet-999",
            "speakers": ["Alice"],
            "start_time": 30.0,
            "end_time": 60.0,
            "source_type": "meeting",
        }
    ]

    with patch("adk_core.services.vector_store.get_pgvector_pool"):
        with patch("adk_core.services.vector_store.get_embedding", return_value=[0.1] * 768):
            with patch(
                "adk_core.services.vector_store.search_meetings",
                new=AsyncMock(return_value=mock_results),
            ):
                import os
                os.environ["MEETING_INTELLIGENCE_ENABLED"] = "true"

                from routers.meetings import router
                app.include_router(router)

                # Stub twin ownership
                with patch("routers.meetings.supabase") as mock_sb:
                    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
                        {"id": "twin-abc"}
                    ]

                    client = TestClient(app)
                    resp = client.get("/v2/meetings/twin-abc/search?q=budget")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "results" in body["data"]
    assert body["data"]["count"] == 1
    assert body["data"]["results"][0]["source_type"] == "meeting"


@pytest.mark.asyncio
async def test_search_meetings_endpoint_requires_query():
    """GET /v2/meetings/{twin_id}/search without q param returns 422."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI, Request
    import os

    os.environ["MEETING_INTELLIGENCE_ENABLED"] = "true"

    app = FastAPI()

    @app.middleware("http")
    async def inject_user(request: Request, call_next):
        request.state.user = {"id": "user-1", "tenant_id": "tenant-1"}
        return await call_next(request)

    from routers.meetings import router
    app.include_router(router)

    client = TestClient(app)
    resp = client.get("/v2/meetings/twin-abc/search")
    assert resp.status_code == 422
