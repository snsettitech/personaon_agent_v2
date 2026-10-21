"""
Phase F.3 — Contacts router (People surface).

Three endpoints, owner-only:
  GET    /v2/twins/{twin_id}/contacts?q=&limit=&offset=  — list
  GET    /v2/twins/{twin_id}/contacts/{contact_id}        — detail
  PATCH  /v2/twins/{twin_id}/contacts/{contact_id}/permission — toggle allow_mention

Phase F.4 — Soft-delete + meetings list.
  DELETE /v2/twins/{twin_id}/contacts/{contact_id}               — soft-delete
  GET    /v2/twins/{twin_id}/contacts/{contact_id}/meetings       — meetings list

Phase W.1 — Contact analysis endpoint (Person Detail uplift).
  GET    /v2/twins/{twin_id}/contacts/{contact_id}/analysis       — stats + open loops
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from services.person_context import build_person_context

from modules.auth_guard import verify_owner, verify_twin_ownership
from modules.observability import supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2/twins", tags=["contacts"])


def _resolve_tenant(user: dict[str, Any]) -> str:
    return str(user.get("tenant_id") or user.get("user_id") or "")


class ContactSummary(BaseModel):
    id: str
    name: str
    email: str | None = None
    linkedin_url: str | None = None
    avatar_url: str | None = None
    meeting_count: int = 0
    last_seen_at: str | None = None
    first_seen_at: str | None = None
    allow_mention: bool = True
    tags: list[str] = Field(default_factory=list)


class PermissionUpdate(BaseModel):
    allow_mention: bool


class MeetingForContact(BaseModel):
    id: str
    title: str | None = None
    meeting_start: str | None = None
    meeting_end: str | None = None
    duration_seconds: int | None = None
    status: str | None = None
    source_link: str | None = None  # how the link was made: 'participant' | 'recap'


_CONTACT_FIELDS = (
    "id, name, email, linkedin_url, avatar_url, meeting_count, "
    "last_seen_at, first_seen_at, allow_mention, tags"
)


@router.get("/{twin_id}/contacts")
async def list_contacts(
    twin_id: str,
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    """List contacts for a twin. Optional fuzzy filter on name via `q`.
    Excludes soft-deleted contacts."""
    verify_twin_ownership(twin_id, user)
    tenant_id = _resolve_tenant(user)

    query = (
        supabase.table("contacts")
        .select(_CONTACT_FIELDS)
        .eq("twin_id", twin_id)
        .eq("tenant_id", tenant_id)
        .is_("deleted_at", "null")
        .order("last_seen_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if q:
        # ilike on name — covers the primary search use case (most contacts
        # are looked up by name). Email search is a follow-up.
        query = query.ilike("name", f"%{q}%")

    try:
        resp = query.execute()
    except Exception as exc:
        logger.info("[contacts/list] query failed twin=%s err=%s", twin_id, type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not load contacts") from exc

    rows = getattr(resp, "data", None) or []
    return {
        "status": "ok",
        "data": {
            "contacts": [ContactSummary(**r).model_dump() for r in rows],
            "count": len(rows),
        },
    }


def _fetch_contact_owned(twin_id: str, contact_id: str, tenant_id: str) -> dict[str, Any]:
    """Tenant + twin-scoped fetch. 404 on miss / cross-tenant / soft-deleted."""
    try:
        resp = (
            supabase.table("contacts")
            .select(_CONTACT_FIELDS + ", notes, metadata, twin_id, tenant_id")
            .eq("id", contact_id)
            .eq("tenant_id", tenant_id)
            .eq("twin_id", twin_id)
            .is_("deleted_at", "null")
            .maybe_single()
            .execute()
        )
    except Exception as exc:
        logger.info("[contacts] fetch failed id=%s err=%s", contact_id, type(exc).__name__)
        raise HTTPException(status_code=404, detail="Contact not found") from exc
    row = getattr(resp, "data", None)
    if not row:
        raise HTTPException(status_code=404, detail="Contact not found")
    return row


@router.get("/{twin_id}/contacts/{contact_id}")
async def get_contact(
    twin_id: str,
    contact_id: str,
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    """Fetch a single contact by ID."""
    verify_twin_ownership(twin_id, user)
    tenant_id = _resolve_tenant(user)
    row = _fetch_contact_owned(twin_id, contact_id, tenant_id)
    return {"status": "ok", "data": row}


@router.delete("/{twin_id}/contacts/{contact_id}")
async def delete_contact(
    twin_id: str,
    contact_id: str,
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    """Soft-delete a contact. The contact stops appearing in list/detail, and the
    recap-extractor's lookups will respect deleted_at so it isn't resurrected on
    the next worker run."""
    verify_twin_ownership(twin_id, user)
    tenant_id = _resolve_tenant(user)
    _fetch_contact_owned(twin_id, contact_id, tenant_id)  # 404 if missing/cross-tenant

    try:
        supabase.table("contacts").update({
            "deleted_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", contact_id).eq("tenant_id", tenant_id).eq("twin_id", twin_id).execute()
    except Exception as exc:
        logger.warning("[contacts] soft-delete failed id=%s err=%s",
                       contact_id, type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not delete contact") from exc

    logger.info("[contacts] soft-deleted id=%s", contact_id)
    return {"status": "ok", "data": {"id": contact_id, "deleted": True}}


@router.get("/{twin_id}/contacts/{contact_id}/meetings")
async def list_contact_meetings(
    twin_id: str,
    contact_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    """List meetings this contact participated in, newest first.
    Excludes soft-deleted meetings."""
    verify_twin_ownership(twin_id, user)
    tenant_id = _resolve_tenant(user)
    _fetch_contact_owned(twin_id, contact_id, tenant_id)  # 404 if missing

    # 1. Get linked meeting_ids + source from join
    try:
        link_resp = (
            supabase.table("contact_meetings")
            .select("meeting_id, source")
            .eq("contact_id", contact_id)
            .eq("tenant_id", tenant_id)
            .eq("twin_id", twin_id)
            .limit(limit)
            .execute()
        )
        links = getattr(link_resp, "data", None) or []
    except Exception as exc:
        logger.info("[contacts] meetings join lookup failed err=%s",
                    type(exc).__name__)
        return {"status": "ok", "data": {"meetings": [], "count": 0}}

    if not links:
        return {"status": "ok", "data": {"meetings": [], "count": 0}}

    meeting_ids = [link["meeting_id"] for link in links]
    source_by_id = {link["meeting_id"]: link.get("source", "recap") for link in links}

    # 2. Fetch meeting details for those ids (tenant-scoped; exclude deleted)
    try:
        m_resp = (
            supabase.table("meetings")
            .select("id, title, meeting_start, meeting_end, duration_seconds, status")
            .in_("id", meeting_ids)
            .eq("tenant_id", tenant_id)
            .neq("status", "deleted")
            .order("meeting_start", desc=True)
            .execute()
        )
        rows = getattr(m_resp, "data", None) or []
    except Exception as exc:
        logger.warning("[contacts] meeting fetch failed err=%s",
                       type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not load meetings") from exc

    meetings = [
        MeetingForContact(
            id=r["id"], title=r.get("title"),
            meeting_start=r.get("meeting_start"),
            meeting_end=r.get("meeting_end"),
            duration_seconds=r.get("duration_seconds"),
            status=r.get("status"),
            source_link=source_by_id.get(r["id"], "recap"),
        ).model_dump()
        for r in rows
    ]
    return {"status": "ok", "data": {"meetings": meetings, "count": len(meetings)}}


@router.patch("/{twin_id}/contacts/{contact_id}/permission")
async def set_contact_permission(
    twin_id: str,
    contact_id: str,
    body: PermissionUpdate,
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    """Toggle allow_mention for a contact (controls whether this person can be
    referenced in twin chat / memory operations)."""
    verify_twin_ownership(twin_id, user)
    tenant_id = _resolve_tenant(user)
    _fetch_contact_owned(twin_id, contact_id, tenant_id)  # 404 if not found

    try:
        supabase.table("contacts").update({
            "allow_mention": body.allow_mention,
        }).eq("id", contact_id).eq("tenant_id", tenant_id).eq("twin_id", twin_id).execute()
    except Exception as exc:
        logger.warning("[contacts] permission update failed id=%s err=%s",
                       contact_id, type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not update permission") from exc

    logger.info("[contacts] permission set contact=%s allow=%s", contact_id, body.allow_mention)
    return {"status": "ok", "data": {"id": contact_id, "allow_mention": body.allow_mention}}


# ---------------------------------------------------------------------------
# Phase W.1 — Contact analysis (Person Detail uplift)
# ---------------------------------------------------------------------------


class _MeetingRef(BaseModel):
    id: str
    title: str | None = None
    meeting_start: str | None = None


class OpenLoop(BaseModel):
    text: str
    meeting: _MeetingRef
    days_open: int
    assignee_role: str  # 'you' | 'them' | 'unknown'


class _OpenLoopBuckets(BaseModel):
    you_owe: list[OpenLoop] = Field(default_factory=list)
    they_owe: list[OpenLoop] = Field(default_factory=list)
    skipped_count: int = 0
    truncated: bool = False


class _AnalysisStats(BaseModel):
    last_talked: str | None = None
    total_meetings: int = 0
    open_loops_you_owe: int = 0
    open_loops_they_owe: int = 0
    next_meeting: None = None  # deferred until calendar phase


class MemoryMention(BaseModel):
    """Approved memory candidate that mentions a contact. Mirrors the frontend
    Candidate shape (PersonDetailScreen renders .text + .predicate)."""
    id: str
    meeting_id: str | None = None
    contact_id: str | None = None
    kind: str
    subject: str
    predicate: str
    text: str
    confidence: float
    status: str
    created_at: str


class _AnalysisData(BaseModel):
    stats: _AnalysisStats
    open_loops: _OpenLoopBuckets
    memory_mentions: list[MemoryMention] = Field(default_factory=list)


def _resolve_owner_name(user: dict[str, Any]) -> str:
    """Resolve the owner's display name the same way graph_outbox_worker does."""
    tenant_id = _resolve_tenant(user)
    try:
        u_resp = (
            supabase.table("users")
            .select("full_name, email")
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        u_row = (getattr(u_resp, "data", None) or [None])[0] or {}
        name = (u_row.get("full_name") or "").strip()
        if not name and u_row.get("email"):
            name = u_row["email"].split("@")[0]
        return name
    except Exception:
        logger.info("[contacts/analysis] owner-name lookup failed; continuing without name")
        return ""


@router.get("/{twin_id}/contacts/{contact_id}/analysis")
async def get_contact_analysis(
    twin_id: str,
    contact_id: str,
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, Any]:
    """Return stats + open loops + memory mentions for a contact.

    - stats: last_talked, total_meetings, open_loops_you_owe, open_loops_they_owe
    - open_loops: bucketed by assignee role (you / them / unknown); unknown
      increments skipped_count and is omitted from result rows
    - memory_mentions: approved memory_candidates that mention this contact
      (by contact link, name, or email), capped at 25

    Open-loops + memory computation lives in services.person_context so the
    dashboard and the persona chat injection stay in sync.
    """
    t_start = datetime.now(timezone.utc)
    verify_twin_ownership(twin_id, user)
    tenant_id = _resolve_tenant(user)
    contact = _fetch_contact_owned(twin_id, contact_id, tenant_id)

    # Resolve owner's display name for assignee matching
    owner_name = _resolve_owner_name(user)

    # --- 1. Get linked meeting IDs ---
    try:
        link_resp = (
            supabase.table("contact_meetings")
            .select("meeting_id")
            .eq("contact_id", contact_id)
            .eq("tenant_id", tenant_id)
            .eq("twin_id", twin_id)
            .execute()
        )
        links = getattr(link_resp, "data", None) or []
    except Exception as exc:
        logger.warning("[contacts/analysis] contact_meetings lookup failed contact=%s err=%s",
                       contact_id, type(exc).__name__)
        links = []

    # --- 2. Fetch meetings (tenant-scoped, exclude deleted, newest first) ---
    meeting_rows: list[dict[str, Any]] = []
    if links:
        meeting_ids = [lnk["meeting_id"] for lnk in links]
        try:
            m_resp = (
                supabase.table("meetings")
                .select("id, title, meeting_start, meeting_end, status, action_items")
                .in_("id", meeting_ids)
                .eq("tenant_id", tenant_id)
                .neq("status", "deleted")
                .order("meeting_start", desc=True)
                .execute()
            )
            meeting_rows = getattr(m_resp, "data", None) or []
        except Exception as exc:
            logger.warning("[contacts/analysis] meetings fetch failed contact=%s err=%s",
                           contact_id, type(exc).__name__)
            raise HTTPException(status_code=500, detail="Could not load meeting data") from exc

    # --- 3. Compute open loops + memory mentions via shared helper ---
    person_ctx = build_person_context(
        supabase,
        twin_id=twin_id,
        tenant_id=tenant_id,
        contact=contact,
        meeting_rows=meeting_rows,
        owner_name=owner_name,
    )

    you_owe_out = [OpenLoop(**loop) for loop in person_ctx.you_owe]
    them_owe_out = [OpenLoop(**loop) for loop in person_ctx.they_owe]

    stats = _AnalysisStats(
        last_talked=contact.get("last_seen_at"),
        total_meetings=contact.get("meeting_count", 0) or 0,
        open_loops_you_owe=len(you_owe_out),
        open_loops_they_owe=len(them_owe_out),
    )
    loops = _OpenLoopBuckets(
        you_owe=you_owe_out,
        they_owe=them_owe_out,
        skipped_count=person_ctx.skipped_count,
        truncated=person_ctx.truncated,
    )
    data = _AnalysisData(
        stats=stats,
        open_loops=loops,
        memory_mentions=[MemoryMention(**m) for m in person_ctx.memory_mentions],
    )

    duration_ms = round((datetime.now(timezone.utc) - t_start).total_seconds() * 1000)
    logger.info(
        "[contacts/analysis] analysis_requested contact=%s twin=%s meetings_scanned=%d duration_ms=%d",
        contact_id, twin_id, len(meeting_rows), duration_ms,
    )

    return {
        "status": "ok",
        "data": data.model_dump(),
        "meta": {
            "generated_at": t_start.isoformat(),
            "schema_version": "1",
        },
    }
