"""Tests for the meeting recap email builder and worker enqueue flow.

Covers:
  - build_meeting_recap_email() happy path with all sections
  - Empty sections gracefully omitted from HTML and text
  - HTML escaping of every dynamic field (XSS prevention)
  - Worker routes meeting_recap_ready through build_meeting_recap_email
  - _process_generate_meeting_summary enqueues recap email after persisting
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# build_meeting_recap_email
# ---------------------------------------------------------------------------


def test_build_meeting_recap_email_with_full_context():
    from services.lifecycle_email_service import build_meeting_recap_email

    result = build_meeting_recap_email(
        frontend_url="https://app.personaon.com",
        preferences_url="https://app.personaon.com/settings?tab=notifications",
        unsubscribe_url="https://api.personaon.com/v2/notifications/unsubscribe/xxx",
        context={
            "subject": "Recap of your call with Alex Chen",
            "meeting_id": "mtg-123",
            "meeting_title": "Coffee with Alex",
            "meeting_start": "2026-05-19T14:30:00Z",
            "recap": "Discussed pricing tiers and security review. Alex agreed to tier 2.",
            "action_items": [
                {"owner": "me", "description": "Send security questionnaire", "due": "Fri"},
            ],
            "commitments": [
                {"by": "me", "to": "Alex", "what": "Send proposal by Friday"},
            ],
            "decisions": ["Move forward with tier 2 pricing"],
            "unanswered_questions": ["When does CTO return?"],
            "cta_path": "/dashboard/meetings/mtg-123",
        },
    )

    assert result["subject"] == "Recap of your call with Alex Chen"
    assert "<html" in result["html"]
    assert "Discussed pricing tiers" in result["html"]
    assert "Send security questionnaire" in result["html"]
    assert "Send proposal by Friday" in result["html"]
    assert "Move forward with tier 2 pricing" in result["html"]
    assert "When does CTO return?" in result["html"]
    assert "View full recap" in result["html"]
    assert "/dashboard/meetings/mtg-123" in result["html"]
    assert "your corrections train your persona" in result["html"]
    # No "twin" mentioned in user-facing copy
    assert " twin " not in result["html"].lower()
    # Plain text version exists with key content
    assert "Send security questionnaire" in result["text"]
    assert "Recap of your call" in result["subject"]
    # Tags include category
    assert any(
        t.get("name") == "category" and t.get("value") == "meeting_recap"
        for t in result["tags"]
    )
    # Email-type tag
    assert any(
        t.get("name") == "email_type" and t.get("value") == "meeting_recap_ready"
        for t in result["tags"]
    )
    # List-Unsubscribe headers preserved
    assert "List-Unsubscribe" in result["headers"]


def test_build_meeting_recap_email_handles_missing_sections():
    """If only recap is present, other sections should be gracefully omitted."""
    from services.lifecycle_email_service import build_meeting_recap_email

    result = build_meeting_recap_email(
        frontend_url="https://app.personaon.com",
        preferences_url="https://app.personaon.com/settings",
        unsubscribe_url="https://api.personaon.com/u/xxx",
        context={
            "subject": "Recap",
            "meeting_id": "m1",
            "meeting_title": "Quick sync",
            "meeting_start": "2026-05-19T10:00:00Z",
            "recap": "Quick sync — nothing to follow up on.",
            "action_items": [],
            "commitments": [],
            "decisions": [],
            "unanswered_questions": [],
            "cta_path": "/dashboard/meetings/m1",
        },
    )

    assert "Quick sync — nothing to follow up on." in result["html"]
    # Empty section labels should NOT appear when their lists are empty
    assert "Action items" not in result["html"]
    assert "Commitments" not in result["html"]
    assert "Decisions" not in result["html"]
    assert "Open for next time" not in result["html"]
    # Plain-text equivalents should also be absent
    assert "ACTION ITEMS" not in result["text"]
    assert "COMMITMENTS" not in result["text"]
    assert "DECISIONS" not in result["text"]
    # CTA + persona prime still rendered
    assert "View full recap" in result["html"]
    assert "your corrections train your persona" in result["html"]


def test_build_meeting_recap_email_escapes_html():
    """Dynamic strings must be HTML-escaped to prevent XSS."""
    from services.lifecycle_email_service import build_meeting_recap_email

    result = build_meeting_recap_email(
        frontend_url="https://app.personaon.com",
        preferences_url="x",
        unsubscribe_url="x",
        context={
            "subject": "<script>alert(1)</script>",
            "meeting_id": "m1",
            "meeting_title": "Pwn & ye<>",
            "meeting_start": "2026-05-19T10:00:00Z",
            "recap": "<img src=x onerror=alert(1)>",
            "action_items": [
                {"description": "<svg onload=alert(2)>", "owner": "<b>me</b>", "due": ""}
            ],
            "commitments": [
                {"by": "<i>a</i>", "to": "<i>b</i>", "what": "<script>", "due": ""}
            ],
            "decisions": ["<style>body{}</style>"],
            "unanswered_questions": ["<a href=javascript:alert(1)>q</a>"],
            "cta_path": "/dashboard/meetings/m1",
        },
    )
    # Raw script tag must not appear unescaped
    assert "<script>alert(1)</script>" not in result["html"]
    assert "&lt;script&gt;" in result["html"]
    # Inline image vector escaped
    assert "<img src=x" not in result["html"]
    assert "&lt;img" in result["html"]
    # Title with & and angle brackets escaped
    assert "Pwn &amp; ye&lt;&gt;" in result["html"]
    # Action item description escaped
    assert "<svg onload=alert(2)>" not in result["html"]
    assert "&lt;svg" in result["html"]
    # Decision string escaped
    assert "<style>" not in result["html"]
    assert "&lt;style&gt;" in result["html"]


def test_build_meeting_recap_email_falls_back_when_meeting_start_unparseable():
    """An unparseable timestamp should not crash; the header still renders."""
    from services.lifecycle_email_service import build_meeting_recap_email

    result = build_meeting_recap_email(
        frontend_url="https://app.personaon.com",
        preferences_url="x",
        unsubscribe_url="x",
        context={
            "subject": "Recap",
            "meeting_id": "m1",
            "meeting_title": "Sync",
            "meeting_start": "not-a-date",
            "recap": "Body",
            "action_items": [],
            "commitments": [],
            "decisions": [],
            "unanswered_questions": [],
            "cta_path": "/dashboard/meetings/m1",
        },
    )

    assert "<h1" in result["html"]
    assert "Sync" in result["html"]


# ---------------------------------------------------------------------------
# Worker routes meeting_recap_ready through the new builder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifecycle_worker_routes_meeting_recap_to_recap_builder():
    """email_type=meeting_recap_ready must call build_meeting_recap_email, not the
    generic build_lifecycle_email."""
    from modules.graph_outbox_worker import _process_send_lifecycle_email

    job = {
        "id": "job-recap-1",
        "payload": {
            "user_id": "u1",
            "tenant_id": "t1",
            "twin_id": "tw1",
            "recipient_email": "owner@example.com",
            "email_type": "meeting_recap_ready",
            "category": "meeting_recap",
            "scope_type": "meeting",
            "scope_id": "mtg-1",
            "period_key": "once",
            "event_id": "evt-1",
            "idempotency_key": "lifecycle:u1:meeting_recap_ready:meeting:mtg-1:once",
            "payload": {
                "subject": "Recap of your call with Alex",
                "cta_path": "/dashboard/meetings/mtg-1",
                "meeting_id": "mtg-1",
                "meeting_title": "Coffee",
                "meeting_start": "2026-05-19T14:30:00Z",
                "recap": "Solid sync.",
                "action_items": [],
                "commitments": [],
                "decisions": [],
                "unanswered_questions": [],
            },
        },
    }

    sample_email = {
        "subject": "Recap of your call with Alex",
        "html": "<html>recap</html>",
        "text": "recap",
        "headers": {},
        "tags": [],
    }

    with patch(
        "services.lifecycle_email_service.load_lifecycle_preferences",
        return_value={"meeting_recap_enabled": True},
    ), patch(
        "services.lifecycle_email_service.is_email_suppressed",
        return_value=False,
    ), patch(
        "services.lifecycle_email_service.mark_lifecycle_event_sent"
    ), patch(
        "services.lifecycle_email_service.build_meeting_recap_email",
        return_value=sample_email,
    ) as mock_recap_builder, patch(
        "services.lifecycle_email_service.build_lifecycle_email"
    ) as mock_generic_builder, patch(
        "services.email_service.send_email",
        new_callable=AsyncMock,
        return_value="resend-123",
    ):
        result = await _process_send_lifecycle_email(job)

    assert result is True
    mock_recap_builder.assert_called_once()
    mock_generic_builder.assert_not_called()


# ---------------------------------------------------------------------------
# _process_generate_meeting_summary enqueues SEND_LIFECYCLE_EMAIL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_handler_enqueues_recap_email():
    """After a recap persists, the handler should enqueue SEND_LIFECYCLE_EMAIL with
    email_type=meeting_recap_ready and a meeting-scoped idempotency key."""
    from modules.graph_outbox import GraphOperationType
    from modules.graph_outbox_worker import _process_generate_meeting_summary

    meeting = {
        "id": "mtg-1",
        "title": "Coffee with Alex",
        "tenant_id": "tenant-1",
        "twin_id": "twin-1",
        "duration_seconds": 600,
        "transcript_raw": [{"participant": {"name": "Alice"}, "words": [{"text": "hi"}]}],
        "transcript_text": "Alice: hi",
        "meeting_start": "2026-05-19T14:30:00Z",
        "attendees_json": [{"displayName": "Alex Chen", "email": "alex@example.com"}],
    }
    summary = {
        "recap": "Sync went well",
        "intent_vs_outcome": {"intent": "", "outcome": ""},
        "topics": [],
        "action_items": [{"owner": "me", "description": "Send proposal", "due": "Fri"}],
        "commitments": [],
        "decisions": [],
        "unanswered_questions": [],
        "people_observed": [{"name": "Alex Chen"}],
        "my_positions": [],
        "style_sample": "",
    }
    analytics = [
        {
            "participant_name": "Alex Chen",
            "talk_time_seconds": 200.0,
            "talk_time_pct": 50.0,
            "word_count": 300,
            "words_per_minute": 90.0,
            "filler_word_count": 1,
            "sentiment_label": "neutral",
            "sentiment_score": 0.5,
        }
    ]

    # Capture submitted outbox jobs
    captured_submits: list[dict] = []

    mock_outbox = MagicMock()

    def _capture_submit(**kwargs):
        captured_submits.append(kwargs)
        return "outbox-job"

    mock_outbox.submit = MagicMock(side_effect=_capture_submit)

    mock_sb = MagicMock()

    # SELECT for meetings row (initial fetch + recap-email twin/user lookups)
    select_resp_meeting = MagicMock(data=meeting)
    select_resp_twin = MagicMock(data={"name": "Owner Persona", "tenant_id": "tenant-1"})
    select_resp_users = MagicMock(data=[{"id": "user-1", "email": "owner@example.com"}])

    def _table_router(table_name: str):
        t = MagicMock()
        if table_name == "meetings":
            chain = MagicMock()
            chain.execute = MagicMock(return_value=select_resp_meeting)
            chain.single = MagicMock(return_value=chain)
            chain.eq = MagicMock(return_value=chain)
            t.select = MagicMock(return_value=chain)

            update_chain = MagicMock()
            update_chain.execute = MagicMock(return_value=MagicMock())
            update_chain.eq = MagicMock(return_value=update_chain)
            t.update = MagicMock(return_value=update_chain)
            return t
        if table_name == "twins":
            chain = MagicMock()
            chain.execute = MagicMock(return_value=select_resp_twin)
            chain.single = MagicMock(return_value=chain)
            chain.eq = MagicMock(return_value=chain)
            t.select = MagicMock(return_value=chain)
            return t
        if table_name == "users":
            chain = MagicMock()
            chain.execute = MagicMock(return_value=select_resp_users)
            chain.limit = MagicMock(return_value=chain)
            chain.eq = MagicMock(return_value=chain)
            t.select = MagicMock(return_value=chain)
            return t
        if table_name == "meeting_analytics":
            upsert_chain = MagicMock()
            upsert_chain.execute = MagicMock(return_value=MagicMock())
            t.upsert = MagicMock(return_value=upsert_chain)
            return t
        # Fallback (shouldn't be hit)
        return MagicMock()

    mock_sb.table.side_effect = _table_router

    job = {
        "id": "job-1",
        "operation": "generate_meeting_summary",
        "payload": {"meeting_id": "mtg-1"},
        "tenant_id": "tenant-1",
        "twin_id": "twin-1",
    }

    with patch("modules.graph_outbox_worker.supabase", mock_sb), patch(
        "modules.graph_outbox_worker.get_graph_outbox", return_value=mock_outbox
    ), patch(
        "services.meeting_analyzer.analyze_meeting",
        new_callable=AsyncMock,
        return_value=(summary, analytics),
    ):
        result = await _process_generate_meeting_summary(job)

    assert result is True

    # Look for the SEND_LIFECYCLE_EMAIL submit among the captured submits.
    recap_submits = [
        s for s in captured_submits
        if s.get("operation") == GraphOperationType.SEND_LIFECYCLE_EMAIL
    ]
    assert recap_submits, f"recap email was not enqueued: submits={captured_submits}"
    recap = recap_submits[0]
    assert recap["idempotency_key"] == "meeting_recap_ready:mtg-1"
    inner = recap["payload"]
    assert inner["email_type"] == "meeting_recap_ready"
    assert inner["category"] == "meeting_recap"
    assert inner["scope_type"] == "meeting"
    assert inner["scope_id"] == "mtg-1"
    assert inner["recipient_email"] == "owner@example.com"
    assert "Alex Chen" in inner["payload"]["subject"]
    assert inner["payload"]["meeting_id"] == "mtg-1"
    assert inner["payload"]["recap"] == "Sync went well"
