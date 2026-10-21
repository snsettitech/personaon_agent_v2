"""Tests for public recap share token + sanitized unauthenticated endpoint.

Security assertions verified:
- share/unshare are owner-only (cross-tenant → 404)
- public endpoint returns ONLY whitelisted fields (no signed URLs, tenant id, etc.)
- action items strip assignee_email
- disabled or missing share token → identical 404 (no existence leak)
- short/bad tokens → 404
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.auth_guard import verify_owner
from routers import desktop_recordings, public_recap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(data: Any) -> SimpleNamespace:
    return SimpleNamespace(data=data)


def _fetch_owned_chain(row: dict[str, Any] | None) -> MagicMock:
    """Fluent chain that mimics _fetch_owned's supabase call path."""
    m = MagicMock()
    m.select.return_value = m
    m.eq.return_value = m
    m.maybe_single.return_value = m
    m.execute.return_value = _result(row)
    return m


def _update_chain() -> MagicMock:
    """Fluent chain for .update().eq().execute()."""
    m = MagicMock()
    m.update.return_value = m
    m.eq.return_value = m
    m.execute.return_value = _result([{"id": "meet-1"}])
    return m


def _app_for_recordings(user: dict[str, Any]) -> FastAPI:
    app = FastAPI()
    app.include_router(desktop_recordings.router)
    app.dependency_overrides[verify_owner] = lambda: user
    return app


def _app_for_public() -> FastAPI:
    app = FastAPI()
    app.include_router(public_recap.router)
    return app


OWNER_USER = {"user_id": "user-1", "tenant_id": "tenant-1", "email": "owner@example.com"}

_BASE_MEETING_ROW = {
    "id": "meet-1",
    "tenant_id": "tenant-1",
    "title": "Weekly Sync",
    "status": "completed",
    "source": "desktop_sdk",
    "platform": "google-meet",
    "duration_seconds": 3600,
    "meeting_start": "2026-05-27T10:00:00+00:00",
    "meeting_end": "2026-05-27T11:00:00+00:00",
    "created_at": "2026-05-27T10:00:00+00:00",
    "updated_at": "2026-05-27T11:00:00+00:00",
    "transcript_url": "https://s3.aws.com/signed?AWSAccessKeyId=SECRET&token=XYZ",
    "video_url": "https://s3.aws.com/video?AWSAccessKeyId=SECRET&token=XYZ",
    "speaker_timeline_url": "https://s3.aws.com/timeline?AWSAccessKeyId=SECRET",
    "transcript_provider": "deepgram",
    "summary": "A great meeting.",
    "summary_json": {"tldr": "We discussed roadmap.", "topics": ["feature A"]},
    "recap_extras_json": {"intent": "Planning", "what_happened": "Discussed scope"},
    "action_items": [
        {
            "text": "Send follow-up email",
            "assignee": "Alice",
            "assignee_email": "alice@example.com",
            "context": "From slide 3",
            "due_at": "2026-06-01T12:00:00Z",
            "completed": False,
        }
    ],
    "twin_id": "twin-111",
    "recall_recording_id": "rec-001",
    "public_share_token": None,
    "public_share_enabled": False,
    "public_shared_at": None,
}


# ---------------------------------------------------------------------------
# Test 1: share then unshare (owner happy path)
# ---------------------------------------------------------------------------

def test_share_then_unshare_owner() -> None:
    """POST share → 200 with token/url/enabled=True; DELETE share → 200 enabled=False."""
    row = {**_BASE_MEETING_ROW, "public_share_token": None}

    fetch_chain = _fetch_owned_chain(row)
    update_chain = _update_chain()

    def _table(name: str) -> MagicMock:
        if name == "meetings":
            return fetch_chain
        return MagicMock()  # pragma: no cover

    update_chain_obj = MagicMock()
    update_chain_obj.update.return_value = update_chain_obj
    update_chain_obj.eq.return_value = update_chain_obj
    update_chain_obj.execute.return_value = _result([{"id": "meet-1"}])

    with patch("routers.desktop_recordings.supabase") as mock_sb:
        # Set up: fetch returns the row; updates return success
        mock_sb.table.return_value = MagicMock(
            select=MagicMock(return_value=MagicMock(
                eq=MagicMock(return_value=MagicMock(
                    maybe_single=MagicMock(return_value=MagicMock(
                        execute=MagicMock(return_value=_result(row))
                    ))
                ))
            )),
            update=MagicMock(return_value=update_chain_obj),
        )

        client = TestClient(_app_for_recordings(OWNER_USER), raise_server_exceptions=False)

        # Build a more ergonomic mock using side_effect on table calls
        # Reset to a simpler per-call approach
        call_count = [0]

        def _table_side_effect(name: str) -> MagicMock:
            call_count[0] += 1
            if name != "meetings":
                return MagicMock()

            chain = MagicMock()
            # select path (used by _fetch_owned)
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.maybe_single.return_value = chain
            chain.execute.return_value = _result(row)
            # update path
            chain.update.return_value = chain
            return chain

        mock_sb.table.side_effect = _table_side_effect

        # POST /share
        resp = client.post("/v2/desktop-recordings/meet-1/share")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "ok"
        share_data = data["data"]
        assert share_data["enabled"] is True
        assert share_data["token"]  # non-empty
        assert len(share_data["token"]) >= 16
        assert share_data["url"].endswith(f"/shared-meeting/{share_data['token']}")

        # DELETE /share
        resp2 = client.delete("/v2/desktop-recordings/meet-1/share")
        assert resp2.status_code == 200, resp2.text
        data2 = resp2.json()
        assert data2["status"] == "ok"
        assert data2["data"]["enabled"] is False


# ---------------------------------------------------------------------------
# Test 2: cross-tenant share attempt → 404
# ---------------------------------------------------------------------------

def test_share_cross_tenant_404() -> None:
    """A row owned by tenant-2 returns 404 when user is tenant-1."""
    other_tenant_row = {**_BASE_MEETING_ROW, "tenant_id": "tenant-2"}

    with patch("routers.desktop_recordings.supabase") as mock_sb:
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.maybe_single.return_value = chain
        chain.execute.return_value = _result(other_tenant_row)
        mock_sb.table.return_value = chain

        client = TestClient(_app_for_recordings(OWNER_USER), raise_server_exceptions=False)
        resp = client.post("/v2/desktop-recordings/meet-1/share")
        assert resp.status_code == 404
        assert "Recording not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Test 3: public recap — sanitized output
# ---------------------------------------------------------------------------

def test_public_recap_returns_sanitized() -> None:
    """GET /v2/public/recap/<token> → 200; no forbidden keys in response data."""
    valid_token = "a" * 22  # 22-char url-safe token (>= 16)
    public_row = {
        "title": "Weekly Sync",
        "meeting_start": "2026-05-27T10:00:00+00:00",
        "duration_seconds": 3600,
        "platform": "google-meet",
        "summary_json": {"tldr": "We discussed roadmap."},
        "recap_extras_json": {"intent": "Planning"},
        "action_items": [
            {
                "text": "Send follow-up email",
                "assignee": "Alice",
                "assignee_email": "alice@example.com",
                "context": "From slide 3",
                "due_at": "2026-06-01T12:00:00Z",
                "completed": False,
            }
        ],
        "public_share_enabled": True,
        "status": "completed",
        # Fields that MUST NOT appear in the public response:
        "transcript_url": "https://s3.aws.com/signed?AWSAccessKeyId=SECRET",
        "video_url": "https://s3.aws.com/video?SECRET",
        "speaker_timeline_url": "https://s3.aws.com/timeline?SECRET",
        "tenant_id": "tenant-1",
        "twin_id": "twin-111",
        "recall_recording_id": "rec-001",
    }

    with patch("routers.public_recap.supabase") as mock_sb:
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.maybe_single.return_value = chain
        chain.execute.return_value = _result(public_row)
        mock_sb.table.return_value = chain

        client = TestClient(_app_for_public(), raise_server_exceptions=False)
        resp = client.get(f"/v2/public/recap/{valid_token}")
        assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["status"] == "ok"
    data = body["data"]

    # Forbidden keys MUST be absent from the returned data
    forbidden_keys = {
        "transcript_url", "video_url", "speaker_timeline_url",
        "tenant_id", "twin_id", "recall_recording_id",
    }
    for key in forbidden_keys:
        assert key not in data, f"Forbidden key '{key}' leaked into public payload"

    # Whitelisted keys ARE present
    assert data["title"] == "Weekly Sync"
    assert data["summary_json"] == {"tldr": "We discussed roadmap."}

    # Action items: assignee_email stripped, text retained
    assert data["action_items"] is not None
    assert len(data["action_items"]) == 1
    item = data["action_items"][0]
    assert "assignee_email" not in item, "assignee_email must be stripped from public action items"
    assert item["text"] == "Send follow-up email"
    assert item["assignee"] == "Alice"
    assert item["context"] == "From slide 3"


# ---------------------------------------------------------------------------
# Test 4: disabled share token → 404
# ---------------------------------------------------------------------------

def test_public_recap_disabled_is_404() -> None:
    """A meeting with public_share_enabled=False returns 404."""
    disabled_row = {
        "title": "Hidden Meeting",
        "public_share_enabled": False,
        "status": "completed",
        "summary_json": None,
        "recap_extras_json": None,
        "action_items": None,
        "meeting_start": None,
        "duration_seconds": None,
        "platform": None,
    }
    valid_token = "b" * 22

    with patch("routers.public_recap.supabase") as mock_sb:
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.maybe_single.return_value = chain
        chain.execute.return_value = _result(disabled_row)
        mock_sb.table.return_value = chain

        client = TestClient(_app_for_public(), raise_server_exceptions=False)
        resp = client.get(f"/v2/public/recap/{valid_token}")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Recording not found"


# ---------------------------------------------------------------------------
# Test 5: bad or short token → 404
# ---------------------------------------------------------------------------

def test_public_recap_bad_or_short_token_404() -> None:
    """Short token (length guard) and unknown token (no row) both return 404."""
    client = TestClient(_app_for_public(), raise_server_exceptions=False)

    # Short token — caught by length guard before any DB call
    resp_short = client.get("/v2/public/recap/x")
    assert resp_short.status_code == 404
    assert resp_short.json()["detail"] == "Recording not found"

    # Unknown token — DB returns None (no matching row)
    unknown_token = "c" * 22
    with patch("routers.public_recap.supabase") as mock_sb:
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.maybe_single.return_value = chain
        chain.execute.return_value = _result(None)
        mock_sb.table.return_value = chain

        resp_unknown = client.get(f"/v2/public/recap/{unknown_token}")

    assert resp_unknown.status_code == 404
    assert resp_unknown.json()["detail"] == "Recording not found"


# ---------------------------------------------------------------------------
# Test 6: _sanitize_action_items edge cases
# ---------------------------------------------------------------------------

def test_sanitize_action_items_edge_cases() -> None:
    """Non-dict entries are filtered out; non-list inputs return []."""
    from routers.public_recap import _sanitize_action_items

    # Mixed list: two non-dict entries + one valid dict
    result = _sanitize_action_items([
        "not a dict",
        123,
        {"text": "ok", "assignee": "Al", "assignee_email": "al@x.com", "completed": True},
    ])
    assert result is not None
    assert len(result) == 1
    item = result[0]
    assert item["text"] == "ok"
    assert "assignee_email" not in item

    # Non-list inputs → empty list (services.recap_sanitizer, 9cd85ee7)
    assert _sanitize_action_items("not a list") == []
    assert _sanitize_action_items(None) == []


# ---------------------------------------------------------------------------
# Test 7: _pick whitelist — summary_json/recap_extras_json keys hardened
# ---------------------------------------------------------------------------

def test_public_recap_summary_extras_whitelist() -> None:
    """summary_json and recap_extras_json are filtered to their public key sets."""
    import json

    from routers.public_recap import _pick

    # --- Direct unit assertions for _pick ---
    assert _pick({"a": 1, "b": 2}, ("a",)) == {"a": 1}
    assert _pick(None, ("a",)) is None
    assert _pick("x", ("a",)) is None

    # --- Integration: leaked keys must be stripped from the HTTP response ---
    valid_token = "d" * 22
    public_row = {
        "title": "Sensitive Sync",
        "meeting_start": "2026-05-27T10:00:00+00:00",
        "duration_seconds": 1800,
        "platform": "zoom",
        "summary_json": {
            "tldr": "ok",
            "topics": ["t"],
            "key_questions": [],
            # Sensitive extras that MUST be dropped:
            "action_items": [{"text": "x", "assignee_email": "leak@x.com"}],
            "internal_secret": "nope",
        },
        "recap_extras_json": {
            "intent": "i",
            "what_happened": "stuff",
            "commitments": [],
            # Sensitive extra that MUST be dropped:
            "leak_field": "nope",
        },
        "action_items": None,
        "public_share_enabled": True,
        "status": "completed",
    }

    with patch("routers.public_recap.supabase") as mock_sb:
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.maybe_single.return_value = chain
        chain.execute.return_value = _result(public_row)
        mock_sb.table.return_value = chain

        client = TestClient(_app_for_public(), raise_server_exceptions=False)
        resp = client.get(f"/v2/public/recap/{valid_token}")

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    # summary_json — only whitelisted keys present
    sj = data["summary_json"]
    assert set(sj.keys()) <= {"tldr", "topics", "key_questions"}, (
        f"summary_json leaked unexpected keys: {set(sj.keys())}"
    )
    assert sj["tldr"] == "ok"
    assert sj["topics"] == ["t"]
    assert "action_items" not in sj
    assert "internal_secret" not in sj

    # recap_extras_json — only whitelisted keys present
    ej = data["recap_extras_json"]
    assert set(ej.keys()) <= {"intent", "what_happened", "commitments"}, (
        f"recap_extras_json leaked unexpected keys: {set(ej.keys())}"
    )
    assert ej["intent"] == "i"
    assert "leak_field" not in ej

    # Confirmed absence of the sensitive email string anywhere in serialized response
    raw_body = json.dumps(data)
    assert "leak@x.com" not in raw_body, "Email address leaked into public response body"
    assert "nope" not in raw_body, "Sensitive value leaked into public response body"
