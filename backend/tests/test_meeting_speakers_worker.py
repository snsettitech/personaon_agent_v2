"""Tests for the speaker resolution worker (P1.3.A).

Verifies _process_resolve_meeting_speakers correctly:
- Resolves participants with known emails to existing nodes
- Creates stub nodes when email has no match
- Handles empty participant lists gracefully (acknowledged, not retried)
- Returns False on missing required payload fields
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _Chain:
    """Tiny chainable mock that records the last operation per table call.

    Mirrors how Supabase's PostgREST builder is used in the worker: every
    builder method (.select, .insert, .eq, .ilike, .limit, .update) returns
    the builder itself, and .execute() returns a final result.
    """

    def __init__(self, table_name: str, insert_sink: list[dict] | None = None,
                 select_results: dict[str, list[dict]] | None = None) -> None:
        self.table_name = table_name
        self._last_op: str | None = None
        self._last_payload: dict | None = None
        self._insert_sink = insert_sink if insert_sink is not None else []
        self._select_results = select_results or {}

    def select(self, *_a, **_k):
        self._last_op = "select"
        return self

    def insert(self, payload, *_a, **_k):
        self._last_op = "insert"
        self._last_payload = payload
        self._insert_sink.append({"table": self.table_name, "payload": payload})
        return self

    def update(self, payload, *_a, **_k):
        self._last_op = "update"
        self._last_payload = payload
        return self

    def eq(self, *_a, **_k):
        return self

    def ilike(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        if self._last_op == "insert":
            if self.table_name == "nodes":
                return MagicMock(data=[{"id": "node-stub-new"}])
            if self.table_name == "meeting_participants":
                return MagicMock(data=[{"id": "mp-new"}])
            return MagicMock(data=[])
        if self._last_op == "update":
            return MagicMock(data=[{"id": "mp-updated"}])
        # select: return per-table seeded results
        return MagicMock(data=self._select_results.get(self.table_name, []))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolves_known_email_to_existing_node():
    """When participant email matches a nodes row, link to that node (no stub)."""
    from modules.graph_outbox_worker import _process_resolve_meeting_speakers

    bot_payload = {
        "id": "bot-x",
        "participants": [
            # Mixed-case email — worker must lowercase before lookup
            {"id": "p1", "name": "Alex Chen", "email": "ALEX@example.com"},
        ],
    }

    inserts: list[dict] = []
    # nodes select returns an existing node; meeting_participants select empty
    select_results = {"nodes": [{"id": "node-alex"}], "meeting_participants": []}

    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: _Chain(
        name, insert_sink=inserts, select_results=select_results,
    )

    with (
        patch("modules.graph_outbox_worker.supabase", mock_sb),
        patch("services.recall_service.get_bot",
              new_callable=AsyncMock, return_value=bot_payload),
    ):
        result = await _process_resolve_meeting_speakers({
            "id": "j1",
            "payload": {
                "meeting_id": "m1",
                "bot_id": "bot-x",
                "twin_id": "t1",
                "tenant_id": "tn1",
            },
        })

    assert result is True
    # No stub node should have been created — we matched an existing one
    node_inserts = [i for i in inserts if i["table"] == "nodes"]
    assert not node_inserts, f"expected no stub nodes, got {node_inserts}"
    # A meeting_participants row should have been inserted
    mp_inserts = [i for i in inserts if i["table"] == "meeting_participants"]
    assert mp_inserts, "expected meeting_participants insert"
    mp_payload = mp_inserts[0]["payload"]
    assert mp_payload["meeting_id"] == "m1"
    assert mp_payload["participant_email"] == "alex@example.com"  # lowercased
    assert mp_payload["person_node_id"] == "node-alex"
    assert mp_payload["diarization_label"] == "speaker_0"


@pytest.mark.asyncio
async def test_creates_stub_node_for_unknown_email():
    """When participant email has no matching node, create stub with source='meeting_attendees'."""
    from modules.graph_outbox_worker import _process_resolve_meeting_speakers

    bot_payload = {
        "id": "bot-x",
        "participants": [
            {"id": "p1", "name": "Mystery Person", "email": "mystery@new.com"},
        ],
    }

    inserts: list[dict] = []
    # nodes select returns empty (no match); meeting_participants select empty
    select_results = {"nodes": [], "meeting_participants": []}

    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: _Chain(
        name, insert_sink=inserts, select_results=select_results,
    )

    with (
        patch("modules.graph_outbox_worker.supabase", mock_sb),
        patch("services.recall_service.get_bot",
              new_callable=AsyncMock, return_value=bot_payload),
    ):
        result = await _process_resolve_meeting_speakers({
            "id": "j1",
            "payload": {
                "meeting_id": "m1",
                "bot_id": "bot-x",
                "twin_id": "t1",
                "tenant_id": "tn1",
            },
        })

    assert result is True
    # Verify a stub node was created with the expected shape
    node_inserts = [i for i in inserts if i["table"] == "nodes"]
    assert node_inserts, f"expected stub node insert, got {inserts}"
    stub = node_inserts[0]["payload"]
    assert stub["twin_id"] == "t1"
    assert stub["type"] == "person"
    assert stub["properties"]["email"] == "mystery@new.com"
    assert stub["properties"]["source"] == "meeting_attendees"
    # And a meeting_participants row pointing at the new stub
    mp_inserts = [i for i in inserts if i["table"] == "meeting_participants"]
    assert mp_inserts, "expected meeting_participants insert"
    assert mp_inserts[0]["payload"]["person_node_id"] == "node-stub-new"


@pytest.mark.asyncio
async def test_handles_empty_participants_gracefully():
    """Empty participants list → ack (True) with no DB writes."""
    from modules.graph_outbox_worker import _process_resolve_meeting_speakers

    bot_payload = {"id": "bot-x", "participants": []}

    inserts: list[dict] = []
    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: _Chain(name, insert_sink=inserts)

    with (
        patch("modules.graph_outbox_worker.supabase", mock_sb),
        patch("services.recall_service.get_bot",
              new_callable=AsyncMock, return_value=bot_payload),
    ):
        result = await _process_resolve_meeting_speakers({
            "id": "j1",
            "payload": {
                "meeting_id": "m1",
                "bot_id": "bot-x",
                "twin_id": "t1",
                "tenant_id": "tn1",
            },
        })

    assert result is True
    assert inserts == []  # nothing to write


@pytest.mark.asyncio
async def test_missing_required_fields_returns_false():
    """If meeting_id/bot_id/twin_id/tenant_id missing, return False (logs error)."""
    from modules.graph_outbox_worker import _process_resolve_meeting_speakers

    # Missing bot_id, twin_id, tenant_id
    result = await _process_resolve_meeting_speakers({
        "id": "j1",
        "payload": {"meeting_id": "m1"},
    })

    assert result is False


@pytest.mark.asyncio
async def test_recall_api_failure_returns_false():
    """If get_bot raises, the worker should return False so the job retries."""
    from modules.graph_outbox_worker import _process_resolve_meeting_speakers

    with patch(
        "services.recall_service.get_bot",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Recall 503"),
    ):
        result = await _process_resolve_meeting_speakers({
            "id": "j1",
            "payload": {
                "meeting_id": "m1",
                "bot_id": "bot-x",
                "twin_id": "t1",
                "tenant_id": "tn1",
            },
        })

    assert result is False
