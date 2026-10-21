"""Tests for the create_followup_draft agent tool (Phase B4).

Imports the ADK tool layer (google-adk) and agent_service; runs in CI.
"""
from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_create_followup_draft_writes_pending_draft() -> None:
    from adk_core.tools.respond_tools import _make_followup_draft_tool

    tool = _make_followup_draft_tool("twin-1")
    with patch(
        "modules.actions_engine.ActionDraftManager.create_draft",
        return_value="draft-1",
    ) as cd:
        result = await tool.func(
            recipient="lead@example.com", subject="Hi", body="Hello there"
        )

    assert result["status"] == "drafted"
    assert result["draft_id"] == "draft-1"
    cd.assert_called_once()
    kwargs = cd.call_args.kwargs
    assert kwargs["twin_id"] == "twin-1"  # bound via closure, not a tool arg
    assert kwargs["proposed_action"]["action_type"] == "draft_email"
    assert kwargs["proposed_action"]["params"]["to"] == "lead@example.com"
    assert kwargs["proposed_action"]["params"]["subject"] == "Hi"
    assert kwargs["context"]["source"] == "chat"


@pytest.mark.asyncio
async def test_create_followup_draft_rejects_invalid_recipient() -> None:
    from adk_core.tools.respond_tools import _make_followup_draft_tool

    tool = _make_followup_draft_tool("twin-1")
    with patch("modules.actions_engine.ActionDraftManager.create_draft") as cd:
        result = await tool.func(recipient="not-an-email", subject="Hi", body="Hello")

    assert result["status"] == "invalid_recipient"
    cd.assert_not_called()  # never persists a relay address smuggled via injection


@pytest.mark.asyncio
async def test_create_followup_draft_rejects_empty_body() -> None:
    from adk_core.tools.respond_tools import _make_followup_draft_tool

    tool = _make_followup_draft_tool("twin-1")
    with patch("modules.actions_engine.ActionDraftManager.create_draft") as cd:
        result = await tool.func(recipient="lead@example.com", subject="Hi", body="   ")

    assert result["status"] == "empty"
    cd.assert_not_called()


def test_followup_tool_registered_in_both_owner_assembly_sites() -> None:
    """Regression guard: the tool must be appended in BOTH owner runner sites
    (cached runner + request runner). Registering in only one site silently
    disables the tool for half the chat paths."""
    from adk_core.services import agent_service

    src = inspect.getsource(agent_service)
    assert src.count("_make_followup_draft_tool(twin_id)") >= 2, (
        "create_followup_draft must be registered in both owner assembly sites"
    )
