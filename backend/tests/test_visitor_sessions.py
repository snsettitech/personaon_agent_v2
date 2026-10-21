"""Tests for the visitor sessions router (Phase G.3 — owner-only).

Security assertions (CR-6):
- List / messages endpoints are owner-only (verify_owner dependency)
- All queries include .eq("tenant_id", ...) for tenant isolation
- Cross-tenant session_id returns 404 (no existence leak)
- tenant_id NEVER appears in response JSON (sanitization)
- Internal fields (tenant_id, metadata) not in VisitorSessionSummary output
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.auth_guard import verify_owner
from routers import visitor_sessions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(data: Any) -> SimpleNamespace:
    return SimpleNamespace(data=data)


def _app(user: dict[str, Any]) -> FastAPI:
    app = FastAPI()
    app.include_router(visitor_sessions.router)
    app.dependency_overrides[verify_owner] = lambda: user
    return app


OWNER = {
    "user_id": "00000000-0000-0000-0000-000000000001",
    "tenant_id": "00000000-0000-0000-0000-000000000002",
}
TWIN_ID = "00000000-0000-0000-0000-000000000003"
SESSION_ID = "00000000-0000-0000-0000-000000000004"


def _make_twin_ownership_mock() -> MagicMock:
    """Mock for modules.auth_guard.get_supabase_client that passes verify_twin_ownership."""
    twin_row = {
        "id": TWIN_ID,
        "tenant_id": OWNER["tenant_id"],
        "creator_id": None,
        "settings": {},
    }
    chain = MagicMock()
    chain.table.return_value = chain
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.single.return_value = chain
    chain.maybe_single.return_value = chain
    chain.execute.return_value = _result(twin_row)
    return chain


@contextmanager
def _patched_ownership():
    with patch("modules.observability.get_supabase_client") as mock_client:
        mock_client.return_value = _make_twin_ownership_mock()
        yield mock_client


def _fluent_chain(return_data: Any) -> MagicMock:
    """Fluent chain where every method returns self; .execute() returns _result(data)."""
    m = MagicMock()
    m.select.return_value = m
    m.eq.return_value = m
    m.ilike.return_value = m
    m.in_.return_value = m
    m.order.return_value = m
    m.range.return_value = m
    m.limit.return_value = m
    m.maybe_single.return_value = m
    m.execute.return_value = _result(return_data)
    return m


_BASE_SESSION = {
    "id": SESSION_ID,
    "visitor_id": "sess-abc-123",
    "surface": "widget",
    "contact_id": None,
    "message_count": 3,
    "first_message_at": "2026-05-27T09:00:00+00:00",
    "last_message_at": "2026-05-27T10:00:00+00:00",
    "visitor_name": None,
    "visitor_email": None,
    "source_domain": "example.com",
    # These must NOT appear in responses (CR-6 sanitization test)
    "tenant_id": OWNER["tenant_id"],
    "metadata": {},
}


# ---------------------------------------------------------------------------
# List endpoint
# ---------------------------------------------------------------------------

def test_list_empty():
    """supabase returns [] → response has empty sessions + count=0."""
    app = _app(OWNER)
    client = TestClient(app)
    chain = _fluent_chain([])
    with _patched_ownership(), patch("routers.visitor_sessions.supabase") as mock_sb:
        mock_sb.table.return_value = chain
        resp = client.get(f"/v2/twins/{TWIN_ID}/visitors")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["data"]["sessions"] == []
    assert body["data"]["count"] == 0


def test_list_populated():
    """Two session rows returned → response has count=2 and correct fields."""
    app = _app(OWNER)
    client = TestClient(app)
    rows = [
        {**_BASE_SESSION, "id": "sess-1", "visitor_id": "v1", "surface": "widget"},
        {**_BASE_SESSION, "id": "sess-2", "visitor_id": "v2", "surface": "public"},
    ]
    chain = _fluent_chain(rows)
    with _patched_ownership(), patch("routers.visitor_sessions.supabase") as mock_sb:
        mock_sb.table.return_value = chain
        resp = client.get(f"/v2/twins/{TWIN_ID}/visitors")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] == 2
    assert data["sessions"][0]["visitor_id"] == "v1"
    assert data["sessions"][1]["visitor_id"] == "v2"


def test_list_surface_filter():
    """?surface=widget triggers .eq('surface', 'widget') in the query chain."""
    app = _app(OWNER)
    client = TestClient(app)
    chain = _fluent_chain([])
    with _patched_ownership(), patch("routers.visitor_sessions.supabase") as mock_sb:
        mock_sb.table.return_value = chain
        resp = client.get(f"/v2/twins/{TWIN_ID}/visitors?surface=widget")
    assert resp.status_code == 200
    eq_calls = [(c.args[0], c.args[1]) for c in chain.eq.call_args_list if c.args]
    assert ("surface", "widget") in eq_calls


def test_list_tenant_isolation():
    """Verify .eq('tenant_id', tenant) is always part of the query."""
    app = _app(OWNER)
    client = TestClient(app)
    chain = _fluent_chain([])
    with _patched_ownership(), patch("routers.visitor_sessions.supabase") as mock_sb:
        mock_sb.table.return_value = chain
        client.get(f"/v2/twins/{TWIN_ID}/visitors")
    eq_calls = [(c.args[0], c.args[1]) for c in chain.eq.call_args_list if c.args]
    assert ("tenant_id", OWNER["tenant_id"]) in eq_calls


def test_list_sanitization_no_tenant_id_in_response():
    """tenant_id and metadata must NEVER appear in the list response JSON (CR-6)."""
    app = _app(OWNER)
    client = TestClient(app)
    chain = _fluent_chain([_BASE_SESSION])
    with _patched_ownership(), patch("routers.visitor_sessions.supabase") as mock_sb:
        mock_sb.table.return_value = chain
        resp = client.get(f"/v2/twins/{TWIN_ID}/visitors")
    assert resp.status_code == 200
    session_obj = resp.json()["data"]["sessions"][0]
    assert "tenant_id" not in session_obj
    assert "metadata" not in session_obj


def test_list_invalid_surface_filter_rejected():
    """?surface=owner should be rejected with 422 (Query regex validation)."""
    app = _app(OWNER)
    client = TestClient(app)
    chain = _fluent_chain([])
    with _patched_ownership(), patch("routers.visitor_sessions.supabase") as mock_sb:
        mock_sb.table.return_value = chain
        resp = client.get(f"/v2/twins/{TWIN_ID}/visitors?surface=owner")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Messages endpoint
# ---------------------------------------------------------------------------

def _build_messages_mock(sess_row, conv_rows, msg_rows):
    """
    Build a sequential mock for the messages endpoint:
    1st table() call → visitor_sessions (sess_row)
    2nd table() call → adk_conversations (conv_rows)
    3rd table() call → adk_messages (msg_rows)
    """
    call_count = {"n": 0}

    def _side_effect(name: str):
        call_count["n"] += 1
        n = call_count["n"]
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.ilike.return_value = chain
        chain.in_.return_value = chain
        chain.order.return_value = chain
        chain.limit.return_value = chain
        chain.maybe_single.return_value = chain
        if n == 1:
            chain.execute.return_value = _result(sess_row)
        elif n == 2:
            chain.execute.return_value = _result(conv_rows)
        else:
            chain.execute.return_value = _result(msg_rows)
        return chain

    sb = MagicMock()
    sb.table.side_effect = _side_effect
    return sb


def test_messages_404_when_session_not_found():
    """Session lookup returns None → 404 'Visitor session not found'."""
    app = _app(OWNER)
    client = TestClient(app)
    sb = _build_messages_mock(None, [], [])
    with _patched_ownership(), patch("routers.visitor_sessions.supabase", sb):
        resp = client.get(f"/v2/twins/{TWIN_ID}/visitors/{SESSION_ID}/messages")
    assert resp.status_code == 404
    assert "Visitor session not found" in resp.json()["detail"]


def test_messages_returns_empty_when_no_conversations():
    """Session found but no matching adk_conversations → messages=[]."""
    app = _app(OWNER)
    client = TestClient(app)
    sess = {"visitor_id": "sess-abc-123", "surface": "widget"}
    sb = _build_messages_mock(sess, [], [])
    with _patched_ownership(), patch("routers.visitor_sessions.supabase", sb):
        resp = client.get(f"/v2/twins/{TWIN_ID}/visitors/{SESSION_ID}/messages")
    assert resp.status_code == 200
    assert resp.json()["data"]["messages"] == []
    assert resp.json()["data"]["count"] == 0


def test_messages_returns_messages():
    """Session + conversations found → messages returned with correct fields."""
    app = _app(OWNER)
    client = TestClient(app)
    sess = {"visitor_id": "sess-abc-123", "surface": "widget"}
    conv_rows = [{"id": "conv-1", "user_id": "widget:twin:sess-abc-123", "surface": "widget"}]
    msg_rows = [
        {"id": "msg-1", "role": "user", "content": "Hello", "created_at": "2026-05-27T09:00:00+00:00"},
        {"id": "msg-2", "role": "assistant", "content": "Hi there", "created_at": "2026-05-27T09:00:01+00:00"},
    ]
    sb = _build_messages_mock(sess, conv_rows, msg_rows)
    with _patched_ownership(), patch("routers.visitor_sessions.supabase", sb):
        resp = client.get(f"/v2/twins/{TWIN_ID}/visitors/{SESSION_ID}/messages")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] == 2
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][1]["role"] == "assistant"


def test_messages_sanitization_no_tenant_id():
    """Messages response must never contain tenant_id (CR-6)."""
    app = _app(OWNER)
    client = TestClient(app)
    sess = {"visitor_id": "sess-abc-123", "surface": "public"}
    conv_rows = [{"id": "conv-1", "user_id": "public:twin:sess", "surface": "public"}]
    msg_rows = [
        {
            "id": "msg-1",
            "role": "user",
            "content": "Question",
            "created_at": "2026-05-27T09:00:00+00:00",
            "tenant_id": OWNER["tenant_id"],  # raw DB row may include this
        }
    ]
    sb = _build_messages_mock(sess, conv_rows, msg_rows)
    with _patched_ownership(), patch("routers.visitor_sessions.supabase", sb):
        resp = client.get(f"/v2/twins/{TWIN_ID}/visitors/{SESSION_ID}/messages")
    assert resp.status_code == 200
    msg = resp.json()["data"]["messages"][0]
    assert "tenant_id" not in msg


def test_messages_cross_tenant_404():
    """Session found but belongs to different tenant → 404 (RLS + .eq filter)."""
    evil_user = {**OWNER, "tenant_id": "00000000-0000-0000-0000-000000000099"}
    app = _app(evil_user)
    client = TestClient(app)
    # When tenant doesn't match, maybe_single returns None
    sb = _build_messages_mock(None, [], [])
    with _patched_ownership(), patch("routers.visitor_sessions.supabase", sb):
        resp = client.get(f"/v2/twins/{TWIN_ID}/visitors/{SESSION_ID}/messages")
    assert resp.status_code == 404
