"""
Tests for notification_service module (Phase 28-02).

Requirements: MTG-22 (pre-meeting briefing), MTG-23 (post-meeting follow-up),
              MTG-24 (weekly digest), MTG-27 (notification preferences)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# MTG-22: Pre-meeting briefing generator
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_briefing_skips_insufficient_kb_context():
    """generate_briefing returns None when vector_store.search returns < 2 chunks."""
    meeting = {
        "id": "meeting-123",
        "title": "Q4 Planning",
        "attendees": ["Alice", "Bob"],
    }

    with patch("adk_core.services.vector_store.search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = [{"text": "only one result"}]  # < 2 chunks

        from services.notification_service import generate_briefing
        result = await generate_briefing(meeting=meeting, twin_id="twin-abc")

    assert result is None


@pytest.mark.asyncio
async def test_briefing_includes_attendees_and_context():
    """generate_briefing returns dict with html and subject when given meeting with attendees + KB chunks."""
    meeting = {
        "id": "meeting-123",
        "title": "Q4 Planning",
        "attendees": ["Alice", "Bob"],
    }

    kb_chunks = [
        {"text": "Alice is the head of product."},
        {"text": "Bob leads the engineering team."},
        {"text": "Q4 focus is on AI features."},
    ]

    mock_genai_response = MagicMock()
    mock_genai_response.text = "Here is your pre-meeting briefing for Q4 Planning..."

    mock_twin_resp = MagicMock()
    mock_twin_resp.data = {"name": "Test Twin", "settings": {"persona_profile": "Senior exec..."}}

    with (
        patch("adk_core.services.vector_store.search", new_callable=AsyncMock) as mock_search,
        patch("modules.observability.supabase") as mock_supabase,
        patch("services.meeting_analyzer._get_genai_client") as mock_client_fn,
        patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread,
    ):
        mock_search.return_value = kb_chunks
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_twin_resp
        mock_thread.return_value = mock_genai_response

        from services.notification_service import generate_briefing
        result = await generate_briefing(meeting=meeting, twin_id="twin-abc")

    assert result is not None
    assert "subject" in result
    assert "html" in result
    assert "Q4 Planning" in result["subject"]
    assert "<html" in result["html"].lower() or "<!DOCTYPE" in result["html"]


# ---------------------------------------------------------------------------
# MTG-23: Post-meeting follow-up generator
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_followup_uses_summary_json():
    """generate_followup reads summary_json from the meeting record and returns {subject, html}."""
    meeting = {
        "id": "meeting-456",
        "title": "Quarterly Review",
        "summary_json": {
            "executive_summary": "We reviewed Q4 results and discussed roadmap priorities.",
            "action_items": ["Follow up with Alice on budget", "Share slides with team"],
        },
    }

    mock_genai_response = MagicMock()
    mock_genai_response.text = "Dear team, following up on our Quarterly Review..."

    mock_twin_resp = MagicMock()
    mock_twin_resp.data = {"name": "Test Twin", "settings": {"persona_profile": "Senior exec..."}}

    with (
        patch("modules.observability.supabase") as mock_supabase,
        patch("services.meeting_analyzer._get_genai_client") as mock_client_fn,
        patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread,
    ):
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_twin_resp
        mock_thread.return_value = mock_genai_response

        from services.notification_service import generate_followup
        result = await generate_followup(meeting=meeting, twin_id="twin-abc")

    assert result is not None
    assert "subject" in result
    assert "html" in result
    assert "Quarterly Review" in result["subject"]
    assert "<html" in result["html"].lower() or "<!DOCTYPE" in result["html"]


# ---------------------------------------------------------------------------
# MTG-24: Weekly digest generator
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_digest_aggregates_week_meetings():
    """generate_digest returns dict with html+subject when given >= 3 meetings."""
    meetings = [
        {
            "id": f"m-{i}",
            "title": f"Meeting {i}",
            "summary_json": {
                "executive_summary": f"Summary of meeting {i}",
                "action_items": [f"Action item {i}"],
            },
        }
        for i in range(3)
    ]

    mock_genai_response = MagicMock()
    mock_genai_response.text = "This week you had 3 meetings covering various topics..."

    mock_twin_resp = MagicMock()
    mock_twin_resp.data = {"name": "Test Twin", "settings": {"persona_profile": "Senior exec..."}}

    with (
        patch("modules.observability.supabase") as mock_supabase,
        patch("services.meeting_analyzer._get_genai_client") as mock_client_fn,
        patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread,
    ):
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_twin_resp
        mock_thread.return_value = mock_genai_response

        from services.notification_service import generate_digest
        result = await generate_digest(twin_id="twin-abc", meetings=meetings)

    assert result is not None
    assert "subject" in result
    assert "html" in result
    assert "Weekly Digest" in result["subject"]
    assert "<html" in result["html"].lower() or "<!DOCTYPE" in result["html"]


@pytest.mark.asyncio
async def test_digest_returns_none_for_insufficient_meetings():
    """generate_digest returns None when given < 3 meetings."""
    meetings = [
        {"id": "m-1", "title": "Solo Meeting", "summary_json": {"executive_summary": "Only one"}},
        {"id": "m-2", "title": "Second Meeting", "summary_json": {"executive_summary": "Two"}},
    ]

    from services.notification_service import generate_digest
    result = await generate_digest(twin_id="twin-abc", meetings=meetings)

    assert result is None


# ---------------------------------------------------------------------------
# MTG-27: Notification preferences
# ---------------------------------------------------------------------------

def test_load_prefs_defaults_all_true():
    """load_notification_prefs returns all True when twins.settings has no meeting_notifications key."""
    mock_resp = MagicMock()
    mock_resp.data = {"settings": {}}  # no meeting_notifications key

    with patch("modules.observability.supabase") as mock_supabase:
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_resp

        from services.notification_service import load_notification_prefs
        prefs = load_notification_prefs("twin-abc")

    assert prefs["pre_meeting"] is True
    assert prefs["post_meeting"] is True
    assert prefs["weekly_digest"] is True
