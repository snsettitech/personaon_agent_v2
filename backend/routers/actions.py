"""Actions router — configurable persona actions (booking, webhooks, canned responses).

Actions are stored in twins.settings.actions[] and executed by visitors
via the public chat or widget. Owner manages them from the dashboard.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from modules.auth_guard import require_tenant, verify_twin_ownership
from modules.observability import get_supabase_client
from modules.share_links import _fetch_twin_row, is_publicly_accessible_twin_record

logger = logging.getLogger(__name__)

router = APIRouter(tags=["actions"])

# ---------------------------------------------------------------------------
# Rate limiting (same pattern as chat.py)
# ---------------------------------------------------------------------------

_action_rate_limits: dict[str, list[float]] = defaultdict(list)
_ACTION_RATE_LIMIT = 30  # max executions per window per IP+twin
_ACTION_RATE_WINDOW = 3600  # 1 hour


def _check_action_rate_limit(tracking_key: str) -> bool:
    """Return True if request is allowed, False if rate limited."""
    now = time.time()
    window_start = now - _ACTION_RATE_WINDOW
    _action_rate_limits[tracking_key] = [
        t for t in _action_rate_limits[tracking_key] if t > window_start
    ]
    if len(_action_rate_limits[tracking_key]) >= _ACTION_RATE_LIMIT:
        return False
    _action_rate_limits[tracking_key].append(now)
    return True


def _get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    return (
        forwarded_for.split(",")[0].strip()
        if forwarded_for
        else (request.client.host if request.client else "unknown")
    )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ActionExecuteRequest(BaseModel):
    action_id: str
    collected_data: dict[str, str] = Field(default_factory=dict)


class ActionExecuteResponse(BaseModel):
    status: str
    result: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_twin_actions(twin_id: str) -> list[dict[str, Any]]:
    """Load actions array from twins.settings.actions."""
    sb = get_supabase_client()
    resp = (
        sb.table("twins")
        .select("id, settings")
        .eq("id", twin_id)
        .single()
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Twin not found")

    settings = resp.data.get("settings") or {}
    actions = settings.get("actions") or []
    return actions


def _find_action(actions: list[dict[str, Any]], action_id: str) -> dict[str, Any] | None:
    """Find an action by id within the actions list."""
    for action in actions:
        if action.get("id") == action_id:
            return action
    return None


def _public_twin_or_404(twin_id: str) -> None:
    """Verify the twin exists and is publicly accessible."""
    twin = _fetch_twin_row(twin_id)
    if not twin or not is_publicly_accessible_twin_record(twin):
        raise HTTPException(status_code=404, detail="Twin not found")


def _log_execution(
    twin_id: str,
    action: dict[str, Any],
    collected_data: dict[str, str],
    status: str,
    result: dict[str, Any],
    client_ip: str,
) -> str | None:
    """Log action execution to action_executions table. Non-critical."""
    try:
        sb = get_supabase_client()
        execution_id = str(uuid.uuid4())
        sb.table("action_executions").insert({
            "id": execution_id,
            "twin_id": twin_id,
            "action_type": action.get("type", "unknown"),
            "status": status,
            "inputs": {
                "action_id": action.get("id"),
                "trigger": action.get("trigger"),
                "label": action.get("label"),
                "collected_data": collected_data,
            },
            "outputs": result,
            "executed_by": client_ip,
        }).execute()
        return execution_id
    except Exception as exc:
        logger.warning("Failed to log action execution: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------


@router.get("/v2/actions/{twin_id}/available")
async def get_available_actions(twin_id: str) -> dict[str, Any]:
    """Return list of active actions for a twin. Public endpoint (no auth)."""
    _public_twin_or_404(twin_id)
    actions = _load_twin_actions(twin_id)

    available = []
    for action in actions:
        if not action.get("is_active", True):
            continue
        available.append({
            "id": action.get("id"),
            "type": action.get("type"),
            "trigger": action.get("trigger"),
            "triggers": action.get("triggers", [action.get("trigger", "")]),
            "label": action.get("label"),
            "collect_fields": action.get("collect_fields", []),
        })

    return {"actions": available}


@router.post("/v2/actions/{twin_id}/execute", response_model=ActionExecuteResponse)
async def execute_action(
    twin_id: str,
    request: ActionExecuteRequest,
    http_request: Request,
) -> ActionExecuteResponse:
    """Execute a specific action for a twin. Public, rate-limited."""
    _public_twin_or_404(twin_id)

    # Rate limit by IP + twin
    client_ip = _get_client_ip(http_request)
    tracking_key = f"action:{twin_id}:{client_ip}"
    if not _check_action_rate_limit(tracking_key):
        raise HTTPException(
            status_code=429,
            detail="Too many action requests. Please try again later.",
        )

    actions = _load_twin_actions(twin_id)
    action = _find_action(actions, request.action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    if not action.get("is_active", True):
        raise HTTPException(status_code=400, detail="Action is not active")

    # Validate required collected fields
    required_fields = action.get("collect_fields", [])
    for field_name in required_fields:
        if field_name not in request.collected_data or not request.collected_data[field_name].strip():
            raise HTTPException(
                status_code=400,
                detail=f"Missing required field: {field_name}",
            )

    action_type = action.get("type", "")
    config = action.get("config", {})
    result: dict[str, Any] = {}
    status = "executed"

    try:
        if action_type == "respond_with_message":
            result = {"message": config.get("message", "")}

        elif action_type == "booking_link":
            # Frontend handles the link redirect; return the URL and optional message
            result = {
                "url": config.get("url", ""),
                "message": config.get("message", "Opening booking page..."),
            }

        elif action_type == "webhook":
            import httpx

            webhook_url = config.get("webhook_url", "")
            if not webhook_url:
                raise HTTPException(status_code=400, detail="Webhook URL not configured")

            # SECURITY: validate webhook URL is external HTTPS (prevent SSRF)
            from urllib.parse import urlparse as _urlparse
            _parsed = _urlparse(webhook_url)
            if _parsed.scheme != "https" or not _parsed.netloc:
                raise HTTPException(status_code=400, detail="Webhook URL must be a valid HTTPS URL")

            payload = {
                "twin_id": twin_id,
                "action_id": action.get("id"),
                "trigger": action.get("trigger"),
                "collected_data": request.collected_data,
                "timestamp": time.time(),
            }

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(webhook_url, json=payload)
                result = {
                    "webhook_status": resp.status_code,
                    "confirmation": config.get("confirmation", "Request submitted successfully."),
                }
                if resp.status_code >= 400:
                    status = "webhook_error"
                    result["webhook_error"] = resp.text[:200]

        elif action_type == "mode_switch":
            result = {
                "mode": config.get("mode", ""),
                "prompt_override": config.get("prompt_override", ""),
                "message": f"Switched to {config.get('mode', 'custom')} mode.",
            }

        else:
            raise HTTPException(status_code=400, detail=f"Unknown action type: {action_type}")

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Action execution failed for twin %s", twin_id)
        status = "error"
        result = {"error": str(exc)}

    # Log execution (non-critical)
    _log_execution(
        twin_id=twin_id,
        action=action,
        collected_data=request.collected_data,
        status=status,
        result=result,
        client_ip=client_ip,
    )

    return ActionExecuteResponse(status=status, result=result)


# ---------------------------------------------------------------------------
# Owner endpoints (auth required)
# ---------------------------------------------------------------------------


@router.get("/v2/actions/{twin_id}/executions")
async def list_executions(
    twin_id: str,
    limit: int = 50,
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """Return recent action executions for the owner's twin."""
    verify_twin_ownership(twin_id, user)

    sb = get_supabase_client()
    try:
        resp = (
            sb.table("action_executions")
            .select("id, twin_id, action_type, status, inputs, outputs, executed_by, executed_at, created_at")
            .eq("twin_id", twin_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        executions = resp.data if resp.data else []
    except Exception as exc:
        logger.warning("Failed to fetch action executions: %s", exc)
        executions = []

    return {"executions": executions, "count": len(executions)}
