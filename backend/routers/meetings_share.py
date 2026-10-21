"""Meeting share-recap endpoints — Wave 5.

POST   /v2/meetings/{twin_id}/{meeting_id}/share   → mint/return share token
DELETE /v2/meetings/{twin_id}/{meeting_id}/share   → revoke (soft)
GET    /m/{share_token}                            → public, anonymous

POST + DELETE are tenant-scoped. GET is public; RLS enforces the share gate
(see migration 20260520_w5_w7_share_and_audit.sql).
"""

from __future__ import annotations

import logging
import os
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from modules.observability import supabase
from routers.meetings import _get_current_user, _require_meeting_intelligence
from services.share_redact import redact_for_public_share, public_owner_display

logger = logging.getLogger(__name__)

router = APIRouter(tags=["meetings-share"])


# ─────────────────────────────────────────────────────────────────────────────
# Request schemas
# ─────────────────────────────────────────────────────────────────────────────

class CreateShareRequest(BaseModel):
    """Body for POST /share. All optional with safe defaults."""
    expires_in_days: int | None = Field(default=7, ge=1, le=365)
    # null = never expires; 7 = default per W5 plan (Fathom-style trust default)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _frontend_base_url() -> str:
    """Where the share link points. Reads FRONTEND_URL, falls back to prod."""
    return os.getenv("FRONTEND_URL", "https://personaon.com").rstrip("/")


def _build_share_url(share_token: str) -> str:
    return f"{_frontend_base_url()}/m/{share_token}"


def _resolve_expires_at(expires_in_days: int | None) -> str | None:
    if not expires_in_days:
        return None
    return (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat()


def _is_expired(iso_string: str) -> bool:
    """True if the ISO-8601 timestamp is in the past.

    Supabase returns TIMESTAMPTZ as 'Z'-suffixed strings; our generator emits
    '+00:00'. Lexicographic comparison breaks across that formatting (the
    character 'Z' < '+'), so we always parse to datetime first.
    """
    try:
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        # Malformed timestamp — treat as expired (fail closed).
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt <= datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# POST /share — mint or return existing
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/v2/meetings/{twin_id}/{meeting_id}/share",
    dependencies=[Depends(_require_meeting_intelligence)],
)
async def create_or_get_share(
    twin_id: str,
    meeting_id: str,
    body: CreateShareRequest,
    request: Request,
) -> dict[str, Any]:
    """Mint a share token for this meeting, or return the existing one.

    Idempotent: re-calling with the same meeting_id returns the existing
    token unless it was revoked, in which case we generate a fresh one
    and clear `share_revoked_at`.
    """
    user = _get_current_user(request)
    tenant_id = user.get("tenant_id") or user.get("id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant context")

    # Fetch current share state, tenant-scoped
    resp = (
        supabase.table("meetings")
        .select(
            "id,share_token,share_enabled,share_expires_at,share_created_at,"
            "share_revoked_at,share_view_count,share_last_viewed_at"
        )
        .eq("id", meeting_id)
        .eq("twin_id", twin_id)
        .eq("tenant_id", tenant_id)
        .single()
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = resp.data

    existing_token = meeting.get("share_token")
    is_revoked = meeting.get("share_revoked_at") is not None
    is_enabled = bool(meeting.get("share_enabled"))

    # Mint a new token if we have none, OR the existing one was revoked.
    new_expires_at = _resolve_expires_at(body.expires_in_days)
    if not existing_token or is_revoked:
        new_token = str(_uuid.uuid4())
        update_payload: dict[str, Any] = {
            "share_token": new_token,
            "share_enabled": True,
            "share_created_at": _now_iso(),
            "share_revoked_at": None,
            "share_view_count": 0,
            "share_last_viewed_at": None,
            "share_expires_at": new_expires_at,
        }
        upd = (
            supabase.table("meetings")
            .update(update_payload)
            .eq("id", meeting_id)
            .eq("twin_id", twin_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not upd.data:
            raise HTTPException(status_code=500, detail="Failed to mint share token")
        meeting = upd.data[0]
    else:
        # Token exists and not revoked. Apply any change to expires/enabled
        # so the user's expiry-dropdown click takes effect (idempotent calls
        # must reflect the request body, not silently no-op).
        update_payload = {}
        if not is_enabled:
            update_payload["share_enabled"] = True
        if meeting.get("share_expires_at") != new_expires_at:
            update_payload["share_expires_at"] = new_expires_at
        if update_payload:
            upd = (
                supabase.table("meetings")
                .update(update_payload)
                .eq("id", meeting_id)
                .eq("twin_id", twin_id)
                .eq("tenant_id", tenant_id)
                .execute()
            )
            if upd.data:
                meeting = upd.data[0]

    token = meeting.get("share_token") or ""
    return {
        "status": "ok",
        "data": {
            "share_token": token,
            "share_url": _build_share_url(token) if token else None,
            "share_enabled": bool(meeting.get("share_enabled")),
            "share_expires_at": meeting.get("share_expires_at"),
            "share_created_at": meeting.get("share_created_at"),
            "share_view_count": int(meeting.get("share_view_count") or 0),
            "share_last_viewed_at": meeting.get("share_last_viewed_at"),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /share — revoke (soft)
# ─────────────────────────────────────────────────────────────────────────────

@router.delete(
    "/v2/meetings/{twin_id}/{meeting_id}/share",
    dependencies=[Depends(_require_meeting_intelligence)],
)
async def revoke_share(
    twin_id: str,
    meeting_id: str,
    request: Request,
) -> dict[str, Any]:
    """Soft-revoke the share token. Token is kept for audit trail but the
    public route returns 404 (RLS gate hides revoked rows).
    """
    user = _get_current_user(request)
    tenant_id = user.get("tenant_id") or user.get("id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant context")

    upd = (
        supabase.table("meetings")
        .update({"share_enabled": False, "share_revoked_at": _now_iso()})
        .eq("id", meeting_id)
        .eq("twin_id", twin_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not upd.data:
        raise HTTPException(status_code=404, detail="Meeting not found")

    return {"status": "ok", "data": {"share_revoked_at": upd.data[0].get("share_revoked_at")}}


# ─────────────────────────────────────────────────────────────────────────────
# GET /m/{share_token} — public, anonymous read
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/m/{share_token}")
async def get_public_share(share_token: str) -> dict[str, Any]:
    """Public recap view. No auth.

    The RLS policy on `meetings` enforces the share gate:
      share_enabled AND NOT revoked AND not expired AND token IS NOT NULL.

    We use the service role to read (RLS is bypassed there), but we manually
    re-check the gate in Python before returning to keep the contract honest
    if someone misconfigures RLS.
    """
    # Validate token shape early — avoids DB hits for garbage requests.
    try:
        _uuid.UUID(share_token)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Not found")

    # SECURITY: Allowlist columns explicitly. Never `select("*")` here —
    # any future column added to `meetings` would default to public.
    # If a new column should be public, add it to this list deliberately.
    _PUBLIC_COLUMNS = (
        "id,twin_id,tenant_id,title,status,meeting_start,meeting_end,"
        "duration_seconds,summary,summary_json,recap,recap_version,"
        "recap_corrected_at,intent_vs_outcome,action_items,commitments,"
        "decisions,topics,unanswered_questions,people_observed,attendees_json,"
        # Share-state needed for gate re-check below — stripped by redact_for_public_share before response.
        "share_token,share_enabled,share_revoked_at,share_expires_at"
    )
    resp = (
        supabase.table("meetings")
        .select(_PUBLIC_COLUMNS)
        .eq("share_token", share_token)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Not found")
    meeting = rows[0]

    # Re-enforce the gate (defense in depth — never trust service role to gate)
    if not meeting.get("share_enabled"):
        raise HTTPException(status_code=404, detail="Not found")
    if meeting.get("share_revoked_at"):
        raise HTTPException(status_code=404, detail="Not found")
    expires_at = meeting.get("share_expires_at")
    if expires_at and _is_expired(expires_at):
        raise HTTPException(status_code=404, detail="Not found")

    now_iso = _now_iso()

    # Fetch owner display name (for "Shared by ..." footer).
    twin_id = meeting.get("twin_id")
    owner_display = {"name": "PersonaOn user"}
    if twin_id:
        try:
            twin_resp = (
                supabase.table("twins")
                .select("name")
                .eq("id", twin_id)
                .single()
                .execute()
            )
            owner_display = public_owner_display(twin_resp.data)
        except Exception as exc:
            logger.warning("[ShareRecap] owner lookup failed twin=%s: %s", twin_id, exc)

    # Bump view counter best-effort. Never blocks the read.
    try:
        new_count = int(meeting.get("share_view_count") or 0) + 1
        supabase.table("meetings").update({
            "share_view_count": new_count,
            "share_last_viewed_at": now_iso,
        }).eq("id", meeting["id"]).execute()
    except Exception as exc:
        logger.warning("[ShareRecap] view count bump failed: %s", exc)

    redacted = redact_for_public_share(meeting)
    return {
        "status": "ok",
        "data": {
            "meeting": redacted,
            "owner": owner_display,
        },
    }
