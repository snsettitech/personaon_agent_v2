"""Phase 2 — memory_mentions in the contact analysis endpoint.

Seeds an APPROVED memory_candidate that mentions a contact (by name) and
asserts it surfaces in the analysis `memory_mentions` array, in the
frontend Candidate shape (id/text/predicate/...).

Mirrors the chained-MagicMock pattern in test_contact_analysis.py.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from tests._supabase_mock import result as _result

from main import app
from modules.auth_guard import verify_owner

TWIN_ID = "twin-1"
TENANT_ID = "tenant-1"
CONTACT_ID = "c-1"

CONTACT = {
    "id": CONTACT_ID,
    "name": "Jordan Reyes",
    "email": "jordan@example.com",
    "linkedin_url": None,
    "avatar_url": None,
    "meeting_count": 1,
    "last_seen_at": "2026-05-16T10:00:00Z",
    "first_seen_at": "2026-04-01T10:00:00Z",
    "allow_mention": True,
    "tags": [],
    "notes": None,
    "metadata": None,
    "twin_id": TWIN_ID,
    "tenant_id": TENANT_ID,
}

OWNER_ROW = {"full_name": "Sainath Setti", "email": "sainath@example.com"}

# An approved fact that mentions the contact by name in its text.
MENTION_BY_NAME = {
    "id": "mc-1",
    "meeting_id": "m-1",
    "contact_id": None,
    "kind": "fact",
    "subject": "Jordan Reyes",
    "predicate": "prefers async updates",
    "text": "Jordan Reyes prefers async updates over standup calls.",
    "confidence": 0.9,
    "status": "approved",
    "created_at": "2026-05-10T10:00:00Z",
}

# An unrelated approved fact that should NOT match.
UNRELATED = {
    "id": "mc-2",
    "meeting_id": "m-2",
    "contact_id": None,
    "kind": "fact",
    "subject": "Acme Corp",
    "predicate": "renews in Q4",
    "text": "Acme Corp contract renews in Q4.",
    "confidence": 0.8,
    "status": "approved",
    "created_at": "2026-05-11T10:00:00Z",
}


def _make_auth_override(tenant_id: str = TENANT_ID, user_id: str = "u-1"):
    def override():
        return {"user_id": user_id, "tenant_id": tenant_id}
    return override


client = TestClient(app)


def _call_analysis(*, memory_rows: list | None = None) -> dict:
    memory_rows = memory_rows if memory_rows is not None else [MENTION_BY_NAME, UNRELATED]

    app.dependency_overrides[verify_owner] = _make_auth_override()

    def _table(name: str):
        m = MagicMock()
        for attr in ("select", "eq", "neq", "in_", "is_", "order", "limit", "maybe_single"):
            getattr(m, attr).return_value = m
        if name == "contacts":
            m.execute.return_value = _result(CONTACT)
        elif name == "users":
            m.execute.return_value = _result([OWNER_ROW])
        elif name == "contact_meetings":
            m.execute.return_value = _result([])  # no linked meetings needed
        elif name == "memory_candidates":
            m.execute.return_value = _result(memory_rows)
        else:
            m.execute.return_value = _result([])
        return m

    try:
        with patch("routers.contacts.supabase") as mock_sb, \
             patch("routers.contacts.verify_twin_ownership", return_value=True):
            mock_sb.table.side_effect = _table
            resp = client.get(
                f"/v2/twins/{TWIN_ID}/contacts/{CONTACT_ID}/analysis",
                headers={"Authorization": "Bearer fake"},
            )
        return resp.json()
    finally:
        app.dependency_overrides.pop(verify_owner, None)


def test_memory_mentions_populated_by_name():
    body = _call_analysis()
    assert body["status"] == "ok"
    mentions = body["data"]["memory_mentions"]
    ids = [m["id"] for m in mentions]
    assert "mc-1" in ids, "approved fact mentioning the contact by name should surface"
    assert "mc-2" not in ids, "unrelated fact must not surface"
    fact = next(m for m in mentions if m["id"] == "mc-1")
    # Shape the frontend Memory section renders: .text + .predicate
    assert fact["text"] == MENTION_BY_NAME["text"]
    assert fact["predicate"] == MENTION_BY_NAME["predicate"]


def test_memory_mentions_empty_when_none_match():
    body = _call_analysis(memory_rows=[UNRELATED])
    assert body["data"]["memory_mentions"] == []
