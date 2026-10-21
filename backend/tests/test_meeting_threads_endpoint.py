"""Tests for GET /v2/meetings/{twin_id}/threads (Task P1.1.G)."""
from unittest.mock import MagicMock, patch
import pytest


def _user(tenant_id="t-1"):
    return {"user_id": "u1", "tenant_id": tenant_id}


def _mock_supabase(meeting_rows):
    """Build a supabase mock that returns owner check + given meeting rows."""
    mock_sb = MagicMock()

    twins_chain = MagicMock()
    twins_chain.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[{"id": "twin-1"}])
    )

    meetings_chain = MagicMock()
    meetings_chain.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=meeting_rows)
    )

    mock_sb.table.side_effect = lambda name: {
        "twins": twins_chain,
        "meetings": meetings_chain,
    }[name]
    return mock_sb


@pytest.mark.asyncio
async def test_threads_groups_two_meetings_with_same_attendee():
    from routers.meetings import list_meeting_threads

    meeting_rows = [
        {
            "id": "m1",
            "title": "Coffee with Alex",
            "organizer_email": "sai@personaon.com",
            "attendees_json": [
                {"email": "alex@example.com", "displayName": "Alex Chen"},
                {"email": "sai@personaon.com", "displayName": "Sai"},  # organizer; skipped
            ],
            "meeting_start": "2026-05-19T10:00:00Z",
            "created_at": "2026-05-19T08:00:00Z",
        },
        {
            "id": "m2",
            "title": "Follow-up",
            "organizer_email": "sai@personaon.com",
            "attendees_json": [{"email": "alex@example.com", "name": "Alex Chen"}],
            "meeting_start": "2026-05-12T10:00:00Z",
            "created_at": "2026-05-12T08:00:00Z",
        },
    ]
    mock_sb = _mock_supabase(meeting_rows)

    with (
        patch("routers.meetings.supabase", mock_sb),
        patch("routers.meetings._get_current_user", return_value=_user()),
        patch("routers.meetings.MEETING_INTELLIGENCE_ENABLED", True),
    ):
        result = await list_meeting_threads(twin_id="twin-1", request=MagicMock())

    threads = result["data"]
    assert len(threads) == 1, f"expected 1 thread, got {len(threads)}: {threads}"
    t = threads[0]
    assert t["person_email"] == "alex@example.com"
    assert t["person_name"] == "Alex Chen"
    assert t["meeting_count"] == 2
    assert t["last_met_at"] == "2026-05-19T10:00:00Z"
    assert len(t["meetings"]) == 2


@pytest.mark.asyncio
async def test_threads_skips_organizer():
    from routers.meetings import list_meeting_threads

    meeting_rows = [{
        "id": "m1",
        "title": "Coffee",
        "organizer_email": "Sai@PersonaOn.Com",  # mixed case
        "attendees_json": [
            {"email": "sai@personaon.com"},
            {"email": "alex@example.com", "displayName": "Alex"},
        ],
        "meeting_start": "2026-05-19T10:00:00Z",
        "created_at": "2026-05-19T08:00:00Z",
    }]
    mock_sb = _mock_supabase(meeting_rows)

    with (
        patch("routers.meetings.supabase", mock_sb),
        patch("routers.meetings._get_current_user", return_value=_user()),
        patch("routers.meetings.MEETING_INTELLIGENCE_ENABLED", True),
    ):
        result = await list_meeting_threads(twin_id="twin-1", request=MagicMock())

    threads = result["data"]
    assert len(threads) == 1
    assert threads[0]["person_email"] == "alex@example.com"


@pytest.mark.asyncio
async def test_threads_handles_string_attendees():
    """Some Recall events may have attendees as plain strings, not dicts."""
    from routers.meetings import list_meeting_threads

    meeting_rows = [{
        "id": "m1",
        "title": "Coffee",
        "organizer_email": None,
        "attendees_json": ["Bob Smith", "alex@example.com"],  # mixed shape
        "meeting_start": "2026-05-19T10:00:00Z",
        "created_at": "2026-05-19T08:00:00Z",
    }]
    mock_sb = _mock_supabase(meeting_rows)

    with (
        patch("routers.meetings.supabase", mock_sb),
        patch("routers.meetings._get_current_user", return_value=_user()),
        patch("routers.meetings.MEETING_INTELLIGENCE_ENABLED", True),
    ):
        result = await list_meeting_threads(twin_id="twin-1", request=MagicMock())

    threads = result["data"]
    # Both should appear as separate threads
    keys = [t.get("person_email") or t.get("person_name") for t in threads]
    assert "Bob Smith" in keys
    assert "alex@example.com" in keys


@pytest.mark.asyncio
async def test_threads_sorted_by_last_met_at_desc():
    from routers.meetings import list_meeting_threads

    meeting_rows = [
        {
            "id": "m1",
            "title": "With Bob",
            "organizer_email": "sai@personaon.com",
            "attendees_json": [{"email": "bob@example.com"}],
            "meeting_start": "2026-05-10T10:00:00Z",
            "created_at": "2026-05-10T08:00:00Z",
        },
        {
            "id": "m2",
            "title": "With Alex",
            "organizer_email": "sai@personaon.com",
            "attendees_json": [{"email": "alex@example.com"}],
            "meeting_start": "2026-05-19T10:00:00Z",
            "created_at": "2026-05-19T08:00:00Z",
        },
    ]
    mock_sb = _mock_supabase(meeting_rows)

    with (
        patch("routers.meetings.supabase", mock_sb),
        patch("routers.meetings._get_current_user", return_value=_user()),
        patch("routers.meetings.MEETING_INTELLIGENCE_ENABLED", True),
    ):
        result = await list_meeting_threads(twin_id="twin-1", request=MagicMock())

    threads = result["data"]
    # alex first because last_met_at is more recent
    assert threads[0]["person_email"] == "alex@example.com"
    assert threads[1]["person_email"] == "bob@example.com"


@pytest.mark.asyncio
async def test_threads_403_on_wrong_tenant():
    from fastapi import HTTPException
    from routers.meetings import list_meeting_threads

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[])  # owner check fails
    )

    with (
        patch("routers.meetings.supabase", mock_sb),
        patch("routers.meetings._get_current_user", return_value=_user()),
        patch("routers.meetings.MEETING_INTELLIGENCE_ENABLED", True),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await list_meeting_threads(twin_id="twin-x", request=MagicMock())

    assert exc_info.value.status_code == 403
