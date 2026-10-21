"""Widget chat endpoints — API key authenticated, for embedded chat widgets."""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field

from adk_core.schemas.api import ChatTurnResponse
from adk_core.services.agent_service import chat_stream
from modules.api_keys import validate_api_key, validate_domain
from modules.auth_guard import require_tenant, verify_twin_ownership
from modules.observability import get_supabase_client
from modules.share_links import _fetch_twin_row, is_publicly_accessible_twin_record

logger = logging.getLogger(__name__)

router = APIRouter(tags=["widget"])

# Sentinel emitted by agent_service.chat_stream when citations are available.
# Widget consumers receive plain text only, so strip this before forwarding.
_CITE_RE = re.compile(r"\n?\[CITATIONS_JSON:.+\]$", re.DOTALL)

# ── Rate limiting per API key ────────────────────────────────────────

_key_rate_limits: dict[str, list[float]] = defaultdict(list)
_DEFAULT_RATE_LIMIT = 100
_RATE_WINDOW = 3600

# ── Per-lead capture rate limiting ───────────────────────────────────
# Prevents a caller with a known UUID from cycling through arbitrary
# emails on the same lead (security review HIGH #5).
_lead_capture_attempts: dict[str, list[float]] = defaultdict(list)
_LEAD_CAPTURE_MAX = 5        # attempts allowed per window
_LEAD_CAPTURE_WINDOW = 3600  # 1 hour


def _check_key_rate_limit(key_id: str, limit: int = _DEFAULT_RATE_LIMIT) -> bool:
    now = time.time()
    window_start = now - _RATE_WINDOW
    _key_rate_limits[key_id] = [
        ts for ts in _key_rate_limits[key_id] if ts > window_start
    ]
    if len(_key_rate_limits[key_id]) >= limit:
        return False
    _key_rate_limits[key_id].append(now)
    return True


# ── API key dependency ───────────────────────────────────────────────


def _validate_widget_request(
    request: Request,
    x_api_key: str = Header(..., alias="X-API-Key"),
) -> dict[str, Any]:
    """Validate API key and origin domain. Returns key record."""
    key_record = validate_api_key(x_api_key)
    if not key_record:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Check domain restriction
    origin = request.headers.get("Origin") or request.headers.get("Referer") or ""
    allowed_domains = key_record.get("allowed_domains", [])
    if allowed_domains and not validate_domain(origin, allowed_domains):
        raise HTTPException(status_code=403, detail="Domain not allowed")

    # Rate limit
    if not _check_key_rate_limit(key_record["id"]):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    return key_record


# ── Schemas ──────────────────────────────────────────────────────────


class WidgetConfigResponse(BaseModel):
    twin_id: str
    persona_name: str
    persona_avatar: str | None = None
    welcome_message: str = "Hi! How can I help you?"
    lead_capture_enabled: bool = False
    bubble_color: str = "#F97316"
    position: str = "bottom-right"
    show_branding: bool = True


class LeadCreateRequest(BaseModel):
    visitor_name: str | None = None
    visitor_email: str | None = None
    source_domain: str | None = None


class LeadCreateResponse(BaseModel):
    lead_id: str


class WidgetChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    conversation_id: str | None = None
    lead_id: str | None = None
    visitor_id: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None


class WidgetConfigUpdateRequest(BaseModel):
    bubble_color: str | None = None
    position: str | None = None
    welcome_message: str | None = None
    lead_capture_enabled: bool | None = None
    lead_capture_prompt: str | None = None


class LeadUpdateRequest(BaseModel):
    contacted_at: datetime | None = None


class VisitorCaptureRequest(BaseModel):
    visitor_name: str | None = Field(default=None, max_length=200)
    visitor_email: EmailStr


# ── Lead lifecycle helper ─────────────────────────────────────────────


def _get_or_create_lead(
    *,
    twin_id: str,
    key_id: str | None,
    conversation_id: str,
    lead_id: str | None,
    visitor_id: str | None,
    source_domain: str,
    utm_source: str | None,
    utm_medium: str | None,
    utm_campaign: str | None,
    utm_content: str | None,
) -> dict:
    """Upsert the widget_leads row and return its current state.

    key_id is the widget API key id for widget leads; pass None for PUBLIC
    persona-page leads (the /p surface has no API key) — the row is then stored
    with api_key_id = NULL, which is how public leads are distinguished from
    widget leads (filter: api_key_id IS NULL).

    Returns dict with: id, offer_state, turn_count, visitor_email, lead_capture_enabled.
    Falls back to a safe disabled-capture default on any DB error so chat always continues.
    """
    _FALLBACK: dict[str, Any] = {
        "id": None,
        "offer_state": "not_yet_offered",
        "turn_count": 0,
        "visitor_email": None,
        "lead_capture_enabled": False,
    }
    sb = get_supabase_client()

    try:
        if lead_id:
            # Atomic, tenant-scoped increment in a single UPDATE (see migration
            # 20260625000200). Replaces the old SELECT-then-UPDATE read-modify-write,
            # which lost increments under concurrent turns. Empty result = the
            # lead_id isn't this twin's (also closes the cross-twin TOCTOU) → fall
            # through to insert.
            resp = sb.rpc(
                "increment_widget_lead_turn",
                {"p_lead_id": lead_id, "p_twin_id": twin_id},
            ).execute()
            rows = resp.data or []
            if rows:
                row = dict(rows[0])
                row["lead_capture_enabled"] = True
                return row

        # First turn: insert a fresh lead. The widget_leads_twin_conv_uniq partial
        # index makes a concurrent duplicate first-turn fail at the DB; the loser
        # is caught below and returns _FALLBACK (chat continues, no dup row).
        insert_data: dict[str, Any] = {
            "twin_id": twin_id,
            "conversation_id": conversation_id,
            "source_domain": source_domain,
            "turn_count": 1,
            "offer_state": "not_yet_offered",
        }
        if key_id:
            insert_data["api_key_id"] = key_id
        if visitor_id:
            insert_data["visitor_id"] = visitor_id
        if utm_source:
            insert_data["utm_source"] = utm_source
        if utm_medium:
            insert_data["utm_medium"] = utm_medium
        if utm_campaign:
            insert_data["utm_campaign"] = utm_campaign
        if utm_content:
            insert_data["utm_content"] = utm_content

        resp = sb.table("widget_leads").insert(insert_data).execute()
        if resp.data:
            row = dict(resp.data[0])
            row["lead_capture_enabled"] = True
            return row

        return _FALLBACK

    except Exception as exc:
        logger.warning("[Widget] lead lifecycle DB error — chat continues: %s", exc)
        return _FALLBACK


# ── Config endpoint (public, no full key needed) ────────────────────


@router.options("/widget/config/{key_prefix}")
async def widget_config_options(key_prefix: str, response: Response):
    """CORS preflight for public widget config endpoint."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return {}


@router.get("/widget/config/{key_prefix}")
async def get_widget_config(key_prefix: str, response: Response) -> WidgetConfigResponse:
    """Get widget config by API key prefix. Public endpoint — returns non-sensitive data only."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    sb = get_supabase_client()

    # Look up key by prefix
    resp = (
        sb.table("twin_api_keys")
        .select("twin_id, widget_config")
        .eq("key_prefix", key_prefix)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Widget not found")

    key_row = resp.data[0]
    twin_id = key_row["twin_id"]
    widget_cfg = key_row.get("widget_config") or {}

    # Get persona info
    twin_resp = (
        sb.table("twins")
        .select("name, settings")
        .eq("id", twin_id)
        .single()
        .execute()
    )
    if not twin_resp.data:
        raise HTTPException(status_code=404, detail="Persona not found")

    twin = twin_resp.data
    settings = twin.get("settings") or {}
    profile = settings.get("persona_profile") or {}
    show_branding = settings.get("show_branding", True)

    return WidgetConfigResponse(
        twin_id=twin_id,
        persona_name=profile.get("name") or twin.get("name", "AI Persona"),
        persona_avatar=profile.get("image_url"),
        welcome_message=widget_cfg.get("welcome_message", "Hi! How can I help you?"),
        lead_capture_enabled=widget_cfg.get("lead_capture_enabled", False),
        bubble_color=widget_cfg.get("bubble_color", "#F97316"),
        position=widget_cfg.get("position", "bottom-right"),
        show_branding=show_branding,
    )


@router.post("/widget/lead/{lead_id}/capture")
async def capture_visitor_contact(
    lead_id: str,
    body: VisitorCaptureRequest,
    request: Request,
):
    """Public (no auth) endpoint: record visitor name + email on a widget_lead row.

    Write is atomic: the UPDATE adds `AND offer_state != 'email_captured'` so
    concurrent calls for the same lead cannot overwrite each other (security
    review HIGH #5 — race + spam fix).  Per-lead rate limit (5 req/hr) prevents
    a caller who has the UUID from cycling through arbitrary emails.

    Rate limiting uses bump_public_rate_limit (shared Postgres counter, cross-instance)
    with _lead_capture_attempts as an in-process fallback when the DB is unreachable —
    matching the two-layer pattern in _check_anon_rate_limit in chat.py.
    """
    # Two-layer rate limit: shared Postgres counter (primary), in-memory fallback.
    bucket = f"capture:{lead_id}"
    try:
        hit_resp = get_supabase_client().rpc(
            "bump_public_rate_limit",
            {"p_bucket": bucket, "p_window_seconds": _LEAD_CAPTURE_WINDOW},
        ).execute()
        shared_hits = hit_resp.data if isinstance(hit_resp.data, int) else None
    except Exception as exc:  # noqa: BLE001 — limiter must never 500 the request
        logger.warning("[Widget] capture rate-limit DB unavailable: %s", exc)
        shared_hits = None

    if shared_hits is not None:
        if shared_hits > _LEAD_CAPTURE_MAX:
            logger.warning("[Widget] capture rate limit hit lead_id=%s", lead_id)
            raise HTTPException(status_code=429, detail="Too many capture attempts")
    else:
        # Fallback: per-instance limiter (not cross-replica; used only on DB outage)
        now = time.time()
        window_start = now - _LEAD_CAPTURE_WINDOW
        _lead_capture_attempts[lead_id] = [
            ts for ts in _lead_capture_attempts[lead_id] if ts > window_start
        ]
        if len(_lead_capture_attempts[lead_id]) >= _LEAD_CAPTURE_MAX:
            logger.warning("[Widget] capture in-memory limit hit lead_id=%s", lead_id)
            raise HTTPException(status_code=429, detail="Too many capture attempts")
        _lead_capture_attempts[lead_id].append(now)

        # Evict stale entries to prevent unbounded growth on unique-lead-id flood.
        if len(_lead_capture_attempts) > 50_000:
            cutoff = now - _LEAD_CAPTURE_WINDOW
            stale = [
                lid for lid, ts_list in _lead_capture_attempts.items()
                if ts_list and all(t < cutoff for t in ts_list)
            ]
            for lid in stale:
                del _lead_capture_attempts[lid]

    sb = get_supabase_client()

    # Pre-flight SELECT: distinguish "not found" from "already captured" so callers
    # get a proper HTTP 404 instead of a silent 200 that masks data loss.
    exist_resp = (
        sb.table("widget_leads")
        .select("id, offer_state, twin_id")
        .eq("id", lead_id)
        .limit(1)
        .execute()
    )
    if not exist_resp.data:
        logger.warning("[Widget] capture lead not found lead_id=%s", lead_id)
        raise HTTPException(status_code=404, detail="Lead not found")

    if exist_resp.data[0].get("offer_state") == "email_captured":
        # Already captured — idempotent success.
        logger.info("[Widget] capture idempotent (already captured) lead_id=%s", lead_id)
        return {"status": "ok"}

    # Atomic conditional update: only write if not already captured.
    resp = (
        sb.table("widget_leads")
        .update({
            "visitor_name": body.visitor_name.strip() if body.visitor_name else None,
            "visitor_email": str(body.visitor_email).lower().strip(),
            "offer_state": "email_captured",
        })
        .eq("id", lead_id)
        .neq("offer_state", "email_captured")
        .execute()
    )

    if not resp.data:
        # Should not happen after the pre-flight SELECT, but handle defensively.
        logger.warning("[Widget] capture update touched 0 rows lead_id=%s", lead_id)
        return {"status": "ok"}

    logger.info("[Widget] capture succeeded lead_id=%s", lead_id)

    # Enqueue a LEAD_CAPTURED job so the persona owner gets notified.
    twin_id = exist_resp.data[0].get("twin_id")
    if twin_id:
        try:
            from modules.graph_outbox import GraphOperationType, get_graph_outbox
            get_graph_outbox().submit(
                tenant_id=twin_id,
                twin_id=twin_id,
                operation=GraphOperationType.LEAD_CAPTURED,
                idempotency_key=f"lead_captured_{lead_id}",
                payload={
                    "lead_id": lead_id,
                    "visitor_name": body.visitor_name.strip() if body.visitor_name else None,
                    "visitor_email": str(body.visitor_email).lower().strip(),
                },
            )
        except Exception as exc:
            logger.warning("[Widget] lead_captured enqueue failed lead_id=%s err=%r", lead_id, exc)

    return {"status": "ok", "captured": True}


@router.patch("/widget/config/{key_id}")
async def update_widget_config_endpoint(
    key_id: str,
    body: WidgetConfigUpdateRequest,
    user: dict = Depends(require_tenant),
):
    """Owner-scoped: update widget customization config for a key."""
    from modules.api_keys import update_widget_config

    sb = get_supabase_client()
    key_row = (
        sb.table("twin_api_keys")
        .select("twin_id")
        .eq("id", key_id)
        .single()
        .execute()
    )
    if not key_row.data:
        raise HTTPException(status_code=404, detail="Key not found")

    verify_twin_ownership(key_row.data["twin_id"], user)

    config_patch = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not config_patch:
        raise HTTPException(status_code=400, detail="No config fields provided")

    ok = update_widget_config(key_id=key_id, config_patch=config_patch)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update config")

    return {"status": "ok", "config": config_patch}


# ── Lead capture ─────────────────────────────────────────────────────


@router.post("/widget/leads", response_model=LeadCreateResponse)
async def create_lead(
    body: LeadCreateRequest,
    key_record: dict = Depends(_validate_widget_request),
):
    """Capture a visitor lead from the widget."""
    sb = get_supabase_client()
    lead_data = {
        "twin_id": key_record["twin_id"],
        "api_key_id": key_record["id"],
        "visitor_name": body.visitor_name,
        "visitor_email": body.visitor_email,
        "source_domain": body.source_domain,
    }

    resp = sb.table("widget_leads").insert(lead_data).execute()
    if not resp.data:
        raise HTTPException(status_code=500, detail="Failed to create lead")

    return LeadCreateResponse(lead_id=resp.data[0]["id"])


@router.patch("/widget/leads/{lead_id}")
async def update_lead(
    lead_id: str,
    body: LeadUpdateRequest,
    user: dict = Depends(require_tenant),
):
    """Owner-scoped: update a captured lead (e.g. mark contacted)."""
    sb = get_supabase_client()
    lead_resp = sb.table("widget_leads").select("twin_id").eq("id", lead_id).execute()
    if not lead_resp.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    verify_twin_ownership(lead_resp.data[0]["twin_id"], user)

    patch = {k: v for k, v in body.model_dump(mode="json", exclude_none=True).items()}
    if not patch:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    sb.table("widget_leads").update(patch).eq("id", lead_id).eq("twin_id", lead_resp.data[0]["twin_id"]).execute()
    return {"status": "ok"}


@router.delete("/widget/leads/{lead_id}", status_code=204)
async def delete_lead(
    lead_id: str,
    user: dict = Depends(require_tenant),
):
    """Owner-scoped: delete a captured lead."""
    sb = get_supabase_client()
    lead_resp = sb.table("widget_leads").select("twin_id").eq("id", lead_id).execute()
    if not lead_resp.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    verify_twin_ownership(lead_resp.data[0]["twin_id"], user)

    sb.table("widget_leads").delete().eq("id", lead_id).eq("twin_id", lead_resp.data[0]["twin_id"]).execute()


@router.get("/widget/leads/list/{twin_id}")
async def list_widget_leads(
    twin_id: str,
    user: dict = Depends(require_tenant),
    limit: int = 100,
):
    """Owner-scoped: list captured leads for a twin, newest first."""
    verify_twin_ownership(twin_id, user)

    sb = get_supabase_client()
    resp = (
        sb.table("widget_leads")
        .select("id, visitor_name, visitor_email, source_domain, created_at, turn_count, conversation_id, offer_state, api_key_id, inferred_visitor_type, inferred_intent, contacted_at")
        .eq("twin_id", twin_id)
        .order("created_at", desc=True)
        .limit(max(1, min(limit, 500)))
        .execute()
    )
    return resp.data or []


# ── Widget chat (API key auth) ───────────────────────────────────────


def _sse(event_type: str, payload: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"


@router.post("/widget/chat/{twin_id}/stream")
async def widget_chat_stream(
    twin_id: str,
    request_body: WidgetChatRequest,
    http_request: Request,
    key_record: dict = Depends(_validate_widget_request),
):
    """Streaming widget chat — API key authenticated."""
    # Verify key matches twin
    if key_record["twin_id"] != twin_id:
        raise HTTPException(status_code=403, detail="API key does not match this persona")

    # Verify twin is publicly accessible
    twin = _fetch_twin_row(twin_id)
    if not twin or not is_publicly_accessible_twin_record(twin):
        raise HTTPException(status_code=404, detail="Persona not found")

    # Build profile from settings
    settings = twin.get("settings") or {}
    profile = settings.get("persona_profile") or {}
    if isinstance(profile, str):
        try:
            profile = json.loads(profile)
        except (ValueError, TypeError):
            profile = {}
    profile.setdefault("name", twin.get("name", ""))

    session_id = request_body.conversation_id or f"widget_{key_record['id']}_{int(time.time())}"
    user_id = f"widget_visitor_{key_record['id']}"

    # Extract source domain from request headers
    origin = http_request.headers.get("Origin") or http_request.headers.get("Referer") or ""
    source_domain = origin.split("://")[-1].split("/")[0] if origin else ""

    # Lead lifecycle — create on turn 1 or fetch+increment on subsequent turns
    lead_row = _get_or_create_lead(
        twin_id=twin_id,
        key_id=key_record["id"],
        conversation_id=session_id,
        lead_id=request_body.lead_id,
        visitor_id=request_body.visitor_id,
        source_domain=source_domain,
        utm_source=request_body.utm_source,
        utm_medium=request_body.utm_medium,
        utm_campaign=request_body.utm_campaign,
        utm_content=request_body.utm_content,
    )

    lead_context: dict | None = None
    if lead_row.get("lead_capture_enabled"):
        widget_ui = settings.get("widget_ui") or {}
        lead_context = {
            "lead_capture_enabled": True,
            "offer_state": lead_row.get("offer_state", "not_yet_offered"),
            "turn_count": lead_row.get("turn_count", 0),
            "email": lead_row.get("visitor_email"),
            "persona_name": profile.get("name", "the persona"),
            "booking_url": widget_ui.get("booking_url") or None,
        }

    current_lead_id: str | None = lead_row.get("id")

    async def generator():
        try:
            async for chunk in chat_stream(
                twin_id=twin_id,
                profile_dict=profile,
                user_id=user_id,
                session_id=session_id,
                message=request_body.message,
                surface="widget_lead",
                lead_id=current_lead_id,
                lead_context=lead_context,
            ):
                clean = _CITE_RE.sub("", chunk)
                if not clean:
                    continue
                yield _sse("token", {"token": clean, "conversation_id": session_id})
        except Exception as exc:
            yield _sse("error", {"error": str(exc)})
            return

        # After successful stream: mark offer as made if conditions met
        if (
            current_lead_id
            and lead_context
            and lead_context.get("offer_state") == "not_yet_offered"
            and lead_context.get("turn_count", 0) >= 3
        ):
            try:
                sb = get_supabase_client()
                sb.table("widget_leads").update(
                    {"offer_state": "already_offered"}
                ).eq("id", current_lead_id).execute()
            except Exception as exc:
                logger.warning("[Widget] offer_state update failed: %s", exc)

        yield _sse("done", {
            "done": True,
            "conversation_id": session_id,
            "lead_id": current_lead_id,
        })

    return StreamingResponse(generator(), media_type="text/event-stream")


@router.post("/widget/chat/{twin_id}", response_model=ChatTurnResponse)
async def widget_chat_turn(
    twin_id: str,
    request_body: WidgetChatRequest,
    http_request: Request,
    key_record: dict = Depends(_validate_widget_request),
):
    """Non-streaming widget chat — API key authenticated."""
    if key_record["twin_id"] != twin_id:
        raise HTTPException(status_code=403, detail="API key does not match this persona")

    twin = _fetch_twin_row(twin_id)
    if not twin or not is_publicly_accessible_twin_record(twin):
        raise HTTPException(status_code=404, detail="Persona not found")

    settings = twin.get("settings") or {}
    profile = settings.get("persona_profile") or {}
    if isinstance(profile, str):
        try:
            profile = json.loads(profile)
        except (ValueError, TypeError):
            profile = {}
    profile.setdefault("name", twin.get("name", ""))

    session_id = request_body.conversation_id or f"widget_{key_record['id']}_{int(time.time())}"
    user_id = f"widget_visitor_{key_record['id']}"

    chunks: list[str] = []
    async for chunk in chat_stream(
        twin_id=twin_id,
        profile_dict=profile,
        user_id=user_id,
        session_id=session_id,
        message=request_body.message,
    ):
        chunks.append(chunk)

    # Strip citation sentinel — widget consumers receive plain text only
    message = _CITE_RE.sub("", "".join(chunks))
    return ChatTurnResponse(
        message=message,
        conversation_id=session_id,
        surface="widget",
        persona_version="v2-clean-slate",
    )


# ── Owner endpoints (authenticated) ─────────────────────────────────


@router.get("/widget/leads/list")
async def list_leads(
    twin_id: str,
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(require_tenant),
):
    """List leads for a twin (owner only)."""
    verify_twin_ownership(twin_id, user)
    sb = get_supabase_client()
    resp = (
        sb.table("widget_leads")
        .select("*")
        .eq("twin_id", twin_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return resp.data or []


# ── API Key management (owner-authenticated) ─────────────────────────────


class CreateKeyRequest(BaseModel):
    name: str = "Widget Key"
    allowed_domains: list[str] = []


@router.post("/widget/keys/{twin_id}")
async def create_widget_key(
    twin_id: str,
    body: CreateKeyRequest,
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """Create a new API key for widget embedding. Returns full key once — store it immediately."""
    verify_twin_ownership(twin_id, user)
    from modules.api_keys import create_api_key
    return create_api_key(
        twin_id=twin_id,
        group_id=None,
        name=body.name,
        allowed_domains=body.allowed_domains,
    )


@router.get("/widget/keys/{twin_id}")
async def list_widget_keys(
    twin_id: str,
    user: dict = Depends(require_tenant),
) -> list[dict[str, Any]]:
    """List API keys for a twin (prefix only — never returns full keys)."""
    verify_twin_ownership(twin_id, user)
    from modules.api_keys import list_api_keys
    return list_api_keys(twin_id)


@router.delete("/widget/keys/{key_id}")
async def revoke_widget_key(
    key_id: str,
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """Revoke (deactivate) a widget API key."""
    sb = get_supabase_client()
    key_row = (
        sb.table("twin_api_keys")
        .select("twin_id")
        .eq("id", key_id)
        .single()
        .execute()
    )
    if not key_row.data:
        raise HTTPException(status_code=404, detail="Key not found")
    verify_twin_ownership(key_row.data["twin_id"], user)
    from modules.api_keys import revoke_api_key
    if not revoke_api_key(key_id):
        raise HTTPException(status_code=404, detail="Key not found or already revoked")
    return {"status": "ok"}
