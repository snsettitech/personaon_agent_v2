"""Google Calendar integration service.

Handles OAuth credential management, FreeBusy availability lookups,
and booking event creation with Google Meet links.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, time as dt_time
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# ── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_BH_START = 9   # 9 AM
DEFAULT_BH_END = 17    # 5 PM
DEFAULT_SLOT_MINS = 30
DEFAULT_BUFFER_MINS = 15


# ── Credential helpers ───────────────────────────────────────────────────────

def get_calendar_credentials(twin_id: str) -> Credentials:
    """Load Google Calendar OAuth credentials for *twin_id*.

    Reads from the ``tool_connectors`` table (connector_type = 'google_calendar').
    If the access token is expired and a refresh token exists, it is refreshed
    automatically and the updated token is written back to the database.

    Raises:
        ValueError: When no active connector or credentials exist.
        RuntimeError: When the token refresh fails.
    """
    from modules.observability import get_supabase_client

    sb = get_supabase_client()

    resp = (
        sb.table("tool_connectors")
        .select("id, credentials_encrypted, config")
        .eq("twin_id", twin_id)
        .eq("connector_type", "google_calendar")
        .eq("is_active", True)
        .limit(1)
        .execute()
    )

    if not resp.data:
        raise ValueError("Google Calendar is not connected for this persona.")

    row = resp.data[0]
    creds_raw = row.get("credentials_encrypted")
    if not creds_raw:
        raise ValueError("No stored credentials for Google Calendar connector.")

    creds_info: dict[str, Any] = (
        json.loads(creds_raw) if isinstance(creds_raw, str) else creds_raw
    )

    creds = Credentials.from_authorized_user_info(creds_info)

    # Auto-refresh if expired
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Persist refreshed token
            updated_token = {
                "token": creds.token,
                "refresh_token": creds.refresh_token,
                "token_uri": creds.token_uri,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "scopes": list(creds.scopes) if creds.scopes else creds_info.get("scopes", []),
            }
            sb.table("tool_connectors").update({
                "credentials_encrypted": json.dumps(updated_token),
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("id", row["id"]).execute()
            logger.info("Refreshed Google Calendar token for twin %s", twin_id)
        except Exception as exc:
            logger.error("Failed to refresh Google Calendar token for twin %s: %s", twin_id, exc)
            # Bug 5: if the user revoked access externally (Google security
            # settings), the refresh fails with `invalid_grant`. Mark the
            # connector inactive so _check_calendar_connected and the public
            # booking surface stop pretending it works. Owner has to reconnect.
            err_str = str(exc).lower()
            is_revoked = "invalid_grant" in err_str or "token has been expired or revoked" in err_str
            try:
                sb.table("tool_connectors").update({
                    "is_active": False,
                    "last_error": "token_revoked" if is_revoked else f"refresh_failed: {exc}"[:500],
                    "updated_at": datetime.utcnow().isoformat(),
                }).eq("id", row["id"]).execute()
            except Exception as update_exc:
                logger.error(
                    "Failed to mark connector inactive after refresh failure twin=%s: %s",
                    twin_id, update_exc,
                )
            raise RuntimeError(f"Google Calendar token refresh failed: {exc}") from exc

    return creds


def _load_booking_settings(twin_id: str) -> dict[str, Any]:
    """Return the ``twins.settings.booking`` dict, falling back to defaults."""
    from modules.observability import get_supabase_client

    sb = get_supabase_client()
    resp = (
        sb.table("twins")
        .select("settings")
        .eq("id", twin_id)
        .single()
        .execute()
    )
    settings = (resp.data or {}).get("settings") or {}
    booking = settings.get("booking") or {}
    return {
        "bh_start": booking.get("bh_start", DEFAULT_BH_START),
        "bh_end": booking.get("bh_end", DEFAULT_BH_END),
        "slot_mins": booking.get("slot_mins", DEFAULT_SLOT_MINS),
        "buffer_mins": booking.get("buffer_mins", DEFAULT_BUFFER_MINS),
        "timezone": booking.get("timezone", "UTC"),
    }


# ── Availability ─────────────────────────────────────────────────────────────

def compute_available_slots(
    busy_periods: list[tuple[datetime, datetime]],
    date: datetime,
    owner_tz: str,
    bh_start: int = DEFAULT_BH_START,
    bh_end: int = DEFAULT_BH_END,
    slot_mins: int = DEFAULT_SLOT_MINS,
    buffer_mins: int = DEFAULT_BUFFER_MINS,
) -> list[dict[str, str]]:
    """Pure function: compute open time slots for *date*.

    Args:
        busy_periods: List of (start, end) UTC datetimes from FreeBusy.
        date: The target date (timezone-aware or naive treated as owner_tz).
        owner_tz: IANA timezone string for the persona owner.
        bh_start: Business-hours start hour (0-23).
        bh_end: Business-hours end hour (0-23).
        slot_mins: Duration of each bookable slot.
        buffer_mins: Buffer between slots (prevents back-to-back meetings).

    Returns:
        List of ``{"start": <iso>, "end": <iso>}`` dicts in UTC.
    """
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

    tz = ZoneInfo(owner_tz)
    day_start = datetime.combine(date.date(), dt_time(bh_start, 0), tzinfo=tz)
    day_end = datetime.combine(date.date(), dt_time(bh_end, 0), tzinfo=tz)

    slot_delta = timedelta(minutes=slot_mins)
    buffer_delta = timedelta(minutes=buffer_mins)

    slots: list[dict[str, str]] = []
    cursor = day_start

    while cursor + slot_delta <= day_end:
        slot_end = cursor + slot_delta
        # Check overlap with any busy period
        is_busy = any(
            busy_start < slot_end and busy_end > cursor
            for busy_start, busy_end in busy_periods
        )
        if not is_busy:
            slots.append({
                "start": cursor.isoformat(),
                "end": slot_end.isoformat(),
                # Bug 1: frontend's TimeSlot interface expects `available: bool`.
                # Returned slots are by definition available (busy ones excluded
                # by the overlap check above), so honor the contract explicitly.
                "available": True,
            })
        cursor = cursor + slot_delta + buffer_delta

    return slots


def freebusy_check_window(twin_id: str, start_iso: str, end_iso: str) -> bool:
    """Return True iff [start_iso, end_iso] is free in the owner's primary calendar.

    Used by ``POST /book`` for a submit-time double-check (Bug 3) so that two
    visitors racing on the same slot can't both submit successfully — the
    second one gets a 409 instead of a silent conflict at owner approval time.

    Returns False on any exception so a transient Google outage degrades to
    "we don't know it's free" rather than blindly creating bookings.
    """
    try:
        creds = get_calendar_credentials(twin_id)
    except (ValueError, RuntimeError) as exc:
        logger.warning(
            "[Calendar] freebusy_check_window failed credential load twin=%s: %s",
            twin_id, exc,
        )
        return False

    try:
        service = build("calendar", "v3", credentials=creds)
        fb_result = service.freebusy().query(body={
            "timeMin": start_iso,
            "timeMax": end_iso,
            "items": [{"id": "primary"}],
        }).execute()
    except Exception as exc:
        logger.warning(
            "[Calendar] freebusy_check_window API error twin=%s: %s",
            twin_id, exc,
        )
        return False

    busy = (fb_result.get("calendars", {}).get("primary", {}).get("busy", []))
    # If Google reports any busy block in the requested window, the slot is taken.
    return len(busy) == 0


def get_available_slots(
    twin_id: str,
    date_str: str,
    visitor_timezone: str = "UTC",
) -> list[dict[str, str]]:
    """Return bookable slots for *twin_id* on the given date.

    1. Load booking settings (business hours, slot size, buffer).
    2. Query Google Calendar FreeBusy API for the date.
    3. Compute and return open slots.
    """
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

    creds = get_calendar_credentials(twin_id)
    settings = _load_booking_settings(twin_id)

    owner_tz = settings["timezone"]
    tz = ZoneInfo(owner_tz)

    # Parse date in owner timezone
    target_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
    day_start = datetime.combine(target_date.date(), dt_time(0, 0), tzinfo=tz)
    day_end = day_start + timedelta(days=1)

    # Query FreeBusy
    service = build("calendar", "v3", credentials=creds)
    freebusy_body = {
        "timeMin": day_start.isoformat(),
        "timeMax": day_end.isoformat(),
        "timeZone": owner_tz,
        "items": [{"id": "primary"}],
    }

    try:
        fb_result = service.freebusy().query(body=freebusy_body).execute()
    except Exception as exc:
        logger.error("FreeBusy API error for twin %s: %s", twin_id, exc)
        raise RuntimeError(f"Failed to check calendar availability: {exc}") from exc

    # Parse busy periods
    busy_raw = (
        fb_result.get("calendars", {}).get("primary", {}).get("busy", [])
    )
    busy_periods: list[tuple[datetime, datetime]] = []
    for period in busy_raw:
        start = datetime.fromisoformat(period["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(period["end"].replace("Z", "+00:00"))
        busy_periods.append((start, end))

    return compute_available_slots(
        busy_periods=busy_periods,
        date=target_date,
        owner_tz=owner_tz,
        bh_start=settings["bh_start"],
        bh_end=settings["bh_end"],
        slot_mins=settings["slot_mins"],
        buffer_mins=settings["buffer_mins"],
    )


# ── Booking creation ─────────────────────────────────────────────────────────

def create_booking_event(
    twin_id: str,
    booking: dict[str, Any],
) -> dict[str, Any]:
    """Create a Google Calendar event with Meet link and send invites.

    Args:
        twin_id: The persona twin whose calendar to use.
        booking: Dict with keys ``visitor_name``, ``visitor_email``,
                 ``proposed_start``, ``proposed_end``, ``visitor_message``.

    Returns:
        Dict with ``event_id``, ``meet_link``, ``event_link``.
    """
    creds = get_calendar_credentials(twin_id)
    service = build("calendar", "v3", credentials=creds)

    start_str = booking["proposed_start"]
    end_str = booking["proposed_end"]
    visitor_name = booking.get("visitor_name", "Visitor")
    visitor_email = booking["visitor_email"]
    visitor_message = booking.get("visitor_message", "")

    summary = f"Meeting with {visitor_name}"
    description = "Booked via PersonaOn.\n\n"
    if visitor_message:
        description += f"Message from {visitor_name}:\n{visitor_message}"

    event_body: dict[str, Any] = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_str, "timeZone": "UTC"},
        "end": {"dateTime": end_str, "timeZone": "UTC"},
        "attendees": [{"email": visitor_email}],
        "conferenceData": {
            "createRequest": {
                "requestId": f"personaon-{twin_id[:8]}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email", "minutes": 30},
                {"method": "popup", "minutes": 10},
            ],
        },
    }

    try:
        event = (
            service.events()
            .insert(
                calendarId="primary",
                body=event_body,
                conferenceDataVersion=1,
                sendUpdates="all",
            )
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to create calendar event for twin %s: %s", twin_id, exc)
        raise RuntimeError(f"Failed to create calendar event: {exc}") from exc

    meet_link = ""
    conference_data = event.get("conferenceData")
    if conference_data:
        entry_points = conference_data.get("entryPoints", [])
        for ep in entry_points:
            if ep.get("entryPointType") == "video":
                meet_link = ep.get("uri", "")
                break

    return {
        "event_id": event.get("id", ""),
        "meet_link": meet_link,
        "event_link": event.get("htmlLink", ""),
        # RFC 5545 iCalendar UID. Google returns this on event creation and Recall
        # reports the SAME value when it later syncs this event back. Carrying it
        # onto the booking's meeting row lets booking + calendar-sync converge on
        # ONE row (prevents the duplicate-meeting bug). See meetings-spec-and-plan.md.
        "ical_uid": event.get("iCalUID", ""),
    }
