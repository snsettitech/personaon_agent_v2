"""Lifecycle education and activity email helpers.

This module keeps lifecycle email state separate from meeting notifications.
It owns preference defaults, send-ledger claims, templates, suppression checks,
and small enqueue helpers used by cron and lead capture paths.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html as _html
import logging
import os
from datetime import datetime, timezone
from typing import Any

from services.lifecycle_email_templates import (
    ACCOUNT as ACCOUNT,
    ANNOUNCEMENTS as ANNOUNCEMENTS,
    CATEGORY_PREF_FIELD,
    DAILY_ACTIVITY as DAILY_ACTIVITY,
    DEFAULT_PREFERENCES,
    EMAIL_DEFINITIONS,
    HOT_LEAD_ALERT,
    MEETING_BRIEF,
    MEETING_RECAP,
    PRODUCT_EDUCATION as PRODUCT_EDUCATION,
    WEEKLY_REPORT as WEEKLY_REPORT,
)

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def lifecycle_idempotency_key(
    *,
    user_id: str,
    email_type: str,
    scope_type: str,
    scope_id: str,
    period_key: str,
) -> str:
    return f"lifecycle:{user_id}:{email_type}:{scope_type}:{scope_id}:{period_key}"


def _token_secret() -> bytes:
    raw = os.getenv("JWT_SECRET") or os.getenv("SUPABASE_JWT_SECRET") or "personaon-local-dev"
    return raw.encode("utf-8")


def generate_unsubscribe_token(user_id: str) -> str:
    mac = hmac.new(_token_secret(), user_id.encode("utf-8"), hashlib.sha256).digest()
    payload = f"{user_id}:{base64.urlsafe_b64encode(mac[:18]).decode('ascii').rstrip('=')}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def parse_unsubscribe_token(token: str) -> str | None:
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        user_id, sig = decoded.rsplit(":", 1)
        expected = generate_unsubscribe_token(user_id)
        return user_id if hmac.compare_digest(expected, token) and sig else None
    except Exception:
        return None


def load_lifecycle_preferences(user_id: str, tenant_id: str | None = None) -> dict[str, Any]:
    from modules.observability import supabase

    try:
        query = supabase.table("notification_preferences").select("*").eq("user_id", user_id)
        if tenant_id:
            query = query.eq("tenant_id", tenant_id)
        resp = query.maybe_single().execute()
        row = resp.data or {}
    except Exception as exc:
        logger.warning("[LifecycleEmail] preference lookup failed user=%s: %s", user_id, exc)
        row = {}

    prefs = dict(DEFAULT_PREFERENCES)
    for key in DEFAULT_PREFERENCES:
        if row.get(key) is not None:
            prefs[key] = row.get(key)
    prefs["user_id"] = user_id
    if tenant_id:
        prefs["tenant_id"] = tenant_id
    return prefs


def save_lifecycle_preferences(user_id: str, tenant_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    from modules.observability import supabase

    allowed = set(DEFAULT_PREFERENCES)
    payload = {key: patch[key] for key in allowed if key in patch}
    payload.update(
        {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "unsubscribe_token_hash": hashlib.sha256(generate_unsubscribe_token(user_id).encode("utf-8")).hexdigest(),
            "updated_at": utc_now_iso(),
        }
    )
    resp = (
        supabase.table("notification_preferences")
        .upsert(payload, on_conflict="user_id")
        .execute()
    )
    row = (resp.data or [payload])[0]
    merged = dict(DEFAULT_PREFERENCES)
    merged.update(row)
    return merged


def is_category_enabled(prefs: dict[str, Any], category: str) -> bool:
    return bool(prefs.get(CATEGORY_PREF_FIELD.get(category, ""), True))


def unsubscribe_user(user_id: str, category: str | None = None) -> None:
    patch: dict[str, Any] = {"updated_at": utc_now_iso()}
    if category and category in CATEGORY_PREF_FIELD:
        patch[CATEGORY_PREF_FIELD[category]] = False
    else:
        for field in CATEGORY_PREF_FIELD.values():
            patch[field] = False
    from modules.observability import supabase

    tenant_id = user_id
    try:
        user_resp = (
            supabase.table("users")
            .select("tenant_id")
            .eq("id", user_id)
            .maybe_single()
            .execute()
        )
        tenant_id = str((user_resp.data or {}).get("tenant_id") or user_id)
    except Exception as exc:
        logger.warning("[LifecycleEmail] unsubscribe tenant lookup failed user=%s: %s", user_id, exc)

    payload = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "unsubscribe_token_hash": hashlib.sha256(generate_unsubscribe_token(user_id).encode("utf-8")).hexdigest(),
        **patch,
    }
    supabase.table("notification_preferences").upsert(payload, on_conflict="user_id").execute()


def claim_lifecycle_email_event(
    *,
    user_id: str,
    tenant_id: str,
    email_type: str,
    category: str,
    scope_type: str,
    scope_id: str,
    period_key: str,
    recipient_email: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    from modules.observability import supabase

    idempotency_key = lifecycle_idempotency_key(
        user_id=user_id,
        email_type=email_type,
        scope_type=scope_type,
        scope_id=scope_id,
        period_key=period_key,
    )
    row = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "email_type": email_type,
        "category": category,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "period_key": period_key,
        "recipient_email": recipient_email,
        "idempotency_key": idempotency_key,
        "status": "sending",
        "payload": payload or {},
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
    }
    try:
        resp = (
            supabase.table("lifecycle_email_events")
            .upsert(
                row,
                on_conflict="email_type,scope_type,scope_id,period_key",
                ignore_duplicates=True,
            )
            .execute()
        )
        data = resp.data or []
        return data[0] if data else None
    except Exception as exc:
        logger.warning("[LifecycleEmail] claim failed key=%s: %s", idempotency_key, exc)
        return None


def mark_lifecycle_event_sent(*, event_id: str, resend_message_id: str) -> None:
    from modules.observability import supabase
    supabase.table("lifecycle_email_events").update(
        {
            "status": "sent",
            "resend_message_id": resend_message_id,
            "sent_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
            "error_message": None,
        }
    ).eq("id", event_id).execute()


def mark_lifecycle_event_failed(*, event_id: str, error_message: str) -> None:
    from modules.observability import supabase
    supabase.table("lifecycle_email_events").update(
        {
            "status": "failed",
            "error_message": error_message[:2000],
            "updated_at": utc_now_iso(),
        }
    ).eq("id", event_id).execute()


def mark_lifecycle_event_skipped(*, event_id: str, reason: str) -> None:
    from modules.observability import supabase
    supabase.table("lifecycle_email_events").update(
        {
            "status": "skipped",
            "skip_reason": reason[:500],
            "updated_at": utc_now_iso(),
        }
    ).eq("id", event_id).execute()


def is_email_suppressed(*, user_id: str, email: str | None = None) -> bool:
    from modules.observability import supabase

    try:
        query = supabase.table("email_suppressions").select("id").eq("user_id", user_id)
        if email:
            query = query.eq("email", email.lower())
        resp = query.limit(1).execute()
        return bool(resp.data)
    except Exception:
        return False


def suppress_email(*, user_id: str | None, email: str, reason: str, provider_event_id: str | None = None) -> None:
    from modules.observability import supabase
    row = {
        "user_id": user_id,
        "email": email.lower(),
        "reason": reason,
        "provider_event_id": provider_event_id,
        "created_at": utc_now_iso(),
    }
    supabase.table("email_suppressions").upsert(row, on_conflict="email,reason").execute()


def record_resend_webhook(payload: dict[str, Any], headers: dict[str, str]) -> None:
    from modules.observability import supabase
    row = {
        "svix_id": headers.get("svix-id") or headers.get("id") or "",
        "event_type": payload.get("type") or payload.get("event") or "",
        "resend_message_id": ((payload.get("data") or {}).get("email_id") or (payload.get("data") or {}).get("id")),
        "payload": payload,
        "received_at": utc_now_iso(),
    }
    supabase.table("resend_webhook_events").upsert(row, on_conflict="svix_id").execute()


def _absolute_url(base: str, path: str) -> str:
    if path.startswith(("http://", "https://", "mailto:")):
        return path
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def build_lifecycle_email(
    *,
    email_type: str,
    frontend_url: str,
    preferences_url: str,
    unsubscribe_url: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = context or {}
    generated_email = bool(context.get("generated_email"))
    if generated_email:
        subject = str(context.get("subject") or "").strip()
        body = str(context.get("body") or "").strip()
        if not subject or not body:
            raise ValueError("generated lifecycle emails require subject and body")
        cta_label = str(context.get("cta_label") or "Open PersonaOn")
        help_path = str(context.get("help_path") or "/help/product-updates")
        cta_path = str(context.get("cta_path") or "/dashboard")
        category = str(context.get("category") or "announcements")
    else:
        definition: dict[str, Any] = EMAIL_DEFINITIONS[email_type]
        subject = str(context.get("subject") or definition["subject"])
        body = str(context.get("body") or definition["body"])
        cta_label = str(context.get("cta_label") or definition["cta_label"])
        help_path = str(definition["help_path"])
        cta_path = str(context.get("cta_path") or definition["cta_path"])
        category = str(definition["category"])
    help_url = _absolute_url(frontend_url, help_path)
    cta_url = _absolute_url(frontend_url, cta_path)
    metrics = context.get("metrics") if isinstance(context.get("metrics"), list) else []
    metric_html = "".join(
        f"<li>{_html.escape(str(item))}</li>" for item in metrics[:6]
    )
    metric_text = "\n".join(f"- {item}" for item in metrics[:6])
    postal = (os.getenv("EMAIL_FOOTER_POSTAL_ADDRESS") or "").strip()
    if os.getenv("ENVIRONMENT", "").lower() == "production":
        if not postal:
            raise RuntimeError("EMAIL_FOOTER_POSTAL_ADDRESS is required for production lifecycle emails")
        if postal.lower() == "personaon":
            raise RuntimeError("EMAIL_FOOTER_POSTAL_ADDRESS must be a real company mailing address")
    postal = postal or "PersonaOn"
    wordmark_html = """
      <table role="presentation" aria-label="PersonaOn wordmark" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:0 0 18px;">
        <tr>
          <td style="font-family:'Instrument Serif',Georgia,'Times New Roman',serif;font-size:28px;line-height:1;color:#0A0A0B;font-weight:400;letter-spacing:0;">PersonaOn</td>
          <td style="width:8px;font-size:0;line-height:0;">&nbsp;</td>
          <td style="vertical-align:middle;">
            <span style="display:inline-block;width:14px;height:14px;border-radius:999px;background:rgba(0,102,204,0.18);line-height:14px;text-align:center;">
              <span style="display:inline-block;width:6px;height:6px;border-radius:999px;background:#0066CC;vertical-align:middle;"></span>
            </span>
          </td>
        </tr>
      </table>"""

    html = f"""<!doctype html>
<html lang="en">
<body style="margin:0;padding:0;background:#F7F7F5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1D1D1F;">
  <div style="max-width:600px;margin:0 auto;padding:32px 20px;">
    <div style="background:#FFFFFF;border:1px solid #E6E2DA;border-radius:12px;padding:28px;">
{wordmark_html}
      <h1 style="font-size:24px;line-height:1.2;margin:0 0 12px;">{_html.escape(subject)}</h1>
      <p style="font-size:15px;line-height:1.6;margin:0 0 18px;color:#344054;">{_html.escape(body)}</p>
      {f'<ul style="margin:0 0 20px 20px;padding:0;color:#344054;font-size:14px;line-height:1.7;">{metric_html}</ul>' if metric_html else ''}
      <p style="margin:24px 0;">
        <a href="{_html.escape(cta_url)}" style="background:#0066CC;color:#FFFFFF;text-decoration:none;border-radius:8px;padding:12px 16px;font-size:14px;font-weight:600;">{_html.escape(cta_label)}</a>
      </p>
      <p style="font-size:13px;line-height:1.5;color:#667085;margin:20px 0 0;">Guide: <a href="{_html.escape(help_url)}" style="color:#0066CC;">{_html.escape(help_url)}</a></p>
    </div>
    <p style="font-size:12px;line-height:1.6;color:#667085;margin:18px 4px 0;">
      <a href="{_html.escape(preferences_url)}" style="color:#0066CC;">Manage preferences</a>
      &nbsp;|&nbsp;
      <a href="{_html.escape(unsubscribe_url)}" style="color:#0066CC;">Unsubscribe</a><br>
      {_html.escape(postal)}
    </p>
  </div>
</body>
</html>"""
    text = (
        f"PersonaOn\n\n{subject}\n\n{body}\n\n"
        + (f"{metric_text}\n\n" if metric_text else "")
        + f"{cta_label}: {cta_url}\n"
        + f"Guide: {help_url}\n"
        + f"Manage preferences: {preferences_url}\n"
        + f"Unsubscribe: {unsubscribe_url}\n"
        + postal
    )
    return {
        "subject": subject,
        "html": html,
        "text": text,
        "headers": {
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
        "tags": [
            {"name": "category", "value": category},
            {"name": "email_type", "value": email_type},
            {"name": "environment", "value": os.getenv("ENVIRONMENT", "development")},
        ],
    }


def _format_meeting_start(value: str | None) -> str:
    """Render an ISO-8601 timestamp as 'Tue May 19 · 2:30 PM'.

    Returns empty string if value is missing or unparseable so the caller can
    omit the subtitle gracefully.
    """
    if not value:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    # datetime.fromisoformat in py3.11+ tolerates the trailing 'Z' suffix only
    # via .replace; do that ourselves to stay compatible.
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(candidate)
    except (TypeError, ValueError):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # Cross-platform-safe formatting (no %-I / %#I shenanigans).
    day_label = dt.strftime("%a %b ") + str(dt.day)
    hour = dt.hour % 12 or 12
    minute = dt.strftime("%M")
    suffix = "AM" if dt.hour < 12 else "PM"
    return f"{day_label} · {hour}:{minute} {suffix}"


def _meeting_recap_section_label(label: str) -> str:
    """Standard small-caps section header used between recap blocks."""
    return (
        '<p style="font-size:11px;letter-spacing:0.15em;text-transform:uppercase;'
        "color:#667085;margin:0 0 10px;font-family:\'JetBrains Mono\',monospace;"
        f'font-weight:500;">{_html.escape(label)}</p>'
    )


def build_meeting_recap_email(
    *,
    frontend_url: str,
    preferences_url: str,
    unsubscribe_url: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Build a meeting recap email with section-based layout.

    Sections render in this order, each omitted when its source list is empty:
      narrative recap -> action items -> commitments -> decisions ->
      open questions -> CTA -> persona-prime footer.

    Required ``context`` keys:
      - ``meeting_id`` (str)        used to build the View full recap link
      - ``meeting_title`` (str)
      - ``meeting_start`` (str)     ISO 8601 timestamp
      - ``recap`` (str|None)        narrative (1-3 sentences)
      - ``action_items`` (list|None)   ``[{owner, description, due}]``
      - ``commitments`` (list|None)    ``[{by, to, what, due}]``
      - ``decisions`` (list|None)      list of strings
      - ``unanswered_questions`` (list|None) list of strings

    Skipped from email (kept in-app): my_positions, people_observed, topics,
    voice samples. Every dynamic string is HTML-escaped.
    """
    context = context or {}
    meeting_id = str(context.get("meeting_id") or "").strip()
    meeting_title = str(context.get("meeting_title") or "Meeting").strip() or "Meeting"
    meeting_start = context.get("meeting_start")
    recap_narrative = str(context.get("recap") or "").strip()
    action_items = context.get("action_items") if isinstance(context.get("action_items"), list) else []
    commitments = context.get("commitments") if isinstance(context.get("commitments"), list) else []
    decisions = context.get("decisions") if isinstance(context.get("decisions"), list) else []
    unanswered_questions = (
        context.get("unanswered_questions")
        if isinstance(context.get("unanswered_questions"), list)
        else []
    )

    definition = EMAIL_DEFINITIONS["meeting_recap_ready"]
    subject = str(context.get("subject") or definition["subject"])
    cta_path = str(context.get("cta_path") or f"/dashboard/meetings/{meeting_id}" or definition["cta_path"])
    cta_url = _absolute_url(frontend_url, cta_path)

    postal = (os.getenv("EMAIL_FOOTER_POSTAL_ADDRESS") or "").strip()
    if os.getenv("ENVIRONMENT", "").lower() == "production":
        if not postal:
            raise RuntimeError("EMAIL_FOOTER_POSTAL_ADDRESS is required for production lifecycle emails")
        if postal.lower() == "personaon":
            raise RuntimeError("EMAIL_FOOTER_POSTAL_ADDRESS must be a real company mailing address")
    postal = postal or "PersonaOn"

    formatted_start = _format_meeting_start(meeting_start if isinstance(meeting_start, str) else None)

    wordmark_html = """
      <table role="presentation" aria-label="PersonaOn wordmark" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:0 0 18px;">
        <tr>
          <td style="font-family:'Instrument Serif',Georgia,'Times New Roman',serif;font-size:28px;line-height:1;color:#0A0A0B;font-weight:400;letter-spacing:0;">PersonaOn</td>
          <td style="width:8px;font-size:0;line-height:0;">&nbsp;</td>
          <td style="vertical-align:middle;">
            <span style="display:inline-block;width:14px;height:14px;border-radius:999px;background:rgba(0,102,204,0.18);line-height:14px;text-align:center;">
              <span style="display:inline-block;width:6px;height:6px;border-radius:999px;background:#0066CC;vertical-align:middle;"></span>
            </span>
          </td>
        </tr>
      </table>"""

    # --- Section builders (all dynamic strings escaped) --------------------
    header_subtitle_html = (
        f'<p style="font-size:13px;color:#667085;margin:0 0 24px;">{_html.escape(formatted_start)}</p>'
        if formatted_start
        else '<p style="font-size:13px;color:#667085;margin:0 0 24px;">&nbsp;</p>'
    )

    narrative_html = ""
    if recap_narrative:
        narrative_html = (
            '<p style="font-size:15px;line-height:1.65;color:#1D1D1F;margin:0 0 24px;">'
            f"{_html.escape(recap_narrative)}</p>"
        )

    def _render_action_item(item: dict[str, Any]) -> str:
        description = _html.escape(str(item.get("description") or "").strip())
        if not description:
            return ""
        owner = str(item.get("owner") or "").strip()
        due = str(item.get("due") or "").strip()
        if owner and due:
            meta = f' <span style="color:#667085;">({_html.escape(owner)}, {_html.escape(due)})</span>'
        elif owner:
            meta = f' <span style="color:#667085;">({_html.escape(owner)})</span>'
        elif due:
            meta = f' <span style="color:#667085;">({_html.escape(due)})</span>'
        else:
            meta = ""
        return f"<li>{description}{meta}</li>"

    action_items_html = ""
    rendered_action_items = "".join(
        _render_action_item(item) for item in action_items if isinstance(item, dict)
    )
    if rendered_action_items:
        action_items_html = (
            _meeting_recap_section_label("Action items")
            + '<ul style="margin:0 0 24px;padding:0 0 0 20px;color:#1D1D1F;font-size:14px;line-height:1.7;">'
            + rendered_action_items
            + "</ul>"
        )

    def _render_commitment(item: dict[str, Any]) -> str:
        by = _html.escape(str(item.get("by") or "").strip())
        to = _html.escape(str(item.get("to") or "").strip())
        what = _html.escape(str(item.get("what") or "").strip())
        if not (by or to or what):
            return ""
        due = str(item.get("due") or "").strip()
        due_suffix = f" ({_html.escape(due)})" if due else ""
        return f"<li>{by} → {to}: {what}{due_suffix}</li>"

    commitments_html = ""
    rendered_commitments = "".join(
        _render_commitment(item) for item in commitments if isinstance(item, dict)
    )
    if rendered_commitments:
        commitments_html = (
            _meeting_recap_section_label("Commitments")
            + '<ul style="list-style:none;margin:0 0 24px;padding:0;color:#1D1D1F;font-size:14px;line-height:1.7;">'
            + rendered_commitments
            + "</ul>"
        )

    decisions_items = [str(d).strip() for d in decisions if str(d or "").strip()]
    decisions_html = ""
    if decisions_items:
        rendered = "".join(f"<li>✓ {_html.escape(d)}</li>" for d in decisions_items)
        decisions_html = (
            _meeting_recap_section_label("Decisions")
            + '<ul style="margin:0 0 24px;padding:0 0 0 20px;color:#1D1D1F;font-size:14px;line-height:1.7;list-style:none;">'
            + rendered
            + "</ul>"
        )

    questions_items = [str(q).strip() for q in unanswered_questions if str(q or "").strip()]
    questions_html = ""
    if questions_items:
        rendered = "".join(f"<li>{_html.escape(q)}</li>" for q in questions_items)
        questions_html = (
            _meeting_recap_section_label("Open for next time")
            + '<ul style="margin:0 0 24px;padding:0 0 0 20px;color:#344054;font-size:14px;line-height:1.7;">'
            + rendered
            + "</ul>"
        )

    html = f"""<!doctype html>
<html lang="en">
<body style="margin:0;padding:0;background:#F7F7F5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1D1D1F;">
  <div style="max-width:600px;margin:0 auto;padding:32px 20px;">
    <div style="background:#FFFFFF;border:1px solid #E6E2DA;border-radius:12px;padding:32px;">
{wordmark_html}
      <p style="font-size:12px;letter-spacing:0.15em;text-transform:uppercase;color:#667085;margin:0 0 8px;font-family:'JetBrains Mono',monospace;">Your recap of</p>
      <h1 style="font-size:24px;line-height:1.2;margin:0 0 8px;font-weight:600;letter-spacing:-0.02em;color:#1D1D1F;">{_html.escape(meeting_title)}</h1>
      {header_subtitle_html}
      <hr style="border:0;border-top:1px solid #E6E2DA;margin:0 0 24px;">
      {narrative_html}
      {action_items_html}
      {commitments_html}
      {decisions_html}
      {questions_html}
      <hr style="border:0;border-top:1px solid #E6E2DA;margin:0 0 24px;">
      <p style="margin:0 0 24px;text-align:center;">
        <a href="{_html.escape(cta_url)}" style="background:#0066CC;color:#FFFFFF;text-decoration:none;border-radius:24px;padding:14px 24px;font-size:14px;font-weight:600;display:inline-block;">View full recap →</a>
      </p>
      <p style="font-size:13px;line-height:1.55;color:#667085;margin:24px 0 0;font-style:italic;text-align:center;">
        Edit any of this on the meeting page — your corrections train your persona.
      </p>
    </div>
    <p style="font-size:12px;line-height:1.6;color:#667085;margin:18px 4px 0;">
      <a href="{_html.escape(preferences_url)}" style="color:#0066CC;">Manage preferences</a>
      &nbsp;|&nbsp;
      <a href="{_html.escape(unsubscribe_url)}" style="color:#0066CC;">Unsubscribe</a><br>
      {_html.escape(postal)}
    </p>
  </div>
</body>
</html>"""

    # --- Plain text version ------------------------------------------------
    text_lines: list[str] = ["PersonaOn", "", f"Your recap of: {meeting_title}"]
    if formatted_start:
        text_lines.append(formatted_start)
    text_lines.append("")
    if recap_narrative:
        text_lines.append(recap_narrative)
        text_lines.append("")
    if rendered_action_items:
        text_lines.append("ACTION ITEMS")
        for item in action_items:
            if not isinstance(item, dict):
                continue
            description = str(item.get("description") or "").strip()
            if not description:
                continue
            owner = str(item.get("owner") or "").strip()
            due = str(item.get("due") or "").strip()
            meta_parts = [p for p in (owner, due) if p]
            meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
            text_lines.append(f"• {description}{meta}")
        text_lines.append("")
    if rendered_commitments:
        text_lines.append("COMMITMENTS")
        for item in commitments:
            if not isinstance(item, dict):
                continue
            by = str(item.get("by") or "").strip()
            to = str(item.get("to") or "").strip()
            what = str(item.get("what") or "").strip()
            if not (by or to or what):
                continue
            due = str(item.get("due") or "").strip()
            due_suffix = f" ({due})" if due else ""
            text_lines.append(f"• {by} -> {to}: {what}{due_suffix}")
        text_lines.append("")
    if decisions_items:
        text_lines.append("DECISIONS")
        for d in decisions_items:
            text_lines.append(f"• {d}")
        text_lines.append("")
    if questions_items:
        text_lines.append("OPEN FOR NEXT TIME")
        for q in questions_items:
            text_lines.append(f"• {q}")
        text_lines.append("")
    text_lines.append(f"View full recap: {cta_url}")
    text_lines.append("")
    text_lines.append("Edit any of this on the meeting page — your corrections train your persona.")
    text_lines.append("")
    text_lines.append(f"Manage preferences: {preferences_url}")
    text_lines.append(f"Unsubscribe: {unsubscribe_url}")
    text_lines.append(postal)
    text = "\n".join(text_lines)

    return {
        "subject": subject,
        "html": html,
        "text": text,
        "headers": {
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
        "tags": [
            {"name": "category", "value": MEETING_RECAP},
            {"name": "email_type", "value": "meeting_recap_ready"},
            {"name": "environment", "value": os.getenv("ENVIRONMENT", "development")},
        ],
    }


def build_meeting_brief_email(
    *,
    frontend_url: str,
    preferences_url: str,
    unsubscribe_url: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Build the meeting_brief_ready email.

    Sections render in this order, each omitted when empty:
      header subtitle -> person paragraph -> top 3 hooks ->
      open commitments -> CTA -> persona-prime footer.

    Required ``context`` keys:
      - ``meeting_id`` (str)        used to build the brief link
      - ``meeting_title`` (str)
      - ``meeting_start`` (str)     ISO 8601 timestamp
      - ``person`` (dict|None)      ``{name, role, company, bio, signals}``
      - ``hooks`` (list|None)       ``[{label, text}]`` — first 3 used
      - ``open_commitments`` (list|None) ``[{description, days_open, ...}]``

    Every dynamic string is HTML-escaped (XSS defense — same pattern as
    ``build_meeting_recap_email``). User-facing copy says "persona" not
    "twin".
    """
    context = context or {}
    meeting_id = str(context.get("meeting_id") or "").strip()
    meeting_title = str(context.get("meeting_title") or "Meeting").strip() or "Meeting"
    meeting_start = context.get("meeting_start")
    person = context.get("person") if isinstance(context.get("person"), dict) else {}
    hooks = context.get("hooks") if isinstance(context.get("hooks"), list) else []
    open_commitments = (
        context.get("open_commitments")
        if isinstance(context.get("open_commitments"), list)
        else []
    )

    definition = EMAIL_DEFINITIONS["meeting_brief_ready"]
    subject = str(context.get("subject") or definition["subject"])
    cta_path = str(
        context.get("cta_path")
        or (f"/dashboard/meetings/{meeting_id}/brief" if meeting_id else definition["cta_path"])
    )
    cta_url = _absolute_url(frontend_url, cta_path)

    postal = (os.getenv("EMAIL_FOOTER_POSTAL_ADDRESS") or "").strip()
    if os.getenv("ENVIRONMENT", "").lower() == "production":
        if not postal:
            raise RuntimeError("EMAIL_FOOTER_POSTAL_ADDRESS is required for production lifecycle emails")
        if postal.lower() == "personaon":
            raise RuntimeError("EMAIL_FOOTER_POSTAL_ADDRESS must be a real company mailing address")
    postal = postal or "PersonaOn"

    formatted_start = _format_meeting_start(meeting_start if isinstance(meeting_start, str) else None)

    wordmark_html = """
      <table role="presentation" aria-label="PersonaOn wordmark" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:0 0 18px;">
        <tr>
          <td style="font-family:'Instrument Serif',Georgia,'Times New Roman',serif;font-size:28px;line-height:1;color:#0A0A0B;font-weight:400;letter-spacing:0;">PersonaOn</td>
          <td style="width:8px;font-size:0;line-height:0;">&nbsp;</td>
          <td style="vertical-align:middle;">
            <span style="display:inline-block;width:14px;height:14px;border-radius:999px;background:rgba(0,102,204,0.18);line-height:14px;text-align:center;">
              <span style="display:inline-block;width:6px;height:6px;border-radius:999px;background:#0066CC;vertical-align:middle;"></span>
            </span>
          </td>
        </tr>
      </table>"""

    # --- Sections ---------------------------------------------------------
    header_subtitle_html = (
        f'<p style="font-size:13px;color:#667085;margin:0 0 24px;">{_html.escape(formatted_start)}</p>'
        if formatted_start
        else '<p style="font-size:13px;color:#667085;margin:0 0 24px;">&nbsp;</p>'
    )

    # Person paragraph
    person_name = str((person or {}).get("name") or "").strip()
    person_role = str((person or {}).get("role") or "").strip()
    person_company = str((person or {}).get("company") or "").strip()
    person_bio = str((person or {}).get("bio") or "").strip()

    person_html = ""
    if person_name or person_role or person_company or person_bio:
        head_bits: list[str] = []
        if person_name:
            head_bits.append(f"<strong>{_html.escape(person_name)}</strong>")
        if person_role and person_company:
            head_bits.append(_html.escape(f"{person_role} at {person_company}"))
        elif person_role:
            head_bits.append(_html.escape(person_role))
        elif person_company:
            head_bits.append(_html.escape(person_company))
        head_line = " — ".join(head_bits)
        bio_paragraph = (
            f'<p style="font-size:14.5px;line-height:1.65;color:#1D1D1F;margin:0 0 18px;">{_html.escape(person_bio)}</p>'
            if person_bio
            else ""
        )
        person_html = (
            _meeting_recap_section_label("Who you're meeting")
            + f'<p style="font-size:15px;line-height:1.55;color:#1D1D1F;margin:0 0 12px;">{head_line}</p>'
            + bio_paragraph
        )

    # Hooks — first 3
    def _render_hook(item: dict[str, Any]) -> str:
        label = _html.escape(str(item.get("label") or "").strip())
        text = _html.escape(str(item.get("text") or "").strip())
        if not text:
            return ""
        label_html = (
            f'<span style="display:inline-block;min-width:90px;font-family:\'JetBrains Mono\',monospace;font-size:10.5px;letter-spacing:0.12em;text-transform:uppercase;color:#667085;">{label}</span>'
            if label
            else ""
        )
        return (
            f'<tr><td style="padding:8px 0;vertical-align:top;">{label_html}</td>'
            f'<td style="padding:8px 0;font-size:14.5px;line-height:1.55;color:#1D1D1F;">{text}</td></tr>'
        )

    rendered_hooks = "".join(
        _render_hook(h) for h in hooks[:3] if isinstance(h, dict)
    )
    hooks_html = ""
    if rendered_hooks:
        hooks_html = (
            _meeting_recap_section_label("Hooks to lead with")
            + '<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:0 0 24px;width:100%;">'
            + rendered_hooks
            + "</table>"
        )

    # Open commitments
    def _render_commitment(item: dict[str, Any]) -> str:
        desc = _html.escape(str(item.get("description") or "").strip())
        if not desc:
            return ""
        days_open = item.get("days_open")
        meta = (
            f' <span style="color:#667085;font-size:12.5px;">(open {int(days_open)} days)</span>'
            if isinstance(days_open, int)
            else ""
        )
        return f"<li>{desc}{meta}</li>"

    rendered_commitments = "".join(
        _render_commitment(c) for c in open_commitments if isinstance(c, dict)
    )
    commitments_html = ""
    if rendered_commitments:
        commitments_html = (
            _meeting_recap_section_label("Open from last time")
            + '<ul style="margin:0 0 24px;padding:0 0 0 20px;color:#1D1D1F;font-size:14px;line-height:1.7;">'
            + rendered_commitments
            + "</ul>"
        )

    html = f"""<!doctype html>
<html lang="en">
<body style="margin:0;padding:0;background:#F7F7F5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1D1D1F;">
  <div style="max-width:600px;margin:0 auto;padding:32px 20px;">
    <div style="background:#FFFFFF;border:1px solid #E6E2DA;border-radius:12px;padding:32px;">
{wordmark_html}
      <p style="font-size:12px;letter-spacing:0.15em;text-transform:uppercase;color:#667085;margin:0 0 8px;font-family:'JetBrains Mono',monospace;">Brief for your meeting</p>
      <h1 style="font-size:24px;line-height:1.2;margin:0 0 8px;font-weight:600;letter-spacing:-0.02em;color:#1D1D1F;">{_html.escape(meeting_title)}</h1>
      {header_subtitle_html}
      <hr style="border:0;border-top:1px solid #E6E2DA;margin:0 0 24px;">
      {person_html}
      {hooks_html}
      {commitments_html}
      <hr style="border:0;border-top:1px solid #E6E2DA;margin:0 0 24px;">
      <p style="margin:0 0 24px;text-align:center;">
        <a href="{_html.escape(cta_url)}" style="background:#0066CC;color:#FFFFFF;text-decoration:none;border-radius:24px;padding:14px 24px;font-size:14px;font-weight:600;display:inline-block;">Read the full brief →</a>
      </p>
      <p style="font-size:13px;line-height:1.55;color:#667085;margin:24px 0 0;font-style:italic;text-align:center;">
        PersonaOn briefs you before every meeting — never walk into a cold conversation.
      </p>
    </div>
    <p style="font-size:12px;line-height:1.6;color:#667085;margin:18px 4px 0;">
      <a href="{_html.escape(preferences_url)}" style="color:#0066CC;">Manage preferences</a>
      &nbsp;|&nbsp;
      <a href="{_html.escape(unsubscribe_url)}" style="color:#0066CC;">Unsubscribe</a><br>
      {_html.escape(postal)}
    </p>
  </div>
</body>
</html>"""

    # --- Plain text version -----------------------------------------------
    text_lines: list[str] = ["PersonaOn", "", f"Brief for: {meeting_title}"]
    if formatted_start:
        text_lines.append(formatted_start)
    text_lines.append("")
    if person_name or person_role or person_company or person_bio:
        text_lines.append("WHO YOU'RE MEETING")
        if person_name:
            head = person_name
            if person_role and person_company:
                head += f" — {person_role} at {person_company}"
            elif person_role:
                head += f" — {person_role}"
            elif person_company:
                head += f" — {person_company}"
            text_lines.append(head)
        if person_bio:
            text_lines.append(person_bio)
        text_lines.append("")
    if rendered_hooks:
        text_lines.append("HOOKS TO LEAD WITH")
        for h in hooks[:3]:
            if not isinstance(h, dict):
                continue
            label = str(h.get("label") or "").strip()
            text = str(h.get("text") or "").strip()
            if not text:
                continue
            text_lines.append(f"• {label}: {text}" if label else f"• {text}")
        text_lines.append("")
    if rendered_commitments:
        text_lines.append("OPEN FROM LAST TIME")
        for c in open_commitments:
            if not isinstance(c, dict):
                continue
            desc = str(c.get("description") or "").strip()
            if not desc:
                continue
            days_open = c.get("days_open")
            meta = f" (open {int(days_open)} days)" if isinstance(days_open, int) else ""
            text_lines.append(f"• {desc}{meta}")
        text_lines.append("")
    text_lines.append(f"Read the full brief: {cta_url}")
    text_lines.append("")
    text_lines.append("PersonaOn briefs you before every meeting — never walk into a cold conversation.")
    text_lines.append("")
    text_lines.append(f"Manage preferences: {preferences_url}")
    text_lines.append(f"Unsubscribe: {unsubscribe_url}")
    text_lines.append(postal)
    text = "\n".join(text_lines)

    return {
        "subject": subject,
        "html": html,
        "text": text,
        "headers": {
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
        "tags": [
            {"name": "category", "value": MEETING_BRIEF},
            {"name": "email_type", "value": "meeting_brief_ready"},
            {"name": "environment", "value": os.getenv("ENVIRONMENT", "development")},
        ],
    }


def enqueue_hot_lead_alert(*, twin_id: str, lead_id: str) -> str | None:
    """Best-effort enqueue helper used by widget lead capture."""
    from modules.graph_outbox import GraphOperationType, get_graph_outbox
    from modules.observability import get_supabase_client

    sb = get_supabase_client()
    lead_resp = (
        sb.table("widget_leads")
        .select("id,twin_id,visitor_email,source_domain,conversation_id,inferred_visitor_type,inferred_intent")
        .eq("id", lead_id)
        .eq("twin_id", twin_id)
        .maybe_single()
        .execute()
    )
    lead = lead_resp.data or {}
    email = str(lead.get("visitor_email") or "").strip()
    if not email:
        return None

    twin_resp = (
        sb.table("twins")
        .select("id,tenant_id,name")
        .eq("id", twin_id)
        .maybe_single()
        .execute()
    )
    twin = twin_resp.data or {}
    tenant_id = str(twin.get("tenant_id") or "")
    if not tenant_id:
        return None

    user_resp = (
        sb.table("users")
        .select("id,email")
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    user_rows = user_resp.data if isinstance(user_resp.data, list) else []
    user = user_rows[0] if user_rows else {}
    if not user:
        legacy_resp = (
            sb.table("users")
            .select("id,email")
            .eq("id", tenant_id)
            .maybe_single()
            .execute()
        )
        user = legacy_resp.data or {}
    user_id = str(user.get("id") or tenant_id)
    recipient = str(user.get("email") or "")
    if not recipient:
        return None

    period_key = str(lead_id)
    idempotency_key = lifecycle_idempotency_key(
        user_id=user_id,
        email_type="hot_lead_alert",
        scope_type="lead",
        scope_id=lead_id,
        period_key=period_key,
    )
    # D11: enrich the alert with the persona's inferred read of the visitor so the
    # owner gets context ("a recruiter asked about backend"), not a bare email.
    visitor_type = str(lead.get("inferred_visitor_type") or "").strip()
    intent = str(lead.get("inferred_intent") or "").strip()
    metrics = [f"Lead email: {email}"]
    why = " — ".join(p for p in (visitor_type, intent) if p)
    if why:
        metrics.append(f"Why this matters: {why}")
    metrics.append(f"Source: {lead.get('source_domain') or 'public page'}")
    conv_id = str(lead.get("conversation_id") or "")
    if conv_id:
        metrics.append(f"Transcript: conversation {conv_id}")

    return get_graph_outbox().submit(
        tenant_id=tenant_id,
        twin_id=twin_id,
        operation=GraphOperationType.SEND_LIFECYCLE_EMAIL,
        idempotency_key=idempotency_key,
        payload={
            "user_id": user_id,
            "tenant_id": tenant_id,
            "twin_id": twin_id,
            "recipient_email": recipient,
            "email_type": "hot_lead_alert",
            "category": HOT_LEAD_ALERT,
            "scope_type": "lead",
            "scope_id": lead_id,
            "period_key": period_key,
            "idempotency_key": idempotency_key,
            "reply_to_email": email,
            "payload": {
                "metrics": metrics,
                "cta_path": "/dashboard/widget",
            },
        },
        priority=5,
    )


# ── Visitor confirmation email ─────────────────────────────────────────────

VISITOR_CONFIRMATION = "visitor_confirmation"


def build_visitor_confirmation_email(
    *,
    persona_name: str,
    persona_handle: str,
    visitor_name: str,
    inferred_intent: str | None,
    persona_page_url: str,
    booking_url: str | None = None,
    frontend_url: str,
) -> dict[str, Any]:
    """Return {"subject", "html"} for the visitor receipt email sent post-capture."""
    greeting = f"Hi {_html.escape(visitor_name)}," if visitor_name.strip() else "Hi there,"
    intent_phrase = (
        f"your questions about {_html.escape(inferred_intent)}"
        if inferred_intent and inferred_intent.strip()
        else "your conversation"
    )
    subject = f"You connected with {persona_name}"

    booking_cta = ""
    if booking_url and booking_url.strip():
        safe_booking = _html.escape(booking_url.strip())
        booking_cta = f"""
      <p style="margin:0 0 12px;">If you'd like to move faster, you can also book time directly:</p>
      <p style="margin:0 0 24px;">
        <a href="{safe_booking}" style="display:inline-block;padding:10px 22px;background:#1C1917;color:#ffffff;text-decoration:none;border-radius:8px;font-weight:600;font-size:14px;">Book a call</a>
      </p>"""

    persona_cta = ""
    if persona_page_url.strip():
        safe_page = _html.escape(persona_page_url.strip())
        persona_cta = f"""
      <p style="margin:0 0 24px;">
        <a href="{safe_page}" style="display:inline-block;padding:10px 22px;background:#F5F0EB;color:#1C1917;text-decoration:none;border-radius:8px;font-weight:600;font-size:14px;">Visit {_html.escape(persona_name)}'s page</a>
      </p>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_html.escape(subject)}</title></head>
<body style="margin:0;padding:0;background:#F7F5F2;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;background:#F7F5F2;">
    <tr><td style="padding:40px 20px;">
      <table role="presentation" cellpadding="0" cellspacing="0" style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;">
        <tr><td style="padding:36px 36px 28px;">
          <p style="margin:0 0 20px;font-size:15px;color:#1C1917;line-height:1.6;">{greeting}</p>
          <p style="margin:0 0 16px;font-size:15px;color:#1C1917;line-height:1.6;">
            Thanks for chatting — we've received your contact info from {intent_phrase}.
            <strong>{_html.escape(persona_name)}</strong> will follow up with you directly within 1 business day.
          </p>
          {booking_cta}
          {persona_cta}
          <p style="margin:24px 0 0;font-size:13px;color:#A8A29E;line-height:1.5;">
            You're receiving this because you shared your contact info on {_html.escape(persona_name)}'s page.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
    return {"subject": subject, "html": html}


def enqueue_visitor_confirmation(
    *,
    twin_id: str,
    lead_id: str,
    visitor_email: str,
    visitor_name: str,
    inferred_intent: str | None,
    frontend_url: str,
) -> str | None:
    """Best-effort: send visitor a receipt email after contact info is captured.

    Fetches persona name, handle, and booking_url from the twin record so the
    caller (capture_tools) doesn't need to pass them. Uses graph_outbox for
    durability and idempotent dedup — safe to call multiple times for same lead.
    """
    from modules.graph_outbox import GraphOperationType, get_graph_outbox
    from modules.observability import get_supabase_client

    if not visitor_email or not visitor_email.strip():
        return None

    sb = get_supabase_client()
    twin_resp = (
        sb.table("twins")
        .select("name,settings,tenant_id")
        .eq("id", twin_id)
        .maybe_single()
        .execute()
    )
    twin = twin_resp.data or {}
    tenant_id = str(twin.get("tenant_id") or "").strip()
    if not tenant_id:
        return None
    persona_name = str(twin.get("name") or "").strip() or "your contact"
    settings = twin.get("settings") or {}
    widget_ui = settings.get("widget_ui") or {}
    persona_handle = str(settings.get("handle") or "").strip()
    booking_url: str | None = str(widget_ui.get("booking_url") or "").strip() or None

    persona_page_url = f"{frontend_url.rstrip('/')}/p/{persona_handle}" if persona_handle else ""
    idempotency_key = f"visitor_confirmation:{lead_id}"

    return get_graph_outbox().submit(
        tenant_id=tenant_id,
        twin_id=twin_id,
        operation=GraphOperationType.SEND_LIFECYCLE_EMAIL,
        idempotency_key=idempotency_key,
        payload={
            "email_type": VISITOR_CONFIRMATION,
            "visitor_recipient_email": visitor_email.strip(),
            "persona_name": persona_name,
            "persona_handle": persona_handle,
            "visitor_name": visitor_name,
            "inferred_intent": inferred_intent,
            "persona_page_url": persona_page_url,
            "booking_url": booking_url,
            "frontend_url": frontend_url,
            "scope_id": lead_id,
        },
        priority=5,
    )
