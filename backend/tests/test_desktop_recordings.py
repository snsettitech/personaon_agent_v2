"""Tests for the desktop recordings router (Layer 1, Commit 2).

Covers:
- POST /sdk-upload happy path (Recall token + meetings INSERT)
- POST /sdk-upload when Recall returns an incomplete response (502)
- GET / lists only the signed-in tenant's desktop_sdk rows, excludes deleted
- GET /{id} returns 404 when row is owned by another tenant (no existence leak)
- PATCH /{id} updates title
- DELETE /{id} soft-deletes (sets status='deleted')
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.auth_guard import verify_owner
from routers.desktop_recordings import router


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

USER = {"user_id": "user-1", "tenant_id": "tenant-1", "email": "u1@example.com"}
OTHER_USER = {"user_id": "user-2", "tenant_id": "tenant-2", "email": "u2@example.com"}


def _app_with_user(user: dict[str, Any]) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_owner] = lambda: user
    return app


def _result(data: Any) -> SimpleNamespace:
    return SimpleNamespace(data=data)


def _chain_returning(rows: Any) -> MagicMock:
    """Fluent supabase chain that resolves to the given rows on .execute()."""
    m = MagicMock()
    for method in (
        "select", "eq", "neq", "order", "range", "limit",
        "single", "maybe_single", "update", "insert",
    ):
        getattr(m, method).return_value = m
    m.execute.return_value = _result(rows)
    return m


# ---------------------------------------------------------------------------
# POST /sdk-upload
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sdk_upload_persists_meeting_row() -> None:
    captured_insert: list[dict[str, Any]] = []
    table_chain = MagicMock()
    table_chain.insert.side_effect = lambda payload: (
        captured_insert.append(payload) or _chain_returning([{"id": "meet-1"}])
    )

    mock_sb = MagicMock()
    mock_sb.table.return_value = table_chain

    recall_response = {
        "id": "upl-1",
        "upload_token": "tok-1",
        "recording_id": "rec-1",
        "status": {"code": "pending"},
    }

    async def _fake_create(**_kwargs: Any) -> dict[str, Any]:
        return recall_response

    with patch("routers.desktop_recordings.supabase", mock_sb), \
         patch("routers.desktop_recordings.create_desktop_sdk_upload", _fake_create):
        app = _app_with_user(USER)
        client = TestClient(app)
        resp = client.post(
            "/v2/desktop-recordings/sdk-upload",
            json={
                "source": "electron",
                "window": {
                    "id": "win-1",
                    "title": "Sprint planning",
                    "platform": "desktop-audio",
                },
            },
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["data"]["id"] == "upl-1"
    assert body["data"]["upload_token"] == "tok-1"
    assert body["data"]["recording_id"] == "rec-1"
    assert body["data"]["meeting_id"] == "meet-1"

    # Verify the row we attempted to insert
    assert len(captured_insert) == 1
    row = captured_insert[0]
    assert row["tenant_id"] == "tenant-1"
    assert row["source"] == "desktop_sdk"
    assert row["status"] == "recording"
    assert row["recall_sdk_upload_id"] == "upl-1"
    assert row["recall_recording_id"] == "rec-1"
    assert row["title"] == "Sprint planning"
    assert row["twin_id"] is None
    assert row["platform"] == "desktop-audio"


@pytest.mark.asyncio
async def test_sdk_upload_502_when_recall_incomplete() -> None:
    async def _fake_create(**_kwargs: Any) -> dict[str, Any]:
        return {"id": "upl-1"}  # missing upload_token

    mock_sb = MagicMock()
    mock_sb.table.return_value = _chain_returning([])

    with patch("routers.desktop_recordings.supabase", mock_sb), \
         patch("routers.desktop_recordings.create_desktop_sdk_upload", _fake_create):
        app = _app_with_user(USER)
        client = TestClient(app)
        resp = client.post(
            "/v2/desktop-recordings/sdk-upload",
            json={"source": "electron", "window": {"id": "win-1"}},
        )

    assert resp.status_code == 502
    assert "incomplete" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_sdk_upload_502_when_recall_raises() -> None:
    """Exception from Recall.ai client wraps to 502 with a generic message."""
    async def _fake_create(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("recall.ai timeout")

    mock_sb = MagicMock()
    mock_sb.table.return_value = _chain_returning([])

    with patch("routers.desktop_recordings.supabase", mock_sb), \
         patch("routers.desktop_recordings.create_desktop_sdk_upload", _fake_create):
        app = _app_with_user(USER)
        client = TestClient(app)
        resp = client.post(
            "/v2/desktop-recordings/sdk-upload",
            json={"source": "electron", "window": {"id": "win-1"}},
        )

    assert resp.status_code == 502
    assert "Failed to create Recall upload" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_sdk_upload_idempotent_on_duplicate_upload_id() -> None:
    """A duplicate recall_sdk_upload_id INSERT should recover the existing
    meeting_id instead of returning meeting_id=null."""
    table_chain = MagicMock()

    # Mimic Postgres unique-violation error on insert
    def _insert_raises(_payload: dict[str, Any]) -> MagicMock:
        raise RuntimeError(
            'duplicate key value violates unique constraint '
            '"meetings_recall_sdk_upload_id_key"'
        )

    table_chain.insert.side_effect = _insert_raises

    # The recovery SELECT chain returns the existing meeting row
    recovery_chain = MagicMock()
    recovery_chain.select.return_value = recovery_chain
    recovery_chain.eq.return_value = recovery_chain
    recovery_chain.maybe_single.return_value = recovery_chain
    recovery_chain.execute.return_value = _result({"id": "meet-existing"})

    call_count = {"n": 0}

    def _table(name: str) -> MagicMock:
        # First call -> insert chain (raises); subsequent -> recovery chain
        call_count["n"] += 1
        return table_chain if call_count["n"] == 1 else recovery_chain

    mock_sb = MagicMock()
    mock_sb.table.side_effect = _table

    async def _fake_create(**_kwargs: Any) -> dict[str, Any]:
        return {
            "id": "upl-dup",
            "upload_token": "tok-dup",
            "recording_id": "rec-dup",
        }

    with patch("routers.desktop_recordings.supabase", mock_sb), \
         patch("routers.desktop_recordings.create_desktop_sdk_upload", _fake_create):
        app = _app_with_user(USER)
        client = TestClient(app)
        resp = client.post(
            "/v2/desktop-recordings/sdk-upload",
            json={"source": "electron", "window": {"id": "win-1"}},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["meeting_id"] == "meet-existing"
    assert body["data"]["id"] == "upl-dup"
    assert body["data"]["upload_token"] == "tok-dup"


# ---------------------------------------------------------------------------
# GET /  list
# ---------------------------------------------------------------------------

def test_list_recordings_returns_only_tenant_rows() -> None:
    rows = [
        {
            "id": "meet-1",
            "title": "Standup",
            "status": "completed",
            "source": "desktop_sdk",
            "tenant_id": "tenant-1",
            "created_at": "2026-05-27T10:00:00Z",
        }
    ]
    captured_eq: list[tuple[str, Any]] = []

    chain = MagicMock()
    chain.select.return_value = chain

    def _eq(col: str, val: Any) -> MagicMock:
        captured_eq.append((col, val))
        return chain

    chain.eq.side_effect = _eq
    chain.neq.return_value = chain
    chain.order.return_value = chain
    chain.range.return_value = chain
    chain.execute.return_value = _result(rows)

    mock_sb = MagicMock()
    mock_sb.table.return_value = chain

    with patch("routers.desktop_recordings.supabase", mock_sb):
        app = _app_with_user(USER)
        client = TestClient(app)
        resp = client.get("/v2/desktop-recordings/")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert len(body["data"]["items"]) == 1
    assert body["data"]["items"][0]["id"] == "meet-1"
    # Critical: must have filtered by tenant_id AND source
    assert ("tenant_id", "tenant-1") in captured_eq
    assert ("source", "desktop_sdk") in captured_eq


# ---------------------------------------------------------------------------
# GET /{id}
# ---------------------------------------------------------------------------

def test_get_recording_404_when_not_found() -> None:
    mock_sb = MagicMock()
    mock_sb.table.return_value = _chain_returning(None)

    with patch("routers.desktop_recordings.supabase", mock_sb):
        app = _app_with_user(USER)
        client = TestClient(app)
        resp = client.get("/v2/desktop-recordings/missing-id")

    assert resp.status_code == 404


def test_get_recording_404_when_wrong_tenant_no_existence_leak() -> None:
    """A row owned by tenant-2 must return 404 (not 403) to user-1."""
    foreign_row = {
        "id": "meet-1",
        "tenant_id": "tenant-2",  # belongs to OTHER_USER
        "status": "completed",
        "source": "desktop_sdk",
    }
    mock_sb = MagicMock()
    mock_sb.table.return_value = _chain_returning(foreign_row)

    with patch("routers.desktop_recordings.supabase", mock_sb):
        app = _app_with_user(USER)  # signed in as user-1
        client = TestClient(app)
        resp = client.get("/v2/desktop-recordings/meet-1")

    assert resp.status_code == 404


def test_get_recording_404_when_deleted() -> None:
    deleted_row = {
        "id": "meet-1",
        "tenant_id": "tenant-1",
        "status": "deleted",
        "source": "desktop_sdk",
    }
    mock_sb = MagicMock()
    mock_sb.table.return_value = _chain_returning(deleted_row)

    with patch("routers.desktop_recordings.supabase", mock_sb):
        app = _app_with_user(USER)
        client = TestClient(app)
        resp = client.get("/v2/desktop-recordings/meet-1")

    assert resp.status_code == 404


def test_get_recording_includes_recap_fields_when_present() -> None:
    row = {
        "id": "meet-1",
        "tenant_id": "tenant-1",
        "title": "Recap meeting",
        "status": "completed",
        "source": "desktop_sdk",
        "summary_json": {"tldr": "A useful recap", "topics": ["Launch"]},
        "recap_extras_json": {
            "intent": "Align launch scope",
            "what_happened": "The team chose the beta path.",
            "commitments": ["Alice will send pricing by Friday"],
        },
        "action_items": [{"text": "Send pricing", "assignee": "Alice"}],
    }
    mock_sb = MagicMock()
    mock_sb.table.return_value = _chain_returning(row)

    with patch("routers.desktop_recordings.supabase", mock_sb):
        app = _app_with_user(USER)
        client = TestClient(app)
        resp = client.get("/v2/desktop-recordings/meet-1")

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["summary_json"] == row["summary_json"]
    assert data["recap_extras_json"] == row["recap_extras_json"]
    assert data["action_items"] == row["action_items"]


# ---------------------------------------------------------------------------
# PATCH /{id}
# ---------------------------------------------------------------------------

def test_patch_updates_title_and_filters_by_tenant_id() -> None:
    """PATCH must filter UPDATE by both id AND tenant_id (defense-in-depth)."""
    owned_row = {
        "id": "meet-1",
        "tenant_id": "tenant-1",
        "status": "completed",
        "source": "desktop_sdk",
        "title": "Old",
    }
    updated_row = {**owned_row, "title": "New title"}

    captured_eq: list[tuple[str, Any]] = []

    chain = MagicMock()
    chain.select.return_value = chain
    chain.maybe_single.return_value = chain
    chain.update.return_value = chain

    def _eq(col: str, val: Any) -> MagicMock:
        captured_eq.append((col, val))
        return chain

    chain.eq.side_effect = _eq
    # First execute (SELECT in _fetch_owned) returns owned_row; second (UPDATE) returns [updated_row]
    chain.execute.side_effect = [_result(owned_row), _result([updated_row])]

    mock_sb = MagicMock()
    mock_sb.table.return_value = chain

    with patch("routers.desktop_recordings.supabase", mock_sb):
        app = _app_with_user(USER)
        client = TestClient(app)
        resp = client.patch(
            "/v2/desktop-recordings/meet-1",
            json={"title": "New title"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["title"] == "New title"
    # Critical: tenant_id filter must be applied to the UPDATE
    assert ("tenant_id", "tenant-1") in captured_eq, \
        f"PATCH must include .eq('tenant_id', ...): {captured_eq}"


def test_patch_400_when_title_whitespace_only() -> None:
    """A whitespace-only title passes Pydantic (min_length counts chars) but
    must be rejected by the handler's .strip() check."""
    owned_row = {
        "id": "meet-1",
        "tenant_id": "tenant-1",
        "status": "completed",
        "source": "desktop_sdk",
    }
    mock_sb = MagicMock()
    mock_sb.table.return_value = _chain_returning(owned_row)

    with patch("routers.desktop_recordings.supabase", mock_sb):
        app = _app_with_user(USER)
        client = TestClient(app)
        resp = client.patch(
            "/v2/desktop-recordings/meet-1",
            json={"title": "   "},
        )
    assert resp.status_code == 400
    assert "non-empty" in resp.json()["detail"].lower()


def _rpc_mock_returning(updated_row: dict[str, Any], edit_id: str = "edit-1") -> tuple[MagicMock, list[tuple[str, dict[str, Any]]]]:
    """Stand up a supabase.rpc('update_recap_with_audit') mock.

    Returns (rpc_chain, captured_calls) so individual tests can assert on
    the RPC parameters threaded through from the router (F3 atomic PATCH).
    """
    rpc_chain = MagicMock()
    captured: list[tuple[str, dict[str, Any]]] = []
    rpc_chain.execute.return_value = _result({"meeting": updated_row, "edit_id": edit_id})
    return rpc_chain, captured


def test_patch_recap_updates_summary_json_and_appends_audit_row() -> None:
    owned_row = {
        "id": "meet-1",
        "tenant_id": "tenant-1",
        "status": "completed",
        "source": "desktop_sdk",
        "summary_json": {"tldr": "Old recap", "topics": []},
        "recap_extras_json": {"intent": "Old intent"},
        "action_items": [],
    }
    updated_row = {
        **owned_row,
        "summary_json": {"tldr": "New recap", "topics": []},
    }

    meetings_chain = MagicMock()
    meetings_chain.select.return_value = meetings_chain
    meetings_chain.maybe_single.return_value = meetings_chain
    meetings_chain.eq.return_value = meetings_chain
    meetings_chain.execute.return_value = _result(owned_row)

    rpc_chain, rpc_calls = _rpc_mock_returning(updated_row)

    mock_sb = MagicMock()
    mock_sb.table.return_value = meetings_chain
    mock_sb.rpc.side_effect = lambda fn, params: (
        rpc_calls.append((fn, params)) or rpc_chain
    )
    mock_outbox = MagicMock()

    with patch("routers.desktop_recordings.supabase", mock_sb), \
         patch("modules.graph_outbox.get_graph_outbox", return_value=mock_outbox):
        app = _app_with_user(USER)
        client = TestClient(app)
        resp = client.patch(
            "/v2/desktop-recordings/meet-1/recap",
            json={"field": "tldr", "after": "New recap"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["summary_json"]["tldr"] == "New recap"
    # Audit + UPDATE both moved inside the RPC. Assert on the params the
    # router passes through (the function body covers the actual SQL
    # before/after capture, jsonb_set, and audit-row INSERT).
    assert len(rpc_calls) == 1
    fn_name, params = rpc_calls[0]
    assert fn_name == "update_recap_with_audit"
    assert params == {
        "p_meeting_id": "meet-1",
        "p_tenant_id": "tenant-1",
        "p_user_id": "user-1",
        "p_field": "tldr",
        "p_json_column": "summary_json",
        "p_after": "New recap",
    }
    mock_outbox.submit.assert_called_once()
    route_kwargs = mock_outbox.submit.call_args.kwargs
    assert route_kwargs["idempotency_key"] == "edit_routing:edit-1"
    # tenant_id added to payload (F1 fix) so the routing worker can apply a
    # tenant filter at SELECT/UPDATE time without falling back to job column.
    assert route_kwargs["payload"] == {"edit_id": "edit-1", "tenant_id": "tenant-1"}


def test_patch_recap_routing_enqueue_failure_does_not_block_success() -> None:
    owned_row = {
        "id": "meet-1",
        "tenant_id": "tenant-1",
        "twin_id": "twin-1",
        "status": "completed",
        "source": "desktop_sdk",
        "summary_json": {"tldr": "Old recap"},
        "recap_extras_json": {},
    }
    updated_row = {**owned_row, "summary_json": {"tldr": "New recap"}}

    meetings_chain = MagicMock()
    meetings_chain.select.return_value = meetings_chain
    meetings_chain.maybe_single.return_value = meetings_chain
    meetings_chain.eq.return_value = meetings_chain
    meetings_chain.execute.return_value = _result(owned_row)

    rpc_chain, _ = _rpc_mock_returning(updated_row)

    mock_sb = MagicMock()
    mock_sb.table.return_value = meetings_chain
    mock_sb.rpc.return_value = rpc_chain
    mock_outbox = MagicMock()
    mock_outbox.submit.side_effect = RuntimeError("outbox down")

    with patch("routers.desktop_recordings.supabase", mock_sb), \
         patch("modules.graph_outbox.get_graph_outbox", return_value=mock_outbox):
        app = _app_with_user(USER)
        client = TestClient(app)
        resp = client.patch(
            "/v2/desktop-recordings/meet-1/recap",
            json={"field": "tldr", "after": "New recap"},
        )

    assert resp.status_code == 200, resp.text
    mock_outbox.submit.assert_called_once()


def test_patch_recap_rejects_whitespace_string() -> None:
    owned_row = {
        "id": "meet-1",
        "tenant_id": "tenant-1",
        "status": "completed",
        "source": "desktop_sdk",
        "summary_json": {"tldr": "Old recap"},
        "recap_extras_json": {},
    }
    mock_sb = MagicMock()
    mock_sb.table.return_value = _chain_returning(owned_row)

    with patch("routers.desktop_recordings.supabase", mock_sb):
        app = _app_with_user(USER)
        client = TestClient(app)
        resp = client.patch(
            "/v2/desktop-recordings/meet-1/recap",
            json={"field": "tldr", "after": "   "},
        )

    assert resp.status_code == 400
    assert "non-empty" in resp.json()["detail"].lower()


def test_patch_recap_rejects_non_string_for_string_fields() -> None:
    """Regression for F6.4 (MAJOR P2 review fix). tldr / intent /
    what_happened are string-typed recap fields per the leadership-spec
    schema. A client sending `{"field": "intent", "after": {"x": "y"}}`
    must be rejected at validation time — otherwise the dict lands
    verbatim in recap_extras_json via the RPC.
    """
    owned_row = {
        "id": "meet-1",
        "tenant_id": "tenant-1",
        "status": "completed",
        "source": "desktop_sdk",
        "summary_json": {"tldr": "Old recap"},
        "recap_extras_json": {"intent": "Old intent"},
    }
    mock_sb = MagicMock()
    mock_sb.table.return_value = _chain_returning(owned_row)

    with patch("routers.desktop_recordings.supabase", mock_sb):
        app = _app_with_user(USER)
        client = TestClient(app)
        for field in ("tldr", "intent", "what_happened"):
            for bad in ({"injected": "dict"}, 42, True):
                resp = client.patch(
                    "/v2/desktop-recordings/meet-1/recap",
                    json={"field": field, "after": bad},
                )
                assert resp.status_code == 400, f"{field}={bad!r} should 400"
                assert "string" in resp.json()["detail"].lower()


def test_patch_recap_wrong_tenant_returns_404() -> None:
    foreign_row = {
        "id": "meet-1",
        "tenant_id": "tenant-2",
        "status": "completed",
        "source": "desktop_sdk",
    }
    mock_sb = MagicMock()
    mock_sb.table.return_value = _chain_returning(foreign_row)

    with patch("routers.desktop_recordings.supabase", mock_sb):
        app = _app_with_user(USER)
        client = TestClient(app)
        resp = client.patch(
            "/v2/desktop-recordings/meet-1/recap",
            json={"field": "tldr", "after": "New recap"},
        )

    assert resp.status_code == 404


def test_patch_recap_action_items_with_future_due_at_schedules_reminder() -> None:
    owned_row = {
        "id": "meet-1",
        "tenant_id": "tenant-1",
        "twin_id": "11111111-1111-1111-1111-111111111111",
        "status": "completed",
        "source": "desktop_sdk",
        "summary_json": {"action_items": []},
        "recap_extras_json": {},
        "action_items": [],
    }
    # 14 days in the future (well within the 90-day clamp horizon from F5.1).
    future_due = (datetime.now(timezone.utc) + timedelta(days=14)).replace(microsecond=0)
    action_items = [{
        "text": "Send pricing",
        "assignee": "Alice",
        "assignee_email": "",
        "due_at": future_due.isoformat(),
    }]
    updated_row = {
        **owned_row,
        "summary_json": {"action_items": action_items},
        "action_items": action_items,
    }

    meetings_chain = MagicMock()
    meetings_chain.select.return_value = meetings_chain
    meetings_chain.maybe_single.return_value = meetings_chain
    meetings_chain.eq.return_value = meetings_chain
    meetings_chain.execute.return_value = _result(owned_row)

    prefs_chain = MagicMock()
    prefs_chain.select.return_value = prefs_chain
    prefs_chain.eq.return_value = prefs_chain
    prefs_chain.maybe_single.return_value = prefs_chain
    prefs_chain.execute.return_value = _result({"action_item_lead_time_minutes": 30})

    def _table(name: str) -> MagicMock:
        if name == "notification_preferences":
            return prefs_chain
        return meetings_chain

    rpc_chain, _ = _rpc_mock_returning(updated_row)

    mock_sb = MagicMock()
    mock_sb.table.side_effect = _table
    mock_sb.rpc.return_value = rpc_chain
    mock_outbox = MagicMock()

    with patch("routers.desktop_recordings.supabase", mock_sb), \
         patch("modules.graph_outbox.get_graph_outbox", return_value=mock_outbox):
        app = _app_with_user(USER)
        client = TestClient(app)
        resp = client.patch(
            "/v2/desktop-recordings/meet-1/recap",
            json={"field": "action_items", "after": action_items},
        )

    assert resp.status_code == 200, resp.text
    reminder_calls = [
        call for call in mock_outbox.submit.call_args_list
        if call.kwargs.get("idempotency_key") == "action_item_reminder:meet-1:0"
    ]
    assert len(reminder_calls) == 1
    kwargs = reminder_calls[0].kwargs
    assert kwargs["idempotency_key"] == "action_item_reminder:meet-1:0"
    assert kwargs["payload"]["recipient_email"] == "u1@example.com"
    assert kwargs["payload"]["action_item_index"] == 0
    assert kwargs["next_attempt_after"] == future_due - timedelta(minutes=30)


def test_patch_recap_action_items_clamps_far_future_due_at_to_90_days() -> None:
    """Regression for review minor F5.1: a malformed due_at far in the
    future (year 2999 or beyond) must clamp to now+90d, otherwise a
    graph_outbox row sits idle and fires at an unexpected time.
    """
    owned_row = {
        "id": "meet-1",
        "tenant_id": "tenant-1",
        "twin_id": "11111111-1111-1111-1111-111111111111",
        "status": "completed",
        "source": "desktop_sdk",
        "summary_json": {"action_items": []},
        "recap_extras_json": {},
        "action_items": [],
    }
    action_items = [{
        "text": "Send pricing",
        "assignee": "Alice",
        "assignee_email": "alice@example.com",
        "due_at": "2999-05-28T12:00:00Z",
    }]
    updated_row = {
        **owned_row,
        "summary_json": {"action_items": action_items},
        "action_items": action_items,
    }
    meetings_chain = MagicMock()
    meetings_chain.select.return_value = meetings_chain
    meetings_chain.maybe_single.return_value = meetings_chain
    meetings_chain.eq.return_value = meetings_chain
    meetings_chain.execute.return_value = _result(owned_row)

    prefs_chain = MagicMock()
    prefs_chain.select.return_value = prefs_chain
    prefs_chain.eq.return_value = prefs_chain
    prefs_chain.maybe_single.return_value = prefs_chain
    prefs_chain.execute.return_value = _result({"action_item_lead_time_minutes": 30})

    rpc_chain, _ = _rpc_mock_returning(updated_row)

    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: prefs_chain if name == "notification_preferences" else meetings_chain
    mock_sb.rpc.return_value = rpc_chain
    mock_outbox = MagicMock()

    now_before = datetime.now(timezone.utc)
    with patch("routers.desktop_recordings.supabase", mock_sb), \
         patch("modules.graph_outbox.get_graph_outbox", return_value=mock_outbox):
        app = _app_with_user(USER)
        client = TestClient(app)
        resp = client.patch(
            "/v2/desktop-recordings/meet-1/recap",
            json={"field": "action_items", "after": action_items},
        )
    now_after = datetime.now(timezone.utc)

    assert resp.status_code == 200, resp.text
    reminder_calls = [
        call for call in mock_outbox.submit.call_args_list
        if call.kwargs.get("idempotency_key") == "action_item_reminder:meet-1:0"
    ]
    assert len(reminder_calls) == 1
    clamped = reminder_calls[0].kwargs["next_attempt_after"]
    # Clamp lands at now + 90 days, within the now_before/now_after window.
    assert (now_before + timedelta(days=90)) <= clamped <= (now_after + timedelta(days=90))


def test_patch_recap_action_items_invalid_assignee_email_does_not_enqueue() -> None:
    """Regression for review blocker #1 (email open-relay).

    Authenticated user supplies a malformed `assignee_email` ("not-an-email")
    to PATCH /recap. The reminder MUST NOT be enqueued — otherwise the
    worker would attempt to send a PersonaOn-domain email to whatever string
    a client could craft.
    """
    owned_row = {
        "id": "meet-1",
        "tenant_id": "tenant-1",
        "twin_id": None,
        "status": "completed",
        "source": "desktop_sdk",
        "summary_json": {"action_items": []},
        "recap_extras_json": {},
        "action_items": [],
    }
    action_items = [{
        "text": "Send MSA",
        "assignee": "Sai",
        "assignee_email": "not-an-email",  # invalid format
        "due_at": "2999-05-28T12:00:00Z",
    }]
    updated_row = {
        **owned_row,
        "summary_json": {"action_items": action_items},
        "action_items": action_items,
    }
    meetings_chain = MagicMock()
    meetings_chain.select.return_value = meetings_chain
    meetings_chain.maybe_single.return_value = meetings_chain
    meetings_chain.eq.return_value = meetings_chain
    meetings_chain.execute.return_value = _result(owned_row)

    # Make USER's fallback email also invalid so the only candidate is the
    # malformed assignee_email — this isolates the validation behaviour.
    invalid_user = {"user_id": USER["user_id"], "tenant_id": USER["tenant_id"], "email": "broken"}

    rpc_chain, _ = _rpc_mock_returning(updated_row)

    mock_sb = MagicMock()
    mock_sb.table.return_value = meetings_chain
    mock_sb.rpc.return_value = rpc_chain
    mock_outbox = MagicMock()

    with patch("routers.desktop_recordings.supabase", mock_sb), \
         patch("modules.graph_outbox.get_graph_outbox", return_value=mock_outbox):
        app = _app_with_user(invalid_user)
        client = TestClient(app)
        resp = client.patch(
            "/v2/desktop-recordings/meet-1/recap",
            json={"field": "action_items", "after": action_items},
        )

    assert resp.status_code == 200, resp.text
    # No reminder enqueueing — both the assignee_email and the fallback
    # email failed the is_valid_email() check.
    reminder_calls = [
        call for call in mock_outbox.submit.call_args_list
        if str(call.kwargs.get("idempotency_key", "")).startswith("action_item_reminder:")
    ]
    assert reminder_calls == [], f"unexpected enqueue: {reminder_calls}"


def test_patch_recap_action_items_with_past_due_at_does_not_schedule() -> None:
    owned_row = {
        "id": "meet-1",
        "tenant_id": "tenant-1",
        "twin_id": None,
        "status": "completed",
        "source": "desktop_sdk",
        "summary_json": {"action_items": []},
        "recap_extras_json": {},
        "action_items": [],
    }
    action_items = [{"text": "Already due", "due_at": "2020-01-01T12:00:00Z"}]
    updated_row = {
        **owned_row,
        "summary_json": {"action_items": action_items},
        "action_items": action_items,
    }
    meetings_chain = MagicMock()
    meetings_chain.select.return_value = meetings_chain
    meetings_chain.maybe_single.return_value = meetings_chain
    meetings_chain.eq.return_value = meetings_chain
    meetings_chain.execute.return_value = _result(owned_row)

    rpc_chain, _ = _rpc_mock_returning(updated_row)

    mock_sb = MagicMock()
    mock_sb.table.return_value = meetings_chain
    mock_sb.rpc.return_value = rpc_chain
    mock_outbox = MagicMock()

    with patch("routers.desktop_recordings.supabase", mock_sb), \
         patch("modules.graph_outbox.get_graph_outbox", return_value=mock_outbox):
        app = _app_with_user(USER)
        client = TestClient(app)
        resp = client.patch(
            "/v2/desktop-recordings/meet-1/recap",
            json={"field": "action_items", "after": action_items},
        )

    assert resp.status_code == 200, resp.text
    reminder_calls = [
        call for call in mock_outbox.submit.call_args_list
        if str(call.kwargs.get("idempotency_key", "")).startswith("action_item_reminder:")
    ]
    assert reminder_calls == []


# ---------------------------------------------------------------------------
# PATCH /{id}/recap atomicity (F3 — review blocker #7)
# ---------------------------------------------------------------------------

def test_patch_recap_uses_atomic_rpc_not_separate_writes() -> None:
    """Regression for review blocker #7 (F3).

    PATCH /recap must apply the JSONB merge AND insert the recap_edits audit
    row inside a single Postgres transaction so the before/after pair
    reflects the row state at UPDATE time. Two concurrent PATCHes reading
    the same `summary_json` would otherwise compute stale `before`
    snapshots and silently overwrite each other.

    We assert at the Python boundary by checking the router no longer
    issues separate `.table('meetings').update(...)` and
    `.table('recap_edits').insert(...)` writes, and instead calls
    `supabase.rpc('update_recap_with_audit', ...)`. The actual row-lock
    behaviour is covered by the Postgres function itself (FOR UPDATE in
    20260529000200_atomic_recap_patch_rpc.sql).
    """
    owned_row = {
        "id": "meet-1",
        "tenant_id": "tenant-1",
        "twin_id": None,
        "status": "completed",
        "source": "desktop_sdk",
        "summary_json": {"tldr": "Old recap"},
        "recap_extras_json": {},
        "action_items": [],
    }
    updated_row = {**owned_row, "summary_json": {"tldr": "New recap"}}

    meetings_chain = MagicMock()
    meetings_chain.select.return_value = meetings_chain
    meetings_chain.maybe_single.return_value = meetings_chain
    meetings_chain.eq.return_value = meetings_chain
    # Only the ownership SELECT is allowed; assert via update/insert side effects.
    meetings_chain.execute.return_value = _result(owned_row)
    update_spy = MagicMock(side_effect=AssertionError(
        "router must not call .table('meetings').update() after F3 RPC"
    ))
    meetings_chain.update = update_spy

    edits_chain = MagicMock()
    insert_spy = MagicMock(side_effect=AssertionError(
        "router must not call .table('recap_edits').insert() after F3 RPC"
    ))
    edits_chain.insert = insert_spy

    rpc_chain = MagicMock()
    rpc_calls: list[tuple[str, dict[str, Any]]] = []
    rpc_chain.execute.return_value = _result({
        "meeting": updated_row,
        "edit_id": "edit-1",
    })

    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: edits_chain if name == "recap_edits" else meetings_chain
    mock_sb.rpc.side_effect = lambda fn, params: (
        rpc_calls.append((fn, params)) or rpc_chain
    )
    mock_outbox = MagicMock()

    with patch("routers.desktop_recordings.supabase", mock_sb), \
         patch("modules.graph_outbox.get_graph_outbox", return_value=mock_outbox):
        app = _app_with_user(USER)
        client = TestClient(app)
        resp = client.patch(
            "/v2/desktop-recordings/meet-1/recap",
            json={"field": "tldr", "after": "New recap"},
        )

    assert resp.status_code == 200, resp.text
    # Critical: exactly one rpc call to update_recap_with_audit with the
    # whitelisted json_column derived from the field.
    assert len(rpc_calls) == 1, f"expected 1 rpc call, got {rpc_calls}"
    fn_name, params = rpc_calls[0]
    assert fn_name == "update_recap_with_audit"
    assert params["p_meeting_id"] == "meet-1"
    assert params["p_tenant_id"] == "tenant-1"
    assert params["p_user_id"] == "user-1"
    assert params["p_field"] == "tldr"
    assert params["p_json_column"] == "summary_json"
    assert params["p_after"] == "New recap"
    # The returned meeting comes from the RPC, not a follow-up SELECT.
    assert resp.json()["data"]["summary_json"]["tldr"] == "New recap"
    # And the edit_id is threaded into the routing-job enqueue.
    mock_outbox.submit.assert_called_once()
    assert mock_outbox.submit.call_args.kwargs["idempotency_key"] == "edit_routing:edit-1"


# ---------------------------------------------------------------------------
# DELETE /{id}
# ---------------------------------------------------------------------------

def test_delete_soft_deletes_and_filters_by_tenant_id() -> None:
    """DELETE must filter UPDATE by both id AND tenant_id (defense-in-depth)."""
    owned_row = {
        "id": "meet-1",
        "tenant_id": "tenant-1",
        "status": "completed",
        "source": "desktop_sdk",
    }
    captured_updates: list[dict[str, Any]] = []
    captured_eq: list[tuple[str, Any]] = []

    chain = MagicMock()
    chain.select.return_value = chain
    chain.maybe_single.return_value = chain

    def _eq(col: str, val: Any) -> MagicMock:
        captured_eq.append((col, val))
        return chain

    chain.eq.side_effect = _eq

    def _update(payload: dict[str, Any]) -> MagicMock:
        captured_updates.append(payload)
        return chain

    chain.update.side_effect = _update
    chain.execute.side_effect = [
        _result(owned_row),                              # SELECT in _fetch_owned
        _result([{**owned_row, "status": "deleted"}]),   # UPDATE
    ]

    mock_sb = MagicMock()
    mock_sb.table.return_value = chain

    with patch("routers.desktop_recordings.supabase", mock_sb):
        app = _app_with_user(USER)
        client = TestClient(app)
        resp = client.delete("/v2/desktop-recordings/meet-1")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["deleted"] is True
    assert captured_updates
    assert captured_updates[0]["status"] == "deleted"
    # Critical: tenant_id filter must be applied to the UPDATE
    assert ("tenant_id", "tenant-1") in captured_eq, \
        f"DELETE must include .eq('tenant_id', ...): {captured_eq}"


# ---------------------------------------------------------------------------
# C3 — Recap list-field sanitization (audit 2026-05-31)
# ---------------------------------------------------------------------------

def test_patch_recap_action_items_strips_unknown_object_keys() -> None:
    """Audit C3: action_items list items must only carry allow-listed keys.
    Unknown keys (anything a future renderer might trust without escaping)
    are dropped before persistence. This blocks the stored-XSS vector where a
    client smuggles `<script>` payloads via fields like `html` or `raw`.
    """
    from routers.desktop_recordings import _normalize_recap_after

    payload = [
        {
            "text": "Review the contract",
            "assignee": "Alice",
            "due_at": "2026-06-15T10:00:00Z",
            # Unknown keys -- must be silently dropped:
            "html": "<script>alert(1)</script>",
            "raw": "<img src=x onerror=alert(1)>",
            "__proto__": {"polluted": True},
        }
    ]
    cleaned = _normalize_recap_after("action_items", payload)
    assert len(cleaned) == 1
    item = cleaned[0]
    assert item["text"] == "Review the contract"
    assert item["assignee"] == "Alice"
    assert item["due_at"] == "2026-06-15T10:00:00Z"
    assert "html" not in item
    assert "raw" not in item
    assert "__proto__" not in item


def test_patch_recap_action_items_caps_string_length() -> None:
    """Audit C3: each list-item string is capped at 2000 chars regardless of
    field. Without this cap a client can park arbitrarily large blobs in
    summary_json / recap_extras_json.
    """
    from routers.desktop_recordings import (
        _MAX_RECAP_TEXT_LEN,
        _normalize_recap_after,
    )

    huge = "x" * (_MAX_RECAP_TEXT_LEN + 5000)
    cleaned = _normalize_recap_after("action_items", [{"text": huge}])
    assert len(cleaned[0]["text"]) == _MAX_RECAP_TEXT_LEN


def test_patch_recap_action_items_rejects_too_many_items() -> None:
    """Audit C3: list length is bounded so a malicious client can't smuggle
    a huge JSONB blob via the recap edit path.
    """
    from fastapi import HTTPException

    from routers.desktop_recordings import (
        _MAX_RECAP_LIST_ITEMS,
        _normalize_recap_after,
    )

    too_many = [{"text": f"item {i}"} for i in range(_MAX_RECAP_LIST_ITEMS + 1)]
    with pytest.raises(HTTPException) as exc:
        _normalize_recap_after("action_items", too_many)
    assert exc.value.status_code == 400
    assert "maximum item count" in exc.value.detail.lower()


def test_patch_recap_action_items_rejects_nested_objects() -> None:
    """Audit C3: a list item's values must be scalars (or scalar lists).
    Nested objects would let a payload smuggle arbitrary depth and shape
    past the cap-and-allow-list defense.
    """
    from fastapi import HTTPException

    from routers.desktop_recordings import _normalize_recap_after

    with pytest.raises(HTTPException) as exc:
        _normalize_recap_after(
            "action_items",
            [{"text": "ok", "context": {"nested": "obj"}}],
        )
    assert exc.value.status_code == 400


def test_patch_recap_topics_accepts_plain_strings() -> None:
    """Audit C3: topics is a list of strings in the normal contract; ensure
    the sanitizer doesn't break the simple path.
    """
    from routers.desktop_recordings import _normalize_recap_after

    cleaned = _normalize_recap_after("topics", ["pricing", "rollout plan"])
    assert cleaned == ["pricing", "rollout plan"]


def test_patch_recap_string_field_caps_length() -> None:
    """Audit C3: paragraph-shaped string fields (tldr, intent, what_happened)
    have a generous-but-finite cap so a runaway client can't store an
    unbounded blob in the column.
    """
    from fastapi import HTTPException

    from routers.desktop_recordings import (
        _MAX_RECAP_TEXT_LEN,
        _normalize_recap_after,
    )

    huge = "x" * (_MAX_RECAP_TEXT_LEN * 10 + 1)
    with pytest.raises(HTTPException) as exc:
        _normalize_recap_after("tldr", huge)
    assert exc.value.status_code == 400
    assert "maximum length" in exc.value.detail.lower()
