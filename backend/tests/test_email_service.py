"""
Phase 28: Proactive Notifications — email_service.py tests

Tests for Resend wrapper and HTML template builders.
All async tests use pytest-asyncio.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# test_send_email_calls_resend_via_thread
# Verifies the happy path: resend.Emails.send is invoked via asyncio.to_thread
# and the message ID is extracted from the result dict.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_send_email_calls_resend_via_thread():
    fake_result = {"id": "msg_abc123"}

    with patch("resend.Emails.send", return_value=fake_result) as mock_send:
        # Remove cached module so it re-imports cleanly with the patch active
        sys.modules.pop("services.email_service", None)
        from services.email_service import send_email

        msg_id = await send_email(
            to="user@example.com",
            subject="Test Subject",
            html="<p>Hello</p>",
        )

        assert msg_id == "msg_abc123"
        mock_send.assert_called_once()
        call_params = mock_send.call_args[0][0]
        assert call_params["to"] == ["user@example.com"]
        assert call_params["subject"] == "Test Subject"
        assert call_params["html"] == "<p>Hello</p>"
        assert "PersonaOn" in call_params["from"]


@pytest.mark.asyncio
async def test_send_email_passes_lifecycle_options_to_resend():
    fake_result = {"id": "msg_lifecycle_123"}

    with patch("resend.Emails.send", return_value=fake_result) as mock_send:
        sys.modules.pop("services.email_service", None)
        from services.email_service import send_email

        msg_id = await send_email(
            to="user@example.com",
            subject="Daily update",
            html="<p>Hello</p>",
            text="Hello",
            reply_to="support@personaon.com",
            headers={"List-Unsubscribe": "<https://app.personaon.com/unsubscribe/tok>"},
            tags=[
                {"name": "category", "value": "daily_activity"},
                {"name": "email_type", "value": "daily_persona_activity"},
            ],
            idempotency_key="lifecycle:user-1:daily:2026-05-02",
        )

        assert msg_id == "msg_lifecycle_123"
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0]
        call_params = call_args[0]
        call_options = call_args[1]
        assert call_params["text"] == "Hello"
        assert call_params["reply_to"] == "support@personaon.com"
        assert call_params["headers"]["List-Unsubscribe"].startswith("<https://")
        assert call_params["tags"][0]["name"] == "category"
        assert call_options["idempotency_key"] == "lifecycle:user-1:daily:2026-05-02"


# ---------------------------------------------------------------------------
# test_send_email_warns_missing_api_key
# When RESEND_API_KEY is empty, a logger.warning must be emitted at module load.
# ---------------------------------------------------------------------------
def test_send_email_warns_missing_api_key():
    # Remove cached module so _configure_resend() re-runs on import
    sys.modules.pop("services.email_service", None)

    with patch.dict(os.environ, {"RESEND_API_KEY": ""}, clear=False):
        with patch("logging.Logger.warning") as mock_warning:
            import services.email_service  # noqa: F401 — triggers _configure_resend()

            warning_calls = [str(call) for call in mock_warning.call_args_list]
            assert any("RESEND_API_KEY" in c for c in warning_calls), (
                f"Expected warning about missing RESEND_API_KEY, got: {warning_calls}"
            )

    # Reload with proper key to restore clean state for other tests
    sys.modules.pop("services.email_service", None)


# ---------------------------------------------------------------------------
# test_briefing_template_contains_title_and_attendees
# ---------------------------------------------------------------------------
def test_briefing_template_contains_title_and_attendees():
    sys.modules.pop("services.email_service", None)
    from services.email_service import build_briefing_html

    html = build_briefing_html(
        title="Q2 Planning",
        attendees=["Alice", "Bob"],
        context="Discuss roadmap priorities",
        persona_name="John Doe",
    )

    assert "Q2 Planning" in html, "Expected meeting title in briefing HTML"
    assert "Alice" in html, "Expected attendee Alice in briefing HTML"
    assert "Bob" in html, "Expected attendee Bob in briefing HTML"


# ---------------------------------------------------------------------------
# test_followup_template_contains_action_items
# ---------------------------------------------------------------------------
def test_followup_template_contains_action_items():
    sys.modules.pop("services.email_service", None)
    from services.email_service import build_followup_html

    html = build_followup_html(
        title="Sprint Review",
        action_items=["Ship v2", "Fix bugs"],
        summary="Team reviewed sprint outcomes and identified next steps.",
        persona_name="Jane Smith",
    )

    assert "Ship v2" in html, "Expected action item 'Ship v2' in followup HTML"
    assert "Fix bugs" in html, "Expected action item 'Fix bugs' in followup HTML"


# ---------------------------------------------------------------------------
# test_digest_template_contains_meeting_count
# ---------------------------------------------------------------------------
def test_digest_template_contains_meeting_count():
    sys.modules.pop("services.email_service", None)
    from services.email_service import build_digest_html

    meetings = [
        {"title": "Standup", "summary": "Daily check-in"},
        {"title": "Design Review", "summary": "Reviewed mockups"},
        {"title": "1:1 with CEO", "summary": "Strategy alignment"},
        {"title": "All Hands", "summary": "Company update"},
        {"title": "Retrospective", "summary": "Sprint lessons"},
    ]

    html = build_digest_html(
        meeting_count=5,
        meetings=meetings,
        persona_name="Alex Johnson",
    )

    assert "5" in html, "Expected meeting count '5' in digest HTML"
    assert "meeting" in html.lower(), "Expected the word 'meeting' in digest HTML"
