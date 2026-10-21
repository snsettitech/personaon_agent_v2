"""Tests for the pre-meeting brief email builder.

Covers:
  - build_meeting_brief_email happy path renders person + hooks + commitments
  - Every dynamic field is HTML-escaped (XSS defense)
  - Lifecycle worker routes meeting_brief_ready through the new builder
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


def test_build_meeting_brief_email_with_full_context():
    from services.lifecycle_email_service import build_meeting_brief_email

    result = build_meeting_brief_email(
        frontend_url="https://app.personaon.com",
        preferences_url="https://app.personaon.com/settings?tab=notifications",
        unsubscribe_url="https://api.personaon.com/v2/notifications/unsubscribe/xxx",
        context={
            "meeting_id": "mtg-123",
            "meeting_title": "Coffee with Alex",
            "meeting_start": "2026-05-20T14:30:00Z",
            "person": {
                "name": "Alex Chen",
                "role": "VP Sales",
                "company": "Acme",
                "bio": "Joined Acme in 2024 from Stripe.",
                "signals": ["Posted about Q2 hiring"],
            },
            "hooks": [
                {"label": "Bring", "text": "Cohort data — he asked May 3."},
                {"label": "Probe", "text": "Their security review timeline."},
                {"label": "They care about", "text": "Predictable revenue."},
            ],
            "open_commitments": [
                {"description": "Send cohort data", "days_open": 17, "from_meeting_id": "m1"},
            ],
        },
    )

    assert "Brief for your meeting" in result["html"]
    assert "Coffee with Alex" in result["html"]
    assert "Alex Chen" in result["html"]
    # Person role + company line
    assert "VP Sales at Acme" in result["html"]
    # Bio paragraph
    assert "Joined Acme in 2024" in result["html"]
    # All three hook bodies present
    assert "Cohort data" in result["html"]
    assert "security review" in result["html"]
    assert "Predictable revenue" in result["html"]
    # Open commitment present
    assert "Send cohort data" in result["html"]
    assert "open 17 days" in result["html"]
    # CTA link points to the brief page
    assert "/dashboard/meetings/mtg-123/brief" in result["html"]
    # Persona-prime closer
    assert "PersonaOn briefs you before every meeting" in result["html"]

    # User-facing copy must say "persona" not "twin"
    assert " twin " not in result["html"].lower()
    assert " twin " not in result["text"].lower()

    # Tags include the brief category + email_type
    assert any(
        t.get("name") == "category" and t.get("value") == "meeting_brief"
        for t in result["tags"]
    )
    assert any(
        t.get("name") == "email_type" and t.get("value") == "meeting_brief_ready"
        for t in result["tags"]
    )

    # Plain text version mirrors the key blocks
    assert "Brief for: Coffee with Alex" in result["text"]
    assert "WHO YOU'RE MEETING" in result["text"]
    assert "HOOKS TO LEAD WITH" in result["text"]
    assert "OPEN FROM LAST TIME" in result["text"]


def test_build_meeting_brief_email_escapes_html():
    """Dynamic strings must be HTML-escaped to prevent XSS."""
    from services.lifecycle_email_service import build_meeting_brief_email

    result = build_meeting_brief_email(
        frontend_url="https://app.personaon.com",
        preferences_url="x",
        unsubscribe_url="x",
        context={
            "meeting_id": "m1",
            "meeting_title": "Pwn & ye<>",
            "meeting_start": "2026-05-19T10:00:00Z",
            "person": {
                "name": "<script>alert(1)</script>",
                "role": "<b>VP</b>",
                "company": "<i>Acme</i>",
                "bio": "<img src=x onerror=alert(2)>",
                "signals": [],
            },
            "hooks": [
                {"label": "<style>", "text": "<svg onload=alert(3)>"},
            ],
            "open_commitments": [
                {"description": "<a href=javascript:1>x</a>", "days_open": 3, "from_meeting_id": "x"},
            ],
        },
    )

    assert "<script>alert(1)</script>" not in result["html"]
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in result["html"]
    # Bio image vector escaped
    assert "<img src=x" not in result["html"]
    assert "&lt;img" in result["html"]
    # Hook body escaped
    assert "<svg onload=alert(3)>" not in result["html"]
    assert "&lt;svg" in result["html"]
    # Commitment description escaped
    assert "javascript:1" in result["html"]  # text stays
    assert "<a href=javascript:1>" not in result["html"]
    # Title with ampersand + angle brackets escaped
    assert "Pwn &amp; ye&lt;&gt;" in result["html"]


@pytest.mark.asyncio
async def test_lifecycle_worker_routes_meeting_brief_to_brief_builder():
    """email_type=meeting_brief_ready must call build_meeting_brief_email."""
    from modules.graph_outbox_worker import _process_send_lifecycle_email

    job = {
        "id": "job-brief-1",
        "payload": {
            "user_id": "u1",
            "tenant_id": "t1",
            "twin_id": "tw1",
            "recipient_email": "owner@example.com",
            "email_type": "meeting_brief_ready",
            "category": "meeting_brief",
            "scope_type": "meeting",
            "scope_id": "mtg-1",
            "period_key": "once",
            "event_id": "evt-1",
            "idempotency_key": "meeting_brief_ready:mtg-1",
            "payload": {
                "subject": "Brief for your meeting with Alex",
                "cta_path": "/dashboard/meetings/mtg-1/brief",
                "meeting_id": "mtg-1",
                "meeting_title": "Coffee",
                "meeting_start": "2026-05-20T14:30:00Z",
                "person": {
                    "name": "Alex",
                    "role": "VP Sales",
                    "company": "Acme",
                    "bio": "",
                    "signals": [],
                },
                "hooks": [],
                "open_commitments": [],
            },
        },
    }

    sample_email = {
        "subject": "Brief for your meeting with Alex",
        "html": "<html>brief</html>",
        "text": "brief",
        "headers": {},
        "tags": [],
    }

    with patch(
        "services.lifecycle_email_service.load_lifecycle_preferences",
        return_value={"meeting_brief_enabled": True},
    ), patch(
        "services.lifecycle_email_service.is_email_suppressed",
        return_value=False,
    ), patch(
        "services.lifecycle_email_service.mark_lifecycle_event_sent"
    ), patch(
        "services.lifecycle_email_service.build_meeting_brief_email",
        return_value=sample_email,
    ) as mock_brief_builder, patch(
        "services.lifecycle_email_service.build_meeting_recap_email"
    ) as mock_recap_builder, patch(
        "services.lifecycle_email_service.build_lifecycle_email"
    ) as mock_generic_builder, patch(
        "services.email_service.send_email",
        new_callable=AsyncMock,
        return_value="resend-456",
    ):
        result = await _process_send_lifecycle_email(job)

    assert result is True
    mock_brief_builder.assert_called_once()
    mock_recap_builder.assert_not_called()
    mock_generic_builder.assert_not_called()
