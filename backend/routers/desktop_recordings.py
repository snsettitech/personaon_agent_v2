"""
Desktop SDK recordings router.

Endpoints:
  POST   /v2/desktop-recordings/sdk-upload  Mint Recall.ai upload token + persist meetings row
  GET    /v2/desktop-recordings/            List the signed-in user's desktop recordings
  GET    /v2/desktop-recordings/{id}        Fetch one recording
  PATCH  /v2/desktop-recordings/{id}        Rename a recording (title only)
  POST   /v2/desktop-recordings/{id}/stop   Terminate + kick off summary off live segments+notes
  DELETE /v2/desktop-recordings/{id}        Soft-delete (status='deleted')

Recordings are stored in the existing `meetings` table with source='desktop_sdk'.
Twin association is optional — ad-hoc desktop audio sessions land with twin_id NULL.

Webhook handling (sdk_upload.complete -> transcript fetch) is wired in the shared
Recall webhook at /v2/meetings/webhook/recall (Commit 3 extends it for SDK events).
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from modules.auth_guard import verify_owner
from modules.email_validation import is_valid_email
from modules.observability import supabase
from services.recall_service import create_desktop_sdk_upload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2/desktop-recordings", tags=["desktop-recordings"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class DesktopRecordingWindow(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    title: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, max_length=2048)
    platform: str | None = Field(default=None, max_length=64)


class DesktopSdkUploadRequest(BaseModel):
    source: str = Field(default="electron", max_length=64)
    window: DesktopRecordingWindow


class UpdateRecordingRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)


class RecapEditField(str, Enum):
    TLDR = "tldr"
    TOPICS = "topics"
    ACTION_ITEMS = "action_items"
    KEY_QUESTIONS = "key_questions"
    INTENT = "intent"
    WHAT_HAPPENED = "what_happened"
    COMMITMENTS = "commitments"


class UpdateRecapRequest(BaseModel):
    field: RecapEditField
    after: Any


# --- Live user notes (Granola Batch 1) --------------------------------------

# The notes artifact the NotesEditor renders. v1 keeps it deliberately simple:
# a single growing text surface, stored as `{ "text": "..." }`. The shape is a
# free-form object (not a bare string) so the column can grow into a block list
# later without a wire-format break — the merge service (Batch 3) reads it.
_MAX_NOTES_TEXT_LEN = 100_000


class NotesArtifact(BaseModel):
    # Cap the body so a runaway client can't park an unbounded blob in the row.
    text: str = Field(default="", max_length=_MAX_NOTES_TEXT_LEN)


class UpdateNotesRequest(BaseModel):
    # The user's own raw notes. NOT routed through update_recap_with_audit —
    # that RPC is allowlisted to summary_json/recap_extras_json. Notes are the
    # user's direct input and are written with a plain owner-scoped UPDATE.
    user_notes_json: NotesArtifact


# --- Live transcript segments (Granola Batch 2) -----------------------------

# Cap the number of segments accepted per POST. The client batches finalized
# utterances (~20 / flush), so 200 is generous headroom while bounding the
# request size and the upsert row count.
_MAX_SEGMENTS_PER_BATCH = 200


class TranscriptSegment(BaseModel):
    # Monotonic client counter; conflict target is (meeting_id, seq) so a
    # replayed seq upserts onto the same row (idempotent). Upper-bounded to
    # the Postgres int4 max — the column is `seq int` (signed 32-bit), so a
    # value above 2,147,483,647 would overflow on INSERT and lose the batch.
    seq: int = Field(ge=0, le=2_147_483_647)
    speaker: str | None = Field(default=None, max_length=256)
    text: str = Field(min_length=1, max_length=10000)
    is_final: bool = False
    start_ms: int | None = Field(default=None, ge=0)


class PostSegmentsRequest(BaseModel):
    segments: list[TranscriptSegment] = Field(min_length=1, max_length=_MAX_SEGMENTS_PER_BATCH)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CLIENT_FIELDS = (
    "id,title,status,source,platform,duration_seconds,meeting_start,meeting_end,"
    "created_at,updated_at,transcript_url,transcript_provider,video_url,"
    "speaker_timeline_url,summary,summary_json,recap_extras_json,action_items,"
    "twin_id,recall_recording_id,"
    # Granola note-taking loop columns (Batch 0 migrations).
    "user_notes_json,notes_updated_at,enhanced_notes_json,enhanced_notes_status,"
    "recap_stage,recap_progress"
)


def _compact(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if value is not None}


def _default_recording_config() -> dict[str, Any]:
    """Recording config: realtime events always, transcript provider only when
    RECALL_TRANSCRIPT_PROVIDER is set (Recall.ai requires per-provider credentials
    configured in the Recall dashboard at /dashboard/transcription).
    """
    config: dict[str, Any] = {
        "realtime_endpoints": [
            {
                "type": "desktop_sdk_callback",
                "events": [
                    "participant_events.join",
                    "participant_events.update",
                    "participant_events.speech_on",
                    "participant_events.speech_off",
                    "transcript.data",
                    "transcript.partial_data",
                    "audio_mixed_raw.data",
                ],
            }
        ],
    }
    provider = os.getenv("RECALL_TRANSCRIPT_PROVIDER", "").strip()
    if provider:
        config["transcript"] = {"provider": {provider: {}}}
    return config


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    """Return only client-safe fields from a meetings row."""
    return {
        "id": row.get("id"),
        "title": row.get("title") or "Untitled recording",
        "status": row.get("status"),
        "source": row.get("source"),
        "platform": row.get("platform"),
        "duration_seconds": row.get("duration_seconds"),
        "meeting_start": row.get("meeting_start"),
        "meeting_end": row.get("meeting_end"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "transcript_url": row.get("transcript_url"),
        "transcript_provider": row.get("transcript_provider"),
        "video_url": row.get("video_url"),
        "speaker_timeline_url": row.get("speaker_timeline_url"),
        "summary": row.get("summary"),
        "summary_json": row.get("summary_json"),
        "recap_extras_json": row.get("recap_extras_json"),
        "action_items": row.get("action_items"),
        "twin_id": row.get("twin_id"),
        "recall_recording_id": row.get("recall_recording_id"),
        # Granola note-taking loop columns (Batch 0).
        "user_notes_json": row.get("user_notes_json"),
        "notes_updated_at": row.get("notes_updated_at"),
        "enhanced_notes_json": row.get("enhanced_notes_json"),
        "enhanced_notes_status": row.get("enhanced_notes_status"),
        "recap_stage": row.get("recap_stage"),
        "recap_progress": row.get("recap_progress"),
    }


def _is_missing_column_error(exc: Exception, column_name: str) -> bool:
    message = str(exc).lower()
    return "42703" in message and f"column meetings.{column_name}" in message


def _resolve_tenant(user: dict[str, Any]) -> str:
    """Return the user's tenant_id, falling back to user_id (single-user tenant)."""
    return str(user.get("tenant_id") or user.get("user_id") or "")


def _fetch_owned(meeting_id: str, user: dict[str, Any]) -> dict[str, Any]:
    """SELECT a meeting by id, raising 404 if it doesn't exist, belongs to
    another tenant, or has been soft-deleted. Existence is not leaked across
    tenants — wrong-owner returns 404, not 403.

    Uses .maybe_single() so a missing row returns data=None instead of raising
    an APIError (supabase-py v2+ .single() raises on zero rows).
    Catches all exceptions from the query layer as 404 to avoid 500s from
    malformed UUIDs in the path.
    """
    tenant_id = _resolve_tenant(user)
    try:
        resp = (
            supabase.table("meetings")
            .select(_CLIENT_FIELDS + ",tenant_id,public_share_token")
            .eq("id", meeting_id)
            .maybe_single()
            .execute()
        )
    except Exception as exc:
        # Most often: invalid UUID syntax. Treat as 404; log for debuggability.
        logger.info(
            "[desktop_recordings] fetch failed meeting_id=%s err=%s",
            meeting_id, type(exc).__name__,
        )
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    row = getattr(resp, "data", None)
    if not row:
        raise HTTPException(status_code=404, detail="Recording not found")
    if row.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=404, detail="Recording not found")
    if row.get("status") == "deleted":
        raise HTTPException(status_code=404, detail="Recording not found")
    return row


_SUMMARY_JSON_FIELDS = {
    RecapEditField.TLDR.value,
    RecapEditField.TOPICS.value,
    RecapEditField.ACTION_ITEMS.value,
    RecapEditField.KEY_QUESTIONS.value,
}
_RECAP_EXTRAS_FIELDS = {
    RecapEditField.INTENT.value,
    RecapEditField.WHAT_HAPPENED.value,
    RecapEditField.COMMITMENTS.value,
}


# Fields whose `after` MUST be a string. F6.4 (MAJOR P2 review fix): the
# prior fallback `return value` accepted dict/int/bool/None for these
# fields, which then landed verbatim in summary_json / recap_extras_json
# and only got coerced to "" downstream when Gemini's _normalize_extras
# ran on its output (not on inbound data).
_STRING_RECAP_FIELDS = {
    "tldr",
    "intent",
    "what_happened",
}
_LIST_RECAP_FIELDS = {
    "topics",
    "key_questions",
    "commitments",
    "action_items",
}

# Caps for stored content in user-edited recap fields. The router writes these
# values verbatim into `meetings.summary_json` / `meetings.recap_extras_json`,
# and the UI/shared-recap page renders them. Without per-item caps a crafted
# payload can store arbitrary-size strings, and without an allow-list on
# object keys it can smuggle attacker-controlled HTML in fields the renderer
# does not expect to sanitize. See docs/audits/2026-05-31-desktop-sdk-recording-audit.md C3.
_MAX_RECAP_LIST_ITEMS = 100
_MAX_RECAP_TEXT_LEN = 2000
_MAX_RECAP_OBJECT_KEYS = 16

# Object-shaped list items (e.g. action_items) are restricted to this set of
# allowed keys. Anything else is dropped before persistence. Update with care:
# new keys here become part of the trusted contract that downstream renderers
# may consume without re-escaping.
_ALLOWED_OBJECT_KEYS = {
    # action_items / commitments
    "id", "text", "title", "description", "assignee", "assignee_email",
    "owner", "owner_email", "due_at", "deadline", "priority", "status",
    "completed", "done", "tags", "context", "source", "speaker",
    # topics / key_questions
    "topic", "question", "answer", "summary",
    # decisions (referenced elsewhere)
    "decision", "rationale",
}


def _sanitize_recap_list_item(value: Any) -> Any:
    """Bound the shape of a single user-edited recap list item.

    Strings are length-capped. Dicts have unknown keys dropped, and each
    string value is length-capped. Nested lists are flattened to strings to
    prevent unbounded depth. None and primitives pass through.

    Raises HTTPException(400) on shapes that cannot be coerced safely.
    """
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value.strip()[:_MAX_RECAP_TEXT_LEN]
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        # Reject pathologically wide objects early; an attacker shouldn't be
        # able to bloat the JSON column with arbitrary key counts.
        if len(value) > _MAX_RECAP_OBJECT_KEYS:
            raise HTTPException(
                status_code=400,
                detail="Recap list item has too many keys",
            )
        for key, item in value.items():
            if not isinstance(key, str) or key not in _ALLOWED_OBJECT_KEYS:
                # Silently drop unknown keys -- safer than failing the whole
                # edit (legacy clients may send extras the new contract no
                # longer expects). The audit trail still has the original via
                # the RPC's `p_before` column for forensics if ever needed.
                continue
            if isinstance(item, str):
                cleaned[key] = item.strip()[:_MAX_RECAP_TEXT_LEN]
            elif isinstance(item, (bool, int, float)) or item is None:
                cleaned[key] = item
            elif isinstance(item, list):
                # One level of list nesting (e.g. tags). Items must be scalar.
                cleaned[key] = [
                    str(it).strip()[:_MAX_RECAP_TEXT_LEN]
                    for it in item
                    if isinstance(it, (str, int, float, bool))
                ][:_MAX_RECAP_LIST_ITEMS]
            else:
                # Nested objects are rejected; the recap contract does not
                # need arbitrary depth and accepting it widens the attack
                # surface against future renderers.
                raise HTTPException(
                    status_code=400,
                    detail=f"Recap list item key '{key}' must be scalar or list of scalars",
                )
        return cleaned
    raise HTTPException(
        status_code=400,
        detail="Recap list item must be a string, dict, or scalar",
    )


def _normalize_recap_after(field: str, value: Any) -> Any:
    if field in _STRING_RECAP_FIELDS:
        if not isinstance(value, str):
            raise HTTPException(status_code=400, detail="Recap field must be a string")
        cleaned = value.strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail="Recap field must be non-empty")
        if len(cleaned) > _MAX_RECAP_TEXT_LEN * 10:
            # String fields (tldr, intent, what_happened) get a more generous
            # cap than per-list-item strings since they are paragraph-shaped.
            raise HTTPException(
                status_code=400,
                detail=f"Recap field exceeds maximum length ({_MAX_RECAP_TEXT_LEN * 10})",
            )
        return cleaned
    if field in _LIST_RECAP_FIELDS:
        if not isinstance(value, list):
            raise HTTPException(status_code=400, detail="Recap field must be a list")
        if len(value) > _MAX_RECAP_LIST_ITEMS:
            raise HTTPException(
                status_code=400,
                detail=f"Recap list exceeds maximum item count ({_MAX_RECAP_LIST_ITEMS})",
            )
        # Sanitize each item so unknown object keys (and any rendered values
        # that downstream surfaces might trust) cannot smuggle attacker
        # content into the stored JSONB.
        return [_sanitize_recap_list_item(item) for item in value]
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail="Recap field must be non-empty")
        return cleaned[:_MAX_RECAP_TEXT_LEN * 10]
    raise HTTPException(status_code=400, detail="Unsupported recap field shape")


def _parse_due_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        logger.info("[desktop_recordings] ignoring invalid action item due_at=%s", value)
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_action_item_lead_time_minutes(user_id: str, tenant_id: str) -> int:
    try:
        resp = (
            supabase.table("notification_preferences")
            .select("action_item_lead_time_minutes")
            .eq("user_id", user_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        value = (getattr(resp, "data", None) or {}).get("action_item_lead_time_minutes")
        return max(0, int(value if value is not None else 60))
    except Exception as exc:
        logger.warning("[desktop_recordings] reminder lead-time lookup failed user=%s: %s", user_id, exc)
        return 60


def _schedule_action_item_reminders(
    *,
    meeting: dict[str, Any],
    action_items: list[Any],
    user: dict[str, Any],
    tenant_id: str,
) -> None:
    user_id = str(user.get("user_id") or "")
    fallback_email = str(user.get("email") or "").strip()
    lead_minutes = _load_action_item_lead_time_minutes(user_id, tenant_id)
    now = datetime.now(timezone.utc)
    # Cap scheduling horizon at 90 days. A malformed `due_at` in the year
    # 2999 (we've seen this in test fixtures and in the wild) would otherwise
    # park a graph_outbox row indefinitely, hold a slot in the queue, and
    # eventually fire when no one expects it. 90d is conservative: typical
    # action items are due in days/weeks; multi-month timelines are rare and
    # better tracked elsewhere than via email reminders.
    max_horizon = now + timedelta(days=90)

    try:
        from modules import graph_outbox

        outbox = graph_outbox.get_graph_outbox()
        for index, item in enumerate(action_items):
            if not isinstance(item, dict):
                continue
            due_at = _parse_due_at(item.get("due_at"))
            if due_at is None:
                continue
            scheduled_at = due_at - timedelta(minutes=lead_minutes)
            if scheduled_at <= now:
                continue
            if scheduled_at > max_horizon:
                logger.warning(
                    "[desktop_recordings] clamping reminder to 90d horizon meeting=%s idx=%d original=%s",
                    meeting.get("id"), index, scheduled_at.isoformat(),
                )
                scheduled_at = max_horizon
            recipient_email = (
                str(item.get("assignee_email") or "").strip()
                or fallback_email
            )
            # Reject syntactically invalid emails BEFORE enqueueing. Without
            # this guard an authenticated user could supply any string as
            # `assignee_email` and trigger an outbound send from PersonaOn's
            # Resend domain to an arbitrary address (open-relay vector).
            if not is_valid_email(recipient_email):
                logger.warning(
                    "[desktop_recordings] skip reminder enqueue — invalid recipient_email meeting=%s idx=%d",
                    meeting.get("id"), index,
                )
                continue
            outbox.submit(
                tenant_id=tenant_id,
                twin_id=str(meeting.get("twin_id") or ""),
                operation=graph_outbox.GraphOperationType.SEND_ACTION_ITEM_REMINDER,
                idempotency_key=f"action_item_reminder:{meeting['id']}:{index}",
                payload={
                    "meeting_id": meeting["id"],
                    "action_item_index": index,
                    "recipient_email": recipient_email,
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                },
                priority=2,
                next_attempt_after=scheduled_at,
            )
    except Exception as exc:
        logger.warning("[desktop_recordings] failed to schedule action reminders meeting=%s: %s", meeting.get("id"), exc)


def _enqueue_recap_edit_routing(
    *,
    edit_id: str,
    meeting: dict[str, Any],
    tenant_id: str,
) -> None:
    if not edit_id:
        return
    try:
        from modules import graph_outbox

        graph_outbox.get_graph_outbox().submit(
            tenant_id=tenant_id,
            twin_id=str(meeting.get("twin_id") or ""),
            operation=graph_outbox.GraphOperationType.ROUTE_RECAP_EDIT_TO_STORE,
            idempotency_key=f"edit_routing:{edit_id}",
            payload={"edit_id": edit_id, "tenant_id": tenant_id},
            priority=2,
        )
    except Exception as exc:
        logger.warning("[desktop_recordings] failed to enqueue recap edit routing edit=%s: %s", edit_id, exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/sdk-upload")
async def create_sdk_upload(
    body: DesktopSdkUploadRequest,
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    """Create a Recall.ai SDK upload + persist a meetings row to track the session."""
    user_id = str(user.get("user_id") or "")
    tenant_id = _resolve_tenant(user)

    if not user_id or not tenant_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    metadata = _compact({
        "source": body.source,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "desktop_window_id": body.window.id,
        "desktop_window_title": body.window.title,
        "desktop_window_url": body.window.url,
        "desktop_window_platform": body.window.platform,
    })

    try:
        result = await create_desktop_sdk_upload(
            metadata=metadata,
            recording_config=_default_recording_config(),
        )
    except Exception as exc:
        logger.exception(
            "[desktop_recordings] recall sdk_upload failed user_id=%s", user_id,
        )
        raise HTTPException(status_code=502, detail="Failed to create Recall upload") from exc

    upload_id = result.get("id")
    upload_token = result.get("upload_token")
    if not upload_id or not upload_token:
        # Never log the raw response: it may contain an upload_token bearer credential.
        logger.error(
            "[desktop_recordings] incomplete recall response keys=%s",
            list(result.keys()) if isinstance(result, dict) else type(result).__name__,
        )
        raise HTTPException(status_code=502, detail="Recall.ai upload response was incomplete")

    recording_id = result.get("recording_id")

    title = (body.window.title or "Desktop recording").strip() or "Desktop recording"
    insert_payload = {
        "tenant_id": tenant_id,
        "twin_id": None,
        "title": title,
        "status": "recording",
        "source": "desktop_sdk",
        "platform": body.window.platform,
        "recall_sdk_upload_id": str(upload_id),
        "recall_recording_id": str(recording_id) if recording_id else None,
        "transcript_provider": os.getenv("RECALL_TRANSCRIPT_PROVIDER", "").strip() or None,
        "meeting_start": datetime.now(timezone.utc).isoformat(),
    }

    meeting_id: str | None = None
    try:
        meeting_resp = supabase.table("meetings").insert(insert_payload).execute()
        rows = getattr(meeting_resp, "data", None) or []
        if rows:
            meeting_id = rows[0].get("id")
    except Exception as exc:
        # Most likely cause: duplicate recall_sdk_upload_id (idempotent retry).
        # Recover the existing row's id by selecting on the unique key so the
        # caller still gets a meeting_id and the upload flow remains idempotent.
        is_dup = "meetings_recall_sdk_upload_id_key" in str(exc) \
            or "duplicate key" in str(exc).lower()
        if is_dup:
            logger.info(
                "[desktop_recordings] duplicate sdk_upload_id=%s — recovering existing meeting",
                upload_id,
            )
            try:
                existing = (
                    supabase.table("meetings")
                    .select("id")
                    .eq("recall_sdk_upload_id", str(upload_id))
                    .eq("tenant_id", tenant_id)
                    .maybe_single()
                    .execute()
                )
                existing_row = getattr(existing, "data", None)
                if existing_row:
                    meeting_id = existing_row.get("id")
            except Exception:
                logger.exception(
                    "[desktop_recordings] recovery select failed sdk_upload_id=%s",
                    upload_id,
                )
        else:
            # Unknown insert failure. Don't fail the upload — webhook can backfill.
            logger.exception(
                "[desktop_recordings] meetings insert failed sdk_upload_id=%s",
                upload_id,
            )

    logger.info(
        "[desktop_recordings] sdk-upload meeting_id=%s recall_recording_id=%s tenant_id=%s",
        meeting_id, recording_id, tenant_id,
    )

    return {
        "status": "ok",
        "data": {
            "id": str(upload_id),
            "upload_token": str(upload_token),
            "recording_id": recording_id,
            "meeting_id": meeting_id,
        },
    }


@router.get("/")
async def list_recordings(
    user: dict[str, Any] = Depends(verify_owner),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List the signed-in user's desktop recordings, newest first."""
    tenant_id = _resolve_tenant(user)
    try:
        resp = (
            supabase.table("meetings")
            .select(_CLIENT_FIELDS)
            .eq("tenant_id", tenant_id)
            .eq("source", "desktop_sdk")
            .neq("status", "deleted")
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
    except Exception as exc:
        if _is_missing_column_error(exc, "source"):
            logger.warning(
                "[desktop_recordings] meetings.source missing; returning empty list until desktop SDK migration is applied"
            )
            return {"status": "ok", "data": {"items": []}}
        raise
    rows = getattr(resp, "data", None) or []
    return {"status": "ok", "data": {"items": [_serialize(r) for r in rows]}}


@router.get("/{meeting_id}")
async def get_recording(
    meeting_id: str,
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    row = _fetch_owned(meeting_id, user)
    return {"status": "ok", "data": _serialize(row)}


@router.patch("/{meeting_id}")
async def update_recording(
    meeting_id: str,
    body: UpdateRecordingRequest,
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    _fetch_owned(meeting_id, user)
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title must be non-empty")
    tenant_id = _resolve_tenant(user)
    resp = (
        supabase.table("meetings")
        .update({
            "title": title,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", meeting_id)
        .eq("tenant_id", tenant_id)  # defense-in-depth: enforce at DB layer too
        .execute()
    )
    rows = getattr(resp, "data", None) or []
    if not rows:
        logger.error("[desktop_recordings] update returned no rows meeting_id=%s", meeting_id)
        raise HTTPException(status_code=500, detail="Failed to update recording")
    return {"status": "ok", "data": _serialize(rows[0])}


@router.patch("/{meeting_id}/recap")
async def update_recording_recap(
    meeting_id: str,
    body: UpdateRecapRequest,
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    row = _fetch_owned(meeting_id, user)
    tenant_id = _resolve_tenant(user)
    user_id = str(user.get("user_id") or "")
    field = body.field.value
    after = _normalize_recap_after(field, body.after)

    if field in _SUMMARY_JSON_FIELDS:
        json_column = "summary_json"
    elif field in _RECAP_EXTRAS_FIELDS:
        json_column = "recap_extras_json"
    else:
        raise HTTPException(status_code=400, detail="Unsupported recap field")

    # Atomic UPDATE + INSERT via Postgres RPC. The function (see
    # supabase/migrations/20260529000200_atomic_recap_patch_rpc.sql) takes a
    # FOR UPDATE row lock, computes the `before` snapshot inside the same
    # transaction as the UPDATE + recap_edits INSERT, eliminating the
    # lost-edit race that the previous 3-call sequence had open between the
    # row read and the write.
    # supabase-py is sync; wrap in to_thread so the async handler doesn't
    # block the event loop on the network round-trip (M2 review fix).
    rpc_resp = await asyncio.to_thread(
        lambda: supabase.rpc(
            "update_recap_with_audit",
            {
                "p_meeting_id": meeting_id,
                "p_tenant_id": tenant_id,
                "p_user_id": user_id or None,
                "p_field": field,
                "p_json_column": json_column,
                "p_after": after,
            },
        ).execute()
    )
    rpc_data = getattr(rpc_resp, "data", None) or {}
    updated_meeting = rpc_data.get("meeting") if isinstance(rpc_data, dict) else None
    edit_id = str(rpc_data.get("edit_id") or "") if isinstance(rpc_data, dict) else ""
    if not updated_meeting or not edit_id:
        logger.error(
            "[desktop_recordings] recap RPC returned unexpected shape meeting_id=%s data=%s",
            meeting_id, type(rpc_data).__name__,
        )
        raise HTTPException(status_code=500, detail="Failed to update recap")

    _enqueue_recap_edit_routing(
        edit_id=edit_id,
        meeting=row,
        tenant_id=tenant_id,
    )

    if field == RecapEditField.ACTION_ITEMS.value and isinstance(after, list):
        _schedule_action_item_reminders(
            meeting=row,
            action_items=after,
            user=user,
            tenant_id=tenant_id,
        )

    return {"status": "ok", "data": _serialize(updated_meeting)}


# ---------------------------------------------------------------------------
# Live user notes (Granola Batch 1 — granola_live_notes)
# ---------------------------------------------------------------------------

@router.patch("/{meeting_id}/notes")
async def update_recording_notes(
    meeting_id: str,
    body: UpdateNotesRequest,
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    """Persist the user's own live meeting notes.

    The desktop/web client autosaves the NotesEditor contents here while a
    recording is active (and post-meeting on the detail screen). This is the
    user's raw input — the AI-merge (Batch 3) later fuses it with the
    transcript — so it is written with a direct owner-scoped UPDATE rather than
    routed through `update_recap_with_audit` (that RPC is allowlisted to
    summary_json/recap_extras_json and would reject this column).

    Concurrency: last-write-wins for v1. A live-recording autosave and a later
    edit on the detail screen both write `user_notes_json` wholesale; the most
    recent flush wins. `notes_updated_at` records the server clock of that flush.
    """
    _fetch_owned(meeting_id, user)  # 404s cross-tenant / missing / deleted
    tenant_id = _resolve_tenant(user)

    try:
        resp = (
            supabase.table("meetings")
            .update({
                "user_notes_json": body.user_notes_json.model_dump(),
                "notes_updated_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", meeting_id)
            .eq("tenant_id", tenant_id)  # tenant_scope_mutations: scope by id AND tenant
            .execute()
        )
    except Exception as exc:
        logger.exception(
            "[desktop_recordings] notes update failed meeting_id=%s", meeting_id,
        )
        raise HTTPException(status_code=500, detail="Failed to save notes") from exc

    rows = getattr(resp, "data", None) or []
    if not rows:
        logger.error("[desktop_recordings] notes update returned no rows meeting_id=%s", meeting_id)
        raise HTTPException(status_code=500, detail="Failed to save notes")
    logger.info("[desktop_recordings] saved notes meeting_id=%s", meeting_id)
    return {"status": "ok", "data": _serialize(rows[0])}


# ---------------------------------------------------------------------------
# Live transcript segments (Granola Batch 2 — granola_segment_persist)
# ---------------------------------------------------------------------------

@router.post("/{meeting_id}/segments")
async def post_transcript_segments(
    meeting_id: str,
    body: PostSegmentsRequest,
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    """Persist a batch of FINALIZED transcript utterances for a recording.

    The desktop client streams `transcript.data` (final) events into this
    endpoint during the call so the transcript is already in Postgres at Stop.
    Partial (`transcript.partial_data`) events are NOT sent here — they stay
    ephemeral in the live display.

    Idempotent: rows upsert ON CONFLICT (meeting_id, seq). The client assigns a
    monotonic `seq`, so a replayed batch (SDK reconnect) updates the same row
    instead of inserting a duplicate.
    """
    _fetch_owned(meeting_id, user)  # 404s cross-tenant / missing / deleted
    tenant_id = _resolve_tenant(user)

    rows: list[dict[str, Any]] = []
    seen_seq: set[int] = set()
    for seg in body.segments:
        # Only persist finalized utterances. Partials are display-only.
        if not seg.is_final:
            continue
        text = seg.text.strip()
        if not text:
            continue
        # Drop intra-batch duplicate seqs so the upsert doesn't error on a
        # conflicting ON CONFLICT target within a single statement.
        if seg.seq in seen_seq:
            continue
        seen_seq.add(seg.seq)
        rows.append({
            "meeting_id": meeting_id,
            "tenant_id": tenant_id,
            "seq": seg.seq,
            "speaker": (seg.speaker or None),
            "text": text,
            "is_final": True,
            "start_ms": seg.start_ms,
        })

    if not rows:
        return {"status": "ok", "data": {"inserted": 0}}

    try:
        supabase.table("meeting_transcript_segments").upsert(
            rows,
            on_conflict="meeting_id,seq",
            ignore_duplicates=True,
        ).execute()
    except Exception as exc:
        logger.exception(
            "[desktop_recordings] segment upsert failed meeting_id=%s count=%d",
            meeting_id, len(rows),
        )
        raise HTTPException(status_code=500, detail="Failed to persist transcript segments") from exc

    logger.info(
        "[desktop_recordings] persisted segments meeting_id=%s count=%d",
        meeting_id, len(rows),
    )
    return {"status": "ok", "data": {"inserted": len(rows)}}


@router.get("/{meeting_id}/segments")
async def list_transcript_segments(
    meeting_id: str,
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    """Return a recording's persisted transcript segments, ordered by `seq`.

    Lets the detail screen render the live transcript directly from Postgres
    without the blocking signed-S3 archive fetch. Returns [] for a recording
    that never produced segments.
    """
    _fetch_owned(meeting_id, user)  # 404s cross-tenant / missing / deleted
    tenant_id = _resolve_tenant(user)
    try:
        resp = (
            supabase.table("meeting_transcript_segments")
            .select("seq,speaker,text,is_final,start_ms,created_at")
            .eq("meeting_id", meeting_id)
            .eq("tenant_id", tenant_id)  # defense-in-depth alongside RLS
            .order("seq")
            .execute()
        )
    except Exception as exc:
        logger.exception(
            "[desktop_recordings] segment list failed meeting_id=%s", meeting_id,
        )
        raise HTTPException(status_code=500, detail="Failed to load transcript segments") from exc
    rows = getattr(resp, "data", None) or []
    return {"status": "ok", "data": {"items": rows}}


# ---------------------------------------------------------------------------
# Enhanced notes re-run (Granola Batch 3 — granola_enhanced_notes)
# ---------------------------------------------------------------------------

@router.post("/{meeting_id}/enhance")
async def enhance_recording_notes(
    meeting_id: str,
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    """(Re)enqueue the AI-merge that fuses the user's notes with the live
    transcript into enhanced notes — backs the "Regenerate notes" button.

    Debounced: if a generation is already in flight (enhanced_notes_status ==
    'generating'), this is a no-op so a user spamming the button doesn't queue
    a pile of jobs.

    Idempotency note: the automatic enqueue at Stop uses the stable key
    `enhance_notes:{meeting_id}` (so a webhook redelivery dedupes). A MANUAL
    re-run must actually re-run even after a prior job `completed` — the outbox
    dedupes on completed jobs with the same key — so we mint a fresh
    timestamped key here. The 'generating' guard above is what prevents spam.
    """
    row = _fetch_owned(meeting_id, user)  # 404s cross-tenant / missing / deleted
    tenant_id = _resolve_tenant(user)

    if row.get("enhanced_notes_status") == "generating":
        logger.info(
            "[desktop_recordings] enhance no-op — already generating meeting_id=%s", meeting_id,
        )
        return {"status": "ok", "data": {"meeting_id": meeting_id, "enqueued": False, "reason": "already_generating"}}

    # Flip status to 'generating' immediately so a rapid second click hits the
    # debounce guard above (and the UI shows the loading state without waiting
    # for the worker). Owner-scoped + tenant-scoped write.
    try:
        supabase.table("meetings").update({
            "enhanced_notes_status": "generating",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", meeting_id).eq("tenant_id", tenant_id).execute()
    except Exception:
        logger.exception(
            "[desktop_recordings] failed to mark generating meeting_id=%s", meeting_id,
        )

    rerun_key = f"enhance_notes:{meeting_id}:{int(datetime.now(timezone.utc).timestamp())}"
    try:
        from modules import graph_outbox

        graph_outbox.get_graph_outbox().submit(
            tenant_id=tenant_id,
            twin_id=(str(row.get("twin_id")) if row.get("twin_id") else None),  # twin OPTIONAL
            operation=graph_outbox.GraphOperationType.ENHANCE_NOTES,
            idempotency_key=rerun_key,
            payload={
                "meeting_id": meeting_id,
                "tenant_id": tenant_id,
                "twin_id": (str(row.get("twin_id")) if row.get("twin_id") else None),
            },
            priority=4,
        )
    except Exception as exc:
        logger.exception(
            "[desktop_recordings] failed to enqueue enhance_notes meeting_id=%s", meeting_id,
        )
        raise HTTPException(status_code=500, detail="Failed to start note enhancement") from exc

    logger.info("[desktop_recordings] enqueued enhance_notes (manual) meeting_id=%s", meeting_id)
    return {"status": "ok", "data": {"meeting_id": meeting_id, "enqueued": True}}


# ---------------------------------------------------------------------------
# Stop recording (Granola — Stop → summary)
# ---------------------------------------------------------------------------

# Non-terminal statuses a Stop is allowed to advance. A row already in a
# terminal/processing state is a no-op (idempotent) so a double-Stop (the SDK
# local stop racing the explicit button, or a webhook redelivery) doesn't
# re-enqueue or re-arm anything.
_STOPPABLE_STATUSES = {"recording", "uploading"}


@router.post("/{meeting_id}/stop")
async def stop_recording(
    meeting_id: str,
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    """Terminate a recording server-side and kick off the summary immediately.

    This is the authoritative stop. It exists because the SDK-only local stop
    (stopActive) could leave the meetings row stuck in `status='recording'`
    forever if the upload→webhook→batch-transcribe chain never landed (a real
    bug). The client calls this in addition to the SDK stop so the recording
    ALWAYS terminates and the summary ALWAYS runs.

    Behavior:
      1. Flip status `recording`/`uploading` → `processing` and `recap_stage`
         → `enhancing` (scoped by id AND tenant_id). The enhance job + watchdog
         then drive the row to a terminal state for the progressive reveal.
      2. Enqueue ENHANCE_NOTES immediately (stable key `enhance_notes:{id}`) so
         the summary generates off the LIVE `meeting_transcript_segments` +
         `user_notes_json` — NOT the slow batch re-transcription chain. The
         enhance worker merges the user's notes WITH the transcript. Twin-optional.
      3. Arm the `recap_timeout_check` watchdog (INDEPENDENT try/except) so the
         row can never spin forever even if the enhance enqueue fails.

    Idempotent: if the recording is already terminal/processing this is a
    graceful no-op (no re-enqueue, no re-arm).
    """
    row = _fetch_owned(meeting_id, user)  # 404s cross-tenant / missing / deleted
    tenant_id = _resolve_tenant(user)
    twin_id = str(row.get("twin_id")) if row.get("twin_id") else None
    current_status = str(row.get("status") or "")

    # Idempotent no-op: already terminal or already processing. Don't re-enqueue.
    if current_status not in _STOPPABLE_STATUSES:
        logger.info(
            "[desktop_recordings] stop no-op — status=%s meeting_id=%s",
            current_status, meeting_id,
        )
        return {
            "status": "ok",
            "data": {"meeting_id": meeting_id, "stopped": False, "reason": "not_active"},
        }

    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Flip to processing + enhancing, scoped by id AND tenant_id. Also stamp
    #    meeting_end so the duration/UI has a terminal marker. enhanced_notes_status
    #    moves to 'generating' so the detail screen shows the in-flight state.
    try:
        resp = (
            supabase.table("meetings")
            .update({
                "status": "processing",
                "recap_stage": "enhancing",
                "enhanced_notes_status": "generating",
                "meeting_end": now_iso,
                "updated_at": now_iso,
            })
            .eq("id", meeting_id)
            .eq("tenant_id", tenant_id)  # tenant_scope_mutations: scope by id AND tenant
            .execute()
        )
    except Exception as exc:
        logger.exception("[desktop_recordings] stop status flip failed meeting_id=%s", meeting_id)
        raise HTTPException(status_code=500, detail="Failed to stop recording") from exc

    rows = getattr(resp, "data", None) or []
    if not rows:
        logger.error("[desktop_recordings] stop returned no rows meeting_id=%s", meeting_id)
        raise HTTPException(status_code=500, detail="Failed to stop recording")

    # 2. Enqueue ENHANCE_NOTES immediately. Stable key so a webhook redelivery
    #    (the SDK upload chain still completes later) dedupes to the same job.
    #    This is the SAME job Batch 3 built — it merges user_notes + live segments.
    try:
        from modules import graph_outbox

        graph_outbox.get_graph_outbox().submit(
            tenant_id=tenant_id,
            twin_id=twin_id,  # twin OPTIONAL — ad-hoc desktop captures have NULL twin
            operation=graph_outbox.GraphOperationType.ENHANCE_NOTES,
            idempotency_key=f"enhance_notes:{meeting_id}",
            payload={
                "meeting_id": meeting_id,
                "tenant_id": tenant_id,
                "twin_id": twin_id,
            },
            priority=4,
        )
        logger.info(
            "[desktop_recordings] stop enqueued enhance_notes meeting_id=%s twin=%s",
            meeting_id, twin_id or "(none)",
        )
    except Exception:
        # Don't fail the stop — the watchdog (armed below) is the backstop.
        logger.exception(
            "[desktop_recordings] stop failed to enqueue enhance_notes meeting_id=%s", meeting_id,
        )

    # 3. Arm the recap_timeout_check watchdog. INDEPENDENT try/except (QG2 H2):
    #    it MUST arm regardless of the enhance enqueue outcome, otherwise a failed
    #    enhance enqueue would also kill the watchdog and the row could spin
    #    forever. Delayed; idempotency keyed on meeting so a redelivery dedupes.
    try:
        from modules import graph_outbox
        from modules.graph_outbox_worker import RECAP_STUCK_TIMEOUT_SECONDS

        graph_outbox.get_graph_outbox().submit(
            tenant_id=tenant_id,
            twin_id=twin_id,
            operation=graph_outbox.GraphOperationType.RECAP_TIMEOUT_CHECK,
            idempotency_key=f"recap_timeout_check:{meeting_id}",
            payload={"meeting_id": meeting_id, "tenant_id": tenant_id},
            priority=1,
            next_attempt_after=datetime.now(timezone.utc) + timedelta(seconds=RECAP_STUCK_TIMEOUT_SECONDS),
        )
        logger.info(
            "[desktop_recordings] stop armed recap_timeout_check meeting_id=%s", meeting_id,
        )
    except Exception:
        logger.exception(
            "[desktop_recordings] stop failed to arm recap_timeout_check meeting_id=%s", meeting_id,
        )

    return {
        "status": "ok",
        "data": {"meeting_id": meeting_id, "stopped": True},
    }


@router.delete("/{meeting_id}")
async def delete_recording(
    meeting_id: str,
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    """Soft-delete: sets status='deleted'. Recall.ai-side delete is best-effort
    (handled by a downstream worker so we never block the request)."""
    _fetch_owned(meeting_id, user)
    tenant_id = _resolve_tenant(user)
    resp = (
        supabase.table("meetings")
        .update({
            "status": "deleted",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", meeting_id)
        .eq("tenant_id", tenant_id)  # defense-in-depth: enforce at DB layer too
        .execute()
    )
    rows = getattr(resp, "data", None) or []
    if not rows:
        logger.error("[desktop_recordings] delete returned no rows meeting_id=%s", meeting_id)
        raise HTTPException(status_code=500, detail="Failed to delete recording")
    return {"status": "ok", "data": {"id": meeting_id, "deleted": True}}


# ---------------------------------------------------------------------------
# Public share / unshare endpoints (owner-only)
# ---------------------------------------------------------------------------

class ShareResult(BaseModel):
    token: str
    url: str
    enabled: bool


def _public_share_url(token: str) -> str:
    base = os.getenv("FRONTEND_URL", "http://localhost:3002").rstrip("/")
    return f"{base}/shared-meeting/{token}"


@router.post("/{meeting_id}/share")
async def share_recording(
    meeting_id: str,
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    """Enable public sharing for a recording. Returns the share token and URL.
    Reuses an existing token if already set so the shareable link is stable."""
    row = _fetch_owned(meeting_id, user)  # 404s cross-tenant/missing/deleted
    token = row.get("public_share_token") or secrets.token_urlsafe(16)
    supabase.table("meetings").update({
        "public_share_token": token,
        "public_share_enabled": True,
        "public_shared_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", meeting_id).eq("tenant_id", _resolve_tenant(user)).execute()
    logger.info("[desktop_recordings] share enabled meeting_id=%s", meeting_id)
    return {
        "status": "ok",
        "data": ShareResult(token=token, url=_public_share_url(token), enabled=True).model_dump(),
    }


@router.delete("/{meeting_id}/share")
async def unshare_recording(
    meeting_id: str,
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    """Disable public sharing for a recording (token is kept, just disabled)."""
    _fetch_owned(meeting_id, user)
    supabase.table("meetings").update({"public_share_enabled": False}).eq("id", meeting_id).eq("tenant_id", _resolve_tenant(user)).execute()
    logger.info("[desktop_recordings] share disabled meeting_id=%s", meeting_id)
    return {"status": "ok", "data": {"enabled": False}}
