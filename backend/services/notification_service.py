"""
Phase 28: Proactive Notifications — Notification Service

Provides:
  - load_notification_prefs: Read twin notification preferences with safe defaults
  - claim_notification_slot: Atomic dedup guard for meeting notifications
  - generate_briefing: Generate pre-meeting briefing content via Gemini
  - _get_user_email: Resolve user email from tenant_id
"""

import logging
from datetime import date, datetime, timezone

from services.llm_budget import run_with_budget

logger = logging.getLogger(__name__)

MIN_KB_CHUNKS_FOR_BRIEFING = 2
MIN_MEETINGS_FOR_DIGEST = 3


def load_notification_prefs(twin_id: str) -> dict:
    """Load meeting notification preferences for a twin. Defaults all to True."""
    from modules.observability import supabase
    resp = supabase.table("twins").select("settings").eq("id", twin_id).single().execute()
    settings = (resp.data or {}).get("settings") or {}
    prefs = settings.get("meeting_notifications") or {}
    return {
        "pre_meeting": prefs.get("pre_meeting", True),
        "post_meeting": prefs.get("post_meeting", True),
        "weekly_digest": prefs.get("weekly_digest", True),
    }


def claim_notification_slot(
    twin_id: str,
    meeting_id: str | None,
    notification_type: str,
    tenant_id: str,
    week_of: date | str | None = None,
) -> bool:
    """Atomic dedup guard: returns True if this caller claimed the slot (first sender).

    Uses upsert with ignore_duplicates=True. If a row already exists for
    (twin_id, meeting_id, notification_type), the upsert is ignored and
    data will be empty, indicating the slot was already claimed.
    """
    from modules.observability import supabase
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    try:
        payload = {
            "twin_id": twin_id,
            "meeting_id": meeting_id,
            "tenant_id": tenant_id,
            "notification_type": notification_type,
            "status": "sending",
            "created_at": now_iso,
        }
        on_conflict = "twin_id,meeting_id,notification_type"
        if notification_type == "weekly_digest":
            if week_of is None:
                now = datetime.now(timezone.utc).date()
                week_of = now.fromordinal(now.toordinal() - now.weekday())
            payload["week_of"] = week_of.isoformat() if hasattr(week_of, "isoformat") else str(week_of)
            on_conflict = "twin_id,notification_type,week_of"

        resp = supabase.table("meeting_notifications").upsert(
            payload,
            on_conflict=on_conflict,
            ignore_duplicates=True,
        ).execute()
        return bool(resp.data)
    except Exception as exc:
        logger.warning("[NotificationGuard] dedup check failed: %s", exc)
        return False


def release_notification_slot(
    twin_id: str,
    meeting_id: str | None,
    notification_type: str,
    tenant_id: str,
) -> None:
    """Roll back a claimed slot — only if still in 'sending' state.

    The claim_notification_slot guards against double-send by inserting a row
    with status='sending' before any work begins. If the work then fails
    (e.g., generate_brief raises), a naive retry will see the row already
    exists and skip — leaving the user without an email.

    This releases the slot ONLY while status is still 'sending'. If the
    email was actually sent (status='sent'), this is a no-op so we never
    nuke a real send record.

    tenant_id is REQUIRED for defense-in-depth: matches the claim_slot
    scope. Prevents any future user-facing caller from accidentally
    deleting another tenant's notification rows by passing only
    twin_id/meeting_id.
    """
    from modules.observability import supabase

    try:
        supabase.table("meeting_notifications").delete().eq(
            "twin_id", twin_id
        ).eq("meeting_id", meeting_id).eq(
            "notification_type", notification_type
        ).eq("tenant_id", tenant_id).eq("status", "sending").execute()
    except Exception as exc:
        logger.warning(
            "[NotificationGuard] release slot failed twin=%s meeting=%s type=%s: %s",
            twin_id, meeting_id, notification_type, exc,
        )


def _get_user_email(tenant_id: str) -> str | None:
    """Resolve user email from tenant (user) ID."""
    from modules.observability import supabase
    resp = supabase.table("users").select("email").eq("id", tenant_id).single().execute()
    return (resp.data or {}).get("email")


def _extract_attendee_display_names(attendees_json: object) -> list[str]:
    """Extract human-readable attendee names from ``attendees_json``.

    The canonical column shape is a JSON array of dicts with at minimum
    ``email`` and (usually) ``displayName`` / ``name``. We also accept plain
    strings for legacy / partial rows. Returns an empty list on any other
    shape — never raises.
    """
    if not isinstance(attendees_json, list):
        return []
    out: list[str] = []
    for a in attendees_json:
        if isinstance(a, dict):
            name = (
                (a.get("displayName") or a.get("name") or a.get("email") or "")
                .strip()
            )
            if name:
                out.append(name)
        elif isinstance(a, str):
            s = a.strip()
            if s:
                out.append(s)
    return out


def _load_persona_profile(twin_id: str) -> str:
    """Load the twin's persona profile text from settings."""
    from modules.observability import supabase
    resp = supabase.table("twins").select("settings,name").eq("id", twin_id).single().execute()
    data = resp.data or {}
    settings = data.get("settings") or {}
    return settings.get("persona_profile", "")


def _render_brief_json_as_email_context(brief_json: dict) -> str:
    """Render structured brief_json into a plain-text block for the email body.

    Mirrors the W9c UI section order: talking points -> suggested agenda ->
    open items from last meeting -> commitments owed. Each section is
    omitted when empty.
    """
    sections: list[str] = []

    talking = brief_json.get("talking_points") or []
    if talking:
        sections.append("Talking points to lead with:\n" + "\n".join(
            f"  - {tp.get('topic', '')} ({tp.get('rationale', '')})"
            for tp in talking
            if tp.get("topic")
        ))

    agenda = brief_json.get("suggested_agenda") or []
    if agenda:
        sections.append("Suggested agenda:\n" + "\n".join(
            f"  {i + 1}. {item}" for i, item in enumerate(agenda)
        ))

    commitments = brief_json.get("open_commitments") or []
    if commitments:
        sections.append("Still open from your end:\n" + "\n".join(
            f"  - {c.get('description', '')} ({c.get('days_open', 0)} days open)"
            for c in commitments
            if c.get("description")
        ))

    prior = brief_json.get("previous_interactions") or []
    if prior:
        section = "From your last meeting(s):"
        for p in prior[:2]:
            date = p.get("date") or "?"
            title = p.get("meeting_title") or "Meeting"
            summary = (p.get("summary") or "")[:200]
            section += f"\n  [{date}] {title}: {summary}"
            for item in (p.get("open_items") or [])[:2]:
                # Cap each item at 150 chars — open_items can be LLM-generated
                # paragraphs and uncapped output bloats the email body.
                item_text = str(item)[:150]
                section += f"\n     • Open: {item_text}"
        sections.append(section)

    return "\n\n".join(sections) if sections else ""


async def build_briefing_email_from_brief_json(
    *,
    brief_json: dict,
    meeting: dict,
    twin_id: str,
) -> dict | None:
    """Format a pre-meeting briefing email from a v2 brief_json.

    Replaces the legacy ``generate_briefing()`` LLM path. Single source of
    truth: whatever ``persona_core.brief.generate_brief()`` produced, this
    function renders. No extra Gemini call.

    Returns ``{"subject": str, "html": str}`` on success, or ``None`` when
    the brief is too sparse to be worth emailing.
    """
    title = brief_json.get("meeting_title") or meeting.get("title") or "Untitled Meeting"
    attendees = _extract_attendee_display_names(meeting.get("attendees_json"))

    context_text = _render_brief_json_as_email_context(brief_json)
    if not context_text:
        # Truly nothing useful — skip the email rather than send "you have a meeting".
        logger.info(
            "[Briefing] brief too sparse to email twin=%s meeting=%s",
            twin_id,
            brief_json.get("meeting_id") or meeting.get("id"),
        )
        return None

    persona_name = _load_persona_name(twin_id)

    from services.email_service import build_briefing_html

    html = build_briefing_html(
        title=title,
        attendees=attendees,
        context=context_text,
        persona_name=persona_name,
    )
    return {"subject": f"Briefing: {title}", "html": html}


def _load_persona_name(twin_id: str) -> str:
    """Twin name for the email header. Falls back to empty string on miss."""
    from modules.observability import supabase

    try:
        resp = supabase.table("twins").select("name").eq("id", twin_id).single().execute()
        return (resp.data or {}).get("name") or ""
    except Exception as exc:
        # Don't fail the email send for a header decoration — but DO log so
        # repeated failures show up in alerts (project rule: never swallow).
        logger.warning(
            "[Briefing] persona name lookup failed twin=%s: %s",
            twin_id, exc,
        )
        return ""


async def generate_briefing(*, meeting: dict, twin_id: str) -> dict | None:
    """Generate pre-meeting briefing content.

    Returns a dict with {subject, html} when sufficient KB context exists,
    or None when fewer than MIN_KB_CHUNKS_FOR_BRIEFING chunks are found.

    Args:
        meeting: Meeting record dict with id, title, attendees keys
        twin_id: Twin ID to search KB for

    Returns:
        {subject: str, html: str} or None
    """
    from adk_core.services.vector_store import search as kb_search

    title = meeting.get("title") or "Untitled Meeting"
    # Canonical column is attendees_json (list of {email, displayName, name, ...}
    # dicts). The prior `meeting.get("attendees")` read returned None on every
    # row, so briefings shipped with empty attendee context. See
    # docs/superpowers/plans/2026-05-21-w9a-schema-unification.md (Task 8).
    attendees = _extract_attendee_display_names(meeting.get("attendees_json"))

    # Query KB for context relevant to this meeting
    query = f"meeting with {', '.join(attendees[:5])} about {title}"
    chunks = await kb_search(query=query, twin_id=twin_id, top_k=5)

    if len(chunks) < MIN_KB_CHUNKS_FOR_BRIEFING:
        logger.info(
            "[Briefing] insufficient KB context meeting=%s chunks=%d",
            meeting.get("id"),
            len(chunks),
        )
        return None

    context = "\n".join(c.get("text", "") for c in chunks)
    persona_profile = _load_persona_profile(twin_id)

    # Generate briefing via Gemini
    from services.meeting_analyzer import _get_genai_client, _strip_markdown_fences
    client = _get_genai_client()
    prompt = f"""You are writing a pre-meeting briefing email on behalf of a professional.
Write in their voice based on this profile:
{persona_profile}

Meeting: {title}
Attendees: {', '.join(attendees)}
Relevant context from their knowledge base:
{context}

Write a concise pre-meeting briefing (150-250 words) they would send themselves."""

    response = await run_with_budget(
        tenant_id=twin_id,
        operation="notif_subject",
        user_id=twin_id,
        model="gemini-2.0-flash",
        call=lambda: client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        ),
    )
    body_text = _strip_markdown_fences(response.text or "")

    from services.email_service import build_briefing_html
    html = build_briefing_html(
        title=title,
        attendees=attendees,
        context=body_text,
        persona_name="",
    )

    return {"subject": f"Briefing: {title}", "html": html}


async def generate_digest(*, twin_id: str, meetings: list[dict]) -> dict | None:
    """Generate weekly digest email content.

    Aggregates executive summaries from the past week's meetings and composes
    a digest via Gemini in the twin's persona voice.

    Returns:
        {subject: str, html: str} or None if fewer than MIN_MEETINGS_FOR_DIGEST meetings.
    """
    if len(meetings) < MIN_MEETINGS_FOR_DIGEST:
        logger.info(
            "[Digest] insufficient meetings twin=%s count=%d",
            twin_id,
            len(meetings),
        )
        return None

    persona_profile = _load_persona_profile(twin_id)

    # Aggregate meeting summaries and action items
    meeting_summaries: list[str] = []
    action_items_all: list[str] = []
    for m in meetings:
        sj = m.get("summary_json") or {}
        summary = (
            sj.get("executive_summary")
            or sj.get("summary")
            or m.get("summary")
            or ""
        )
        title = m.get("title") or "Untitled"
        meeting_summaries.append(f"- {title}: {summary[:200]}")
        action_items_all.extend(sj.get("action_items") or [])

    from services.meeting_analyzer import _get_genai_client, _strip_markdown_fences
    client = _get_genai_client()
    prompt = f"""You are writing a weekly meeting digest email on behalf of a professional.
Write in their voice based on this profile:
{persona_profile}

This week's meetings ({len(meetings)} total):
{chr(10).join(meeting_summaries)}

Key action items across all meetings:
{chr(10).join(str(a) for a in action_items_all[:20])}

Write a concise weekly digest (200-400 words) summarising key themes, decisions, and next steps."""

    response = await run_with_budget(
        tenant_id=twin_id,
        operation="notif_body",
        user_id=twin_id,
        model="gemini-2.0-flash",
        call=lambda: client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        ),
    )
    digest_text = _strip_markdown_fences(response.text or "")

    from services.email_service import build_digest_html
    html = build_digest_html(
        meeting_count=len(meetings),
        meetings=[
            {
                "title": m.get("title", ""),
                "summary": (m.get("summary_json") or {}).get("executive_summary", ""),
            }
            for m in meetings
        ],
        persona_name="",
        digest_body=digest_text,
    )

    week_str = datetime.now(timezone.utc).strftime("%b %d")
    return {"subject": f"Weekly Digest — Week of {week_str}", "html": html}


async def generate_followup(*, meeting: dict, twin_id: str) -> dict | None:
    """Generate post-meeting follow-up draft email in the twin's persona voice.

    Reads summary_json from the meeting record, calls Gemini to compose a
    follow-up email, and returns {subject, html}. Returns None when no
    executive summary is available.

    Args:
        meeting: Meeting record dict with id, title, summary_json keys
        twin_id: Twin ID whose persona profile is used for tone

    Returns:
        {subject: str, html: str} or None
    """
    title = meeting.get("title") or "Untitled Meeting"
    summary_json = meeting.get("summary_json") or {}
    summary_text = (
        summary_json.get("executive_summary")
        or summary_json.get("summary")
        or ""
    )
    action_items = summary_json.get("action_items") or []

    if not summary_text:
        logger.info(
            "[Followup] no summary_json for meeting=%s", meeting.get("id")
        )
        return None

    persona_profile = _load_persona_profile(twin_id)

    from services.meeting_analyzer import _get_genai_client, _strip_markdown_fences
    client = _get_genai_client()
    prompt = f"""You are writing a post-meeting follow-up email on behalf of a professional.
Write in their voice based on this profile:
{persona_profile}

Meeting: {title}
Summary: {summary_text}
Action Items: {', '.join(str(a) for a in action_items)}

Write a concise follow-up email (150-300 words) that recaps key points and lists next steps.
Write as if sending to meeting attendees."""

    response = await run_with_budget(
        tenant_id=twin_id,
        operation="notif_digest",
        user_id=twin_id,
        model="gemini-2.0-flash",
        call=lambda: client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        ),
    )
    body_text = _strip_markdown_fences(response.text or "")

    from services.email_service import build_followup_html
    html = build_followup_html(
        title=title,
        action_items=[str(a) for a in action_items],
        summary=body_text,
    )

    return {"subject": f"Follow-up: {title}", "html": html}
