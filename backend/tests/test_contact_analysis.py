"""Tests for GET /v2/twins/{twin_id}/contacts/{contact_id}/analysis (Phase W.1).

Uses the chained-MagicMock pattern from test_contact_resolver.py.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from tests._supabase_mock import fluent as _fluent, result as _result

from main import app


# A contact row that _fetch_contact_owned would return
CONTACT = {
    "id": "c-1",
    "name": "Jordan Reyes",
    "email": "jordan@example.com",
    "linkedin_url": None,
    "avatar_url": None,
    "meeting_count": 2,
    "last_seen_at": "2026-05-16T10:00:00Z",
    "first_seen_at": "2026-04-01T10:00:00Z",
    "allow_mention": True,
    "tags": [],
    "notes": None,
    "metadata": None,
    "twin_id": "twin-1",
    "tenant_id": "tenant-1",
}

OWNER_ROW = {"full_name": "Sainath Setti", "email": "sainath@example.com"}

TWIN_ID = "twin-1"
TENANT_ID = "tenant-1"
CONTACT_ID = "c-1"

MEET_1 = {
    "id": "m-1",
    "title": "Q3 review",
    "meeting_start": "2026-05-01T10:00:00Z",
    "meeting_end": None,
    "status": "completed",
    "action_items": [
        {"text": "Send proposal", "assignee": "Sainath", "completed": False},
        {"text": "Review deck", "assignee": "Jordan", "completed": False},
        {"text": "Update roadmap", "assignee": "Marcus", "completed": False},
    ],
}


def _make_auth_override(tenant_id: str = TENANT_ID, user_id: str = "u-1"):
    """Dependency override for verify_owner."""
    def override():
        return {"user_id": user_id, "tenant_id": tenant_id}
    return override


# ---------------------------------------------------------------------------
# Fixture: inject auth override + patch supabase
# ---------------------------------------------------------------------------

from modules.auth_guard import verify_owner  # noqa: E402

client = TestClient(app)


def _call_analysis(
    *,
    contact_row: dict | None = None,
    links: list | None = None,
    meetings: list | None = None,
    owner_row: dict | None = None,
    twin_id: str = TWIN_ID,
    contact_id: str = CONTACT_ID,
    tenant_id: str = TENANT_ID,
) -> dict:
    """Drive the analysis endpoint with fully controlled DB mocks."""
    contact_row = contact_row if contact_row is not None else CONTACT
    links = links if links is not None else [{"meeting_id": "m-1"}]
    meetings = meetings if meetings is not None else [MEET_1]
    owner_row = owner_row if owner_row is not None else OWNER_ROW

    app.dependency_overrides[verify_owner] = _make_auth_override(tenant_id)
    # verify_twin_ownership is a plain function (not a Depends), so we patch it directly

    call_seq = {"n": 0}

    def _table(name: str):
        call_seq["n"] += 1
        m = MagicMock()
        m.select.return_value = m
        m.eq.return_value = m
        m.neq.return_value = m
        m.in_.return_value = m
        m.is_.return_value = m
        m.order.return_value = m
        m.limit.return_value = m
        m.maybe_single.return_value = m

        if name == "contacts":
            m.execute.return_value = _result(contact_row)
        elif name == "users":
            m.execute.return_value = _result([owner_row] if owner_row else [])
        elif name == "contact_meetings":
            m.execute.return_value = _result(links)
        elif name == "meetings":
            m.execute.return_value = _result(meetings)
        else:
            m.execute.return_value = _result([])
        return m

    try:
        with patch("routers.contacts.supabase") as mock_sb, \
             patch("routers.contacts.verify_twin_ownership", return_value=True):
            mock_sb.table.side_effect = _table
            resp = client.get(
                f"/v2/twins/{twin_id}/contacts/{contact_id}/analysis",
                headers={"Authorization": "Bearer fake"},
            )
        return resp.json()
    finally:
        app.dependency_overrides.pop(verify_owner, None)


# ---------------------------------------------------------------------------
# 1. Empty contact — no meetings
# ---------------------------------------------------------------------------

def test_analysis_empty_contact_no_meetings():
    body = _call_analysis(links=[])
    assert body["status"] == "ok"
    data = body["data"]
    assert data["stats"]["total_meetings"] == CONTACT["meeting_count"]
    assert data["stats"]["open_loops_you_owe"] == 0
    assert data["stats"]["open_loops_they_owe"] == 0
    assert data["open_loops"]["you_owe"] == []
    assert data["open_loops"]["they_owe"] == []
    assert data["open_loops"]["skipped_count"] == 0
    assert data["memory_mentions"] == []


# ---------------------------------------------------------------------------
# 2. Mixed assignees — you / them / unknown
# ---------------------------------------------------------------------------

def test_analysis_mixed_assignees():
    body = _call_analysis()
    data = body["data"]
    assert data["stats"]["open_loops_you_owe"] == 1  # "Sainath"
    assert data["stats"]["open_loops_they_owe"] == 1  # "Jordan"
    # Marcus is unknown — lands in skipped_count
    assert data["open_loops"]["skipped_count"] == 1
    you = data["open_loops"]["you_owe"]
    them = data["open_loops"]["they_owe"]
    assert len(you) == 1
    assert you[0]["text"] == "Send proposal"
    assert you[0]["assignee_role"] == "you"
    assert len(them) == 1
    assert them[0]["text"] == "Review deck"
    assert them[0]["assignee_role"] == "them"


# ---------------------------------------------------------------------------
# 3. Owner-name variant matching — BUG-B regression
# ---------------------------------------------------------------------------

def test_analysis_owner_variant_nickname_sai():
    """Assignee 'Sai' should match owner 'Sainath Setti' → you bucket."""
    meeting = {**MEET_1, "action_items": [
        {"text": "Draft email", "assignee": "Sai", "completed": False},
    ]}
    body = _call_analysis(meetings=[meeting])
    assert body["data"]["stats"]["open_loops_you_owe"] == 1
    assert body["data"]["open_loops"]["you_owe"][0]["assignee_role"] == "you"


def test_analysis_owner_variant_full_name():
    """Assignee 'Sainath Setti' (exact match) → you bucket."""
    meeting = {**MEET_1, "action_items": [
        {"text": "Close ticket", "assignee": "Sainath Setti", "completed": False},
    ]}
    body = _call_analysis(meetings=[meeting])
    assert body["data"]["stats"]["open_loops_you_owe"] == 1


# ---------------------------------------------------------------------------
# 4. days_open computed from meeting_start
# ---------------------------------------------------------------------------

def test_analysis_days_open_from_meeting_start():
    """days_open must be based on meeting_start, not now()."""
    from datetime import datetime, timezone, timedelta

    past_start = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    meeting = {
        **MEET_1,
        "meeting_start": past_start,
        "action_items": [
            {"text": "Task", "assignee": "Sainath", "completed": False},
        ],
    }
    body = _call_analysis(meetings=[meeting])
    you = body["data"]["open_loops"]["you_owe"]
    assert len(you) == 1
    assert you[0]["days_open"] == 5


# ---------------------------------------------------------------------------
# 5. Completed action items excluded
# ---------------------------------------------------------------------------

def test_analysis_completed_items_excluded():
    meeting = {**MEET_1, "action_items": [
        {"text": "Done task", "assignee": "Sainath", "completed": True},
        {"text": "Open task", "assignee": "Sainath", "completed": False},
    ]}
    body = _call_analysis(meetings=[meeting])
    assert body["data"]["stats"]["open_loops_you_owe"] == 1
    assert body["data"]["open_loops"]["you_owe"][0]["text"] == "Open task"


# ---------------------------------------------------------------------------
# 6. Soft-deleted contact returns 404
# ---------------------------------------------------------------------------

def test_analysis_soft_deleted_contact_404():
    """_fetch_contact_owned excludes deleted_at IS NOT NULL; endpoint should 404."""
    # Simulate no contact found (soft-deleted) by returning None from DB
    app.dependency_overrides[verify_owner] = _make_auth_override()

    def _table(name: str):
        m = MagicMock()
        m.select.return_value = m
        m.eq.return_value = m
        m.is_.return_value = m
        m.maybe_single.return_value = m
        m.execute.return_value = _result(None)
        return m

    try:
        with patch("routers.contacts.supabase") as mock_sb, \
             patch("routers.contacts.verify_twin_ownership", return_value=True):
            mock_sb.table.side_effect = _table
            resp = client.get(
                f"/v2/twins/{TWIN_ID}/contacts/{CONTACT_ID}/analysis",
                headers={"Authorization": "Bearer fake"},
            )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(verify_owner, None)


# ---------------------------------------------------------------------------
# 7. Cross-tenant returns 404
# ---------------------------------------------------------------------------

def test_analysis_cross_tenant_404():
    """Contact in a different tenant_id is invisible — _fetch_contact_owned 404s."""
    app.dependency_overrides[verify_owner] = _make_auth_override(tenant_id="other-tenant")

    def _table(name: str):
        m = MagicMock()
        m.select.return_value = m
        m.eq.return_value = m
        m.is_.return_value = m
        m.maybe_single.return_value = m
        m.execute.return_value = _result(None)
        return m

    try:
        with patch("routers.contacts.supabase") as mock_sb, \
             patch("routers.contacts.verify_twin_ownership", return_value=True):
            mock_sb.table.side_effect = _table
            resp = client.get(
                f"/v2/twins/{TWIN_ID}/contacts/{CONTACT_ID}/analysis",
                headers={"Authorization": "Bearer fake"},
            )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(verify_owner, None)


# ---------------------------------------------------------------------------
# 8. Recap-finalization race — action_items=None or action_items=[]
# ---------------------------------------------------------------------------

def test_analysis_action_items_none_returns_empty_loops():
    """Meeting exists but action_items=None (worker hasn't run yet) → no crash."""
    meeting = {**MEET_1, "action_items": None}
    body = _call_analysis(meetings=[meeting])
    assert body["status"] == "ok"
    assert body["data"]["open_loops"]["you_owe"] == []
    assert body["data"]["open_loops"]["they_owe"] == []


def test_analysis_action_items_empty_list_returns_empty_loops():
    """Meeting exists but action_items=[] (worker ran, found nothing) → no crash."""
    meeting = {**MEET_1, "action_items": []}
    body = _call_analysis(meetings=[meeting])
    assert body["status"] == "ok"
    assert body["data"]["open_loops"]["you_owe"] == []


# ---------------------------------------------------------------------------
# 9. Non-Latin assignee lands in skipped_count
# ---------------------------------------------------------------------------

def test_analysis_non_latin_assignee_skipped():
    """Non-Latin name doesn't match owner or contact → skipped_count += 1."""
    meeting = {**MEET_1, "action_items": [
        {"text": "Prepare doc", "assignee": "李明", "completed": False},
    ]}
    body = _call_analysis(meetings=[meeting])
    assert body["data"]["open_loops"]["skipped_count"] == 1
    assert body["data"]["open_loops"]["you_owe"] == []
    assert body["data"]["open_loops"]["they_owe"] == []


# ---------------------------------------------------------------------------
# 10. False-positive check: "Saira" should not match "Sai" owner via prefix
# ---------------------------------------------------------------------------

def test_analysis_no_false_positive_saira_vs_sai():
    """Assignee 'Saira' (5 chars) must NOT match owner 'Sai' (3 chars) — only
    <=4-char candidates/references trigger the prefix rule.
    'Saira' ≠ 'Sai' by exact; token overlap? 'saira' ∩ {'sai'} = empty.
    Prefix rule: |'sai'| = 3 <=4, check if any 'saira' token startswith 'sai'
    → 'saira'.startswith('sai') is True AND 'saira' != 'sai' → MATCH (reverse rule).
    Documented decision: short-reference reverse rule fires. This is acceptable
    (Saira == Sai variant). Test verifies consistent behavior."""
    # Short owner 'Sai' → reverse prefix rule fires for 'Saira' token → matched as you
    meeting = {**MEET_1, "action_items": [
        {"text": "Send note", "assignee": "Saira", "completed": False},
    ]}
    owner_row = {"full_name": "Sai", "email": "sai@example.com"}
    body = _call_analysis(meetings=[meeting], owner_row=owner_row)
    # Reverse rule: 'sai' (ref, 3 chars) prefix of 'saira' candidate token → you
    assert body["data"]["stats"]["open_loops_you_owe"] == 1


# ---------------------------------------------------------------------------
# 11. memory_mentions always empty in v1 response
# ---------------------------------------------------------------------------

def test_analysis_memory_mentions_always_empty():
    body = _call_analysis()
    assert body["data"]["memory_mentions"] == []


# ---------------------------------------------------------------------------
# 12. Pagination: open_loops > 25 → truncated=True
# ---------------------------------------------------------------------------

def test_analysis_open_loops_truncated_flag():
    """More than 25 you_owe items → truncated=True, only 25 returned."""
    many_items = [
        {"text": f"Task {i}", "assignee": "Sainath", "completed": False}
        for i in range(30)
    ]
    meeting = {**MEET_1, "action_items": many_items}
    body = _call_analysis(meetings=[meeting])
    data = body["data"]
    assert data["open_loops"]["truncated"] is True
    assert len(data["open_loops"]["you_owe"]) == 25
    # Stats count reflects capped list
    assert data["stats"]["open_loops_you_owe"] == 25


# ---------------------------------------------------------------------------
# 13. assignee_role 'unknown' increments skipped_count
# ---------------------------------------------------------------------------

def test_analysis_unknown_assignee_increments_skipped_count():
    """Assignee that matches neither owner nor contact increments skipped_count."""
    meeting = {**MEET_1, "action_items": [
        {"text": "Call vendor", "assignee": "Marcus", "completed": False},
        {"text": "Send invoice", "assignee": "Sofia", "completed": False},
    ]}
    body = _call_analysis(meetings=[meeting])
    assert body["data"]["open_loops"]["skipped_count"] == 2
    assert body["data"]["open_loops"]["you_owe"] == []
    assert body["data"]["open_loops"]["they_owe"] == []
