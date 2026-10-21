"""Phase 2 — persona chat grounded in per-person meeting memory.

Asserts on the INJECTED CONTEXT (not LLM output): given a contact with a
meeting that has an open action item the owner owes, asking "what do I owe
<contact>?" produces a people-context block that (a) contains the open loop,
and (b) is woven into the assembled per-request system instruction.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from tests._supabase_mock import result as _result

from services.person_context import resolve_people_context_block
from adk_core.services.agent_service import _build_per_request_instruction

TWIN_ID = "twin-1"
TENANT_ID = "tenant-1"

CONTACT = {
    "id": "c-1",
    "name": "Jordan Reyes",
    "email": "jordan@example.com",
    "meeting_count": 2,
    "last_seen_at": "2026-05-16T10:00:00Z",
    "allow_mention": True,
}

OWNER_ROW = {"full_name": "Sainath Setti", "email": "sainath@example.com"}

MEETING = {
    "id": "m-1",
    "title": "Q3 review",
    "meeting_start": "2026-05-01T10:00:00Z",
    "meeting_end": None,
    "status": "completed",
    "action_items": [
        {"text": "Send the revised proposal", "assignee": "Sainath", "completed": False},
        {"text": "Share the deck", "assignee": "Jordan", "completed": False},
    ],
}


def _supabase_mock(*, contacts, meetings, links, memory=None):
    """Build a supabase mock whose .table(name) returns name-specific data."""
    memory = memory if memory is not None else []

    def _table(name: str):
        m = MagicMock()
        for attr in ("select", "eq", "neq", "in_", "is_", "order", "limit", "maybe_single"):
            getattr(m, attr).return_value = m
        if name == "contacts":
            m.execute.return_value = _result(contacts)
        elif name == "users":
            m.execute.return_value = _result([OWNER_ROW])
        elif name == "contact_meetings":
            m.execute.return_value = _result(links)
        elif name == "meetings":
            m.execute.return_value = _result(meetings)
        elif name == "memory_candidates":
            m.execute.return_value = _result(memory)
        else:
            m.execute.return_value = _result([])
        return m

    sb = MagicMock()
    sb.table.side_effect = _table
    return sb


def test_people_block_includes_open_loop_you_owe():
    sb = _supabase_mock(
        contacts=[CONTACT],
        meetings=[MEETING],
        links=[{"meeting_id": "m-1"}],
    )
    block = resolve_people_context_block(
        sb,
        twin_id=TWIN_ID,
        tenant_id=TENANT_ID,
        message="what do I owe Jordan?",
    )
    assert block, "expected a non-empty people-context block"
    assert "Jordan Reyes" in block
    assert "You owe" in block
    assert "Send the revised proposal" in block


def test_people_block_woven_into_system_instruction():
    sb = _supabase_mock(
        contacts=[CONTACT],
        meetings=[MEETING],
        links=[{"meeting_id": "m-1"}],
    )
    block = resolve_people_context_block(
        sb,
        twin_id=TWIN_ID,
        tenant_id=TENANT_ID,
        message="what do I owe Jordan?",
    )
    instruction = _build_per_request_instruction(
        {"name": "Persona"},
        surface_class="owner",
        actions=None,
        kb_block="",
        mode_override=None,
        people_block=block,
    )
    assert "PERSON CONTEXT" in instruction
    assert "Send the revised proposal" in instruction


def test_no_block_when_contact_not_referenced():
    sb = _supabase_mock(
        contacts=[CONTACT],
        meetings=[MEETING],
        links=[{"meeting_id": "m-1"}],
    )
    block = resolve_people_context_block(
        sb,
        twin_id=TWIN_ID,
        tenant_id=TENANT_ID,
        message="what is the weather today?",
    )
    assert block == ""


def test_no_block_when_mention_not_allowed():
    blocked = {**CONTACT, "allow_mention": False}
    # contacts query already filters allow_mention=True at the DB layer, so a
    # blocked contact simply isn't returned — model that here.
    sb = _supabase_mock(
        contacts=[],
        meetings=[MEETING],
        links=[{"meeting_id": "m-1"}],
    )
    block = resolve_people_context_block(
        sb,
        twin_id=TWIN_ID,
        tenant_id=TENANT_ID,
        message="what do I owe Jordan?",
    )
    assert block == ""
    assert blocked["allow_mention"] is False  # documents intent
