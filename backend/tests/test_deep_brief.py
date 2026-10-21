"""W9d — Deep brief module unit tests.

Covers the pure helpers (subject extraction + participant names + markdown
fence stripping). Integration coverage of the ADK runner end-to-end lives
in test_deep_brief_worker.py with mocked Runner.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# _strip_markdown_fences
# ---------------------------------------------------------------------------

def test_strip_markdown_fences_plain_passthrough():
    from adk_core.services.persona_core.deep_brief import _strip_markdown_fences
    assert _strip_markdown_fences("plain text") == "plain text"


def test_strip_markdown_fences_json_fence():
    from adk_core.services.persona_core.deep_brief import _strip_markdown_fences
    text = '```json\n{"x": 1}\n```'
    assert _strip_markdown_fences(text) == '{"x": 1}'


def test_strip_markdown_fences_bare_fence():
    from adk_core.services.persona_core.deep_brief import _strip_markdown_fences
    text = '```\n{"x": 1}\n```'
    assert _strip_markdown_fences(text) == '{"x": 1}'


# ---------------------------------------------------------------------------
# _primary_subject
# ---------------------------------------------------------------------------

def test_primary_subject_picks_first_non_organizer():
    from adk_core.services.persona_core.deep_brief import _primary_subject
    meeting = {
        "organizer_email": "me@self.com",
        "attendees_json": [
            {"email": "me@self.com", "displayName": "Me"},
            {"email": "sarah@acme.com", "displayName": "Sarah Chen", "company": "Acme"},
        ],
    }
    subject = _primary_subject(meeting)
    assert subject["name"] == "Sarah Chen"
    assert subject["email"] == "sarah@acme.com"
    assert subject["company"] == "Acme"


def test_primary_subject_handles_string_attendees():
    """attendees_json sometimes contains plain strings (legacy rows)."""
    from adk_core.services.persona_core.deep_brief import _primary_subject
    meeting = {
        "organizer_email": "me@self.com",
        "attendees_json": ["Sarah Chen"],
    }
    subject = _primary_subject(meeting)
    assert subject["name"] == "Sarah Chen"
    assert subject["email"] == ""


def test_primary_subject_empty_when_no_attendees():
    from adk_core.services.persona_core.deep_brief import _primary_subject
    assert _primary_subject({"attendees_json": []})["name"] == ""
    assert _primary_subject({"attendees_json": None})["name"] == ""
    assert _primary_subject({})["name"] == ""


def test_primary_subject_skips_only_organizer_returns_empty():
    """When the only attendee IS the organizer, return empty (the deep
    research has no subject to look up)."""
    from adk_core.services.persona_core.deep_brief import _primary_subject
    meeting = {
        "organizer_email": "me@self.com",
        "attendees_json": [{"email": "me@self.com", "displayName": "Me"}],
    }
    assert _primary_subject(meeting)["name"] == ""


# ---------------------------------------------------------------------------
# _participant_names
# ---------------------------------------------------------------------------

def test_participant_names_excludes_organizer_caps_at_four():
    from adk_core.services.persona_core.deep_brief import _participant_names
    meeting = {
        "organizer_email": "me@self.com",
        "attendees_json": [
            {"email": "me@self.com", "displayName": "Me"},
            *[
                {"email": f"p{i}@x.com", "displayName": f"Person {i}"}
                for i in range(6)
            ],
        ],
    }
    names = _participant_names(meeting)
    assert "Me" not in names  # organizer dropped
    assert len(names) == 4  # cap


def test_participant_names_empty_input():
    from adk_core.services.persona_core.deep_brief import _participant_names
    assert _participant_names({}) == []
    assert _participant_names({"attendees_json": []}) == []
    assert _participant_names({"attendees_json": None}) == []


def test_participant_names_handles_strings():
    from adk_core.services.persona_core.deep_brief import _participant_names
    meeting = {
        "organizer_email": None,
        "attendees_json": ["Alice", "Bob"],
    }
    assert _participant_names(meeting) == ["Alice", "Bob"]


@pytest.mark.asyncio
async def test_run_deep_brief_parse_failure_redacts_agent_output(monkeypatch, caplog):
    from adk_core.services.persona_core import deep_brief

    private_output = "PRIVATE CUSTOMER DATA: renewal risk at BigCo"

    class _FakeSessionService:
        async def create_session(self, **kwargs):
            return None

    class _FakeRunner:
        def __init__(self, **kwargs):
            pass

        async def run_async(self, **kwargs):
            yield SimpleNamespace(
                content=SimpleNamespace(
                    parts=[SimpleNamespace(text=private_output)]
                )
            )

    monkeypatch.setattr(deep_brief, "build_brief_agent", lambda **kwargs: object())
    monkeypatch.setattr(deep_brief, "_get_session_service", lambda: _FakeSessionService())
    monkeypatch.setattr(deep_brief, "Runner", _FakeRunner)
    caplog.set_level(logging.WARNING, logger=deep_brief.logger.name)

    result = await deep_brief.run_deep_brief(
        twin_id="twin-1",
        tenant_id="tenant-1",
        meeting={
            "id": "meeting-1",
            "title": "Private Review",
            "attendees_json": [{"displayName": "Sarah Chen"}],
        },
    )

    assert result is None
    assert "PRIVATE CUSTOMER DATA" not in caplog.text
    assert "output_len=" in caplog.text
    assert "output_hash=" in caplog.text
