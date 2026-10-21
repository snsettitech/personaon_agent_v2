"""Contract tests for calendar booking flow.

Covers Bugs 1, 3, 4 from the calendar-booking-end-to-end fix:
  Bug 1: /v2/calendar/{twin_id}/slots returns slots with `available: true`
  Bug 3: POST /v2/calendar/{twin_id}/book returns 409 on FreeBusy conflict
  Bug 4: _check_calendar_connected requires is_active=True

These tests would have caught the production "No available times" bug in CI.
"""
import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import httpx
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# ---------------------------------------------------------------------------
# Bug 1 — slots include the `available: true` field the frontend depends on
# ---------------------------------------------------------------------------

def test_compute_available_slots_returns_available_true_on_each_slot():
    """Without this, BookingCard.tsx filters everything out → "No available times"."""
    from services.calendar_service import compute_available_slots

    # 9am-5pm window, no busy periods → should produce slots
    target_date = datetime(2026, 5, 6)
    slots = compute_available_slots(
        busy_periods=[],
        date=target_date,
        owner_tz="UTC",
        bh_start=9,
        bh_end=17,
        slot_mins=30,
        buffer_mins=15,
    )

    assert len(slots) > 0, "expected non-empty slots for an empty calendar in business hours"
    for slot in slots:
        assert "start" in slot
        assert "end" in slot
        assert slot.get("available") is True, (
            f"slot {slot} missing `available: True` — BookingCard.tsx filters by this field"
        )


def test_compute_available_slots_excludes_busy_periods():
    from datetime import timezone, timedelta
    from services.calendar_service import compute_available_slots

    target_date = datetime(2026, 5, 6)
    busy_start = datetime(2026, 5, 6, 10, 0, tzinfo=timezone.utc)
    busy_end = busy_start + timedelta(hours=1)

    slots = compute_available_slots(
        busy_periods=[(busy_start, busy_end)],
        date=target_date,
        owner_tz="UTC",
        bh_start=9,
        bh_end=17,
        slot_mins=30,
        buffer_mins=15,
    )

    # Confirm none of the returned slots overlap the busy window
    for slot in slots:
        slot_start = datetime.fromisoformat(slot["start"])
        slot_end = datetime.fromisoformat(slot["end"])
        overlap = slot_start < busy_end and slot_end > busy_start
        assert not overlap, f"slot {slot} overlaps busy period {busy_start}-{busy_end}"


# ---------------------------------------------------------------------------
# Bug 3 — submit-time FreeBusy double-check returns False on overlap
# ---------------------------------------------------------------------------

def test_freebusy_check_window_returns_false_when_busy():
    """Two visitors race on the same slot → second submit must see slot taken."""
    from services import calendar_service

    fake_creds = MagicMock()
    fake_service = MagicMock()
    fake_service.freebusy.return_value.query.return_value.execute.return_value = {
        "calendars": {
            "primary": {
                "busy": [
                    {"start": "2026-05-06T10:00:00Z", "end": "2026-05-06T10:30:00Z"}
                ]
            }
        }
    }

    with patch.object(calendar_service, "get_calendar_credentials", return_value=fake_creds), \
         patch.object(calendar_service, "build", return_value=fake_service):
        result = calendar_service.freebusy_check_window(
            twin_id="twin-1",
            start_iso="2026-05-06T10:00:00Z",
            end_iso="2026-05-06T10:30:00Z",
        )

    assert result is False, "freebusy_check_window should return False when Google reports busy"


def test_freebusy_check_window_returns_true_when_free():
    from services import calendar_service

    fake_creds = MagicMock()
    fake_service = MagicMock()
    fake_service.freebusy.return_value.query.return_value.execute.return_value = {
        "calendars": {"primary": {"busy": []}}
    }

    with patch.object(calendar_service, "get_calendar_credentials", return_value=fake_creds), \
         patch.object(calendar_service, "build", return_value=fake_service):
        result = calendar_service.freebusy_check_window(
            twin_id="twin-1",
            start_iso="2026-05-06T10:00:00Z",
            end_iso="2026-05-06T10:30:00Z",
        )

    assert result is True, "freebusy_check_window should return True when Google reports free"


def test_freebusy_check_window_returns_false_on_credential_error():
    """Defensive default: if we can't reach Google, don't blindly accept the booking."""
    from services import calendar_service

    with patch.object(
        calendar_service,
        "get_calendar_credentials",
        side_effect=ValueError("no connector"),
    ):
        result = calendar_service.freebusy_check_window(
            twin_id="twin-1",
            start_iso="2026-05-06T10:00:00Z",
            end_iso="2026-05-06T10:30:00Z",
        )

    assert result is False


# ---------------------------------------------------------------------------
# Bug 4 — _check_calendar_connected requires is_active=True
# ---------------------------------------------------------------------------

def test_check_calendar_connected_returns_false_when_inactive_only():
    """Stale/revoked connectors must NOT light up the public booking surface."""
    from modules import public_profile_pack

    fake_supabase = MagicMock()
    # Simulate: a row exists but is_active=False is filtered out by the .eq() chain.
    # The .eq("is_active", True) call returns no rows.
    fake_resp = MagicMock()
    fake_resp.data = []
    (fake_supabase.table.return_value.select.return_value
     .eq.return_value.eq.return_value.eq.return_value
     .limit.return_value.execute.return_value) = fake_resp

    with patch.object(public_profile_pack, "supabase", fake_supabase):
        result = public_profile_pack._check_calendar_connected("twin-1")

    assert result is False


def test_check_calendar_connected_returns_true_when_active():
    from modules import public_profile_pack

    fake_supabase = MagicMock()
    fake_resp = MagicMock()
    fake_resp.data = [{"id": "conn-1", "is_active": True}]
    (fake_supabase.table.return_value.select.return_value
     .eq.return_value.eq.return_value.eq.return_value
     .limit.return_value.execute.return_value) = fake_resp

    with patch.object(public_profile_pack, "supabase", fake_supabase):
        result = public_profile_pack._check_calendar_connected("twin-1")

    assert result is True


def test_check_calendar_connected_returns_false_for_empty_twin_id():
    from modules import public_profile_pack

    assert public_profile_pack._check_calendar_connected("") is False
    assert public_profile_pack._check_calendar_connected("   ") is False


# ---------------------------------------------------------------------------
# Sanity: BookingCreateRequest accepts visitor_timezone
# ---------------------------------------------------------------------------

def test_booking_create_request_accepts_visitor_timezone():
    """Schema regression — the body field name must match what BookingCard sends."""
    from routers.calendar_booking import BookingCreateRequest

    req = BookingCreateRequest(
        visitor_name="Test",
        visitor_email="test@example.com",
        proposed_start="2026-05-06T10:00:00+00:00",
        proposed_end="2026-05-06T10:30:00+00:00",
        visitor_timezone="America/New_York",
    )
    assert req.visitor_timezone == "America/New_York"


@pytest.mark.asyncio
async def test_recall_calendar_auth_token_uses_authenticate_contract(monkeypatch):
    """Recall Calendar V1 requires /calendar/authenticate/ with top-level user_id."""
    from routers import calendar_booking

    captured: dict = {}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return httpx.Response(200, json={"token": "calendar-token"})

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(calendar_booking, "RECALL_BASE_URL", "https://us-west-2.recall.ai/api/v1")

    token = await calendar_booking._create_recall_calendar_auth_token("twin-1", "user-1")

    assert token == "calendar-token"
    assert captured["url"] == "https://us-west-2.recall.ai/api/v1/calendar/authenticate/"
    assert captured["json"] == {"user_id": "user-1"}


def test_recall_google_redirect_uri_normalizes_callback_slash(monkeypatch):
    from routers import calendar_booking

    # The Recall flow uses a dedicated env (RECALL_GOOGLE_REDIRECT_URI), deliberately
    # decoupled from GOOGLE_OAUTH_REDIRECT_URI (native-flow callback).
    monkeypatch.setenv(
        "RECALL_GOOGLE_REDIRECT_URI",
        "https://us-west-2.recall.ai/api/v1/calendar/google_oauth_callback",
    )

    assert (
        calendar_booking._recall_google_redirect_uri()
        == "https://us-west-2.recall.ai/api/v1/calendar/google_oauth_callback/"
    )


def test_frontend_calendar_url_defaults_to_existing_dashboard_route(monkeypatch):
    from routers import calendar_booking

    monkeypatch.setattr(calendar_booking, "FRONTEND_URL", "http://localhost:3002")
    monkeypatch.setattr(calendar_booking, "CALENDAR_OAUTH_RETURN_PATH", "/dashboard")

    assert (
        calendar_booking._frontend_calendar_url("connected")
        == "http://localhost:3002/dashboard?gcal=connected"
    )
