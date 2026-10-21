"""
Meeting Intelligence Router — Phase 25

Endpoints:
  POST /v2/meetings/webhook/recall   — Recall.ai webhook (NOT feature-flagged)
  GET  /v2/meetings/{twin_id}        — List meetings for a twin (feature-flagged)
  GET  /v2/meetings/{twin_id}/{id}   — Meeting detail + transcript (feature-flagged)
"""

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from modules.graph_outbox import GraphOperationType, get_graph_outbox
from modules.observability import supabase
from modules.telemetry import get_tracer
from services.recall_auth import verify_recall_webhook

logger = logging.getLogger(__name__)
_brief_tracer = get_tracer("brief")

router = APIRouter(tags=["meetings"])

MEETING_INTELLIGENCE_ENABLED = (
    os.getenv("MEETING_INTELLIGENCE_ENABLED", "false").lower() == "true"
)

# ---------------------------------------------------------------------------
# Feature flag dependency — REST endpoints only (webhook is always open)
# ---------------------------------------------------------------------------

def _require_meeting_intelligence() -> None:
    if not MEETING_INTELLIGENCE_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")


# ---------------------------------------------------------------------------
# HMAC verification (Svix standard used by Recall.ai)
# ---------------------------------------------------------------------------

# verify_recall_webhook imported from services.recall_auth


# ---------------------------------------------------------------------------
# Webhook endpoint — NOT gated by feature flag
# ---------------------------------------------------------------------------

@router.post("/v2/meetings/webhook/recall")
async def recall_webhook(request: Request) -> dict[str, str]:
    """Receive Recall.ai bot lifecycle events and dispatch graph_outbox jobs."""
    body = await request.body()
    webhook_id = request.headers.get("webhook-id", "")
    webhook_timestamp = request.headers.get("webhook-timestamp", "")
    webhook_signature = request.headers.get("webhook-signature", "")

    if not verify_recall_webhook(body, webhook_id, webhook_timestamp, webhook_signature):
        logger.warning("[MeetingWebhook] invalid signature webhook_id=%s", webhook_id)
        raise HTTPException(status_code=401, detail="Invalid signature")

    data: dict[str, Any] = json.loads(body)
    event = data.get("event", "")
    # Payload shape: {"event": "...", "data": {"bot": {"id": "..."}, "data": {...}}}
    bot_data = (data.get("data") or {}).get("bot") or {}
    bot_id = str(bot_data.get("id") or "")

    logger.info("[MeetingWebhook] event=%s bot_id=%s", event, bot_id)

    if event == "bot.done":
        # Look up meeting by recall_bot_id to get twin/tenant context
        resp = (
            supabase.table("meetings")
            .select("id,twin_id,tenant_id")
            .eq("recall_bot_id", bot_id)
            .limit(1)
            .execute()
        )
        if resp.data:
            meeting = resp.data[0]
            meeting_id = meeting["id"]

            # Flush ADK transcript to DB before the worker runs.
            # For native audio bots there is no Recall STT transcript — Gemini
            # accumulates it in-memory. teardown_session writes transcript_text +
            # transcript_raw + duration_seconds so the downstream worker can skip
            # the Recall API fetch and go straight to summary generation.
            try:
                from services import meeting_adk_session as _session_mgr
                await _session_mgr.teardown_session(meeting_id, reason="bot.done")
            except Exception as _te:
                logger.warning(
                    "[MeetingWebhook] teardown_session failed meeting=%s: %s",
                    meeting_id, _te,
                )

            outbox = get_graph_outbox()
            outbox.submit(
                tenant_id=meeting["tenant_id"],
                twin_id=meeting["twin_id"],
                operation=GraphOperationType.PROCESS_MEETING_TRANSCRIPT,
                idempotency_key=f"meeting_transcript:{bot_id}",
                payload={"bot_id": bot_id, "meeting_id": meeting_id},
                priority=5,
            )
            logger.info(
                "[MeetingWebhook] enqueued transcript job meeting=%s bot=%s",
                meeting_id, bot_id,
            )

            # Phase 30-K: resolve diarization labels (speaker_0, speaker_1, ...)
            # to person nodes using Recall's participant list. Runs in parallel
            # with the transcript worker — they touch different tables.
            outbox.submit(
                tenant_id=meeting["tenant_id"],
                twin_id=meeting["twin_id"],
                operation=GraphOperationType.RESOLVE_MEETING_SPEAKERS,
                idempotency_key=f"resolve_speakers:{bot_id}",
                payload={
                    "bot_id": bot_id,
                    "meeting_id": meeting_id,
                    "twin_id": meeting["twin_id"],
                    "tenant_id": meeting["tenant_id"],
                },
                priority=6,
            )
            logger.info(
                "[MeetingWebhook] enqueued speaker resolution meeting=%s bot=%s",
                meeting_id, bot_id,
            )
        else:
            logger.warning("[MeetingWebhook] no meeting found for bot_id=%s", bot_id)

    elif event in ("bot.joining_call", "bot.in_call_recording", "bot.call_ended"):
        status_map = {
            "bot.joining_call": "bot_joining",
            "bot.in_call_recording": "recording",
            "bot.call_ended": "processing",
        }
        new_status = status_map[event]
        supabase.table("meetings").update({"status": new_status}).eq(
            "recall_bot_id", bot_id
        ).execute()
        logger.info("[MeetingWebhook] status update bot=%s status=%s", bot_id, new_status)

        if event == "bot.joining_call":
            meeting_resp = (
                supabase.table("meetings")
                .select("id, twin_id, tenant_id")
                .eq("recall_bot_id", bot_id)
                .limit(1)
                .execute()
            )
            if meeting_resp.data:
                m = meeting_resp.data[0]
                get_graph_outbox().submit(
                    tenant_id=m["tenant_id"],
                    twin_id=m["twin_id"],
                    operation=GraphOperationType.PREP_MEETING_CONTEXT,
                    idempotency_key=f"prep_meeting_context:{bot_id}",
                    payload={"meeting_id": m["id"], "twin_id": m["twin_id"]},
                    priority=8,
                )
                logger.info(
                    "[MeetingWebhook] enqueued PREP_MEETING_CONTEXT meeting=%s", m["id"]
                )

    elif event == "bot.fatal":
        supabase.table("meetings").update({"status": "failed"}).eq(
            "recall_bot_id", bot_id
        ).execute()
        logger.warning("[MeetingWebhook] bot fatal bot=%s", bot_id)

    # -----------------------------------------------------------------
    # Desktop SDK upload events (Layer 1)
    # Payload shape: {"event":"sdk_upload.complete","data":{"recording":{"id":...},"sdk_upload":{"id":...}}}
    # -----------------------------------------------------------------
    elif event.startswith("sdk_upload."):
        sdk_payload = (data.get("data") or {})
        sdk_upload = sdk_payload.get("sdk_upload") or {}
        recording = sdk_payload.get("recording") or {}
        sdk_upload_id = str(sdk_upload.get("id") or "")
        recording_id = str(recording.get("id") or "")

        logger.info(
            "[MeetingWebhook] sdk_upload event=%s sdk_upload_id=%s recording_id=%s",
            event, sdk_upload_id, recording_id,
        )

        if not sdk_upload_id:
            logger.warning("[MeetingWebhook] sdk_upload missing id, event=%s", event)
            return {"status": "ok"}

        # Locate the meetings row via recall_sdk_upload_id (set on POST /sdk-upload)
        row_resp = (
            supabase.table("meetings")
            .select("id,tenant_id,twin_id")
            .eq("recall_sdk_upload_id", sdk_upload_id)
            .limit(1)
            .execute()
        )
        if not row_resp.data:
            logger.warning(
                "[MeetingWebhook] no meeting found for sdk_upload_id=%s event=%s",
                sdk_upload_id, event,
            )
            return {"status": "ok"}

        meeting = row_resp.data[0]
        meeting_id = meeting["id"]
        meeting_tenant_id = meeting["tenant_id"]

        if event == "sdk_upload.uploading":
            # Dual-scope by id + tenant_id. HMAC gates the endpoint, but a
            # misrouted webhook (e.g. wrong Recall account env) MUST NOT be
            # able to flip another tenant's meeting row.
            supabase.table("meetings").update({"status": "uploading"}).eq(
                "id", meeting_id
            ).eq("tenant_id", meeting_tenant_id).execute()
            logger.warning(
                "[MeetingWebhook] sdk_upload uploading meeting=%s tenant=%s",
                meeting_id, meeting_tenant_id,
            )
        elif event == "sdk_upload.failed":
            error_detail = sdk_payload.get("error") or sdk_upload.get("status") or {}
            supabase.table("meetings").update({"status": "failed"}).eq(
                "id", meeting_id
            ).eq("tenant_id", meeting_tenant_id).execute()
            logger.warning(
                "[MeetingWebhook] sdk_upload failed meeting=%s tenant=%s error=%s",
                meeting_id, meeting_tenant_id, error_detail,
            )
        elif event == "sdk_upload.complete":
            if not recording_id:
                logger.warning(
                    "[MeetingWebhook] sdk_upload.complete missing recording_id meeting=%s",
                    meeting_id,
                )
                return {"status": "ok"}

            # Enqueue FIRST, then bump status to 'processing' on success. This
            # avoids the row getting stuck at 'processing' when the queue is
            # unreachable: if enqueue raises, status stays at 'uploading' so
            # Recall's retry of sdk_upload.complete (8 attempts over 5 days)
            # gets another chance.
            twin_id_for_job = meeting.get("twin_id") or f"desktop:{meeting['tenant_id']}"
            try:
                get_graph_outbox().submit(
                    tenant_id=meeting["tenant_id"],
                    twin_id=twin_id_for_job,
                    operation=GraphOperationType.PROCESS_DESKTOP_SDK_RECORDING,
                    idempotency_key=f"desktop_sdk_recording:{recording_id}",
                    payload={
                        "recall_recording_id": recording_id,
                        "meeting_id": meeting_id,
                        "tenant_id": meeting["tenant_id"],
                    },
                    priority=5,
                )
            except Exception:
                logger.exception(
                    "[MeetingWebhook] enqueue failed meeting=%s recording_id=%s — leaving status untouched for retry",
                    meeting_id, recording_id,
                )
                # Return ok so Recall doesn't retry-storm us, but we'll handle the
                # retry on the next sdk_upload.complete delivery (Recall sends 8).
                return {"status": "ok"}

            # PR #181 follow-up: dual-scope this UPDATE the same way as the
            # .uploading and .failed branches. PR #181 missed this branch on
            # the FIRST pass -- caught by the 2026-05-31 second-pass audit.
            supabase.table("meetings").update({"status": "processing"}).eq(
                "id", meeting_id
            ).eq("tenant_id", meeting_tenant_id).execute()
            logger.warning(
                "[MeetingWebhook] enqueued PROCESS_DESKTOP_SDK_RECORDING meeting=%s tenant=%s",
                meeting_id, meeting_tenant_id,
            )

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# REST endpoints — feature-flagged
# ---------------------------------------------------------------------------

def _get_current_user(request: Request) -> dict[str, Any]:
    """Extract authenticated user from request state or Authorization header."""
    from modules.auth_guard import authenticate_request, get_token_from_header, AuthenticationError

    user = getattr(request.state, "user", None)
    if user:
        return user

    authorization = request.headers.get("authorization", "")
    token = get_token_from_header(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        auth_context = authenticate_request(token)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    if not auth_context.get("tenant_id"):
        from modules.auth_guard import resolve_tenant_id
        import contextlib
        with contextlib.suppress(Exception):
            auth_context["tenant_id"] = resolve_tenant_id(
                user_id=auth_context.get("user_id"),
                email=auth_context.get("email"),
                create_if_missing=False,
            )

    return auth_context


@router.get(
    "/v2/meetings/{twin_id}",
    dependencies=[Depends(_require_meeting_intelligence)],
)
async def list_meetings(twin_id: str, request: Request) -> dict[str, Any]:
    """List meetings for a twin, ordered by meeting_start desc."""
    user = _get_current_user(request)
    tenant_id = user.get("tenant_id") or user.get("id")

    # Ownership check: twin must belong to this tenant
    twin_check = (
        supabase.table("twins")
        .select("id")
        .eq("id", twin_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    if not twin_check.data:
        raise HTTPException(status_code=403, detail="Forbidden")

    resp = (
        supabase.table("meetings")
        .select(
            "id,title,status,meet_link,meeting_start,meeting_end,"
            "duration_seconds,summary,created_at,twin_attends,recall_bot_id,"
            "attendees_json"
        )
        .eq("twin_id", twin_id)
        .eq("tenant_id", tenant_id)
        .order("meeting_start", desc=True)
        .limit(50)
        .execute()
    )
    return {"status": "ok", "data": resp.data or []}


@router.get(
    "/v2/meetings/{twin_id}/threads",
    dependencies=[Depends(_require_meeting_intelligence)],
)
async def list_meeting_threads(twin_id: str, request: Request) -> dict[str, Any]:
    """Group meetings by attendee — one thread per unique person.

    Source: `attendees_json` on the meetings row (written by calendar sync from
    Recall's event data). Attendees with an email are grouped by lowercased email;
    attendees with only a name fall back to name match. Twin owner is filtered
    out of attendee groupings.

    Returns up to 50 threads sorted by `last_met_at DESC`, each with up to 5
    meetings sorted by `created_at DESC`. Designed to be a single round-trip —
    no per-attendee SQL.
    """
    user = _get_current_user(request)
    tenant_id = user.get("tenant_id") or user.get("id")

    # Ownership check
    twin_check = (
        supabase.table("twins")
        .select("id")
        .eq("id", twin_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    if not twin_check.data:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Fetch recent meetings — we group client-side. 100 meetings cap; threads
    # over a longer horizon need either the meeting_speakers normalized table
    # (P1.3.A) or a SQL-level group-by.
    resp = (
        supabase.table("meetings")
        .select("id, title, attendees_json, organizer_email, meeting_start, created_at")
        .eq("twin_id", twin_id)
        .eq("tenant_id", tenant_id)
        .order("meeting_start", desc=True)
        .limit(100)
        .execute()
    )
    meetings_rows = resp.data or []

    threads: dict[str, dict[str, Any]] = {}

    for m in meetings_rows:
        attendees = m.get("attendees_json") or []
        if not isinstance(attendees, list):
            continue
        organizer_email = (m.get("organizer_email") or "").lower().strip() or None

        for a in attendees:
            if isinstance(a, dict):
                email = (a.get("email") or "").lower().strip() or None
                name = (a.get("displayName") or a.get("name") or "").strip() or None
            elif isinstance(a, str):
                email = None
                name = a.strip() or None
            else:
                continue

            # Skip blank entries and the organizer (twin owner)
            if not email and not name:
                continue
            if email and organizer_email and email == organizer_email:
                continue

            # Group key: email if present, else lowercased name
            key = email or (name or "").lower()
            if not key:
                continue

            entry = threads.get(key)
            if entry is None:
                entry = {
                    "person_email": email,
                    "person_name": name,
                    "meeting_count": 0,
                    "last_met_at": None,
                    "meetings": [],
                }
                threads[key] = entry

            # Prefer the most complete name (some events have email but no name)
            if name and not entry["person_name"]:
                entry["person_name"] = name

            entry["meeting_count"] += 1
            sort_ts = m.get("meeting_start") or m.get("created_at")
            if sort_ts and (entry["last_met_at"] is None or sort_ts > entry["last_met_at"]):
                entry["last_met_at"] = sort_ts
            if len(entry["meetings"]) < 5:
                entry["meetings"].append({
                    "id": m["id"],
                    "title": m.get("title"),
                    "meeting_start": m.get("meeting_start"),
                    "created_at": m.get("created_at"),
                })

    # Sort threads by last_met_at desc; cap at 50
    sorted_threads = sorted(
        threads.values(),
        key=lambda t: t["last_met_at"] or "",
        reverse=True,
    )[:50]

    # Attach person_node_id so the frontend can deep-link to /dashboard/people/{id}.
    # Single round-trip — match by lowercase email since the speaker resolver stored
    # emails via ILIKE-friendly properties->>email.
    thread_emails = [
        t["person_email"] for t in sorted_threads if t.get("person_email")
    ]
    if thread_emails:
        try:
            nodes_resp = (
                supabase.table("nodes")
                .select("id, name, properties")
                .eq("twin_id", twin_id)
                .eq("type", "person")
                .execute()
            )
            email_to_node: dict[str, str] = {}
            name_to_node: dict[str, str] = {}
            for n in nodes_resp.data or []:
                node_email = ((n.get("properties") or {}).get("email") or "").lower().strip()
                if node_email:
                    email_to_node.setdefault(node_email, n["id"])
                node_name = (n.get("name") or "").lower().strip()
                if node_name:
                    name_to_node.setdefault(node_name, n["id"])
            for t in sorted_threads:
                email_key = (t.get("person_email") or "").lower()
                name_key = (t.get("person_name") or "").lower()
                t["person_node_id"] = (
                    email_to_node.get(email_key)
                    or name_to_node.get(name_key)
                )
        except Exception as exc:
            logger.warning("[Threads] node id attach failed: %s", exc)
            for t in sorted_threads:
                t["person_node_id"] = None

    return {"status": "ok", "data": sorted_threads}


@router.get(
    "/v2/meetings/{twin_id}/search",
    dependencies=[Depends(_require_meeting_intelligence)],
)
async def search_meetings_endpoint(
    twin_id: str,
    q: str,
    top_k: int = 10,
    request: Request = None,
) -> dict[str, Any]:
    """Cross-meeting semantic search (MTG-17).

    Searches only meeting chunks for a twin. Requires MEETING_INTELLIGENCE_ENABLED.
    Returns text, score, meeting_id, speakers, start_time, end_time per result.
    """
    user = _get_current_user(request)
    tenant_id = user.get("tenant_id") or user.get("id")

    # Ownership check: twin must belong to this tenant
    twin_check = (
        supabase.table("twins")
        .select("id")
        .eq("id", twin_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    if not twin_check.data:
        raise HTTPException(status_code=403, detail="Forbidden")

    from adk_core.services.vector_store import search_meetings
    results = await search_meetings(query=q, twin_id=twin_id, top_k=min(top_k, 50))

    return {"status": "ok", "data": {"results": results, "query": q, "count": len(results)}}


@router.get(
    "/v2/meetings/{twin_id}/{meeting_id}",
    dependencies=[Depends(_require_meeting_intelligence)],
)
async def get_meeting(twin_id: str, meeting_id: str, request: Request) -> dict[str, Any]:
    """Get meeting detail including transcript and participants."""
    user = _get_current_user(request)
    tenant_id = user.get("tenant_id") or user.get("id")

    resp = (
        supabase.table("meetings")
        .select("*")
        .eq("id", meeting_id)
        .eq("twin_id", twin_id)
        .eq("tenant_id", tenant_id)
        # maybe_single (not single): a meeting you don't own is filtered out by the
        # tenant_id predicate, leaving 0 rows. single() RAISES on 0 rows → bubbles up
        # as a 500; maybe_single() returns data=None so the 404 below fires cleanly.
        .maybe_single()
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Meeting not found")

    parts = (
        supabase.table("meeting_participants")
        .select("*")
        .eq("meeting_id", meeting_id)
        .execute()
    )

    analytics = (
        supabase.table("meeting_analytics")
        .select(
            "participant_name,talk_time_seconds,talk_time_pct,word_count,"
            "words_per_minute,filler_word_count,sentiment_label,sentiment_score"
        )
        .eq("meeting_id", meeting_id)
        .execute()
    )

    twin_responses = (
        supabase.table("meeting_twin_responses")
        .select("turn_seq,question_text,response_text,confidence,sources,is_deferral,responded_at")
        .eq("meeting_id", meeting_id)
        .order("turn_seq")
        .execute()
    )

    return {
        "status": "ok",
        "data": {
            **resp.data,
            "participants": parts.data or [],
            "analytics": analytics.data or [],
            "twin_responses": twin_responses.data or [],
        },
    }


class UpdateMeetingRequest(BaseModel):
    """Updatable fields on a meeting row owned by the authenticated tenant.

    Empty string ("") and whitespace-only values are coerced to NULL after
    trim+cap — this is the intended "clear the field" semantic. Clients that
    want to no-op should omit the field entirely (it's optional in the body).

    user_goal: 1-line intent statement, max 500 chars after trim. NULL clears.
    user_context: free-text background, max 5000 chars after trim. NULL clears.
    """
    user_goal: str | None = None
    user_context: str | None = None


@router.patch(
    "/v2/meetings/{twin_id}/{meeting_id}",
    dependencies=[Depends(_require_meeting_intelligence)],
)
async def update_meeting(
    twin_id: str,
    meeting_id: str,
    body: UpdateMeetingRequest,
    request: Request,
) -> dict[str, Any]:
    """Update the user-stated goal + context for a meeting. Tenant-scoped."""
    user = _get_current_user(request)
    tenant_id = user.get("tenant_id") or user.get("id")

    update_payload: dict[str, Any] = {}
    if body.user_goal is not None:
        # Trim and cap length to defend against accidental dumps
        update_payload["user_goal"] = body.user_goal.strip()[:500] or None
    if body.user_context is not None:
        update_payload["user_context"] = body.user_context.strip()[:5000] or None

    if not update_payload:
        # Nothing to update — return current row
        existing = (
            supabase.table("meetings")
            .select("id, user_goal, user_context")
            .eq("id", meeting_id)
            .eq("twin_id", twin_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()  # 0 rows (not owned) → None → clean 404, not a 500
            .execute()
        )
        if not existing.data:
            raise HTTPException(status_code=404, detail="Meeting not found")
        return {"status": "ok", "data": existing.data}

    # Tenant-scoped UPDATE (defense per feedback_tenant_scope_mutations.md)
    update_payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    resp = (
        supabase.table("meetings")
        .update(update_payload)
        .eq("id", meeting_id)
        .eq("twin_id", twin_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )

    if not resp.data:
        raise HTTPException(status_code=404, detail="Meeting not found")

    logger.info(
        "[Meetings] updated user intent meeting=%s twin=%s fields=%s",
        meeting_id, twin_id, list(update_payload.keys()),
    )

    return {"status": "ok", "data": resp.data[0]}


# ---------------------------------------------------------------------------
# Pre-meeting brief — P1.2
# ---------------------------------------------------------------------------


def _enqueue_brief_email(
    *,
    user_id: str,
    user_email: str,
    tenant_id: str,
    twin_id: str,
    meeting_id: str,
    brief: dict[str, Any],
) -> None:
    """Best-effort enqueue of the meeting_brief_ready lifecycle email.

    Called when a brief is generated lazily for the first time. The 15-min
    scheduled delivery is P1.2.1; for now the email goes out at first-view
    so users still get the "we briefed you" loop.
    """
    if not user_email or not user_id:
        return
    person = brief.get("person") or {}
    person_name = (person.get("name") or "").strip() or "your meeting"
    subject = f"Brief for your meeting with {person_name}"
    cta_path = f"/dashboard/meetings/{meeting_id}/brief"

    try:
        get_graph_outbox().submit(
            tenant_id=tenant_id,
            twin_id=twin_id,
            operation=GraphOperationType.SEND_LIFECYCLE_EMAIL,
            idempotency_key=f"meeting_brief_ready:{meeting_id}",
            payload={
                "user_id": user_id,
                "tenant_id": tenant_id,
                "twin_id": twin_id,
                "recipient_email": user_email,
                "email_type": "meeting_brief_ready",
                "category": "meeting_brief",
                "scope_type": "meeting",
                "scope_id": meeting_id,
                "period_key": "once",
                "payload": {
                    "subject": subject,
                    "cta_path": cta_path,
                    "meeting_id": meeting_id,
                    "meeting_title": brief.get("meeting_title") or "Meeting",
                    "meeting_start": brief.get("meeting_start"),
                    "person": person,
                    "hooks": brief.get("hooks") or [],
                    "open_commitments": brief.get("open_commitments") or [],
                },
            },
        )
        logger.info(
            "[Meetings] brief email enqueued meeting=%s", meeting_id
        )
    except Exception as exc:
        logger.warning(
            "[Meetings] brief email enqueue failed meeting=%s: %s",
            meeting_id, exc,
        )


@router.get(
    "/v2/meetings/{twin_id}/{meeting_id}/brief",
    dependencies=[Depends(_require_meeting_intelligence)],
)
async def get_meeting_brief(
    twin_id: str,
    meeting_id: str,
    request: Request,
) -> dict[str, Any]:
    """Return the pre-meeting brief, generating it lazily on first hit.

    Tenant-scoped on the initial SELECT and on the UPDATE that persists the
    generated brief (defense per feedback_tenant_scope_mutations.md).
    """
    user = _get_current_user(request)
    tenant_id = user.get("tenant_id") or user.get("id")

    meeting_resp = (
        supabase.table("meetings")
        .select("*")
        .eq("id", meeting_id)
        .eq("twin_id", twin_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    meeting = meeting_resp.data if meeting_resp else None
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # v2 schema invalidation: if the flag is on AND the cached brief is
    # below v2 (or has no schema_version), regenerate instead of returning
    # stale. Without this, users with pre-flag-flip briefs are frozen on
    # v1 forever and the W9c UI would render undefined for missing v2
    # fields. NOTE: comparison is `< 2`, not `!= 2`, so a future v3 brief
    # isn't silently DOWNGRADED to v2 by this handler.
    from adk_core.services.persona_core.brief import _schema_v2_enabled
    existing = meeting.get("brief_json")
    if existing:
        cached_version_raw = (
            existing.get("schema_version") if isinstance(existing, dict) else None
        )
        try:
            cached_version = int(cached_version_raw) if cached_version_raw is not None else 0
        except (TypeError, ValueError):
            cached_version = 0
        v2_on = _schema_v2_enabled()
        if v2_on and cached_version < 2:
            logger.info(
                "[Meetings] invalidating pre-v2 brief cache meeting=%s twin=%s cached_version=%s",
                meeting_id, twin_id, cached_version,
            )
        else:
            return {"status": "ok", "data": existing}

    # Lazy generation. Brief engine degrades gracefully on PDL/Gemini
    # failures; only crash if the meeting row itself goes missing mid-flight.
    try:
        from adk_core.services.persona_core.brief import generate_brief
        brief = await generate_brief(
            twin_id=twin_id,
            meeting_id=meeting_id,
            meeting=meeting,
            self_email=user.get("email"),
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.exception(
            "[Meetings] brief generation failed meeting=%s: %s",
            meeting_id, exc,
        )
        raise HTTPException(status_code=500, detail="Could not generate brief") from exc

    now_iso = datetime.now(timezone.utc).isoformat()
    with _brief_tracer.start_as_current_span("brief.persist") as span:
        span.set_attribute("meeting.id", meeting_id)
        span.set_attribute("twin.id", twin_id)
        try:
            supabase.table("meetings").update({
                "brief_json": brief,
                "brief_generated_at": now_iso,
            }).eq("id", meeting_id).eq("twin_id", twin_id).eq("tenant_id", tenant_id).execute()
            span.set_attribute("brief.persist.success", True)
        except Exception as exc:
            # Persist failure shouldn't block the response — the brief is still
            # valid; next request will re-generate. Span attribute records
            # only the exception CLASS (not message) — Supabase/PostgREST
            # exception text can embed table names, constraint names, or
            # row values which would leak to whatever OTEL endpoint is
            # configured. The full exception goes to the structured log
            # which has tighter access controls.
            span.set_attribute("brief.persist.success", False)
            span.set_attribute("brief.persist.error_class", type(exc).__name__)
            logger.warning(
                "[Meetings] brief persist failed meeting=%s: %s",
                meeting_id, exc,
            )

    # Best-effort first-view email enqueue (P1.2.1 will move this to scheduler).
    try:
        owner_email = (user.get("email") or "").strip()
        owner_user_id = str(user.get("user_id") or user.get("id") or "").strip()
        _enqueue_brief_email(
            user_id=owner_user_id,
            user_email=owner_email,
            tenant_id=str(tenant_id),
            twin_id=twin_id,
            meeting_id=meeting_id,
            brief=brief,
        )
    except Exception as exc:  # noqa: BLE001 — defensive: never block the GET
        logger.warning(
            "[Meetings] brief first-view email enqueue failed meeting=%s: %s",
            meeting_id, exc,
        )

    return {"status": "ok", "data": brief}


def _deep_brief_enabled() -> bool:
    """W9d feature flag read at call time. Default false."""
    return os.getenv("BRIEF_DEEP_MODE_ENABLED", "false").lower() in {
        "true",
        "1",
        "yes",
        "on",
    }


@router.post(
    "/v2/meetings/{twin_id}/{meeting_id}/brief/deep",
    dependencies=[Depends(_require_meeting_intelligence)],
)
async def trigger_deep_brief(
    twin_id: str,
    meeting_id: str,
    request: Request,
) -> dict[str, Any]:
    """W9d — opt-in deep research mode for the pre-meeting brief.

    Enqueues a long-running graph_outbox job (~25-45s) that runs the
    ``brief_agent`` ReAct loop and merges the result into the meeting's
    ``brief_json``. Client polls the existing GET endpoint to detect
    completion (look for ``deep_generated_at``).

    Responses:
      - 202 ``{status, job_id, deep_generated_at?}`` — job enqueued or
        already in flight; client should poll
      - 200 ``{status: "cached", data: brief}`` — recent (< 24h) deep
        brief exists; client uses it immediately
      - 404 — meeting not found or out of scope for this twin/tenant
      - 503 — feature flag off (deep mode disabled in this environment)
    """
    if not _deep_brief_enabled():
        raise HTTPException(
            status_code=503,
            detail="Deep brief mode is not enabled in this environment.",
        )

    user = _get_current_user(request)
    tenant_id = user.get("tenant_id") or user.get("id")
    user_id_for_log = str(user.get("user_id") or user.get("id") or "")

    # Tenant-scoped fetch — never trust client-supplied IDs.
    meeting_resp = (
        supabase.table("meetings")
        .select("id, brief_json")
        .eq("id", meeting_id)
        .eq("twin_id", twin_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    meeting = meeting_resp.data if meeting_resp else None
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # 24h cache short-circuit — return the existing brief directly so the
    # client doesn't need to poll a second time.
    from adk_core.services.persona_core.deep_brief_merge import (
        deep_cache_is_fresh,
    )
    existing_brief = meeting.get("brief_json")
    if deep_cache_is_fresh(existing_brief):
        logger.info(
            "[DeepBrief] cache hit meeting=%s user=%s — returning cached",
            meeting_id, user_id_for_log,
        )
        return {"status": "cached", "data": existing_brief}

    # AUDIT FIX (W9d HIGH security): per-tenant rate limit before enqueue.
    # Without this, a malicious caller could enqueue one job per upcoming
    # meeting (potentially 50+) in a single burst — each job a 25-45s
    # ReAct loop costing $0.05-0.15. Hard cap at DEEP_BRIEF_MAX_PER_DAY
    # (default 10) jobs per tenant per 24h, counted from graph_outbox rows.
    # 429 with Retry-After when over.
    try:
        max_per_day = int(os.getenv("DEEP_BRIEF_MAX_PER_DAY", "10"))
    except ValueError:
        max_per_day = 10
    try:
        # Count deep-brief jobs enqueued in the last 24h for this tenant.
        # Uses iso timestamp comparison since graph_outbox.created_at is
        # a tz-aware timestamp column.
        window_start = (
            datetime.now(timezone.utc) - timedelta(hours=24)
        ).isoformat()
        # AUDIT FIX (PR #132 post-merge): exclude `failed` rows from the
        # daily cap so a tenant whose meeting hit the retry ceiling isn't
        # locked out for 24h on jobs that produced zero output. The
        # original hotfix commit message claimed this filter but the
        # query was missing it.
        count_resp = (
            supabase.table("graph_outbox")
            .select("id", count="exact")
            .eq("tenant_id", tenant_id)
            .eq("operation", GraphOperationType.GENERATE_DEEP_BRIEF.value)
            .in_("status", ["pending", "processing", "completed"])
            .gte("created_at", window_start)
            .execute()
        )
        recent_count = getattr(count_resp, "count", None)
        if recent_count is None:
            # Defensive: if the count attr isn't populated, fall back to
            # length of returned rows. Should not happen with count="exact".
            recent_count = len(count_resp.data or [])
        if recent_count >= max_per_day:
            logger.warning(
                "[DeepBrief] rate-limited tenant=%s user=%s count=%d max=%d",
                tenant_id, user_id_for_log, recent_count, max_per_day,
            )
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Deep research is limited to {max_per_day} runs per day. "
                    "Try again tomorrow."
                ),
                headers={"Retry-After": "3600"},
            )
        logger.info(
            "[DeepBrief] enqueue twin=%s meeting=%s user=%s count=%d/%d",
            twin_id, meeting_id, user_id_for_log, recent_count, max_per_day,
        )
    except HTTPException:
        raise
    except Exception as exc:
        # Don't fail-closed on a count query error — fall back to log-only
        # behaviour (the cache check still prevents repeat-runs per meeting).
        logger.warning(
            "[DeepBrief] rate-limit count failed (allowing): %s", exc,
        )

    idempotency_prefix = f"deep_brief:{twin_id}:{meeting_id}"
    try:
        active_resp = (
            supabase.table("graph_outbox")
            .select("id,status")
            .eq("tenant_id", tenant_id)
            .eq("operation", GraphOperationType.GENERATE_DEEP_BRIEF.value)
            .in_("status", ["pending", "processing"])
            .like("idempotency_key", f"{idempotency_prefix}%")
            .limit(1)
            .execute()
        )
        active_jobs = active_resp.data if active_resp else []
        if active_jobs:
            active_job_id = active_jobs[0].get("id")
            if active_job_id:
                logger.info(
                    "[DeepBrief] active job reused meeting=%s job=%s",
                    meeting_id, active_job_id,
                )
                return {"status": "queued", "job_id": str(active_job_id)}
    except Exception as exc:
        logger.warning(
            "[DeepBrief] active-job lookup failed (submitting new): %s",
            exc,
        )

    outbox = get_graph_outbox()
    # Scope the idempotency prefix by twin_id so two twins under the same
    # tenant who both brief on the same meeting_id don't collide. Add a
    # per-attempt suffix so a terminal failed historical row cannot poison
    # later explicit retries via the graph_outbox unique constraint.
    submit_result = outbox.submit(
        tenant_id=str(tenant_id),
        twin_id=twin_id,
        operation=GraphOperationType.GENERATE_DEEP_BRIEF,
        idempotency_key=f"{idempotency_prefix}:{uuid.uuid4().hex[:8]}",
        payload={"meeting_id": meeting_id},
        priority=3,
    )
    # AUDIT FIX (W9d HIGH): GraphOutbox.submit returns a str job_id, not a
    # dict — the previous isinstance/dict.get() dance was dead code.
    return {"status": "queued", "job_id": str(submit_result)}
