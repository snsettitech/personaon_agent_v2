"""Contract test for the calendar_status endpoint after extension to dual-provider."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_status_returns_both_providers_disconnected_when_no_rows():
    from routers.calendar_booking import calendar_status

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value = (
        MagicMock(data=[])
    )

    with (
        patch("routers.calendar_booking.get_supabase_client", return_value=mock_sb),
        patch("routers.calendar_booking.verify_twin_ownership"),
    ):
        result = await calendar_status(twin_id="t1", user={"user_id": "u1"})

    assert result["connected"] is False
    assert result["providers"]["google"]["connected"] is False
    assert result["providers"]["microsoft"]["connected"] is False


@pytest.mark.asyncio
async def test_status_returns_google_connected_only():
    from routers.calendar_booking import calendar_status

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value = (
        MagicMock(data=[{
            "connector_type": "google_calendar",
            "is_active": True,
            "last_error": None,
            "updated_at": "2026-05-19T10:00:00Z",
            "recall_calendar_id": "cal_g_abc",
        }])
    )

    with (
        patch("routers.calendar_booking.get_supabase_client", return_value=mock_sb),
        patch("routers.calendar_booking.verify_twin_ownership"),
    ):
        result = await calendar_status(twin_id="t1", user={"user_id": "u1"})

    assert result["connected"] is True
    assert result["providers"]["google"]["connected"] is True
    assert result["providers"]["google"]["is_active"] is True
    assert result["providers"]["google"]["recall_synced"] is True
    assert result["providers"]["microsoft"]["connected"] is False


@pytest.mark.asyncio
async def test_status_returns_both_providers_when_both_connected():
    from routers.calendar_booking import calendar_status

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value = (
        MagicMock(data=[
            {"connector_type": "google_calendar", "is_active": True, "last_error": None, "updated_at": "2026-05-19T10:00:00Z", "recall_calendar_id": "cal_g_abc"},
            {"connector_type": "microsoft_outlook", "is_active": True, "last_error": None, "updated_at": "2026-05-19T11:00:00Z", "recall_calendar_id": "cal_ms_xyz"},
        ])
    )

    with (
        patch("routers.calendar_booking.get_supabase_client", return_value=mock_sb),
        patch("routers.calendar_booking.verify_twin_ownership"),
    ):
        result = await calendar_status(twin_id="t1", user={"user_id": "u1"})

    assert result["connected"] is True
    assert result["providers"]["google"]["connected"] is True
    assert result["providers"]["microsoft"]["connected"] is True
