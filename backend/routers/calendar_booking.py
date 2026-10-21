"""Calendar router -- Google Calendar OAuth, availability slots, and booking management.

Public endpoints allow visitors to view open slots and request bookings.
Authenticated endpoints let the persona owner connect Google Calendar,
manage booking requests (approve / reject), and check connection status.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from modules.auth_guard import require_tenant, verify_twin_ownership
from modules.observability import get_supabase_client
from modules.share_links import _fetch_twin_row, is_publicly_accessible_twin_record

logger = logging.getLogger(__name__)

router = APIRouter(tags=["calendar"])

# ── OAuth config ─────────────────────────────────────────────────────────────

GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_OAUTH_REDIRECT_URI = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://personaon.com")
CALENDAR_OAUTH_RETURN_PATH = os.getenv("CALENDAR_OAUTH_RETURN_PATH", "/dashboard")
RECALL_API_KEY = os.getenv("RECALL_API_KEY", "")
RECALL_API_REGION = os.getenv("RECALL_API_REGION", "us-east-1")
RECALL_BASE_URL = f"https://{RECALL_API_REGION}.recall.ai/api/v1"
CALENDAR_OAUTH_PROVIDER = os.getenv("CALENDAR_OAUTH_PROVIDER", "recall").lower()

_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]

_RECALL_GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
]

# Microsoft OAuth config — credentials wired to Cloud Run secrets when ready
MS_OAUTH_CLIENT_ID = os.getenv("MS_OAUTH_CLIENT_ID", "")
MS_OAUTH_CLIENT_SECRET = os.getenv("MS_OAUTH_CLIENT_SECRET", "")
MS_OAUTH_REDIRECT_URI = os.getenv("MS_OAUTH_REDIRECT_URI", "")
MS_OAUTH_AUTHORIZE_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MS_OAUTH_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

_MS_SCOPES = [
    "https://graph.microsoft.com/Calendars.ReadWrite",
    "https://graph.microsoft.com/User.Read",
    "offline_access",
]

# ── Rate limiting (booking) ──────────────────────────────────────────────────

_booking_rate_limits: dict[str, list[float]] = defaultdict(list)
_BOOKING_RATE_LIMIT = 5       # max requests per window per IP+twin
_BOOKING_RATE_WINDOW = 3600   # 1 hour


def _enqueue_initial_recall_sync(
    *,
    user_id: str,
    twin_id: str,
    recall_calendar_id: str,
    platform: str,
) -> None:
    """Trigger an immediate calendar event sync after a successful OAuth connect.

    Recall's ``calendar.sync_events`` webhook does NOT fire on initial calendar
    registration -- it only fires on subsequent change events (or periodic
    sync, which can be hours away). Without this enqueue, users see an empty
    meetings list until they edit a calendar event or the periodic sync runs.

    Failures are non-fatal: the OAuth flow still completes and Recall will
    eventually push events via webhook on the next change.
    """
    from modules.auth_guard import resolve_tenant_id
    from modules.graph_outbox import GraphOperationType, get_graph_outbox

    try:
        tenant_id = resolve_tenant_id(user_id)
    except Exception as exc:
        logger.warning(
            "[CalBooking] could not resolve tenant_id for initial Recall sync "
            "user=%s twin=%s recall_cal_id=%s: %s",
            user_id, twin_id, recall_calendar_id, exc,
        )
        return

    if not tenant_id:
        logger.warning(
            "[CalBooking] empty tenant_id; skipping initial Recall sync "
            "user=%s twin=%s recall_cal_id=%s",
            user_id, twin_id, recall_calendar_id,
        )
        return

    try:
        get_graph_outbox().submit(
            tenant_id=tenant_id,
            twin_id=twin_id,
            operation=GraphOperationType.RECALL_CALENDAR_SYNC,
            idempotency_key=f"recall_calendar_initial_sync:{recall_calendar_id}",
            payload={
                "recall_calendar_id": recall_calendar_id,
                "twin_id": twin_id,
                "tenant_id": tenant_id,
                # last_updated_ts unset -> worker pulls all events on this calendar
                "last_updated_ts": None,
            },
            priority=5,
        )
        logger.info(
            "[CalBooking] enqueued initial Recall sync twin=%s platform=%s recall_cal_id=%s",
            twin_id, platform, recall_calendar_id,
        )
    except Exception as exc:
        logger.warning(
            "[CalBooking] failed to enqueue initial Recall sync "
            "twin=%s platform=%s recall_cal_id=%s: %s",
            twin_id, platform, recall_calendar_id, exc,
        )


async def _disconnect_stale_recall_calendar(
    existing_data: list[dict] | None,
    *,
    twin_id: str,
    platform: str,
) -> None:
    """Delete any pre-existing Recall calendar for this twin before re-registering.

    Recall V2 has no "update credentials" endpoint; re-running OAuth without
    this step orphans the old calendar on Recall (one per re-connect attempt).
    Failures are non-fatal: the caller proceeds to register a new calendar.
    """
    if not existing_data:
        return
    old_id = existing_data[0].get("recall_calendar_id")
    if not old_id:
        return

    from services import recall_calendar_v2  # lazy: avoid import at module load

    try:
        await recall_calendar_v2.disconnect_calendar(old_id)
        logger.info(
            "[CalBooking] disconnected stale Recall calendar twin=%s platform=%s old_recall_cal_id=%s",
            twin_id, platform, old_id,
        )
    except Exception as disconnect_exc:
        logger.warning(
            "[CalBooking] failed to disconnect stale Recall calendar "
            "twin=%s platform=%s old_recall_cal_id=%s: %s",
            twin_id, platform, old_id, disconnect_exc,
        )


def _check_booking_rate_limit(tracking_key: str) -> bool:
    """Return True if the request is allowed, False if rate-limited."""
    now = time.time()
    window_start = now - _BOOKING_RATE_WINDOW
    _booking_rate_limits[tracking_key] = [
        t for t in _booking_rate_limits[tracking_key] if t > window_start
    ]
    if len(_booking_rate_limits[tracking_key]) >= _BOOKING_RATE_LIMIT:
        return False
    _booking_rate_limits[tracking_key].append(now)
    return True


def _get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    return (
        forwarded_for.split(",")[0].strip()
        if forwarded_for
        else (request.client.host if request.client else "unknown")
    )


# ── OAuth state store (Supabase-backed, with in-memory fallback) ────────────

# State must survive across Cloud Run instances -- the OAuth flow generates
# the state on instance A but the provider may redirect the callback to
# instance B, in which case an in-memory dict misses every time. Persist to
# `public.oauth_states` (migration 20260613000300) so all instances share it.
# The in-memory dict stays as a local-dev fallback when Supabase is
# unreachable (no env vars, dev env, etc.).
# Audit 2026-05-31 security pass.

_oauth_states: dict[str, dict[str, Any]] = {}
_OAUTH_STATE_TTL = 600  # 10 minutes


def _oauth_state_table():
    """Lazy Supabase table handle; returns None on any failure so callers
    transparently fall back to the in-memory dict."""
    try:
        sb = get_supabase_client()
        return sb.table("oauth_states") if sb is not None else None
    except Exception as exc:
        logger.debug("[OAuth] Supabase unavailable, using in-memory: %s", exc)
        return None


def _save_oauth_state(state: str, data: dict[str, Any]) -> None:
    """Persist OAuth state with a 10-min TTL.

    Prefers the Supabase-backed table (works across Cloud Run instances);
    falls back to the in-memory dict on any DB error so local dev keeps
    working without Supabase configured.
    """
    table = _oauth_state_table()
    if table is not None:
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            expires_iso = (
                datetime.now(timezone.utc) + timedelta(seconds=_OAUTH_STATE_TTL)
            ).isoformat()
            # Best-effort sweep of expired rows before insert.
            try:
                table.delete().lt("expires_at", now_iso).execute()
            except Exception:
                pass
            # PersonaOn single-tenant convention: tenant_id == user_id. Existing
            # call sites pass user_id only; fall back to it for the row's
            # tenant_id column (which is the table's CHECK constraint input).
            tenant_id = data.get("tenant_id") or data.get("user_id")
            provider = data.get("provider")
            if not tenant_id or not provider:
                raise ValueError(
                    f"OAuth state requires tenant_id/user_id and provider; got tenant_id={tenant_id!r}, provider={provider!r}"
                )
            table.insert({
                "state": state,
                "tenant_id": str(tenant_id),
                "provider": str(provider),
                "payload": data,
                "created_at": now_iso,
                "expires_at": expires_iso,
            }).execute()
            return
        except Exception as exc:
            logger.warning(
                "[OAuth] DB store failed for state=%s..., falling back to in-memory: %s",
                state[:8], exc,
            )
    # Fallback: in-memory.
    _cleanup_expired_states_local()
    _oauth_states[state] = {**data, "_created_at": time.time()}


# Backward-compat alias matching existing call sites.
_store_oauth_state = _save_oauth_state


def _pop_oauth_state(state: str) -> dict[str, Any] | None:
    """Atomically read + delete an OAuth state entry.

    Returns the original payload (without internal bookkeeping fields) or
    None if the state is unknown / expired. Single-use semantics: a second
    pop for the same state always returns None.
    """
    table = _oauth_state_table()
    if table is not None:
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            # PostgREST DELETE with `returning=representation` (the default in
            # supabase-py) returns the deleted rows. Filter expires_at >= now
            # so expired rows are not returned even if the sweep hasn't fired.
            resp = (
                table.delete()
                .eq("state", state)
                .gte("expires_at", now_iso)
                .execute()
            )
            rows = getattr(resp, "data", None) or []
            if rows:
                payload = rows[0].get("payload") or {}
                # Best-effort expired-row sweep.
                try:
                    table.delete().lt("expires_at", now_iso).execute()
                except Exception:
                    pass
                return payload
            # Not found in DB; fall through to in-memory in case this
            # process saved it locally before Supabase came back online.
        except Exception as exc:
            logger.warning(
                "[OAuth] DB pop failed for state=%s..., trying in-memory: %s",
                state[:8], exc,
            )
    # Fallback: in-memory.
    _cleanup_expired_states_local()
    entry = _oauth_states.pop(state, None)
    if entry:
        entry.pop("_created_at", None)
    return entry


def _cleanup_expired_states_local() -> None:
    """Sweep expired entries from the in-memory dict (no-op for DB path)."""
    now = time.time()
    expired = [
        k for k, v in _oauth_states.items()
        if now - v.get("_created_at", 0) > _OAUTH_STATE_TTL
    ]
    for k in expired:
        _oauth_states.pop(k, None)


# Backward-compat alias for any tests patching the old helper name.
_cleanup_expired_states = _cleanup_expired_states_local


# ── Helpers ──────────────────────────────────────────────────────────────────

def _public_twin_or_404(twin_id: str) -> None:
    """Verify the twin exists and is publicly accessible."""
    twin = _fetch_twin_row(twin_id)
    if not twin or not is_publicly_accessible_twin_record(twin):
        raise HTTPException(status_code=404, detail="Twin not found")


def _recall_google_redirect_uri() -> str:
    # The Recall-hosted calendar flow must send Google's redirect to RECALL's
    # callback (Recall completes the token exchange and holds the tokens), NOT
    # our native /v2/calendar/oauth/callback. Use a dedicated env so it never
    # collides with GOOGLE_OAUTH_REDIRECT_URI, which is the native-flow callback
    # — that collision was the source of the gcal=error&reason=invalid_state bug.
    redirect_uri = (
        os.getenv("RECALL_GOOGLE_REDIRECT_URI", "").strip()
        or f"{RECALL_BASE_URL}/calendar/google_oauth_callback/"
    )
    if redirect_uri.rstrip("/").endswith("/calendar/google_oauth_callback"):
        return f"{redirect_uri.rstrip('/')}/"
    return redirect_uri


def _frontend_calendar_url(status: str, reason: str | None = None, param: str = "gcal") -> str:
    # Always route back to CALENDAR_OAUTH_RETURN_PATH (default /dashboard). The
    # old /dashboard/meetings route was removed in the new app and 404s.
    query = {param: status}
    if reason:
        query["reason"] = reason
    return f"{FRONTEND_URL.rstrip()}/{CALENDAR_OAUTH_RETURN_PATH.strip('/')}?{urlencode(query)}"


async def _create_recall_calendar_auth_token(twin_id: str, user_id: str) -> str:
    """Create a Recall.ai calendar auth token for a Google Calendar OAuth grant."""
    import httpx

    payload = {
        # Recall Calendar V1 expects a stable top-level user_id. The twin_id is
        # kept out of the token request because extra payload fields are not part
        # of the documented contract.
        "user_id": user_id,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"{RECALL_BASE_URL}/calendar/authenticate/",
            json=payload,
            headers={
                "Authorization": f"Token {RECALL_API_KEY}",
                "Content-Type": "application/json",
            },
        )

    if response.status_code >= 400:
        logger.error(
            "Recall calendar auth-token failed: status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
        raise HTTPException(
            status_code=502,
            detail="Recall Calendar auth token request failed.",
        )

    data = response.json()
    token = data.get("token") or data.get("auth_token") or data.get("recall_calendar_auth_token")
    if not token:
        logger.error("Recall calendar auth-token response missing token: %s", data)
        raise HTTPException(
            status_code=502,
            detail="Recall Calendar auth token response was incomplete.",
        )
    return str(token)


async def _recall_google_authorization_url(twin_id: str, user_id: str) -> str:
    if not RECALL_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="Recall Calendar OAuth is not configured. Missing RECALL_API_KEY.",
        )
    if not GOOGLE_OAUTH_CLIENT_ID:
        raise HTTPException(
            status_code=500,
            detail="Recall Calendar OAuth is not configured. Missing GOOGLE_OAUTH_CLIENT_ID.",
        )

    auth_token = await _create_recall_calendar_auth_token(twin_id, user_id)
    state = json.dumps(
        {
            "recall_calendar_auth_token": auth_token,
            "google_oauth_redirect_url": _recall_google_redirect_uri(),
            "success_url": _frontend_calendar_url("connected"),
            "error_url": _frontend_calendar_url("error", "recall_oauth_failed"),
        },
        separators=(",", ":"),
    )
    params = {
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": _recall_google_redirect_uri(),
        "response_type": "code",
        "scope": " ".join(_RECALL_GOOGLE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


# ── Schemas ──────────────────────────────────────────────────────────────────

class BookingCreateRequest(BaseModel):
    visitor_name: str = Field(..., min_length=1, max_length=200)
    visitor_email: str = Field(..., min_length=3, max_length=200)
    visitor_message: str | None = Field(None, max_length=2000)
    proposed_start: str = Field(..., description="ISO 8601 datetime with timezone")
    proposed_end: str = Field(..., description="ISO 8601 datetime with timezone")
    visitor_timezone: str | None = Field("UTC", max_length=100)


class BookingCreateResponse(BaseModel):
    booking_id: str
    status: str
    message: str


class BookingRejectRequest(BaseModel):
    reason: str | None = Field(None, max_length=2000)


# ═════════════════════════════════════════════════════════════════════════════
# OAuth Flow
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/v2/calendar/oauth/authorize")
async def oauth_authorize(
    twin_id: str = Query(..., description="Twin to connect calendar for"),
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """Generate a Google OAuth authorization URL for the authenticated owner."""
    verify_twin_ownership(twin_id, user)

    if CALENDAR_OAUTH_PROVIDER == "recall" or (RECALL_API_KEY and not GOOGLE_OAUTH_CLIENT_SECRET):
        auth_url = await _recall_google_authorization_url(twin_id, str(user["user_id"]))
        return {"authorization_url": auth_url, "provider": "recall"}

    if not GOOGLE_OAUTH_CLIENT_ID or not GOOGLE_OAUTH_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Google OAuth is not configured on this server. Missing GOOGLE_OAUTH_CLIENT_ID or GOOGLE_OAUTH_CLIENT_SECRET.",
        )

    state = str(uuid.uuid4())
    _store_oauth_state(state, {
        "twin_id": twin_id,
        "user_id": user["user_id"],
        "provider": "google",
    })

    params = {
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

    return {"authorization_url": auth_url, "state": state}


@router.get("/v2/calendar/oauth/callback")
async def oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
) -> RedirectResponse:
    """Handle the Google OAuth callback, exchange code for tokens, store them."""
    state_data = _pop_oauth_state(state)
    if not state_data:
        return RedirectResponse(url=_frontend_calendar_url("error", "invalid_state"))

    twin_id = state_data["twin_id"]

    # Exchange authorization code for tokens
    token_payload = {
        "code": code,
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
        "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data=token_payload,
            )
            if resp.status_code != 200:
                # Avoid logging full response body (may echo OAuth code, client
                # identifiers, or other PII). Extract just the standard OAuth
                # `error` code; mirror the Microsoft callback at line ~635.
                err_code = "unknown"
                try:
                    if "application/json" in (resp.headers.get("content-type") or ""):
                        err_code = (resp.json() or {}).get("error", "unknown")
                except Exception:
                    pass
                logger.error(
                    "[CalBooking] Google token exchange failed: status=%s error=%s",
                    resp.status_code, err_code,
                )
                return RedirectResponse(url=_frontend_calendar_url("error", "token_exchange_failed"))
            token_data = resp.json()
    except Exception as exc:
        logger.error("Token exchange request failed: %s", exc)
        return RedirectResponse(url=_frontend_calendar_url("error", "network_error"))

    # Build credentials JSON to store
    creds_json = {
        "token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
        "scopes": _SCOPES,
    }

    sb = get_supabase_client()

    # Upsert connector row
    try:
        existing = (
            sb.table("tool_connectors")
            .select("id, recall_calendar_id")
            .eq("twin_id", twin_id)
            .eq("connector_type", "google_calendar")
            .limit(1)
            .execute()
        )

        now_iso = datetime.now(timezone.utc).isoformat()

        if existing.data:
            sb.table("tool_connectors").update({
                "credentials_encrypted": json.dumps(creds_json),
                "is_active": True,
                "last_error": None,
                "updated_at": now_iso,
            }).eq("id", existing.data[0]["id"]).execute()
        else:
            sb.table("tool_connectors").insert({
                "twin_id": twin_id,
                "connector_type": "google_calendar",
                "name": "Google Calendar",
                "credentials_encrypted": json.dumps(creds_json),
                "config": {"scopes": _SCOPES},
                "is_active": True,
            }).execute()

        logger.info("Google Calendar connected for twin %s", twin_id)
    except Exception as exc:
        logger.error("Failed to store Google Calendar credentials for twin %s: %s", twin_id, exc)
        return RedirectResponse(url=_frontend_calendar_url("error", "storage_failed"))

    # Register the same refresh_token with Recall.ai Calendar V2 so they can sync
    # calendar events + auto-dispatch meeting bots. Non-fatal: if Recall is down,
    # the booking flow still works on the credentials we just stored locally.
    recall_cal: dict | None = None
    refresh_token = token_data.get("refresh_token")
    if refresh_token:
        try:
            from services import recall_calendar_v2

            await _disconnect_stale_recall_calendar(
                existing.data, twin_id=twin_id, platform="google_calendar"
            )

            backend_base = os.getenv("CLOUD_RUN_SERVICE_URL", "").strip()
            recall_webhook_url = (
                f"{backend_base.rstrip('/')}/v2/meeting-calendar/webhook"
                if backend_base.startswith("http")
                else None
            )
            recall_cal = await recall_calendar_v2.register_calendar(
                twin_id=twin_id,
                platform="google_calendar",
                oauth_refresh_token=refresh_token,
                oauth_client_id=GOOGLE_OAUTH_CLIENT_ID,
                oauth_client_secret=GOOGLE_OAUTH_CLIENT_SECRET,
                webhook_url=recall_webhook_url,
            )
        except Exception as exc:
            # Non-fatal: Recall side is down; local booking flow continues to work.
            logger.warning(
                "[CalBooking] Recall Calendar V2 registration failed twin=%s: %s",
                twin_id,
                exc,
            )
            # Mark the row so the status endpoint can surface a "needs reconnect"
            # signal to the UI -- otherwise the user sees connected=true but
            # webhooks/events never arrive.
            try:
                sb.table("tool_connectors").update({
                    "last_error": f"recall_register_failed: {exc}",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("twin_id", twin_id).eq("connector_type", "google_calendar").execute()
            except Exception as mark_exc:
                logger.warning(
                    "[CalBooking] failed to write last_error twin=%s: %s",
                    twin_id, mark_exc,
                )

        if recall_cal:
            recall_calendar_id = recall_cal.get("id")
            if recall_calendar_id:
                try:
                    sb.table("tool_connectors").update({
                        "recall_calendar_id": recall_calendar_id,
                        "last_error": None,
                    }).eq("twin_id", twin_id).eq("connector_type", "google_calendar").execute()
                    logger.info(
                        "[CalBooking] Recall Calendar V2 registered twin=%s recall_cal_id=%s",
                        twin_id,
                        recall_calendar_id,
                    )
                except Exception as exc:
                    # Non-fatal but distinct failure mode: Recall is now hot but our
                    # local row doesn't know it. Future disconnect will skip Recall
                    # deregistration -> orphaned subscription. Logged separately so
                    # operators can monitor for this distinct failure.
                    logger.warning(
                        "[CalBooking] failed to persist recall_calendar_id twin=%s recall_cal_id=%s: %s",
                        twin_id,
                        recall_calendar_id,
                        exc,
                    )

                _enqueue_initial_recall_sync(
                    user_id=str(state_data["user_id"]),
                    twin_id=twin_id,
                    recall_calendar_id=recall_calendar_id,
                    platform="google_calendar",
                )
    else:
        logger.warning(
            "[CalBooking] no refresh_token in Google response twin=%s -- Recall sync skipped",
            twin_id,
        )

    return RedirectResponse(url=_frontend_calendar_url("connected"))


# ─── Microsoft Outlook OAuth (Task P1.1.C) ──────────────────────────────────

@router.get("/v2/calendar/microsoft/oauth/authorize")
async def microsoft_oauth_authorize(
    twin_id: str = Query(..., description="Twin to connect Microsoft calendar for"),
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """Generate a Microsoft OAuth authorization URL for the authenticated owner."""
    verify_twin_ownership(twin_id, user)

    if not MS_OAUTH_CLIENT_ID or not MS_OAUTH_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Microsoft OAuth is not configured on this server.",
        )

    state = str(uuid.uuid4())
    _store_oauth_state(state, {
        "twin_id": twin_id,
        "user_id": user["user_id"],
        "provider": "microsoft",
    })

    params = {
        "client_id": MS_OAUTH_CLIENT_ID,
        "redirect_uri": MS_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(_MS_SCOPES),
        "response_mode": "query",
        "state": state,
    }
    auth_url = f"{MS_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

    return {"authorization_url": auth_url, "state": state}


@router.get("/v2/calendar/microsoft/oauth/callback")
async def microsoft_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
) -> RedirectResponse:
    """Handle the Microsoft OAuth callback, exchange code for tokens, store them."""
    state_data = _pop_oauth_state(state)
    if not state_data:
        return RedirectResponse(url=_frontend_calendar_url("error", "invalid_state", "outlook"))

    twin_id = state_data["twin_id"]

    # Exchange authorization code for tokens
    token_payload = {
        "code": code,
        "client_id": MS_OAUTH_CLIENT_ID,
        "client_secret": MS_OAUTH_CLIENT_SECRET,
        "redirect_uri": MS_OAUTH_REDIRECT_URI,
        "grant_type": "authorization_code",
        "scope": " ".join(_MS_SCOPES),
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(MS_OAUTH_TOKEN_URL, data=token_payload)
            if resp.status_code != 200:
                # Avoid logging full response body (may contain user identifiers,
                # tenant info, or other sensitive PII). Extract just the standard
                # OAuth `error` code if present.
                err_code = "unknown"
                try:
                    if "application/json" in (resp.headers.get("content-type") or ""):
                        err_code = (resp.json() or {}).get("error", "unknown")
                except Exception:
                    pass
                logger.error(
                    "[CalBooking] Microsoft token exchange failed: status=%s error=%s",
                    resp.status_code, err_code,
                )
                return RedirectResponse(
                    url=_frontend_calendar_url("error", "token_exchange_failed", "outlook")
                )
            token_data = resp.json()
    except Exception as exc:
        logger.error("[CalBooking] Microsoft token request failed: %s", exc)
        return RedirectResponse(url=_frontend_calendar_url("error", "network_error", "outlook"))

    creds_json = {
        "token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "token_uri": MS_OAUTH_TOKEN_URL,
        "client_id": MS_OAUTH_CLIENT_ID,
        "client_secret": MS_OAUTH_CLIENT_SECRET,
        "scopes": _MS_SCOPES,
    }

    sb = get_supabase_client()

    try:
        existing = (
            sb.table("tool_connectors")
            .select("id, recall_calendar_id")
            .eq("twin_id", twin_id)
            .eq("connector_type", "microsoft_outlook")
            .limit(1)
            .execute()
        )

        now_iso = datetime.now(timezone.utc).isoformat()

        if existing.data:
            sb.table("tool_connectors").update({
                "credentials_encrypted": json.dumps(creds_json),
                "is_active": True,
                "last_error": None,
                "updated_at": now_iso,
            }).eq("id", existing.data[0]["id"]).execute()
        else:
            sb.table("tool_connectors").insert({
                "twin_id": twin_id,
                "connector_type": "microsoft_outlook",
                "name": "Microsoft Outlook",
                "credentials_encrypted": json.dumps(creds_json),
                "config": {"scopes": _MS_SCOPES},
                "is_active": True,
            }).execute()

        logger.info("[CalBooking] Microsoft Outlook connected twin=%s", twin_id)
    except Exception as exc:
        logger.error(
            "[CalBooking] Failed to store Microsoft credentials twin=%s: %s",
            twin_id, exc,
        )
        return RedirectResponse(url=_frontend_calendar_url("error", "storage_failed", "outlook"))

    # Register with Recall.ai Calendar V2 (non-fatal, mirrors Google flow from P1.1.B)
    recall_cal: dict | None = None
    refresh_token = token_data.get("refresh_token")
    if refresh_token:
        try:
            from services import recall_calendar_v2

            await _disconnect_stale_recall_calendar(
                existing.data, twin_id=twin_id, platform="microsoft_outlook"
            )

            backend_base = os.getenv("CLOUD_RUN_SERVICE_URL", "").strip()
            recall_webhook_url = (
                f"{backend_base.rstrip('/')}/v2/meeting-calendar/webhook"
                if backend_base.startswith("http")
                else None
            )
            recall_cal = await recall_calendar_v2.register_calendar(
                twin_id=twin_id,
                platform="microsoft_outlook",
                oauth_refresh_token=refresh_token,
                oauth_client_id=MS_OAUTH_CLIENT_ID,
                oauth_client_secret=MS_OAUTH_CLIENT_SECRET,
                webhook_url=recall_webhook_url,
            )
        except Exception as exc:
            logger.warning(
                "[CalBooking] Recall Calendar V2 registration failed twin=%s platform=microsoft_outlook: %s",
                twin_id, exc,
            )
            # See Google callback above: surface the failure via last_error so
            # the status endpoint can prompt a reconnect.
            try:
                sb.table("tool_connectors").update({
                    "last_error": f"recall_register_failed: {exc}",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("twin_id", twin_id).eq("connector_type", "microsoft_outlook").execute()
            except Exception as mark_exc:
                logger.warning(
                    "[CalBooking] failed to write last_error twin=%s platform=microsoft_outlook: %s",
                    twin_id, mark_exc,
                )

        if recall_cal:
            recall_calendar_id = recall_cal.get("id")
            if recall_calendar_id:
                try:
                    sb.table("tool_connectors").update({
                        "recall_calendar_id": recall_calendar_id,
                        "last_error": None,
                    }).eq("twin_id", twin_id).eq("connector_type", "microsoft_outlook").execute()
                    logger.info(
                        "[CalBooking] Recall Calendar V2 registered twin=%s platform=microsoft_outlook recall_cal_id=%s",
                        twin_id, recall_calendar_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "[CalBooking] failed to persist recall_calendar_id twin=%s recall_cal_id=%s: %s",
                        twin_id, recall_calendar_id, exc,
                    )

                _enqueue_initial_recall_sync(
                    user_id=str(state_data["user_id"]),
                    twin_id=twin_id,
                    recall_calendar_id=recall_calendar_id,
                    platform="microsoft_outlook",
                )
    else:
        logger.warning(
            "[CalBooking] no refresh_token in Microsoft response twin=%s -- Recall sync skipped",
            twin_id,
        )

    return RedirectResponse(url=_frontend_calendar_url("connected", None, "outlook"))


_DISCONNECTABLE_PROVIDERS = {
    "google": "google_calendar",
    "google_calendar": "google_calendar",
    "microsoft": "microsoft_outlook",
    "outlook": "microsoft_outlook",
    "microsoft_outlook": "microsoft_outlook",
}


@router.delete("/v2/calendar/{twin_id}/disconnect")
async def disconnect_calendar(
    twin_id: str,
    provider: str = "google",
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """Remove the calendar connector for a twin (and deregister from Recall).

    Accepts ?provider=google|microsoft (default google). Previously hardcoded
    to google_calendar; Outlook users had no disconnect path.
    """
    verify_twin_ownership(twin_id, user)

    connector_type = _DISCONNECTABLE_PROVIDERS.get(provider.lower())
    if not connector_type:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unknown provider. Use 'google' or 'microsoft'."
            ),
        )

    sb = get_supabase_client()
    resp = (
        sb.table("tool_connectors")
        .select("id, recall_calendar_id")
        .eq("twin_id", twin_id)
        .eq("connector_type", connector_type)
        .limit(1)
        .execute()
    )

    if not resp.data:
        # Friendly per-provider 404 messages.
        provider_label = (
            "Google Calendar" if connector_type == "google_calendar" else "Microsoft Outlook"
        )
        raise HTTPException(status_code=404, detail=f"{provider_label} is not connected.")

    row = resp.data[0]
    recall_cal_id = row.get("recall_calendar_id")

    # Try to deregister from Recall. If it fails (Recall down, transient
    # network error, calendar already gone server-side), we do NOT hard-delete
    # the local row -- preserving recall_calendar_id lets a follow-up retry
    # (or the dedup helper on next reconnect) clean up the orphan. Hard-delete
    # only happens after Recall confirms (or when there was nothing to delete).
    recall_disconnect_ok = True
    recall_disconnect_error: str | None = None
    if recall_cal_id:
        try:
            from services import recall_calendar_v2

            await recall_calendar_v2.disconnect_calendar(recall_cal_id)
            logger.info(
                "[CalBooking] Recall Calendar V2 disconnected twin=%s recall_cal_id=%s",
                twin_id,
                recall_cal_id,
            )
        except Exception as exc:
            recall_disconnect_ok = False
            recall_disconnect_error = str(exc)
            logger.warning(
                "[CalBooking] Recall Calendar V2 disconnect failed twin=%s recall_cal_id=%s: %s",
                twin_id,
                recall_cal_id,
                exc,
            )

    if recall_disconnect_ok:
        # Clean break: hard-delete the local row so a future Connect is fresh.
        sb.table("tool_connectors").delete().eq("id", row["id"]).execute()
        logger.info(
            "[CalBooking] %s disconnected for twin %s",
            connector_type, twin_id,
        )
        return {"status": "disconnected", "twin_id": twin_id, "provider": connector_type}

    # Partial disconnect: Recall did not confirm. Soft-mark the row so:
    #   - status endpoint surfaces is_active=False + last_error to the UI
    #   - recall_calendar_id stays available for retry / next-reconnect cleanup
    # If even this write fails, still return partial_disconnect so the
    # client knows the operation was not fully successful (better than
    # a bare 500 that conveys nothing).
    try:
        sb.table("tool_connectors").update({
            "is_active": False,
            "last_error": f"recall_disconnect_failed: {recall_disconnect_error}",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", row["id"]).execute()
    except Exception as mark_exc:
        logger.warning(
            "[CalBooking] soft-mark write failed twin=%s recall_cal_id=%s: %s",
            twin_id, recall_cal_id, mark_exc,
        )

    logger.warning(
        "[CalBooking] disconnect partial twin=%s recall_cal_id=%s (Recall unreachable; row soft-marked for retry)",
        twin_id, recall_cal_id,
    )
    return {
        "status": "partial_disconnect",
        "twin_id": twin_id,
        "provider": connector_type,
        "reason": "recall_unavailable",
    }


@router.get("/v2/calendar/{twin_id}/status")
async def calendar_status(
    twin_id: str,
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """Return connection state for both Google and Microsoft calendars."""
    verify_twin_ownership(twin_id, user)

    sb = get_supabase_client()
    resp = (
        sb.table("tool_connectors")
        .select("connector_type, is_active, last_error, updated_at, recall_calendar_id")
        .eq("twin_id", twin_id)
        .in_("connector_type", ["google_calendar", "microsoft_outlook"])
        .execute()
    )

    google: dict[str, Any] = {"connected": False}
    microsoft: dict[str, Any] = {"connected": False}

    for row in (resp.data or []):
        ctype = row.get("connector_type")
        entry = {
            "connected": True,
            "is_active": bool(row.get("is_active")),
            "last_error": row.get("last_error"),
            "updated_at": row.get("updated_at"),
            "recall_synced": bool(row.get("recall_calendar_id")),
        }
        if ctype == "google_calendar":
            google = entry
        elif ctype == "microsoft_outlook":
            microsoft = entry

    return {
        # Backward-compat: top-level `connected` is true if EITHER provider is connected.
        # Frontend can use `providers.{google,microsoft}.connected` for finer state.
        "connected": google["connected"] or microsoft["connected"],
        "twin_id": twin_id,
        "providers": {
            "google": google,
            "microsoft": microsoft,
        },
    }


# ═════════════════════════════════════════════════════════════════════════════
# Public Booking Endpoints
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/v2/calendar/{twin_id}/slots")
async def get_slots(
    twin_id: str,
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    visitor_timezone: str | None = Query(None, description="Visitor IANA timezone"),
    timezone: str | None = Query(None, description="Alias for visitor_timezone (frontend back-compat)"),
) -> dict[str, Any]:
    """Return available booking slots for a twin on a given date. Public endpoint.

    Bug 2 fix: BookingCard.tsx historically sent ``?timezone=`` while this
    endpoint only accepted ``?visitor_timezone=``. Both are now accepted; the
    frontend should standardize on ``visitor_timezone`` going forward.
    """
    _public_twin_or_404(twin_id)

    from services.calendar_service import get_available_slots

    effective_timezone = visitor_timezone or timezone or "UTC"

    try:
        slots = get_available_slots(
            twin_id=twin_id,
            date_str=date,
            visitor_timezone=effective_timezone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return {"twin_id": twin_id, "date": date, "slots": slots, "count": len(slots)}


@router.post("/v2/calendar/{twin_id}/book", response_model=BookingCreateResponse)
async def create_booking(
    twin_id: str,
    body: BookingCreateRequest,
    http_request: Request,
) -> BookingCreateResponse:
    """Create a booking request. Public, rate-limited (5/hour per IP+twin)."""
    _public_twin_or_404(twin_id)

    # Rate limit
    client_ip = _get_client_ip(http_request)
    tracking_key = f"booking:{twin_id}:{client_ip}"
    if not _check_booking_rate_limit(tracking_key):
        raise HTTPException(
            status_code=429,
            detail="Too many booking requests. Please try again later.",
        )

    # Validate proposed times
    try:
        proposed_start = datetime.fromisoformat(body.proposed_start)
        proposed_end = datetime.fromisoformat(body.proposed_end)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="proposed_start and proposed_end must be valid ISO 8601 datetimes.",
        )

    if proposed_end <= proposed_start:
        raise HTTPException(
            status_code=400,
            detail="proposed_end must be after proposed_start.",
        )

    if proposed_start <= datetime.now(proposed_start.tzinfo):
        raise HTTPException(
            status_code=400,
            detail="Cannot book a slot in the past.",
        )

    # Compute duration
    duration_minutes = int((proposed_end - proposed_start).total_seconds() / 60)

    # Bug 3 fix: submit-time FreeBusy double-check. The slots endpoint computes
    # availability when the visitor opens the slot picker, but they may sit on
    # the page while another visitor (or the owner themselves) takes the slot.
    # Re-query Google immediately before insert; return 409 on conflict so the
    # frontend can refresh and show "that time was just taken".
    from services.calendar_service import freebusy_check_window
    if not freebusy_check_window(twin_id, body.proposed_start, body.proposed_end):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "slot_taken",
                "message": "That time was just taken — please pick another.",
            },
        )

    sb = get_supabase_client()
    booking_id = str(uuid.uuid4())

    booking_row = {
        "id": booking_id,
        "twin_id": twin_id,
        "visitor_name": body.visitor_name,
        "visitor_email": body.visitor_email,
        "visitor_message": body.visitor_message,
        "visitor_timezone": body.visitor_timezone or "UTC",
        "proposed_start": body.proposed_start,
        "proposed_end": body.proposed_end,
        "slot_duration_minutes": duration_minutes,
        "status": "pending",
    }
    try:
        sb.table("booking_requests").insert(booking_row).execute()
    except Exception as exc:
        logger.error("Failed to create booking request for twin %s: %s", twin_id, exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to create booking request. Please try again.",
        )

    # Phase 1 polish: notify the persona owner that a request landed. Failure
    # to send is logged but never raised — we don't want booking creation to
    # fail just because Resend is down.
    try:
        from services.booking_email import notify_owner_booking_received
        await notify_owner_booking_received(twin_id, booking_row)
    except Exception:
        logger.exception(
            "[CalendarBooking] owner notification dispatch failed booking=%s",
            booking_id,
        )

    return BookingCreateResponse(
        booking_id=booking_id,
        status="pending",
        # Message is built client-side using the persona display name; this is
        # only a safe fallback for clients that don't render their own copy.
        message="Request sent! The owner will review your booking.",
    )


# ═════════════════════════════════════════════════════════════════════════════
# Owner Endpoints
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/v2/calendar/{twin_id}/bookings")
async def list_bookings(
    twin_id: str,
    status_filter: str | None = Query(None, alias="status", description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """List booking requests for the owner's twin."""
    verify_twin_ownership(twin_id, user)

    sb = get_supabase_client()
    query = (
        sb.table("booking_requests")
        .select("*")
        .eq("twin_id", twin_id)
        .order("created_at", desc=True)
        .limit(limit)
    )

    if status_filter:
        query = query.eq("status", status_filter)

    try:
        resp = query.execute()
        bookings = resp.data if resp.data else []
    except Exception as exc:
        logger.warning("Failed to fetch bookings for twin %s: %s", twin_id, exc)
        bookings = []

    return {"bookings": bookings, "count": len(bookings)}


@router.post("/v2/calendar/{twin_id}/bookings/{booking_id}/approve")
async def approve_booking(
    twin_id: str,
    booking_id: str,
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """Approve a booking request: create a Google Calendar event with Meet link."""
    verify_twin_ownership(twin_id, user)

    sb = get_supabase_client()

    # Fetch the booking
    resp = (
        sb.table("booking_requests")
        .select("*")
        .eq("id", booking_id)
        .eq("twin_id", twin_id)
        .single()
        .execute()
    )

    if not resp.data:
        raise HTTPException(status_code=404, detail="Booking request not found.")

    booking = resp.data

    if booking["status"] != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Booking is already {booking['status']}. Only pending bookings can be approved.",
        )

    # Create Google Calendar event
    from services.calendar_service import create_booking_event

    try:
        event_result = create_booking_event(twin_id=twin_id, booking=booking)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    # Update booking row
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        sb.table("booking_requests").update({
            "status": "approved",
            "approved_at": now_iso,
            "gcal_event_id": event_result.get("event_id"),
            "meet_link": event_result.get("meet_link"),
            "event_link": event_result.get("event_link"),
            "updated_at": now_iso,
        }).eq("id", booking_id).execute()
    except Exception as exc:
        logger.error("Failed to update booking %s after approval: %s", booking_id, exc)
        # Event was created but DB update failed -- still return success with a warning
        return {
            "status": "approved",
            "booking_id": booking_id,
            "warning": "Calendar event created but database update failed. Please refresh.",
            **event_result,
        }

    # --- Phase 25: Schedule meeting bot if meeting intelligence is enabled ---
    try:
        from modules.observability import MEETING_INTELLIGENCE_ENABLED as _mtg_enabled  # noqa: F401
    except ImportError:
        _mtg_enabled = False

    _mtg_enabled = (
        __import__("os").getenv("MEETING_INTELLIGENCE_ENABLED", "false").lower() == "true"
    )
    if _mtg_enabled and event_result.get("meet_link"):
        try:
            from modules.graph_outbox import GraphOperationType, get_graph_outbox

            booking_resp = sb.table("booking_requests").select(
                "proposed_start,visitor_name"
            ).eq("id", booking_id).single().execute()
            booking_data = booking_resp.data or {}

            outbox = get_graph_outbox()
            outbox.submit(
                tenant_id=user["tenant_id"],
                twin_id=twin_id,
                operation=GraphOperationType.SCHEDULE_MEETING_BOT,
                idempotency_key=f"meeting_bot:{booking_id}",
                payload={
                    "booking_id": booking_id,
                    "twin_id": twin_id,
                    "meet_link": event_result["meet_link"],
                    # Carry the calendar identity so the worker can resolve-or-create
                    # ONE meeting row keyed by ical_uid (prevents the booking row and
                    # the calendar-synced row from duplicating). See _process_schedule_meeting_bot.
                    "ical_uid": event_result.get("ical_uid") or None,
                    "provider_event_id": event_result.get("event_id") or None,
                    "proposed_start": booking_data.get("proposed_start"),
                    "visitor_name": booking_data.get("visitor_name", "Unknown"),
                    "tenant_id": user["tenant_id"],
                },
                priority=5,
            )
            logger.info(
                "[CalendarBooking] meeting bot scheduled booking=%s twin=%s",
                booking_id, twin_id,
            )
        except Exception:
            # Non-fatal: booking approval succeeded, bot scheduling failed
            logger.exception(
                "[CalendarBooking] failed to schedule meeting bot booking=%s", booking_id
            )

    return {
        "status": "approved",
        "booking_id": booking_id,
        **event_result,
    }


@router.post("/v2/calendar/{twin_id}/bookings/{booking_id}/reject")
async def reject_booking(
    twin_id: str,
    booking_id: str,
    body: BookingRejectRequest,
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """Reject a booking request with an optional reason."""
    verify_twin_ownership(twin_id, user)

    sb = get_supabase_client()

    # Fetch the booking. Pull visitor fields too so we can send a rejection
    # email after the update succeeds — saves a second round-trip.
    resp = (
        sb.table("booking_requests")
        .select(
            "id, status, visitor_name, visitor_email, visitor_message, "
            "proposed_start, proposed_end"
        )
        .eq("id", booking_id)
        .eq("twin_id", twin_id)
        .single()
        .execute()
    )

    if not resp.data:
        raise HTTPException(status_code=404, detail="Booking request not found.")

    booking = resp.data

    if booking["status"] != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Booking is already {booking['status']}. Only pending bookings can be rejected.",
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        sb.table("booking_requests").update({
            "status": "rejected",
            "rejected_at": now_iso,
            "rejection_reason": body.reason,
            "updated_at": now_iso,
        }).eq("id", booking_id).execute()
    except Exception as exc:
        logger.error("Failed to reject booking %s: %s", booking_id, exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to reject booking. Please try again.",
        )

    # Phase 1 polish: notify the visitor by email. Failure is logged, not raised.
    try:
        from services.booking_email import notify_visitor_booking_rejected
        await notify_visitor_booking_rejected(twin_id, booking, body.reason)
    except Exception:
        logger.exception(
            "[CalendarBooking] visitor rejection email dispatch failed booking=%s",
            booking_id,
        )

    return {
        "status": "rejected",
        "booking_id": booking_id,
        "reason": body.reason,
    }
