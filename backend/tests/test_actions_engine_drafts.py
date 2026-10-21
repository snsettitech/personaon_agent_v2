"""Unit tests for ActionDraftManager.create_draft chat-path changes (Phase B1)."""
from __future__ import annotations

from unittest.mock import patch

from tests._supabase_mock import fluent

from modules.actions_engine import ActionDraftManager


def _draft_insert_payload(mock) -> dict | None:
    """Return the action_drafts insert payload (the dict with status=pending)."""
    for call in mock.insert.call_args_list:
        if not call.args:
            continue
        arg = call.args[0]
        if isinstance(arg, dict) and arg.get("status") == "pending":
            return arg
    return None


def test_create_draft_from_chat_omits_trigger_and_event() -> None:
    """The chat 'Respond' tool creates a draft without a trigger/event."""
    mock = fluent({"tenant_id": "tenant-1", "id": "twin-1"})
    with patch("modules.actions_engine.supabase", mock), \
            patch("modules.actions_engine.AuditLogger.log"):
        draft_id = ActionDraftManager.create_draft(
            twin_id="twin-1",
            proposed_action={"action_type": "draft_email", "params": {"to": "a@b.com"}},
            context={"source": "chat"},
        )

    assert draft_id is not None
    payload = _draft_insert_payload(mock)
    assert payload is not None, "create_draft must insert into action_drafts"
    assert payload["trigger_id"] is None
    assert payload["event_id"] is None


def test_create_draft_stamps_tenant_from_twin() -> None:
    """Drafts are owner-scoped: tenant_id resolved from the twin."""
    mock = fluent({"tenant_id": "tenant-9", "id": "twin-1"})
    with patch("modules.actions_engine.supabase", mock), \
            patch("modules.actions_engine.AuditLogger.log"):
        ActionDraftManager.create_draft(
            twin_id="twin-1",
            proposed_action={"action_type": "draft_email"},
            context={"source": "chat"},
        )

    payload = _draft_insert_payload(mock)
    assert payload is not None
    assert payload["tenant_id"] == "tenant-9"
    assert payload["twin_id"] == "twin-1"


def test_create_draft_preserves_source_tag() -> None:
    """context['source'] is preserved (chat vs automation provenance)."""
    mock = fluent({"tenant_id": "tenant-1", "id": "twin-1"})
    with patch("modules.actions_engine.supabase", mock), \
            patch("modules.actions_engine.AuditLogger.log"):
        ActionDraftManager.create_draft(
            twin_id="twin-1",
            proposed_action={"action_type": "draft_email"},
            context={"source": "chat", "thread": "t1"},
        )

    payload = _draft_insert_payload(mock)
    assert payload is not None
    assert payload["context"]["source"] == "chat"
    assert payload["context"]["thread"] == "t1"


def test_create_draft_defaults_source_to_automation() -> None:
    """A draft created without an explicit source defaults to automation."""
    mock = fluent({"tenant_id": "tenant-1", "id": "twin-1"})
    with patch("modules.actions_engine.supabase", mock), \
            patch("modules.actions_engine.AuditLogger.log"):
        ActionDraftManager.create_draft(
            twin_id="twin-1",
            proposed_action={"action_type": "draft_email"},
            context={},
            trigger_id="trig-1",
            event_id="evt-1",
        )

    payload = _draft_insert_payload(mock)
    assert payload is not None
    assert payload["context"]["source"] == "automation"
    assert payload["trigger_id"] == "trig-1"
    assert payload["event_id"] == "evt-1"
