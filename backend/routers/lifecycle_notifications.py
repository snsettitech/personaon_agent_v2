"""Lifecycle notification preferences, cron, and Resend webhooks."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from modules.auth_guard import get_current_user, resolve_tenant_id
from modules.graph_outbox import GraphOperationType, get_graph_outbox
from routers.twins_helpers import _require_authenticated_user
from services.lifecycle_email_service import (
    CATEGORY_PREF_FIELD,
    lifecycle_idempotency_key,
    load_lifecycle_preferences,
    parse_unsubscribe_token,
    record_resend_webhook,
    save_lifecycle_preferences,
    suppress_email,
    unsubscribe_user,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["lifecycle-notifications"])


class NotificationPreferencePatch(BaseModel):
    product_education_enabled: bool | None = None
    daily_activity_enabled: bool | None = None
    weekly_report_enabled: bool | None = None
    hot_lead_alerts_enabled: bool | None = None
    timezone: str | None = None


def _verify_cron_request(request: Request) -> bool:
    cloud_run_service_url = os.getenv("CLOUD_RUN_SERVICE_URL", "")
    cron_secret = os.getenv("CRON_SECRET", "")
    if not cloud_run_service_url and not cron_secret:
        logger.warning("[LifecycleCronAuth] no auth configured")
        return False
    if not cloud_run_service_url and cron_secret:
        return request.headers.get("X-Cron-Secret") == cron_secret

    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        return False
    token = authorization[7:]
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token

        google_id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=cloud_run_service_url,
        )
        return True
    except Exception as exc:
        logger.warning("[LifecycleCronAuth] OIDC verification failed: %s", exc)
        return False


def _enqueue_candidate(candidate: dict[str, Any]) -> None:
    email_type = str(candidate["email_type"])
    scope_type = str(
        candidate.get("scope_type")
        or ("user" if email_type.startswith("welcome") else "twin")
    )
    default_scope_id = candidate["user_id"] if scope_type == "user" else candidate.get("twin_id")
    scope_id = str(candidate.get("scope_id") or default_scope_id or candidate["user_id"])
    idempotency_key = lifecycle_idempotency_key(
        user_id=str(candidate["user_id"]),
        email_type=email_type,
        scope_type=scope_type,
        scope_id=scope_id,
        period_key=str(candidate["period_key"]),
    )
    payload = {
        **candidate,
        "email_type": email_type,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "idempotency_key": idempotency_key,
    }
    get_graph_outbox().submit(
        tenant_id=str(candidate["tenant_id"]),
        twin_id=str(candidate.get("twin_id") or scope_id),
        operation=GraphOperationType.SEND_LIFECYCLE_EMAIL,
        idempotency_key=idempotency_key,
        payload=payload,
        priority=3 if candidate.get("category") == "hot_lead_alert" else 1,
    )


def _tag_value(tags: Any, name: str) -> str:
    if isinstance(tags, dict):
        return str(tags.get(name) or "")
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, dict) and tag.get("name") == name:
                return str(tag.get("value") or "")
    return ""


def _first_email(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0] if value else "")
    return str(value or "")


def _candidate_reason_counts(candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        reason = str(candidate.get("candidate_reason") or "unspecified")
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def _capture_cron_event(
    *,
    event: str,
    candidate_count: int,
    enqueued: int,
    dry_run: bool,
    reasons: dict[str, int],
) -> None:
    try:
        from modules.posthog_analytics import ph_capture

        ph_capture(
            user_id="system:lifecycle-cron",
            event=event,
            properties={
                "candidate_count": candidate_count,
                "enqueued": enqueued,
                "dry_run": dry_run,
                "reasons": reasons,
            },
        )
    except Exception:
        pass


@router.get("/v2/notifications/preferences")
async def get_notification_preferences(user=Depends(get_current_user)) -> dict[str, Any]:
    user = _require_authenticated_user(user)
    user_id = str(user.get("user_id") or user.get("id") or "")
    email = str(user.get("email") or "")
    tenant_id = resolve_tenant_id(user_id, email)
    prefs = load_lifecycle_preferences(user_id=user_id, tenant_id=tenant_id)
    return {"status": "ok", "data": prefs}


@router.patch("/v2/notifications/preferences")
async def update_notification_preferences(
    patch: NotificationPreferencePatch,
    user=Depends(get_current_user),
) -> dict[str, Any]:
    user = _require_authenticated_user(user)
    user_id = str(user.get("user_id") or user.get("id") or "")
    email = str(user.get("email") or "")
    tenant_id = resolve_tenant_id(user_id, email)
    saved = save_lifecycle_preferences(
        user_id=user_id,
        tenant_id=tenant_id,
        patch=patch.model_dump(exclude_none=True),
    )
    try:
        from modules.posthog_analytics import ph_capture

        ph_capture(
            user_id=user_id,
            event="notification_preferences_updated",
            properties={key: saved.get(key) for key in CATEGORY_PREF_FIELD.values()},
        )
    except Exception:
        pass
    return {"status": "ok", "data": saved}


@router.post("/v2/cron/lifecycle/daily")
async def lifecycle_daily_cron(
    request: Request,
    dry_run: bool = Query(False),
) -> dict[str, Any]:
    if not _verify_cron_request(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    from services.lifecycle_digest_service import collect_daily_lifecycle_candidates

    candidates = collect_daily_lifecycle_candidates()
    reasons = _candidate_reason_counts(candidates)
    dry = dry_run or os.getenv("LIFECYCLE_EMAIL_DRY_RUN", "true").lower() in {"1", "true", "yes", "on"}
    max_sends = int(os.getenv("LIFECYCLE_EMAIL_MAX_SENDS_PER_RUN", "10"))
    enqueued = 0
    if not dry:
        for candidate in candidates[:max_sends]:
            _enqueue_candidate(candidate)
            enqueued += 1
    logger.info("[LifecycleDailyCron] candidates=%d enqueued=%d dry_run=%s", len(candidates), enqueued, dry)
    _capture_cron_event(
        event="lifecycle_daily_cron_run",
        candidate_count=len(candidates),
        enqueued=enqueued,
        dry_run=dry,
        reasons=reasons,
    )
    return {"status": "ok", "data": {"candidates": len(candidates), "enqueued": enqueued, "dry_run": dry, "reasons": reasons}}


@router.post("/v2/cron/lifecycle/weekly")
async def lifecycle_weekly_cron(
    request: Request,
    dry_run: bool = Query(False),
) -> dict[str, Any]:
    if not _verify_cron_request(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    from services.lifecycle_digest_service import collect_weekly_lifecycle_candidates

    candidates = collect_weekly_lifecycle_candidates()
    reasons = _candidate_reason_counts(candidates)
    dry = dry_run or os.getenv("LIFECYCLE_EMAIL_DRY_RUN", "true").lower() in {"1", "true", "yes", "on"}
    max_sends = int(os.getenv("LIFECYCLE_EMAIL_MAX_SENDS_PER_RUN", "10"))
    enqueued = 0
    if not dry:
        for candidate in candidates[:max_sends]:
            _enqueue_candidate(candidate)
            enqueued += 1
    logger.info("[LifecycleWeeklyCron] candidates=%d enqueued=%d dry_run=%s", len(candidates), enqueued, dry)
    _capture_cron_event(
        event="lifecycle_weekly_cron_run",
        candidate_count=len(candidates),
        enqueued=enqueued,
        dry_run=dry,
        reasons=reasons,
    )
    return {"status": "ok", "data": {"candidates": len(candidates), "enqueued": enqueued, "dry_run": dry, "reasons": reasons}}


@router.get("/v2/notifications/unsubscribe/{token}")
async def unsubscribe_get(token: str, category: str | None = None) -> HTMLResponse:
    user_id = parse_unsubscribe_token(token)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid unsubscribe link")
    unsubscribe_user(user_id, category=category)
    return HTMLResponse(
        "<!doctype html><title>Unsubscribed</title><p>You have been unsubscribed. You can change this in PersonaOn notification settings.</p>"
    )


@router.post("/v2/notifications/unsubscribe/{token}")
async def unsubscribe_post(token: str, category: str | None = None) -> dict[str, Any]:
    user_id = parse_unsubscribe_token(token)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid unsubscribe link")
    unsubscribe_user(user_id, category=category)
    return {"status": "ok"}


@router.post("/v2/webhooks/resend")
async def resend_webhook(request: Request) -> dict[str, Any]:
    secret = os.getenv("RESEND_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook verification is not configured")
    raw = await request.body()
    payload_text = raw.decode("utf-8")
    headers = {
        "id": request.headers.get("svix-id", ""),
        "timestamp": request.headers.get("svix-timestamp", ""),
        "signature": request.headers.get("svix-signature", ""),
    }
    try:
        import resend

        resend.Webhooks.verify(
            {
                "payload": payload_text,
                "headers": headers,
                "webhook_secret": secret,
            }
        )
    except Exception as exc:
        logger.warning("[ResendWebhook] invalid signature: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid signature") from exc

    try:
        payload = json.loads(payload_text or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    record_resend_webhook(payload, dict(request.headers))
    event_type = str(payload.get("type") or payload.get("event") or "")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    to_email = _first_email(data.get("to") or data.get("email"))
    user_id = _tag_value(data.get("tags"), "user_id")
    if event_type in {"email.bounced", "email.complained", "email.suppressed"} and to_email:
        suppress_email(
            user_id=user_id or None,
            email=to_email,
            reason=event_type,
            provider_event_id=request.headers.get("svix-id"),
        )
    return {"status": "ok"}
