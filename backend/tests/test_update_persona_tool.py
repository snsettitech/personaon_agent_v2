"""Tests for the update_persona agent tool (Home v1 — chief-of-staff edits the page).

The tool merges one allowlisted public-profile text field via the atomic
`update_persona_field` RPC (service key). Allowlist + length caps + HTML stripping
guard against editing structural fields, oversized input, or stored XSS.
"""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest

from adk_core.tools.persona_edit_tools import _make_update_persona_tool


def _mock_sb() -> MagicMock:
    """Chainable Supabase mock: rpc(...).execute() -> ok. Captures rpc.call_args."""
    sb = MagicMock()
    sb.rpc.return_value = sb
    sb.execute.return_value = MagicMock(data=None)
    return sb


@pytest.mark.asyncio
async def test_update_persona_calls_rpc_with_trimmed_value() -> None:
    sb = _mock_sb()
    tool = _make_update_persona_tool("twin-1")
    bio = "A much sharper, more specific bio describing my actual work in AI infrastructure."
    with patch("adk_core.tools.persona_edit_tools.get_supabase_client", return_value=sb):
        result = await tool.func(field="Bio", value=f"  {bio}  ")

    assert result["status"] == "updated"
    assert result["field"] == "bio"  # field is normalized (case/space)
    fn, params = sb.rpc.call_args.args
    assert fn == "update_persona_field"
    assert params == {"p_twin_id": "twin-1", "p_field": "bio", "p_value": bio}


@pytest.mark.asyncio
async def test_update_persona_strips_html_before_save() -> None:
    sb = _mock_sb()
    tool = _make_update_persona_tool("twin-1")
    with patch("adk_core.tools.persona_edit_tools.get_supabase_client", return_value=sb):
        result = await tool.func(
            field="headline", value="<script>alert(1)</script>Founder <b>at</b> Acme"
        )

    assert result["status"] == "updated"
    assert sb.rpc.call_args.args[1]["p_value"] == "alert(1)Founder at Acme"


@pytest.mark.asyncio
async def test_update_persona_rejects_html_only_as_empty() -> None:
    sb = _mock_sb()
    tool = _make_update_persona_tool("twin-1")
    with patch("adk_core.tools.persona_edit_tools.get_supabase_client", return_value=sb):
        result = await tool.func(field="bio", value="<br><hr/>")
    assert result["status"] == "rejected"
    sb.rpc.assert_not_called()


@pytest.mark.asyncio
async def test_update_persona_rejects_non_allowlisted_field() -> None:
    tool = _make_update_persona_tool("twin-1")
    with patch("adk_core.tools.persona_edit_tools.get_supabase_client") as get_sb:
        for bad in ("status", "handle", "theme_id", "tenant_id", "settings", "public_profile"):
            result = await tool.func(field=bad, value="malicious")
            assert result["status"] == "rejected", bad
        get_sb.assert_not_called()  # never even opened a DB connection


@pytest.mark.asyncio
async def test_update_persona_rejects_empty_and_too_long() -> None:
    tool = _make_update_persona_tool("twin-1")
    with patch("adk_core.tools.persona_edit_tools.get_supabase_client") as get_sb:
        empty = await tool.func(field="bio", value="   ")
        toolong = await tool.func(field="headline", value="x" * 241)
        assert empty["status"] == "rejected"
        assert toolong["status"] == "rejected"
        get_sb.assert_not_called()


@pytest.mark.asyncio
async def test_update_persona_rejects_thin_bio() -> None:
    """Phase 0 review follow-up: this tool used to only check length/HTML, so
    a chat-driven edit could quietly reintroduce "nill"-style thin bio content
    that every other write path (onboarding, profile PATCH, the publish gate
    itself) already blocks via modules.text_quality. Same bar applies here now."""
    tool = _make_update_persona_tool("twin-1")
    with patch("adk_core.tools.persona_edit_tools.get_supabase_client") as get_sb:
        result = await tool.func(field="bio", value="nill")
    assert result["status"] == "rejected"
    get_sb.assert_not_called()


@pytest.mark.asyncio
async def test_update_persona_allows_short_legitimate_headline() -> None:
    """Headlines get a much lower bar than bio (real titles are often one
    word — "CEO", "Founder") — the meaningfulness gate must not over-reject."""
    sb = _mock_sb()
    tool = _make_update_persona_tool("twin-1")
    with patch("adk_core.tools.persona_edit_tools.get_supabase_client", return_value=sb):
        result = await tool.func(field="headline", value="CEO")
    assert result["status"] == "updated"
    assert sb.rpc.call_args.args[1]["p_value"] == "CEO"


def test_update_persona_registered_for_assistant_in_both_sites() -> None:
    """Must be appended in BOTH runner builders, gated to the assistant surface
    only (the persona-preview 'owner' chat must not edit the page)."""
    from adk_core.services import agent_service

    src = inspect.getsource(agent_service)
    assert src.count("_make_update_persona_tool(twin_id)") >= 2
    assert 'surface_class == "assistant"' in src
