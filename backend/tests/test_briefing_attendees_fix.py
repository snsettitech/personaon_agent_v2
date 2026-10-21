"""W9a Task 8 — Regression tests for the cron briefing attendees_json fix.

Bug: notification_service.generate_briefing() read meeting.get("attendees")
which always returned None on real rows, so briefing emails shipped with
empty attendee context. Canonical column is attendees_json (list of dicts).
"""

from __future__ import annotations

from services.notification_service import _extract_attendee_display_names


def test_extracts_display_names_from_dicts():
    attendees = [
        {"email": "sarah@acme.com", "displayName": "Sarah Chen"},
        {"email": "tom@beta.com", "name": "Tom Lee"},
    ]
    assert _extract_attendee_display_names(attendees) == ["Sarah Chen", "Tom Lee"]


def test_falls_back_to_email_when_no_name():
    attendees = [{"email": "alice@x.com"}]
    assert _extract_attendee_display_names(attendees) == ["alice@x.com"]


def test_handles_plain_string_attendees():
    """Legacy rows can contain plain strings in attendees_json."""
    attendees = ["alice@x.com", "Bob Stevens"]
    assert _extract_attendee_display_names(attendees) == ["alice@x.com", "Bob Stevens"]


def test_skips_empty_entries():
    attendees = [
        {"email": "", "displayName": ""},
        {"email": "real@x.com", "displayName": "Real Person"},
        "",
    ]
    assert _extract_attendee_display_names(attendees) == ["Real Person"]


def test_safe_on_none_or_non_list():
    assert _extract_attendee_display_names(None) == []
    assert _extract_attendee_display_names("not a list") == []
    assert _extract_attendee_display_names({"not": "a list"}) == []


def test_safe_on_garbage_entries():
    attendees = [None, 42, {"email": "good@x.com", "displayName": "Good"}]
    assert _extract_attendee_display_names(attendees) == ["Good"]


# ---------------------------------------------------------------------------
# Task 9 — render brief_json into email context
# ---------------------------------------------------------------------------


def test_render_brief_json_includes_talking_points():
    from services.notification_service import _render_brief_json_as_email_context

    brief = {
        "talking_points": [{"topic": "Pricing memo", "rationale": "Bring"}],
    }
    text = _render_brief_json_as_email_context(brief)
    assert "Pricing memo" in text
    assert "Bring" in text


def test_render_brief_json_includes_agenda_numbered():
    from services.notification_service import _render_brief_json_as_email_context

    brief = {
        "suggested_agenda": ["First topic", "Second topic"],
    }
    text = _render_brief_json_as_email_context(brief)
    assert "1. First topic" in text
    assert "2. Second topic" in text


def test_render_brief_json_includes_open_commitments():
    from services.notification_service import _render_brief_json_as_email_context

    brief = {
        "open_commitments": [{"description": "Send Q2 doc", "days_open": 13}],
    }
    text = _render_brief_json_as_email_context(brief)
    assert "Send Q2 doc" in text
    assert "13 days open" in text


def test_render_brief_json_omits_empty_sections():
    """When a section is empty, it shouldn't render as 'Section: '."""
    from services.notification_service import _render_brief_json_as_email_context

    brief = {
        "talking_points": [{"topic": "Real topic", "rationale": "Bring"}],
        "suggested_agenda": [],
        "open_commitments": [],
        "previous_interactions": [],
    }
    text = _render_brief_json_as_email_context(brief)
    assert "Real topic" in text
    assert "Suggested agenda" not in text
    assert "Still open" not in text
    assert "From your last meeting" not in text


def test_render_brief_json_empty_returns_empty_string():
    from services.notification_service import _render_brief_json_as_email_context

    assert _render_brief_json_as_email_context({}) == ""
    assert _render_brief_json_as_email_context({
        "talking_points": [],
        "suggested_agenda": [],
        "open_commitments": [],
        "previous_interactions": [],
    }) == ""
