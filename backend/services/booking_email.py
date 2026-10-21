"""Booking lifecycle emails — owner notification when a booking lands and
visitor notification when a booking is rejected.

Both emails go through ``services.email_service.send_email`` (Resend SDK).
Failure to send is logged but never raises — booking creation/rejection
should not fail just because Resend is down.
"""
from __future__ import annotations

import html as _html
import logging
import os
from datetime import datetime
from typing import Any

from services.email_service import send_email

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _public_site_url() -> str:
    return (os.getenv("PUBLIC_SITE_URL") or "https://personaon.com").rstrip("/")


def _format_proposed_window(booking: dict[str, Any]) -> str:
    """Format the proposed_start/proposed_end pair as a human-readable window."""
    try:
        start = datetime.fromisoformat(str(booking.get("proposed_start") or ""))
        end = datetime.fromisoformat(str(booking.get("proposed_end") or ""))
        date_str = start.strftime("%a, %b %-d, %Y") if hasattr(start, "strftime") else str(start)
        # Windows strftime doesn't accept %-d; fall back to platform-safe.
        try:
            date_str = start.strftime("%a, %b %-d, %Y")
        except Exception:
            date_str = start.strftime("%a, %b %d, %Y")
        start_t = start.strftime("%I:%M %p").lstrip("0")
        end_t = end.strftime("%I:%M %p").lstrip("0")
        tz = ""
        if start.tzinfo is not None:
            tz = start.strftime(" %Z").strip()
        return f"{date_str} · {start_t} – {end_t}{(' ' + tz) if tz else ''}"
    except Exception:
        return f"{booking.get('proposed_start')} – {booking.get('proposed_end')}"


def _safe(s: Any) -> str:
    """HTML-escape user-supplied content."""
    return _html.escape(str(s or ""), quote=True)


def _resolve_owner_email(twin_id: str) -> tuple[str | None, str]:
    """Return (owner_email, persona_name) for a twin, or (None, persona_name)."""
    from modules.observability import get_supabase_client

    sb = get_supabase_client()
    try:
        twin_resp = (
            sb.table("twins")
            .select("tenant_id, name")
            .eq("id", twin_id)
            .single()
            .execute()
        )
        twin_row = twin_resp.data or {}
        persona_name = str(twin_row.get("name") or "your persona")
        tenant_id = twin_row.get("tenant_id")
        if not tenant_id:
            return None, persona_name

        user_resp = (
            sb.table("users")
            .select("email")
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        rows = user_resp.data or []
        owner_email = (rows[0].get("email") if rows else None) or None
        return owner_email, persona_name
    except Exception as exc:
        logger.warning("[BookingEmail] failed to resolve owner email twin=%s: %s", twin_id, exc)
        return None, "your persona"


# ---------------------------------------------------------------------------
# Owner notification — fires when a booking lands
# ---------------------------------------------------------------------------

async def notify_owner_booking_received(twin_id: str, booking: dict[str, Any]) -> None:
    """Email the persona owner that a new booking request landed.

    Failures are logged but never raise — booking creation must not fail
    because Resend is down.
    """
    owner_email, persona_name = _resolve_owner_email(twin_id)
    if not owner_email:
        logger.info(
            "[BookingEmail] skipping owner notification — no owner email for twin=%s",
            twin_id,
        )
        return

    visitor_name = _safe(booking.get("visitor_name") or "A visitor")
    visitor_email = _safe(booking.get("visitor_email") or "")
    visitor_message = _safe(booking.get("visitor_message") or "")
    window = _safe(_format_proposed_window(booking))
    inbox_url = f"{_public_site_url()}/dashboard/meetings"

    subject = f"{visitor_name} wants to meet — booking request"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 560px; margin: 0 auto; padding: 24px; color: #1d1d1f;">
      <h2 style="font-size: 20px; font-weight: 600; margin: 0 0 8px;">New booking request</h2>
      <p style="font-size: 14px; color: #6e6e73; margin: 0 0 24px;">
        Someone booked a meeting with <strong>{_safe(persona_name)}</strong>.
      </p>
      <div style="background: #f5f5f7; border-radius: 16px; padding: 20px; margin-bottom: 24px;">
        <p style="margin: 0 0 4px; font-size: 16px; font-weight: 600;">{visitor_name}</p>
        <p style="margin: 0 0 12px; font-size: 14px; color: #6e6e73;">
          <a href="mailto:{visitor_email}" style="color: #0066cc; text-decoration: none;">{visitor_email}</a>
        </p>
        <p style="margin: 0 0 4px; font-size: 14px; font-weight: 500;">{window}</p>
        {f'<p style="margin: 12px 0 0; padding: 12px; background: white; border-radius: 12px; font-size: 14px; color: #3a3a3c; font-style: italic;">&ldquo;{visitor_message}&rdquo;</p>' if visitor_message else ''}
      </div>
      <a href="{inbox_url}" style="display: inline-block; background: #1d1d1f; color: white; text-decoration: none; padding: 12px 20px; border-radius: 999px; font-size: 14px; font-weight: 600;">
        Review in dashboard
      </a>
      <p style="font-size: 12px; color: #86868b; margin-top: 32px;">
        You're getting this because someone booked a meeting through your PersonaOn public profile.
        Approve it to send a Google Calendar invite, or reject it with a reason.
      </p>
    </div>
    """.strip()

    try:
        await send_email(
            to=owner_email,
            subject=subject,
            html=html,
            reply_to=str(booking.get("visitor_email") or "").strip() or None,
            tags=[{"name": "type", "value": "booking_request"}],
            idempotency_key=f"booking_owner:{booking.get('id')}",
        )
        logger.info(
            "[BookingEmail] sent owner notification booking=%s twin=%s to=%s",
            booking.get("id"), twin_id, owner_email,
        )
    except Exception as exc:
        logger.exception(
            "[BookingEmail] owner notification failed booking=%s twin=%s: %s",
            booking.get("id"), twin_id, exc,
        )


# ---------------------------------------------------------------------------
# Visitor notification — fires when a booking is rejected
# ---------------------------------------------------------------------------

async def notify_visitor_booking_rejected(
    twin_id: str,
    booking: dict[str, Any],
    reason: str | None,
) -> None:
    """Email the visitor that their booking was rejected, optionally with a reason."""
    visitor_email = str(booking.get("visitor_email") or "").strip()
    if not visitor_email:
        logger.info(
            "[BookingEmail] skipping visitor rejection email — no visitor_email booking=%s",
            booking.get("id"),
        )
        return

    _, persona_name = _resolve_owner_email(twin_id)
    visitor_name = _safe(booking.get("visitor_name") or "there")
    window = _safe(_format_proposed_window(booking))
    safe_reason = _safe(reason) if reason and reason.strip() else ""
    public_url = _public_site_url()

    subject = f"Your booking with {persona_name} couldn't be confirmed"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 560px; margin: 0 auto; padding: 24px; color: #1d1d1f;">
      <h2 style="font-size: 20px; font-weight: 600; margin: 0 0 8px;">Booking not confirmed</h2>
      <p style="font-size: 14px; color: #3a3a3c; margin: 0 0 16px;">
        Hi {visitor_name},
      </p>
      <p style="font-size: 14px; color: #3a3a3c; margin: 0 0 16px;">
        Unfortunately your booking with <strong>{_safe(persona_name)}</strong> for {window} couldn't be confirmed.
      </p>
      {f'<div style="background: #f5f5f7; border-radius: 16px; padding: 16px; margin: 16px 0; font-size: 14px; color: #3a3a3c;"><strong>Note from {_safe(persona_name)}:</strong><br/>{safe_reason}</div>' if safe_reason else ''}
      <p style="font-size: 14px; color: #3a3a3c; margin: 16px 0;">
        You're welcome to pick a different time — visit the public profile to try again.
      </p>
      <a href="{public_url}" style="display: inline-block; background: #1d1d1f; color: white; text-decoration: none; padding: 12px 20px; border-radius: 999px; font-size: 14px; font-weight: 600;">
        Visit PersonaOn
      </a>
      <p style="font-size: 12px; color: #86868b; margin-top: 32px;">
        Sent by PersonaOn on behalf of {_safe(persona_name)}. Reply to this email to reach the owner directly.
      </p>
    </div>
    """.strip()

    try:
        await send_email(
            to=visitor_email,
            subject=subject,
            html=html,
            tags=[{"name": "type", "value": "booking_rejection"}],
            idempotency_key=f"booking_reject:{booking.get('id')}",
        )
        logger.info(
            "[BookingEmail] sent visitor rejection email booking=%s twin=%s to=%s",
            booking.get("id"), twin_id, visitor_email,
        )
    except Exception as exc:
        logger.exception(
            "[BookingEmail] visitor rejection email failed booking=%s twin=%s: %s",
            booking.get("id"), twin_id, exc,
        )
