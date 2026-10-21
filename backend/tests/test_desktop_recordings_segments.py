"""Tests for the live transcript segments endpoints (Granola Batch 2).

Covers POST /v2/desktop-recordings/{id}/segments and GET .../segments:
- owner gate (401 unauthenticated, 404 cross-tenant)
- idempotent upsert (on_conflict=meeting_id,seq, ignore_duplicates=True)
- only is_final segments persist; partials are dropped
- empty/whitespace text skipped
- intra-batch duplicate seq collapsed
- validation (empty batch, oversized batch, bad seq)
- GET returns ordered segments, [] when none exist
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from modules.auth_guard import verify_owner
from routers.desktop_recordings import router

USER = {"user_id": "user-1", "tenant_id": "tenant-1", "email": "u1@example.com"}
OTHER_USER = {"user_id": "user-2", "tenant_id": "tenant-2", "email": "u2@example.com"}
MEETING_ID = "11111111-1111-1111-1111-111111111111"


def _result(data: Any) -> SimpleNamespace:
    return SimpleNamespace(data=data)


def _owned_row(tenant_id: str = "tenant-1") -> dict[str, Any]:
    return {"id": MEETING_ID, "tenant_id": tenant_id, "status": "recording"}


def _client(user: dict[str, Any] | None) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    if user is not None:
        app.dependency_overrides[verify_owner] = lambda: user
    else:
        app.dependency_overrides[verify_owner] = lambda: (_ for _ in ()).throw(
            HTTPException(status_code=401, detail="Authentication required")
        )
    return TestClient(app, raise_server_exceptions=False)


def _supabase_mock(*, owned_row: dict[str, Any] | None, segments: list[dict[str, Any]] | None = None) -> MagicMock:
    """A supabase mock routed by table name.

    - meetings -> _fetch_owned SELECT returns owned_row (or None for 404)
    - meeting_transcript_segments -> records upsert calls / returns segments on select
    """
    captured: dict[str, Any] = {"upserts": []}

    meetings_chain = MagicMock()
    for method in ("select", "eq", "neq", "order", "range", "maybe_single"):
        getattr(meetings_chain, method).return_value = meetings_chain
    meetings_chain.execute.return_value = _result(owned_row)

    seg_chain = MagicMock()
    for method in ("select", "eq", "order"):
        getattr(seg_chain, method).return_value = seg_chain
    seg_chain.execute.return_value = _result(segments or [])

    def _upsert(rows: Any, **kwargs: Any) -> MagicMock:
        captured["upserts"].append({"rows": rows, "kwargs": kwargs})
        out = MagicMock()
        out.execute.return_value = _result(rows)
        return out

    seg_chain.upsert.side_effect = _upsert

    sb = MagicMock()
    sb.table.side_effect = lambda name: (
        meetings_chain if name == "meetings" else seg_chain
    )
    sb._captured = captured  # type: ignore[attr-defined]
    return sb


# ---------------------------------------------------------------------------
# Auth / ownership
# ---------------------------------------------------------------------------

def test_post_segments_requires_auth() -> None:
    resp = _client(None).post(
        f"/v2/desktop-recordings/{MEETING_ID}/segments",
        json={"segments": [{"seq": 0, "text": "hi", "is_final": True}]},
    )
    assert resp.status_code == 401


def test_post_segments_cross_tenant_returns_404() -> None:
    sb = _supabase_mock(owned_row=_owned_row(tenant_id="tenant-1"))
    with patch("routers.desktop_recordings.supabase", sb):
        resp = _client(OTHER_USER).post(
            f"/v2/desktop-recordings/{MEETING_ID}/segments",
            json={"segments": [{"seq": 0, "text": "hi", "is_final": True}]},
        )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Persistence behavior
# ---------------------------------------------------------------------------

def test_post_segments_upserts_only_finals_idempotently() -> None:
    sb = _supabase_mock(owned_row=_owned_row())
    with patch("routers.desktop_recordings.supabase", sb):
        resp = _client(USER).post(
            f"/v2/desktop-recordings/{MEETING_ID}/segments",
            json={"segments": [
                {"seq": 0, "speaker": "Alice", "text": "hello", "is_final": True, "start_ms": 100},
                {"seq": 1, "speaker": "Alice", "text": "partial", "is_final": False},
                {"seq": 2, "speaker": "Bob", "text": "   ", "is_final": True},
                {"seq": 3, "text": "world", "is_final": True},
            ]},
        )
    assert resp.status_code == 200
    # is_final=True with non-empty text => seq 0 and seq 3 only.
    assert resp.json() == {"status": "ok", "data": {"inserted": 2}}

    upserts = sb._captured["upserts"]
    assert len(upserts) == 1
    rows = upserts[0]["rows"]
    assert [r["seq"] for r in rows] == [0, 3]
    assert all(r["is_final"] is True for r in rows)
    assert all(r["meeting_id"] == MEETING_ID for r in rows)
    assert all(r["tenant_id"] == "tenant-1" for r in rows)
    # idempotent upsert config
    assert upserts[0]["kwargs"]["on_conflict"] == "meeting_id,seq"
    assert upserts[0]["kwargs"]["ignore_duplicates"] is True


def test_post_segments_collapses_intra_batch_duplicate_seq() -> None:
    sb = _supabase_mock(owned_row=_owned_row())
    with patch("routers.desktop_recordings.supabase", sb):
        resp = _client(USER).post(
            f"/v2/desktop-recordings/{MEETING_ID}/segments",
            json={"segments": [
                {"seq": 5, "text": "first", "is_final": True},
                {"seq": 5, "text": "replay", "is_final": True},
            ]},
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["inserted"] == 1
    rows = sb._captured["upserts"][0]["rows"]
    assert [r["seq"] for r in rows] == [5]


def test_post_segments_no_finals_returns_zero_no_upsert() -> None:
    sb = _supabase_mock(owned_row=_owned_row())
    with patch("routers.desktop_recordings.supabase", sb):
        resp = _client(USER).post(
            f"/v2/desktop-recordings/{MEETING_ID}/segments",
            json={"segments": [{"seq": 0, "text": "partial", "is_final": False}]},
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["inserted"] == 0
    assert sb._captured["upserts"] == []


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_post_segments_rejects_empty_batch() -> None:
    sb = _supabase_mock(owned_row=_owned_row())
    with patch("routers.desktop_recordings.supabase", sb):
        resp = _client(USER).post(
            f"/v2/desktop-recordings/{MEETING_ID}/segments",
            json={"segments": []},
        )
    assert resp.status_code == 422


def test_post_segments_rejects_oversized_batch() -> None:
    sb = _supabase_mock(owned_row=_owned_row())
    big = [{"seq": i, "text": "x", "is_final": True} for i in range(201)]
    with patch("routers.desktop_recordings.supabase", sb):
        resp = _client(USER).post(
            f"/v2/desktop-recordings/{MEETING_ID}/segments",
            json={"segments": big},
        )
    assert resp.status_code == 422


def test_post_segments_rejects_empty_text_field() -> None:
    sb = _supabase_mock(owned_row=_owned_row())
    with patch("routers.desktop_recordings.supabase", sb):
        resp = _client(USER).post(
            f"/v2/desktop-recordings/{MEETING_ID}/segments",
            json={"segments": [{"seq": 0, "text": "", "is_final": True}]},
        )
    assert resp.status_code == 422


def test_post_segments_rejects_non_int_seq() -> None:
    sb = _supabase_mock(owned_row=_owned_row())
    with patch("routers.desktop_recordings.supabase", sb):
        resp = _client(USER).post(
            f"/v2/desktop-recordings/{MEETING_ID}/segments",
            json={"segments": [{"seq": "abc", "text": "hi", "is_final": True}]},
        )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET segments
# ---------------------------------------------------------------------------

def test_get_segments_returns_ordered_items() -> None:
    seg_rows = [
        {"seq": 0, "speaker": "Alice", "text": "hello", "is_final": True, "start_ms": 100, "created_at": "t0"},
        {"seq": 1, "speaker": "Bob", "text": "world", "is_final": True, "start_ms": 200, "created_at": "t1"},
    ]
    sb = _supabase_mock(owned_row=_owned_row(), segments=seg_rows)
    with patch("routers.desktop_recordings.supabase", sb):
        resp = _client(USER).get(f"/v2/desktop-recordings/{MEETING_ID}/segments")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "data": {"items": seg_rows}}


def test_get_segments_returns_empty_when_none() -> None:
    sb = _supabase_mock(owned_row=_owned_row(), segments=[])
    with patch("routers.desktop_recordings.supabase", sb):
        resp = _client(USER).get(f"/v2/desktop-recordings/{MEETING_ID}/segments")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "data": {"items": []}}


def test_get_segments_cross_tenant_returns_404() -> None:
    sb = _supabase_mock(owned_row=_owned_row(tenant_id="tenant-1"))
    with patch("routers.desktop_recordings.supabase", sb):
        resp = _client(OTHER_USER).get(f"/v2/desktop-recordings/{MEETING_ID}/segments")
    assert resp.status_code == 404
