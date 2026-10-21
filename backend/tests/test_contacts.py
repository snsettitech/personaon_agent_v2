"""Tests for the contacts router (Phase F.3/F.4 — People surface).

Security assertions:
- list/get/patch/delete are owner-only (verify_owner dependency)
- All queries include .eq("tenant_id", ...) for tenant isolation
- Cross-tenant contact_id returns 404 (not 403 — no existence leak)
- PATCH permission update chain includes twin_id + tenant_id guards
- Soft-deleted contacts are excluded from list/get/delete (404 if deleted)

Phase F.4 additions:
- DELETE endpoint soft-deletes (sets deleted_at)
- GET /meetings endpoint returns joined meetings ordered by start desc
- list_contacts excludes soft-deleted contacts
- get_contact returns 404 for soft-deleted contacts
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.auth_guard import verify_owner
from routers import contacts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(data: Any) -> SimpleNamespace:
    return SimpleNamespace(data=data)


def _app(user: dict[str, Any]) -> FastAPI:
    app = FastAPI()
    app.include_router(contacts.router)
    app.dependency_overrides[verify_owner] = lambda: user
    return app


# Use valid UUIDs so auth_guard.verify_twin_ownership's DB call gets a
# well-formed UUID; we also mock get_supabase_client used by that function.
OWNER = {"user_id": "00000000-0000-0000-0000-000000000001",
         "tenant_id": "00000000-0000-0000-0000-000000000002"}
TWIN_ID = "00000000-0000-0000-0000-000000000003"
CONTACT_ID = "00000000-0000-0000-0000-000000000004"


def _make_twin_ownership_mock() -> MagicMock:
    """Mock for modules.auth_guard.get_supabase_client that returns a successful
    twin ownership row (passes verify_twin_ownership)."""
    twin_row = {"id": TWIN_ID, "tenant_id": OWNER["tenant_id"], "creator_id": None,
                "settings": {}}
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
    """Context manager that patches modules.observability.get_supabase_client
    (the lazy import used inside verify_twin_ownership) so that the ownership
    check succeeds without a real DB call."""
    with patch("modules.observability.get_supabase_client") as mock_client:
        mock_client.return_value = _make_twin_ownership_mock()
        yield mock_client

_BASE_CONTACT = {
    "id": CONTACT_ID,
    "name": "Alice Smith",
    "email": "alice@example.com",
    "linkedin_url": None,
    "avatar_url": None,
    "meeting_count": 3,
    "last_seen_at": "2026-05-27T10:00:00+00:00",
    "first_seen_at": "2026-05-01T09:00:00+00:00",
    "allow_mention": True,
    "tags": [],
    "twin_id": TWIN_ID,
    "tenant_id": OWNER["tenant_id"],
    "notes": None,
    "metadata": {},
}


def _fluent_chain(return_data: Any) -> MagicMock:
    """Return a MagicMock where every chained call returns itself, then
    .execute() returns _result(return_data)."""
    m = MagicMock()
    m.select.return_value = m
    m.eq.return_value = m
    m.ilike.return_value = m
    m.is_.return_value = m
    m.not_.is_.return_value = m
    m.neq.return_value = m
    m.in_.return_value = m
    m.order.return_value = m
    m.range.return_value = m
    m.limit.return_value = m
    m.maybe_single.return_value = m
    m.update.return_value = m
    m.insert.return_value = m
    m.execute.return_value = _result(return_data)
    return m


# ---------------------------------------------------------------------------
# List endpoint
# ---------------------------------------------------------------------------

def test_list_empty():
    """supabase returns [] → response has empty list + count=0."""
    app = _app(OWNER)
    client = TestClient(app)
    chain = _fluent_chain([])
    with _patched_ownership(), patch("routers.contacts.supabase") as mock_sb:
        mock_sb.table.return_value = chain
        resp = client.get(f"/v2/twins/{TWIN_ID}/contacts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["data"]["contacts"] == []
    assert body["data"]["count"] == 0


def test_list_populated():
    """Mock returns 2 contact rows → response has 2 items with correct fields."""
    app = _app(OWNER)
    client = TestClient(app)
    rows = [
        {**_BASE_CONTACT, "id": "00000000-0000-0000-0001-000000000001", "name": "Alice"},
        {**_BASE_CONTACT, "id": "00000000-0000-0000-0001-000000000002", "name": "Bob",
         "email": "bob@example.com"},
    ]
    chain = _fluent_chain(rows)
    with _patched_ownership(), patch("routers.contacts.supabase") as mock_sb:
        mock_sb.table.return_value = chain
        resp = client.get(f"/v2/twins/{TWIN_ID}/contacts")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] == 2
    assert data["contacts"][0]["name"] == "Alice"
    assert data["contacts"][1]["name"] == "Bob"


def test_list_filter_q():
    """?q=alice triggers .ilike('name', '%alice%') in the call chain."""
    app = _app(OWNER)
    client = TestClient(app)
    chain = _fluent_chain([])
    with _patched_ownership(), patch("routers.contacts.supabase") as mock_sb:
        mock_sb.table.return_value = chain
        resp = client.get(f"/v2/twins/{TWIN_ID}/contacts?q=alice")
    assert resp.status_code == 200
    # Verify .ilike was called with the expected arguments
    chain.ilike.assert_called_once_with("name", "%alice%")


def test_list_cross_tenant_isolation():
    """Verify .eq('tenant_id', tenant) is recorded; a different tenant's data
    would be filtered at the DB layer."""
    app = _app(OWNER)
    client = TestClient(app)
    chain = _fluent_chain([])
    with _patched_ownership(), patch("routers.contacts.supabase") as mock_sb:
        mock_sb.table.return_value = chain
        client.get(f"/v2/twins/{TWIN_ID}/contacts")
    # Collect all .eq() calls and verify tenant_id is in there
    eq_calls = chain.eq.call_args_list
    eq_kwargs = [(c.args[0], c.args[1]) for c in eq_calls if c.args]
    assert ("tenant_id", OWNER["tenant_id"]) in eq_kwargs


def test_list_contacts_excludes_soft_deleted():
    """list_contacts query chain must include .is_('deleted_at', 'null')."""
    app = _app(OWNER)
    client = TestClient(app)
    chain = _fluent_chain([])
    with _patched_ownership(), patch("routers.contacts.supabase") as mock_sb:
        mock_sb.table.return_value = chain
        resp = client.get(f"/v2/twins/{TWIN_ID}/contacts")
    assert resp.status_code == 200
    # Verify .is_ was called to filter out deleted contacts
    chain.is_.assert_called_with("deleted_at", "null")


# ---------------------------------------------------------------------------
# Get single contact
# ---------------------------------------------------------------------------

def test_get_contact_404_if_missing():
    """supabase maybe_single returns data=None → 404 'Contact not found'."""
    app = _app(OWNER)
    client = TestClient(app)
    chain = _fluent_chain(None)
    with _patched_ownership(), patch("routers.contacts.supabase") as mock_sb:
        mock_sb.table.return_value = chain
        resp = client.get(f"/v2/twins/{TWIN_ID}/contacts/{CONTACT_ID}")
    assert resp.status_code == 404
    assert "Contact not found" in resp.json()["detail"]


def test_get_contact_cross_tenant_404():
    """Contact exists but with different tenant_id (mock returns data=None due
    to the .eq filter) → 404, no existence leak."""
    evil_user = {**OWNER, "tenant_id": "00000000-0000-0000-0000-000000000099"}
    app = _app(evil_user)
    client = TestClient(app)
    # When tenant does not match, supabase returns None (row filtered out)
    chain = _fluent_chain(None)
    with _patched_ownership(), patch("routers.contacts.supabase") as mock_sb:
        mock_sb.table.return_value = chain
        resp = client.get(f"/v2/twins/{TWIN_ID}/contacts/{CONTACT_ID}")
    assert resp.status_code == 404


def test_get_contact_404_when_soft_deleted():
    """_fetch_contact_owned uses .is_('deleted_at','null') — if deleted, mock
    returns None → 404."""
    app = _app(OWNER)
    client = TestClient(app)
    # Simulate soft-deleted: the query with .is_("deleted_at","null") returns no row
    chain = _fluent_chain(None)
    with _patched_ownership(), patch("routers.contacts.supabase") as mock_sb:
        mock_sb.table.return_value = chain
        resp = client.get(f"/v2/twins/{TWIN_ID}/contacts/{CONTACT_ID}")
    assert resp.status_code == 404
    assert "Contact not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Permission update
# ---------------------------------------------------------------------------

def test_permission_update_toggles_allow_mention():
    """PATCH with {allow_mention: false} → 200, returns updated value.
    Verify the update chain recorded .eq('twin_id', ...) and .eq('tenant_id', ...)."""
    app = _app(OWNER)
    client = TestClient(app)

    fetch_chain = _fluent_chain({**_BASE_CONTACT, "id": CONTACT_ID,
                                  "twin_id": TWIN_ID, "tenant_id": OWNER["tenant_id"],
                                  "notes": None, "metadata": {}})
    update_chain = _fluent_chain([{"id": CONTACT_ID}])

    call_count = {"n": 0}

    def _table_side_effect(name: str):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First call = _fetch_contact_owned (select)
            return fetch_chain
        # Second call = update
        return update_chain

    with _patched_ownership(), patch("routers.contacts.supabase") as mock_sb:
        mock_sb.table.side_effect = _table_side_effect
        resp = client.patch(
            f"/v2/twins/{TWIN_ID}/contacts/{CONTACT_ID}/permission",
            json={"allow_mention": False},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["data"]["allow_mention"] is False
    assert body["data"]["id"] == CONTACT_ID

    # The update chain must have been called with twin_id and tenant_id guards
    eq_calls = update_chain.eq.call_args_list
    eq_pairs = [(c.args[0], c.args[1]) for c in eq_calls if c.args]
    assert ("twin_id", TWIN_ID) in eq_pairs
    assert ("tenant_id", OWNER["tenant_id"]) in eq_pairs


def test_permission_update_404_if_contact_missing():
    """_fetch_contact_owned returns None → 404 before any UPDATE."""
    app = _app(OWNER)
    client = TestClient(app)
    chain = _fluent_chain(None)
    with _patched_ownership(), patch("routers.contacts.supabase") as mock_sb:
        mock_sb.table.return_value = chain
        resp = client.patch(
            f"/v2/twins/{TWIN_ID}/contacts/{CONTACT_ID}/permission",
            json={"allow_mention": True},
        )
    assert resp.status_code == 404
    # UPDATE must NOT have been called
    chain.update.assert_not_called()


# ---------------------------------------------------------------------------
# Phase F.4: DELETE (soft-delete) endpoint
# ---------------------------------------------------------------------------

def test_delete_contact_sets_deleted_at_then_returns_ok():
    """DELETE endpoint: fetch 200 → update with deleted_at → returns {deleted: true}."""
    app = _app(OWNER)
    client = TestClient(app)

    fetch_chain = _fluent_chain({**_BASE_CONTACT, "id": CONTACT_ID,
                                  "twin_id": TWIN_ID, "tenant_id": OWNER["tenant_id"],
                                  "notes": None, "metadata": {}})
    update_chain = _fluent_chain([])

    call_count = {"n": 0}

    def _table_side_effect(name: str):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return fetch_chain   # _fetch_contact_owned
        return update_chain      # soft-delete update

    with _patched_ownership(), patch("routers.contacts.supabase") as mock_sb:
        mock_sb.table.side_effect = _table_side_effect
        resp = client.delete(f"/v2/twins/{TWIN_ID}/contacts/{CONTACT_ID}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["data"]["deleted"] is True
    assert body["data"]["id"] == CONTACT_ID

    # Verify the update was called with deleted_at
    update_chain.update.assert_called_once()
    update_args = update_chain.update.call_args[0][0]
    assert "deleted_at" in update_args


def test_delete_contact_cross_tenant_404():
    """DELETE: contact not found for this tenant → _fetch_contact_owned raises 404."""
    app = _app(OWNER)
    client = TestClient(app)
    chain = _fluent_chain(None)
    with _patched_ownership(), patch("routers.contacts.supabase") as mock_sb:
        mock_sb.table.return_value = chain
        resp = client.delete(f"/v2/twins/{TWIN_ID}/contacts/{CONTACT_ID}")
    assert resp.status_code == 404
    chain.update.assert_not_called()


# ---------------------------------------------------------------------------
# Phase F.4: GET /meetings endpoint
# ---------------------------------------------------------------------------

def test_list_contact_meetings_returns_meetings_ordered_by_start_desc():
    """GET /meetings: join lookup returns 2 meeting_ids, meetings fetch returns 2 rows
    ordered by meeting_start desc."""
    app = _app(OWNER)
    client = TestClient(app)

    contact_row = {**_BASE_CONTACT, "id": CONTACT_ID, "twin_id": TWIN_ID,
                   "tenant_id": OWNER["tenant_id"], "notes": None, "metadata": {}}
    links = [
        {"meeting_id": "meet-a", "source": "participant"},
        {"meeting_id": "meet-b", "source": "recap"},
    ]
    meeting_rows = [
        {"id": "meet-a", "title": "Meeting A", "meeting_start": "2026-05-20T10:00:00Z",
         "meeting_end": "2026-05-20T11:00:00Z", "duration_seconds": 3600, "status": "completed"},
        {"id": "meet-b", "title": "Meeting B", "meeting_start": "2026-05-10T10:00:00Z",
         "meeting_end": "2026-05-10T10:30:00Z", "duration_seconds": 1800, "status": "completed"},
    ]

    call_count = {"n": 0}

    def _table(name: str):
        call_count["n"] += 1
        if name == "contacts" and call_count["n"] == 1:
            # _fetch_contact_owned
            return _fluent_chain(contact_row)
        if name == "contact_meetings" and call_count["n"] == 2:
            return _fluent_chain(links)
        if name == "meetings" and call_count["n"] == 3:
            return _fluent_chain(meeting_rows)
        return _fluent_chain([])

    with _patched_ownership(), patch("routers.contacts.supabase") as mock_sb:
        mock_sb.table.side_effect = _table
        resp = client.get(f"/v2/twins/{TWIN_ID}/contacts/{CONTACT_ID}/meetings")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    data = body["data"]
    assert data["count"] == 2
    assert data["meetings"][0]["id"] == "meet-a"
    assert data["meetings"][0]["source_link"] == "participant"
    assert data["meetings"][1]["id"] == "meet-b"
    assert data["meetings"][1]["source_link"] == "recap"


def test_list_contact_meetings_empty_when_no_links():
    """GET /meetings: no rows in contact_meetings → empty list, count=0."""
    app = _app(OWNER)
    client = TestClient(app)

    contact_row = {**_BASE_CONTACT, "id": CONTACT_ID, "twin_id": TWIN_ID,
                   "tenant_id": OWNER["tenant_id"], "notes": None, "metadata": {}}

    call_count = {"n": 0}

    def _table(name: str):
        call_count["n"] += 1
        if name == "contacts" and call_count["n"] == 1:
            return _fluent_chain(contact_row)
        if name == "contact_meetings":
            return _fluent_chain([])
        return _fluent_chain([])

    with _patched_ownership(), patch("routers.contacts.supabase") as mock_sb:
        mock_sb.table.side_effect = _table
        resp = client.get(f"/v2/twins/{TWIN_ID}/contacts/{CONTACT_ID}/meetings")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["meetings"] == []
    assert body["data"]["count"] == 0


def test_list_contact_meetings_404_when_contact_missing():
    """GET /meetings: contact not found → 404."""
    app = _app(OWNER)
    client = TestClient(app)
    chain = _fluent_chain(None)
    with _patched_ownership(), patch("routers.contacts.supabase") as mock_sb:
        mock_sb.table.return_value = chain
        resp = client.get(f"/v2/twins/{TWIN_ID}/contacts/{CONTACT_ID}/meetings")
    assert resp.status_code == 404
