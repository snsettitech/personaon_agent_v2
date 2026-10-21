"""
Phase 28: Proactive Notifications — Email Service

Resend wrapper + HTML template builders for meeting briefings,
post-meeting followups, and weekly digest emails.

All email sends use asyncio.to_thread (Resend SDK is synchronous).
HTML templates use inline CSS for email client compatibility.
"""

import asyncio
import html as _html
import logging
import os

import resend

logger = logging.getLogger(__name__)


def _configure_resend() -> None:
    """Configure Resend SDK with API key from environment."""
    api_key = os.getenv("RESEND_API_KEY", "")
    if not api_key:
        logger.warning("[EmailService] RESEND_API_KEY not configured — emails will fail")
    resend.api_key = api_key


_configure_resend()


async def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    text: str | None = None,
    reply_to: str | list[str] | None = None,
    headers: dict[str, str] | None = None,
    tags: list[dict[str, str]] | None = None,
    idempotency_key: str | None = None,
    from_address: str = "PersonaOn <notifications@mail.personaon.com>",
) -> str:
    """
    Send an email via Resend.

    Uses asyncio.to_thread since the Resend SDK is synchronous.
    Returns the Resend message ID on success.

    Args:
        to: Recipient email address
        subject: Email subject line
        html: HTML body content
        from_address: Sender address (defaults to PersonaOn notifications address)

    Returns:
        Resend message ID string (empty string if unavailable)
    """
    params: resend.Emails.SendParams = {
        "from": from_address,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if text is not None:
        params["text"] = text
    if reply_to is not None:
        params["reply_to"] = reply_to
    if headers:
        params["headers"] = headers
    if tags:
        params["tags"] = tags

    options: resend.Emails.SendOptions = {}
    if idempotency_key:
        options["idempotency_key"] = idempotency_key

    result = await asyncio.to_thread(resend.Emails.send, params, options)
    msg_id = (result or {}).get("id", "")
    logger.info(
        "[EmailService] sent to=%s subject=%s msg_id=%s",
        to,
        subject[:60],
        msg_id,
    )
    return msg_id


# ---------------------------------------------------------------------------
# HTML Template Builders
# All templates use inline CSS for email client compatibility (no external sheets).
# PersonaOn brand: teal accent #0D9488, dark text #1F2937, light background #F9FAFB.
# ---------------------------------------------------------------------------

_BASE_STYLE = """
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background-color: #F9FAFB;
  margin: 0;
  padding: 0;
""".strip()

_CARD_STYLE = (
    "max-width:600px;margin:32px auto;background:#FFFFFF;"
    "border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);"
)

_HEADER_STYLE = (
    "background:#0D9488;padding:24px 32px;"
)

_BODY_STYLE = "padding:32px;"

_H1_STYLE = "color:#FFFFFF;margin:0;font-size:20px;font-weight:600;"

_H2_STYLE = "color:#1F2937;font-size:16px;font-weight:600;margin:0 0 8px 0;"

_P_STYLE = "color:#374151;font-size:14px;line-height:1.6;margin:0 0 16px 0;"

_LI_STYLE = "color:#374151;font-size:14px;line-height:1.8;"

_FOOTER_STYLE = (
    "padding:16px 32px;background:#F3F4F6;"
    "border-top:1px solid #E5E7EB;text-align:center;"
)

_FOOTER_P_STYLE = "color:#9CA3AF;font-size:12px;margin:0;"


def _wrap_template(header_title: str, body_html: str, persona_name: str = "") -> str:
    """Wrap content in the base email template."""
    safe_title = _html.escape(header_title)
    safe_persona = _html.escape(persona_name)
    subtitle = (
        f'<p style="color:#CCFBF1;font-size:13px;margin:4px 0 0 0;">'
        f"For {safe_persona}"
        f"</p>"
        if persona_name
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>{safe_title}</title>
</head>
<body style="{_BASE_STYLE}">
  <div style="{_CARD_STYLE}">
    <div style="{_HEADER_STYLE}">
      <h1 style="{_H1_STYLE}">{safe_title}</h1>
      {subtitle}
    </div>
    <div style="{_BODY_STYLE}">
      {body_html}
    </div>
    <div style="{_FOOTER_STYLE}">
      <p style="{_FOOTER_P_STYLE}">
        Sent by <strong>PersonaOn</strong> &middot; Meeting Intelligence
      </p>
    </div>
  </div>
</body>
</html>"""


def build_briefing_html(
    *,
    title: str,
    attendees: list[str],
    context: str,
    persona_name: str = "",
) -> str:
    """
    Build pre-meeting briefing email HTML.

    Includes: meeting title, attendee list, knowledge-base context excerpt.

    Args:
        title: Meeting title
        attendees: List of attendee names
        context: KB context to surface before the meeting
        persona_name: Twin persona name (shown in header subtitle)

    Returns:
        HTML string ready to send via send_email()
    """
    safe_title = _html.escape(title)
    safe_context = _html.escape(context)
    attendee_items = "".join(
        f'<li style="{_LI_STYLE}">{_html.escape(att)}</li>' for att in attendees
    )
    body = f"""
<h2 style="{_H2_STYLE}">Upcoming Meeting: {safe_title}</h2>
<p style="{_P_STYLE}">
  You have a meeting coming up. Here's what you need to know.
</p>

<h2 style="{_H2_STYLE}">Attendees</h2>
<ul style="margin:0 0 16px 0;padding-left:20px;">
  {attendee_items}
</ul>

<h2 style="{_H2_STYLE}">Relevant Context</h2>
<p style="{_P_STYLE}">{safe_context}</p>
"""
    return _wrap_template(f"Meeting Briefing: {title}", body, persona_name)


def build_followup_html(
    *,
    title: str,
    action_items: list[str],
    summary: str,
    persona_name: str = "",
) -> str:
    """
    Build post-meeting followup email HTML.

    Includes: meeting title, summary, action items list.

    Args:
        title: Meeting title
        action_items: List of action item strings extracted from the meeting
        summary: Short meeting summary / TL;DR
        persona_name: Twin persona name (shown in header subtitle)

    Returns:
        HTML string ready to send via send_email()
    """
    safe_title = _html.escape(title)
    safe_summary = _html.escape(summary)
    action_items_html = "".join(
        f'<li style="{_LI_STYLE}">{_html.escape(item)}</li>' for item in action_items
    )
    body = f"""
<h2 style="{_H2_STYLE}">Meeting Complete: {safe_title}</h2>
<p style="{_P_STYLE}">{safe_summary}</p>

<h2 style="{_H2_STYLE}">Action Items</h2>
<ul style="margin:0 0 16px 0;padding-left:20px;">
  {action_items_html}
</ul>
"""
    return _wrap_template(f"Meeting Followup: {title}", body, persona_name)


def build_action_item_reminder_html(
    *,
    meeting_title: str,
    item_text: str,
    due_at: str | None = None,
    link: str | None = None,
    persona_name: str = "",
) -> str:
    """Build an action item reminder email."""
    safe_title = _html.escape(meeting_title or "Meeting")
    safe_item = _html.escape(item_text or "Action item")
    safe_due = _html.escape(due_at or "")
    cta = (
        f'<p style="{_P_STYLE}"><a href="{_html.escape(link)}" style="color:#0D9488;">Open meeting recap</a></p>'
        if link
        else ""
    )
    due_html = f'<p style="{_P_STYLE}"><strong>Due:</strong> {safe_due}</p>' if safe_due else ""
    body = f"""
<h2 style="{_H2_STYLE}">Action item from {safe_title}</h2>
<p style="{_P_STYLE}">{safe_item}</p>
{due_html}
{cta}
"""
    return _wrap_template("Action Item Reminder", body, persona_name)


def build_digest_html(
    *,
    meeting_count: int,
    meetings: list[dict],
    persona_name: str = "",
    digest_body: str = "",
) -> str:
    """
    Build weekly digest email HTML.

    Includes: Gemini-composed persona-voice digest body, then per-meeting summary cards.

    Args:
        meeting_count: Total number of meetings this week
        meetings: List of meeting dicts with 'title' and 'summary' keys
        persona_name: Twin persona name (shown in header subtitle)
        digest_body: Gemini-generated persona-voice digest narrative

    Returns:
        HTML string ready to send via send_email()
    """
    meeting_cards = ""
    for m in meetings:
        m_title = _html.escape(m.get("title", "Untitled Meeting"))
        m_summary = _html.escape(m.get("summary", "No summary available."))
        meeting_cards += f"""
<div style="border-left:3px solid #0D9488;padding:8px 12px;margin:0 0 12px 0;background:#F0FDFA;">
  <p style="color:#1F2937;font-size:14px;font-weight:600;margin:0 0 4px 0;">{m_title}</p>
  <p style="color:#374151;font-size:13px;margin:0;line-height:1.5;">{m_summary}</p>
</div>"""

    noun = "meeting" if meeting_count == 1 else "meetings"
    safe_digest_body = _html.escape(digest_body) if digest_body else ""
    digest_section = (
        f'<p style="{_P_STYLE}">{safe_digest_body}</p>' if safe_digest_body else ""
    )
    body = f"""
<h2 style="{_H2_STYLE}">Your Weekly Digest</h2>
<p style="{_P_STYLE}">
  You had <strong>{meeting_count} {noun}</strong> this week.
</p>
{digest_section}
<h2 style="{_H2_STYLE}">Meeting Summaries</h2>
{meeting_cards}
"""
    return _wrap_template("Weekly Meeting Digest", body, persona_name)
