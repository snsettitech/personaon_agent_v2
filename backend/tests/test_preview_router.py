"""Tests for GET /v2/twins/{twin_id}/preview."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import twins_preview
from tests._supabase_mock import fluent, result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TWIN_ID = "twin-abc"
USER = {"user_id": "user-123", "email": "owner@example.com"}

TWIN_ROW = {"display_name": "Ada Lovelace", "public_share_enabled": True}


def _make_app(supabase_mock: MagicMock) -> TestClient:
    """Spin up a minimal FastAPI app with the preview router, DI overrides applied."""
    app = FastAPI()
    app.include_router(twins_preview.router)

    # Override auth dependencies so no real JWT validation occurs
    app.dependency_overrides[twins_preview.verify_owner] = lambda: USER

    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_preview_returns_shape_with_no_meetings():
    """Owner gets PreviewOut shape even when twin has zero public meetings."""
    # maybe_single() path returns a single dict; meetings query returns []
    sb = MagicMock()

    # First chain: twins table — maybe_single path
    twins_chain = MagicMock()
    for method in ("table", "select", "eq", "maybe_single"):
        getattr(twins_chain, method).return_value = twins_chain
    twins_chain.execute.return_value = result(TWIN_ROW)

    # Second chain: meetings table — returns empty list
    meetings_chain = MagicMock()
    for method in ("table", "select", "eq", "neq", "order", "limit"):
        getattr(meetings_chain, method).return_value = meetings_chain
    meetings_chain.execute.return_value = result([])

    def _table(name: str):
        return twins_chain if name == "twins" else meetings_chain

    sb.table.side_effect = _table

    client = _make_app(sb)

    with (
        patch("routers.twins_preview.supabase", sb),
        patch("routers.twins_preview.verify_twin_ownership", return_value=None),
        patch("routers.twins_preview.ph_capture", return_value=None),
    ):
        resp = client.get(f"/v2/twins/{TWIN_ID}/preview")

    assert resp.status_code == 200
    body = resp.json()
    assert body["twin_name"] == "Ada Lovelace"
    assert body["public_meetings"] == []
    assert body["visitor_questions"] == []
    assert body["public_share_enabled"] is True


def test_preview_returns_404_when_twin_missing():
    """Returns 404 when the twins table returns no row."""
    sb = MagicMock()

    twins_chain = MagicMock()
    for method in ("table", "select", "eq", "maybe_single"):
        getattr(twins_chain, method).return_value = twins_chain
    # maybe_single with no match → data is None
    twins_chain.execute.return_value = result(None)

    sb.table.return_value = twins_chain

    client = _make_app(sb)

    with (
        patch("routers.twins_preview.supabase", sb),
        patch("routers.twins_preview.verify_twin_ownership", return_value=None),
        patch("routers.twins_preview.ph_capture", return_value=None),
    ):
        resp = client.get(f"/v2/twins/{TWIN_ID}/preview")

    assert resp.status_code == 404


def test_preview_derives_visitor_questions_from_topics():
    """Visitor questions are generated from summary_json.topics of recent meetings."""
    sb = MagicMock()

    twins_chain = MagicMock()
    for method in ("table", "select", "eq", "maybe_single"):
        getattr(twins_chain, method).return_value = twins_chain
    twins_chain.execute.return_value = result(TWIN_ROW)

    meeting_row = {
        "id": "m1",
        "title": "Q1 Review",
        "public_share_enabled": True,
        "summary_json": {"tldr": "...", "topics": ["machine learning", "hiring"]},
        "recap_extras_json": None,
    }

    meetings_chain = MagicMock()
    for method in ("table", "select", "eq", "neq", "order", "limit"):
        getattr(meetings_chain, method).return_value = meetings_chain
    meetings_chain.execute.return_value = result([meeting_row])

    def _table(name: str):
        return twins_chain if name == "twins" else meetings_chain

    sb.table.side_effect = _table

    client = _make_app(sb)

    with (
        patch("routers.twins_preview.supabase", sb),
        patch("routers.twins_preview.verify_twin_ownership", return_value=None),
        patch("routers.twins_preview.ph_capture", return_value=None),
    ):
        resp = client.get(f"/v2/twins/{TWIN_ID}/preview")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["public_meetings"]) == 1
    assert any("machine learning" in q for q in body["visitor_questions"])
    assert any("hiring" in q for q in body["visitor_questions"])
