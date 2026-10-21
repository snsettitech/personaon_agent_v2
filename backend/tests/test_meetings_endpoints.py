"""
Tests for meetings REST endpoints (Phase 26-03).

Verifies:
- list_meetings returns summary field in select
- get_meeting returns analytics array alongside participants
- get_meeting returns summary_json from select("*")
- 403 is raised when twin ownership check fails
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Enable the feature flag so endpoints are not 404'd
os.environ["MEETING_INTELLIGENCE_ENABLED"] = "true"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routers.meetings import router  # noqa: E402


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _inject_user_middleware(app: FastAPI, user: dict | None = None) -> None:
    """Add middleware that injects user into request.state."""
    resolved = user or {"id": "tenant-1", "tenant_id": "tenant-1"}

    @app.middleware("http")
    async def _set_user(request, call_next):  # type: ignore[no-untyped-def]
        request.state.user = resolved
        return await call_next(request)


def _chain(data) -> MagicMock:
    """Return a fluent Supabase query chain that resolves to data."""
    result = SimpleNamespace(data=data)
    m = MagicMock()
    m.select.return_value = m
    m.eq.return_value = m
    m.order.return_value = m
    m.limit.return_value = m
    m.single.return_value = m
    m.maybe_single.return_value = m
    m.execute.return_value = result
    return m


# ---------------------------------------------------------------------------
# Tests — list_meetings
# ---------------------------------------------------------------------------

def test_list_meetings_includes_summary() -> None:
    """list_meetings select call must include the 'summary' column."""
    captured_select: list[str] = []

    twin_chain = _chain([{"id": "twin-1"}])
    meetings_chain = MagicMock()

    def _capture_select(cols: str) -> MagicMock:
        captured_select.append(cols)
        return meetings_chain

    meetings_chain.select.side_effect = _capture_select
    meetings_chain.eq.return_value = meetings_chain
    meetings_chain.order.return_value = meetings_chain
    meetings_chain.limit.return_value = meetings_chain
    meetings_chain.execute.return_value = SimpleNamespace(data=[])

    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: twin_chain if name == "twins" else meetings_chain

    with patch("routers.meetings.supabase", mock_sb):
        app = _build_app()
        _inject_user_middleware(app)
        client = TestClient(app)
        resp = client.get("/v2/meetings/twin-1")

    assert resp.status_code == 200, resp.text
    assert captured_select, "select() was never called on meetings table"
    assert "summary" in captured_select[0], (
        f"'summary' missing from select cols: {captured_select[0]!r}"
    )


# ---------------------------------------------------------------------------
# Tests — get_meeting
# ---------------------------------------------------------------------------

def test_get_meeting_detail_includes_analytics() -> None:
    """get_meeting response must contain an 'analytics' key in data."""
    analytics_row = {
        "participant_name": "Alice",
        "talk_time_seconds": 120.0,
        "talk_time_pct": 60.0,
        "word_count": 200,
        "words_per_minute": 100.0,
        "filler_word_count": 3,
        "sentiment_label": "positive",
        "sentiment_score": 0.8,
    }
    meeting_row = {"id": "mtg-1", "title": "Kickoff", "summary_json": None}

    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: {
        "twins": _chain([{"id": "twin-1"}]),
        "meetings": _chain(meeting_row),
        "meeting_participants": _chain([]),
        "meeting_analytics": _chain([analytics_row]),
    }.get(name, _chain([]))

    with patch("routers.meetings.supabase", mock_sb):
        app = _build_app()
        _inject_user_middleware(app)
        client = TestClient(app)
        resp = client.get("/v2/meetings/twin-1/mtg-1")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "analytics" in body["data"], "response data missing 'analytics' key"
    assert len(body["data"]["analytics"]) == 1
    assert body["data"]["analytics"][0]["sentiment_label"] == "positive"


def test_get_meeting_detail_includes_summary_json() -> None:
    """get_meeting response must surface summary_json from the meetings row."""
    summary_json = {
        "recap": "Short meeting.",
        "topics": ["budget"],
        "action_items": [],
        "unanswered_questions": [],
    }
    meeting_row = {
        "id": "mtg-2",
        "title": "Budget Review",
        "summary": "Short meeting.",
        "summary_json": summary_json,
    }

    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: {
        "twins": _chain([{"id": "twin-1"}]),
        "meetings": _chain(meeting_row),
        "meeting_participants": _chain([]),
        "meeting_analytics": _chain([]),
    }.get(name, _chain([]))

    with patch("routers.meetings.supabase", mock_sb):
        app = _build_app()
        _inject_user_middleware(app)
        client = TestClient(app)
        resp = client.get("/v2/meetings/twin-1/mtg-2")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["summary_json"] == summary_json


# ---------------------------------------------------------------------------
# Tests — ownership / auth
# ---------------------------------------------------------------------------

def test_get_meeting_403_wrong_tenant() -> None:
    """list_meetings returns 403 when twin ownership check fails (empty data)."""
    mock_sb = MagicMock()
    # Twin ownership check returns empty — not owned by this tenant
    mock_sb.table.side_effect = lambda name: (
        _chain([]) if name == "twins" else _chain([])
    )

    with patch("routers.meetings.supabase", mock_sb):
        app = _build_app()
        _inject_user_middleware(app)
        client = TestClient(app)
        resp = client.get("/v2/meetings/twin-other")

    assert resp.status_code == 403


def test_get_meeting_404_when_not_owned() -> None:
    """A meeting that doesn't belong to the caller is filtered out by the
    tenant_id predicate, leaving 0 rows. The endpoint must return a clean 404,
    NOT a 500. Regression guard for the .single()->.maybe_single() fix: .single()
    RAISES on 0 rows (bubbling up as 500); .maybe_single() returns data=None so
    the 404 path fires. Here the mock simulates real PostgREST by making
    .single() raise while .maybe_single() yields data=None."""
    def _meetings_no_rows() -> MagicMock:
        m = MagicMock()
        m.select.return_value = m
        m.eq.return_value = m
        m.order.return_value = m
        m.limit.return_value = m
        # Real supabase: .single() on 0 rows raises -> would surface as 500.
        m.single.side_effect = AssertionError("single() must not be used — use maybe_single()")
        m.maybe_single.return_value = m
        m.execute.return_value = SimpleNamespace(data=None)
        return m

    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: _meetings_no_rows() if name == "meetings" else _chain([])

    with patch("routers.meetings.supabase", mock_sb):
        app = _build_app()
        _inject_user_middleware(app)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/v2/meetings/twin-1/mtg-missing")

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "Meeting not found"


def test_list_meetings_401_no_user() -> None:
    """list_meetings returns 401 when request.state.user is absent."""
    mock_sb = MagicMock()

    with patch("routers.meetings.supabase", mock_sb):
        app = _build_app()
        # No middleware — state.user is absent
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/v2/meetings/twin-1")

    assert resp.status_code == 401
