"""ADK-first v2 chat routes."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import defaultdict
from typing import Any, Dict, Optional

# Regex to strip the citations sentinel emitted at the end of the chat stream.
# Uses a unique enough prefix to avoid false positives from LLM output.
_CITE_RE = re.compile(r'\n?\[CITATIONS_JSON:(.+?)\]$', re.DOTALL)

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from adk_core.app import get_conversation_repository
from adk_core.errors import conversation_not_found, rate_limited, twin_not_found
from adk_core.schemas.api import ChatTurnRequest, ChatTurnResponse
from adk_core.services.agent_service import chat_stream
from modules.auth_guard import ensure_twin_active, require_tenant, verify_twin_ownership
from modules.observability import get_supabase_client
from modules.posthog_analytics import ph_capture
from modules.runtime_kill_switches import public_chat_enabled
from services.visitor_session_recorder import record_visitor_turn
from modules.share_links import (
    _fetch_twin_row,
    is_publicly_accessible_twin_record,
    validate_share_token,
)

_anon_rate_limits: dict[str, list[float]] = defaultdict(list)
_ANON_RATE_LIMIT = 20  # per IP, per twin, per hour
_ANON_TWIN_CEILING = 300  # global per-twin per hour (all IPs) — abuse/cost ceiling
_ANON_RATE_WINDOW = 3600

# Server-defined allowlist for mode_override values. Anything not in this set
# is rejected with HTTP 400 before reaching the agent layer.
ALLOWED_MODE_OVERRIDES: frozenset[str] = frozenset(
    {"deep_dive", "casual", "technical", "professional", "friendly"}
)

router = APIRouter(tags=["chat-v2"])


def _check_anon_rate_limit_inmemory(tracking_key: str) -> bool:
    """In-process fallback limiter — used ONLY when the shared DB counter is
    unreachable. Per-instance, so not reliable on its own; do not depend on it."""
    now = time.time()
    window_start = now - _ANON_RATE_WINDOW
    _anon_rate_limits[tracking_key] = [
        timestamp for timestamp in _anon_rate_limits[tracking_key] if timestamp > window_start
    ]
    if len(_anon_rate_limits[tracking_key]) >= _ANON_RATE_LIMIT:
        return False
    _anon_rate_limits[tracking_key].append(now)

    # Evict fully-stale entries when dict grows too large to prevent unbounded memory growth.
    if len(_anon_rate_limits) > 10_000:
        cutoff = now - _ANON_RATE_WINDOW
        stale = [ip for ip, ts_list in _anon_rate_limits.items() if ts_list and all(t < cutoff for t in ts_list)]
        for ip in stale:
            del _anon_rate_limits[ip]

    return True


def _bump_shared_limit(bucket: str) -> int | None:
    """Atomically increment the shared (Postgres) counter for `bucket`'s current
    window; returns the post-increment count, or None if the DB is unreachable."""
    try:
        resp = get_supabase_client().rpc(
            "bump_public_rate_limit",
            {"p_bucket": bucket, "p_window_seconds": _ANON_RATE_WINDOW},
        ).execute()
        return resp.data if isinstance(resp.data, int) else None
    except Exception as exc:  # noqa: BLE001 — the limiter must never 500 the request
        logger.warning("[chat] public rate-limit DB unavailable, falling back: %s", exc)
        return None


def _check_anon_rate_limit(twin_id: str, client_ip: str) -> bool:
    """Shared-store public-chat rate limit (H2): per-IP-per-twin (20/hr) plus a
    global per-twin ceiling (300/hr) so one twin can't be turned into a Gemini
    cost sink by a rotating-IP botnet. The counter lives in Postgres, so limits
    hold across Cloud Run instances and restarts. Falls back to the in-memory
    limiter only when the shared counter is unreachable (fail-open + log, so a
    limiter outage doesn't take public chat down)."""
    ip_bucket = f"anon:{twin_id}:{client_ip}"
    ip_hits = _bump_shared_limit(ip_bucket)
    if ip_hits is None:
        return _check_anon_rate_limit_inmemory(ip_bucket)
    if ip_hits > _ANON_RATE_LIMIT:
        return False
    twin_hits = _bump_shared_limit(f"twin:{twin_id}")
    if twin_hits is not None and twin_hits > _ANON_TWIN_CEILING:
        return False
    return True


def _sse(event_type: str, payload: Dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"


# ── Runtime kill switch: PUBLIC_CHAT_ENABLED (execution-board 0.10) ─────────
# Gates the public/widget chat endpoints only (never owner/assistant). When
# false, visitors get a graceful "resting" message — never a 503/error — so an
# incident-response pause never looks like a broken site.
_PUBLIC_CHAT_RESTING_MESSAGE = (
    "This persona is resting right now and isn't taking messages. Please check back soon."
)


def _resting_chat_response(surface: str, conversation_id: Optional[str] = None) -> ChatTurnResponse:
    """Graceful non-streaming reply for PUBLIC_CHAT_ENABLED=false.

    Echoes back the client's existing conversation_id (if it sent one) instead
    of minting a fresh uuid — otherwise toggling the kill switch off and back on
    mid-conversation silently orphans the visitor's session (the frontend would
    overwrite its real conversationId with this throwaway one).
    """
    import uuid

    return ChatTurnResponse(
        message=_PUBLIC_CHAT_RESTING_MESSAGE,
        conversation_id=conversation_id or str(uuid.uuid4()),
        surface=surface,
        persona_version="v2-clean-slate",
        lead_id=None,
    )


def _resting_chat_stream(conversation_id: Optional[str] = None) -> StreamingResponse:
    """Graceful streaming reply for PUBLIC_CHAT_ENABLED=false — mirrors the
    normal session/message/done SSE event shape so the widget/public chat UI
    renders it exactly like an ordinary turn, not an error state.

    Echoes back the client's existing conversation_id (if it sent one) instead
    of minting a fresh uuid — see _resting_chat_response for why.
    """
    import uuid

    session_id = conversation_id or str(uuid.uuid4())

    async def generator():
        yield _sse("session", {"session_id": session_id, "lead_id": None})
        yield _sse("message", {"text": _PUBLIC_CHAT_RESTING_MESSAGE})
        yield _sse("done", {"done": True})

    return StreamingResponse(generator(), media_type="text/event-stream")


def _widget_access_or_404(twin_id: str) -> None:
    twin = _fetch_twin_row(twin_id)
    if not twin or not is_publicly_accessible_twin_record(twin):
        raise twin_not_found()


def _public_access_or_404(twin_id: str, token: str) -> None:
    twin = _fetch_twin_row(twin_id)
    if not twin or not is_publicly_accessible_twin_record(twin) or not validate_share_token(token, twin_id):
        raise twin_not_found()


def _get_client_ip(http_request: Request) -> str:
    forwarded_for = http_request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return http_request.client.host if http_request.client else "unknown"


def _load_twin_context(twin_id: str) -> tuple[dict, list[dict]]:
    """Load twin profile and active actions from Supabase for the system prompt."""
    sb = get_supabase_client()
    resp = (
        sb.table("twins")
        .select("id, name, status, settings")
        .eq("id", twin_id)
        .single()
        .execute()
    )
    if not resp.data:
        raise twin_not_found()

    twin = resp.data
    settings = twin.get("settings") or {}

    profile = settings.get("persona_profile") or {}
    if isinstance(profile, str):
        import json as _json

        try:
            profile = _json.loads(profile)
        except (ValueError, TypeError):
            profile = {}
    profile.setdefault("name", twin.get("name", ""))

    # Merge user-edited career context so the persona knows why each
    # career move was made (stored in public_profile, not persona_profile)
    public_profile = settings.get("public_profile") or {}
    if isinstance(public_profile, dict):
        career_context = public_profile.get("career_context", "")
        if career_context and isinstance(career_context, str):
            profile["career_context"] = career_context

    all_actions = settings.get("actions") or []
    active_actions = [action for action in all_actions if action.get("is_active", True)]
    return profile, active_actions


# Phase 2 — People-memory USP. Default ON for the production launch: grounds
# owner chat in per-person meeting history (open loops + approved facts) when the
# user references a known, mention-allowed contact. Set PEOPLE_CONTEXT_V1_ENABLED=
# false to disable. Owner-surface only; allow_mention-gated; tenant-scoped.
def _people_context_enabled() -> bool:
    return os.getenv("PEOPLE_CONTEXT_V1_ENABLED", "true").lower() == "true"


def _build_people_block(
    *,
    twin_id: str,
    tenant_id: Optional[str],
    surface: str,
    message: str,
) -> str:
    """Resolve per-person context for a referenced contact (owner surface only).

    Returns "" unless the flag is on, the surface is owner, and the message
    references a known mention-allowed contact. Best-effort — never raises.
    """
    if not _people_context_enabled() or surface != "owner" or not tenant_id:
        return ""
    try:
        from services.person_context import resolve_people_context_block

        return resolve_people_context_block(
            get_supabase_client(),
            twin_id=twin_id,
            tenant_id=tenant_id,
            message=message,
        )
    except Exception:
        logger.warning("[chat] people-context resolution failed twin=%s (non-fatal)", twin_id)
        return ""


def _build_conversation_metadata(
    request: ChatTurnRequest,
    *,
    surface: str,
) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {"surface": surface}
    if request.client_context:
        metadata["client_context"] = request.client_context
    return metadata


def _build_message_metadata(
    request: ChatTurnRequest,
    *,
    surface: str,
    share_token: Optional[str] = None,
) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {"surface": surface}
    if request.client_context:
        metadata["client_context"] = request.client_context
    if request.mode_override:
        metadata["mode_override"] = request.mode_override
    if share_token:
        metadata["share_token_present"] = True
    return metadata


def _persist_chat_turn(
    *,
    twin_id: str,
    tenant_id: Optional[str],
    user_id: str,
    surface: str,
    session_id: str,
    request: ChatTurnRequest,
    assistant_response: str,
    share_token: Optional[str] = None,
) -> None:
    conv_repo = get_conversation_repository()
    existing = conv_repo.get_conversation(conversation_id=session_id)
    if not existing:
        conv_repo.create_conversation(
            conversation_id=session_id,
            twin_id=twin_id,
            tenant_id=tenant_id,
            user_id=user_id,
            surface=surface,
            share_token=share_token,
            metadata=_build_conversation_metadata(request, surface=surface),
        )

    message_metadata = _build_message_metadata(
        request,
        surface=surface,
        share_token=share_token,
    )
    conv_repo.add_message(
        conversation_id=session_id,
        twin_id=twin_id,
        tenant_id=tenant_id,
        role="user",
        content=request.message,
        metadata=message_metadata,
    )

    if assistant_response:
        conv_repo.add_message(
            conversation_id=session_id,
            twin_id=twin_id,
            tenant_id=tenant_id,
            role="assistant",
            content=assistant_response,
            metadata=message_metadata,
        )

    # Best-effort visitor session tracking (Phase G.2).
    # Uses session_id as visitor_id — each widget/public session gets a unique
    # UUID so distinct visitor rows are created per session. tenant_id is None
    # for widget/public; the recorder resolves it from the twins table.
    # Must NEVER raise — swallowed in try/except here and inside record_visitor_turn.
    try:
        if surface in ("widget", "public", "widget_lead"):
            record_visitor_turn(
                tenant_id=tenant_id,
                twin_id=twin_id,
                visitor_id=session_id,
                surface=surface,
            )
    except Exception:
        logger.exception("[chat] visitor_session record failed (non-fatal)")


def _origin_domain(http_request: Request | None) -> str:
    """Best-effort source domain from Origin/Referer (mirrors the widget)."""
    if http_request is None:
        return ""
    origin = http_request.headers.get("Origin") or http_request.headers.get("Referer") or ""
    return origin.split("://")[-1].split("/")[0] if origin else ""


def _infer_value_frame(profile: dict) -> str:
    """Fallback offer value_frame from occupation/role keywords when the owner has
    not set settings.value_frame (D17). Coarse, deterministic, defaults to 'interest'."""
    text = " ".join(
        str(profile.get(k, "")) for k in ("occupation", "role", "headline", "organization")
    ).lower()
    if any(w in text for w in ("student", "mba", "graduate", "undergrad")):
        return "opportunity"
    if any(w in text for w in ("realtor", "broker", "lawyer", "attorney", "insurance")):
        return "inquiry"
    if any(w in text for w in ("creator", "artist", "designer", "writer", "influencer", "musician")):
        return "collaboration"
    if any(w in text for w in ("founder", "ceo", "consultant", "agency", "engineer", "developer")):
        return "lead"
    return "interest"


def _public_capture_config(twin_id: str) -> dict:
    """Read public-page lead-capture config from twins.settings. Fail-safe to OFF.

    Returns {"enabled": bool, "value_frame": str|None}. Source of truth:
    twins.settings.lead_capture_enabled (default False = OFF, so capture is fully
    inert until the owner turns it on) and .value_frame (optional; callers fall back
    to _infer_value_frame). Any read error or missing/non-bool flag resolves to OFF.
    """
    try:
        resp = (
            get_supabase_client()
            .table("twins")
            .select("settings")
            .eq("id", twin_id)
            .single()
            .execute()
        )
        settings = (resp.data or {}).get("settings") or {}
        widget_ui = settings.get("widget_ui") or {}
        return {
            "enabled": settings.get("lead_capture_enabled") is True,
            "value_frame": settings.get("value_frame"),
            "booking_url": str(widget_ui.get("booking_url") or "").strip() or None,
        }
    except Exception as exc:
        logger.warning("[chat] lead_capture config read failed twin=%s error=%s — OFF", twin_id, exc)
        return {"enabled": False, "value_frame": None, "booking_url": None}


def _public_capture_enabled(twin_id: str) -> bool:
    """Thin bool wrapper over _public_capture_config (kept for call sites/tests)."""
    return _public_capture_config(twin_id)["enabled"]


_OFFER_ASK_MARKERS = (
    "your email", "best email", "share your email", "drop your email",
    "what email", "follow up directly", "email and i", "email so i",
)


def _looks_like_offer(text: str) -> bool:
    """Heuristic: did the persona just make the connect/email offer? Detected from
    the persona's OWN output (reliable) rather than guessing visitor intent."""
    t = (text or "").lower()
    return any(m in t for m in _OFFER_ASK_MARKERS)


def _advance_offer_state_if_offered(
    *,
    chat_surface: str,
    lead_id: Optional[str],
    twin_id: str,
    lead_context: Optional[dict],
    assistant_response: str,
) -> None:
    """Mark offer_state=already_offered once the persona has made the offer, so it
    is not repeated on later turns (public_lead only). Best-effort + non-fatal."""
    if chat_surface != "public_lead" or not lead_id or not lead_context:
        return
    if lead_context.get("offer_state") != "not_yet_offered":
        return
    if not _looks_like_offer(assistant_response):
        return
    try:
        get_supabase_client().table("widget_leads").update(
            {"offer_state": "already_offered"}
        ).eq("id", lead_id).eq("twin_id", twin_id).execute()
    except Exception as exc:
        logger.warning("[chat] offer_state advance failed lead=%s: %s", lead_id, exc)


async def _handle_chat(
    *,
    twin_id: str,
    request: ChatTurnRequest,
    surface: str,
    stream: bool,
    tenant_id: Optional[str] = None,
    user_id: str,
    share_token: Optional[str] = None,
    http_request: Request | None = None,
):
    import uuid

    if request.mode_override is not None and request.mode_override not in ALLOWED_MODE_OVERRIDES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode_override. Allowed values: {sorted(ALLOWED_MODE_OVERRIDES)}",
        )

    chat_start = time.time()
    profile, actions = _load_twin_context(twin_id)
    session_id = request.conversation_id or str(uuid.uuid4())

    # Create the conversation row up-front so mid-stream tools (queue_question) can
    # FK-link to it (D10). Idempotent — _persist_chat_turn finds it and only adds
    # messages. Non-fatal: on failure, linkage just falls back to NULL.
    try:
        _conv_repo = get_conversation_repository()
        if not _conv_repo.get_conversation(conversation_id=session_id):
            _conv_repo.create_conversation(
                conversation_id=session_id,
                twin_id=twin_id,
                tenant_id=tenant_id,
                user_id=user_id,
                surface=surface,
                share_token=share_token,
                metadata=_build_conversation_metadata(request, surface=surface),
            )
    except Exception as _conv_err:
        logger.warning("[chat] early conversation create failed session_id=%s error=%s", session_id, _conv_err)
        # Observable counter so a systemic DB issue (which would silently degrade
        # queue->transcript linkage to NULL across all turns) is detectable, not
        # just log-scraped. ph_capture swallows its own errors internally.
        ph_capture(
            user_id=user_id,
            event="chat_early_conversation_create_failed",
            properties={"twin_id": twin_id, "surface": surface},
        )

    people_block = _build_people_block(
        twin_id=twin_id,
        tenant_id=tenant_id,
        surface=surface,
        message=request.message,
    )

    # ── Public-page conversational lead capture (opt-in; default OFF) ─────────
    # When the owner has enabled capture, route this public turn through the
    # "public_lead" RUNTIME surface (gets capture_lead_contact + the offer block)
    # and bootstrap/advance a widget_leads row (api_key_id NULL). Sessions are
    # still RECORDED as "public" below, so visitor analytics stay unfragmented.
    chat_surface = surface
    lead_id: Optional[str] = None
    lead_context: Optional[dict] = None
    _capture_cfg = (
        _public_capture_config(twin_id) if surface == "public" else {"enabled": False, "value_frame": None}
    )
    if _capture_cfg["enabled"]:
        from routers.widget import _get_or_create_lead  # shared lead lifecycle

        lead_row = _get_or_create_lead(
            twin_id=twin_id,
            key_id=None,
            conversation_id=session_id,
            lead_id=request.lead_id,
            # Per-conversation key: the token-stable user_id (public:{twin}:{token})
            # would merge distinct anonymous visitors into one lead (PR1 audit). A
            # persistent cross-session visitor_id arrives with frontend threading (PR5).
            visitor_id=session_id,
            source_domain=_origin_domain(http_request),
            utm_source=None,
            utm_medium=None,
            utm_campaign=None,
            utm_content=None,
        )
        if lead_row.get("id") and lead_row.get("lead_capture_enabled"):
            lead_id = lead_row["id"]
            chat_surface = "public_lead"
            lead_context = {
                "lead_capture_enabled": True,
                "offer_state": lead_row.get("offer_state", "not_yet_offered"),
                "turn_count": lead_row.get("turn_count", 0),
                "email": lead_row.get("visitor_email"),
                "persona_name": profile.get("name", "the persona"),
                "value_frame": _capture_cfg.get("value_frame") or _infer_value_frame(profile),
                "booking_url": _capture_cfg.get("booking_url"),
            }
            # Funnel telemetry: a public visitor entered the capture flow this turn.
            try:
                ph_capture(
                    user_id=user_id,
                    event="public_capture_turn",
                    properties={
                        "twin_id": twin_id,
                        "turn_count": lead_context["turn_count"],
                        "value_frame": lead_context["value_frame"],
                        "offer_state": lead_context["offer_state"],
                    },
                )
            except Exception as _tel_err:
                logger.warning("[chat] public_capture_turn analytics failed twin=%s: %s", twin_id, _tel_err)

    if stream:

        async def generator():
            session_meta = {"session_id": session_id, "lead_id": lead_id}
            if lead_context:
                session_meta["lead_capture_enabled"] = True
                session_meta["offer_state"] = lead_context.get("offer_state", "not_yet_offered")
            yield _sse("session", session_meta)
            collected_chunks: list[str] = []

            citations_payload: list[dict] = []
            try:
                async for chunk in chat_stream(
                    twin_id=twin_id,
                    profile_dict=profile,
                    user_id=user_id,
                    session_id=session_id,
                    message=request.message,
                    surface=chat_surface,
                    tenant_id=tenant_id,
                    mode_override=request.mode_override,
                    actions=actions,
                    lead_id=lead_id,
                    lead_context=lead_context,
                    people_block=people_block,
                ):
                    m = _CITE_RE.search(chunk)
                    if m:
                        try:
                            citations_payload = json.loads(m.group(1))
                        except Exception:
                            pass
                        chunk = _CITE_RE.sub('', chunk).rstrip()
                        if not chunk:
                            continue
                    collected_chunks.append(chunk)
                    yield _sse("message", {"text": chunk})
            except Exception as exc:
                if "RESOURCE_EXHAUSTED" in str(exc) or "ResourceExhausted" in type(exc).__name__:
                    yield _sse(
                        "error",
                        {
                            "error": "The AI service is currently rate-limited. Please wait a moment and try again."
                        },
                    )
                else:
                    logger.exception("Error during chat stream")
                    yield _sse("error", {"error": "An internal error occurred."})

            full_response = "".join(collected_chunks)
            try:
                _persist_chat_turn(
                    twin_id=twin_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    surface=surface,
                    session_id=session_id,
                    request=request,
                    assistant_response=full_response,
                    share_token=share_token,
                )
            except Exception as conv_err:
                logger.warning("conversation save failed for %s: %s", session_id, conv_err)

            _advance_offer_state_if_offered(
                chat_surface=chat_surface, lead_id=lead_id, twin_id=twin_id,
                lead_context=lead_context, assistant_response=full_response,
            )

            ph_capture(
                user_id=user_id,
                event="chat_message_completed",
                properties={
                    "twin_id": twin_id,
                    "surface": surface,
                    "conversation_id": session_id,
                    "message_length": len(request.message),
                    "response_length": len(full_response),
                    "duration_ms": int((time.time() - chat_start) * 1000),
                    "stream": True,
                },
            )

            if citations_payload:
                yield _sse("metadata", {
                    "citation_details": citations_payload,
                    "citations": [c.get("filename", "") for c in citations_payload],
                })
            yield _sse("done", {"done": True})

        return StreamingResponse(generator(), media_type="text/event-stream")

    chunks: list[str] = []
    async for chunk in chat_stream(
        twin_id=twin_id,
        profile_dict=profile,
        user_id=user_id,
        session_id=session_id,
        message=request.message,
        surface=chat_surface,
        tenant_id=tenant_id,
        mode_override=request.mode_override,
        actions=actions,
        lead_id=lead_id,
        lead_context=lead_context,
        people_block=people_block,
    ):
        chunks.append(chunk)

    # Strip citation sentinel — sync callers receive plain text only
    full_response = _CITE_RE.sub("", "".join(chunks)).rstrip()
    try:
        _persist_chat_turn(
            twin_id=twin_id,
            tenant_id=tenant_id,
            user_id=user_id,
            surface=surface,
            session_id=session_id,
            request=request,
            assistant_response=full_response,
            share_token=share_token,
        )
    except Exception as conv_err:
        logger.warning("[chat] conversation save failed session_id=%s error=%s", session_id, conv_err)

    _advance_offer_state_if_offered(
        chat_surface=chat_surface, lead_id=lead_id, twin_id=twin_id,
        lead_context=lead_context, assistant_response=full_response,
    )

    ph_capture(
        user_id=user_id,
        event="chat_message_completed",
        properties={
            "twin_id": twin_id,
            "surface": surface,
            "conversation_id": session_id,
            "message_length": len(request.message),
            "response_length": len(full_response),
            "duration_ms": int((time.time() - chat_start) * 1000),
            "stream": False,
        },
    )
    return ChatTurnResponse(
        message=full_response,
        conversation_id=session_id,
        surface=surface,
        persona_version="v2-clean-slate",
        lead_id=lead_id,
    )


@router.post("/v2/chat/owner/{twin_id}", response_model=ChatTurnResponse)
async def owner_chat_turn(
    twin_id: str,
    request: ChatTurnRequest,
    user: dict = Depends(require_tenant),
):
    verify_twin_ownership(twin_id, user)
    ensure_twin_active(twin_id)
    return await _handle_chat(
        twin_id=twin_id,
        request=request,
        surface="owner",
        stream=False,
        tenant_id=user["tenant_id"],
        user_id=user["user_id"],
    )


@router.post("/v2/chat/owner/{twin_id}/stream")
async def owner_chat_stream(
    twin_id: str,
    request: ChatTurnRequest,
    user: dict = Depends(require_tenant),
):
    verify_twin_ownership(twin_id, user)
    ensure_twin_active(twin_id)
    return await _handle_chat(
        twin_id=twin_id,
        request=request,
        surface="owner",
        stream=True,
        tenant_id=user["tenant_id"],
        user_id=user["user_id"],
    )


@router.post("/v2/chat/assistant/{twin_id}/stream")
async def assistant_chat_stream(
    twin_id: str,
    request: ChatTurnRequest,
    user: dict = Depends(require_tenant),
):
    """Chief-of-staff assistant for the owner's Home (Improve + Respond).

    Distinct from /owner, which is the persona-preview chat (the persona answering
    as itself). This agent speaks TO the owner about their persona — it finds
    knowledge gaps and asks to fill them (capture_knowledge), and drafts follow-ups
    (create_followup_draft). It never embodies the persona.
    """
    verify_twin_ownership(twin_id, user)
    ensure_twin_active(twin_id)
    return await _handle_chat(
        twin_id=twin_id,
        request=request,
        surface="assistant",
        stream=True,
        tenant_id=user["tenant_id"],
        user_id=user["user_id"],
    )


@router.post("/v2/chat/widget/{twin_id}", response_model=ChatTurnResponse)
async def widget_chat_turn(twin_id: str, request: ChatTurnRequest):
    if not public_chat_enabled():
        return _resting_chat_response("widget", request.conversation_id)
    _widget_access_or_404(twin_id)
    return await _handle_chat(
        twin_id=twin_id,
        request=request,
        surface="widget",
        stream=False,
        user_id=f"widget:{twin_id}",
    )


@router.post("/v2/chat/widget/{twin_id}/stream")
async def widget_chat_stream(twin_id: str, request: ChatTurnRequest):
    if not public_chat_enabled():
        return _resting_chat_stream(request.conversation_id)
    _widget_access_or_404(twin_id)
    return await _handle_chat(
        twin_id=twin_id,
        request=request,
        surface="widget",
        stream=True,
        user_id=f"widget:{twin_id}",
    )


def _enforce_public_rate_limit(twin_id: str, http_request: Request) -> None:
    client_ip = _get_client_ip(http_request)
    if not _check_anon_rate_limit(twin_id, client_ip):
        raise rate_limited()


@router.post("/v2/chat/public/{twin_id}/{token}", response_model=ChatTurnResponse)
async def public_chat_turn(
    twin_id: str,
    token: str,
    request: ChatTurnRequest,
    http_request: Request,
):
    if not public_chat_enabled():
        return _resting_chat_response("public", request.conversation_id)
    _public_access_or_404(twin_id, token)
    _enforce_public_rate_limit(twin_id, http_request)
    return await _handle_chat(
        twin_id=twin_id,
        request=request,
        surface="public",
        stream=False,
        user_id=f"public:{twin_id}:{token[:8]}",
        share_token=token,
        http_request=http_request,
    )


@router.post("/v2/chat/public/{twin_id}/{token}/stream")
async def public_chat_stream(
    twin_id: str,
    token: str,
    request: ChatTurnRequest,
    http_request: Request,
):
    if not public_chat_enabled():
        return _resting_chat_stream(request.conversation_id)
    _public_access_or_404(twin_id, token)
    _enforce_public_rate_limit(twin_id, http_request)
    return await _handle_chat(
        twin_id=twin_id,
        request=request,
        surface="public",
        stream=True,
        user_id=f"public:{twin_id}:{token[:8]}",
        share_token=token,
        http_request=http_request,
    )


def _get_conversation_or_404(conversation_id: str, user: dict) -> Dict[str, Any]:
    conv = get_conversation_repository().get_conversation_for_tenant(
        conversation_id=conversation_id,
        tenant_id=user["tenant_id"],
    )
    if not conv:
        raise conversation_not_found()
    return conv


@router.get("/v2/chat/conversations")
async def list_conversations(
    twin_id: Optional[str] = None,
    limit: int = Query(default=20, le=50, ge=1),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(require_tenant),
) -> Dict[str, Any]:
    if twin_id:
        verify_twin_ownership(twin_id, user)
    conversations = get_conversation_repository().list_conversations(
        tenant_id=user["tenant_id"],
        twin_id=twin_id,
        limit=limit,
        offset=offset,
    )
    return {"conversations": conversations, "count": len(conversations)}


@router.get("/v2/chat/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    user: dict = Depends(require_tenant),
) -> Dict[str, Any]:
    return _get_conversation_or_404(conversation_id, user)


@router.get("/v2/chat/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    user: dict = Depends(require_tenant),
) -> Dict[str, Any]:
    _get_conversation_or_404(conversation_id, user)
    return {
        "conversation_id": conversation_id,
        "messages": get_conversation_repository().list_messages(conversation_id=conversation_id),
    }


@router.post("/v2/chat/conversations/{conversation_id}/promote")
async def promote_to_knowledge(
    conversation_id: str,
    request: Request,
    user: dict = Depends(require_tenant),
) -> Dict[str, Any]:
    """Promote a Q&A pair from a conversation into Pinecone knowledge."""
    from adk_core.services.agent_service import invalidate_agent
    from adk_core.services.vector_store import upsert_faq

    conv = _get_conversation_or_404(conversation_id, user)
    twin_id = conv.get("twin_id")
    if not twin_id:
        raise HTTPException(status_code=400, detail="Conversation has no twin_id")

    body = await request.json()
    question = (body.get("question") or "").strip()
    answer = (body.get("answer") or "").strip()

    if not question or not answer:
        raise HTTPException(status_code=400, detail="question and answer are required")

    point_id = await upsert_faq(question=question, answer=answer, twin_id=twin_id)
    invalidate_agent(twin_id)

    return {
        "status": "promoted",
        "point_id": point_id,
        "twin_id": twin_id,
        "question": question,
    }
