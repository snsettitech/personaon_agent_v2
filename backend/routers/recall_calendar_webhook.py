"""Recall.ai Calendar V2 webhook handler — Task P1.1.D.

Receives ``calendar.update`` and ``calendar.sync_events`` webhooks from Recall.
Verifies the Svix HMAC signature (shared ``RECALL_WEBHOOK_SECRET``).

On ``calendar.sync_events`` we enqueue a ``RECALL_CALENDAR_SYNC`` graph_outbox
job that fetches the updated calendar events and upserts them into the
``meetings`` table. The webhook itself is a pull trigger; the actual event
data lives behind ``GET /api/v2/calendars/{id}/calendar-events/``.

On ``calendar.update`` with ``status: disconnected`` we deactivate the matching
``tool_connectors`` row so the booking flow stops handing out a dead calendar.

Webhook responses are intentionally 200 for non-fatal local errors (DB lookup,
enqueue failure) — Recall retries forever on 5xx and we don't want our queue
to back up because of transient infra blips. Real signature failures still
return 401 so a misconfigured endpoint is loud.

Docs: https://docs.recall.ai/docs/calendar-v2-webhooks
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from modules.graph_outbox import GraphOperationType, get_graph_outbox
from modules.observability import supabase
from services.recall_auth import verify_recall_webhook

logger = logging.getLogger(__name__)

router = APIRouter(tags=["recall-calendar-webhook"])


@router.post("/v2/meeting-calendar/webhook")
async def recall_calendar_webhook(request: Request) -> dict[str, str]:
    """Receive Recall.ai Calendar V2 webhook events.

    Returns a structured ``{"status": "..."}`` payload so the integration
    test contract stays explicit. All non-signature failures resolve to 200
    so Recall does not retry on our DB/queue blips.
    """
    body = await request.body()
    webhook_id = request.headers.get("webhook-id", "")
    webhook_timestamp = request.headers.get("webhook-timestamp", "")
    webhook_signature = request.headers.get("webhook-signature", "")

    if not verify_recall_webhook(body, webhook_id, webhook_timestamp, webhook_signature):
        logger.warning(
            "[RecallCalWebhook] invalid signature webhook_id=%s", webhook_id
        )
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        data: dict[str, Any] = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.warning("[RecallCalWebhook] malformed JSON body: %s", exc)
        return {"status": "ignored_bad_json"}

    event = str(data.get("event") or "")
    payload = data.get("data") or {}
    recall_calendar_id = str(payload.get("calendar_id") or "")

    logger.info(
        "[RecallCalWebhook] event=%s recall_calendar_id=%s",
        event, recall_calendar_id,
    )

    if not recall_calendar_id:
        logger.warning("[RecallCalWebhook] payload missing calendar_id event=%s", event)
        return {"status": "ignored_no_calendar_id"}

    # Look up twin via tool_connectors. This is the only source of truth that
    # ties a Recall calendar_id back to a PersonaOn twin. tool_connectors does
    # not store tenant_id (the table predates the per-tenant data model), so
    # we resolve tenant_id via twins.tenant_id in a second query.
    try:
        connector = (
            supabase.table("tool_connectors")
            .select("twin_id, is_active")
            .eq("recall_calendar_id", recall_calendar_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.error(
            "[RecallCalWebhook] connector lookup failed recall_cal=%s: %s",
            recall_calendar_id, exc,
        )
        # 200 so Recall does not retry forever on our DB issues.
        return {"status": "deferred_db_error"}

    rows = getattr(connector, "data", None) or []
    if not rows:
        logger.warning(
            "[RecallCalWebhook] no connector for recall_cal=%s (orphaned subscription?)",
            recall_calendar_id,
        )
        return {"status": "ignored_orphan"}

    connector_row = rows[0]
    twin_id = str(connector_row.get("twin_id") or "")

    # Resolve tenant_id from twins table (tool_connectors has no tenant_id column).
    try:
        twin_lookup = (
            supabase.table("twins")
            .select("tenant_id")
            .eq("id", twin_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.error(
            "[RecallCalWebhook] tenant lookup failed twin=%s: %s",
            twin_id, exc,
        )
        return {"status": "deferred_db_error"}

    twin_rows = getattr(twin_lookup, "data", None) or []
    if not twin_rows:
        logger.warning(
            "[RecallCalWebhook] twin not found twin=%s recall_cal=%s",
            twin_id, recall_calendar_id,
        )
        return {"status": "ignored_orphan"}

    tenant_id = str(twin_rows[0].get("tenant_id") or "")
    if not tenant_id:
        logger.warning(
            "[RecallCalWebhook] twin missing tenant_id twin=%s recall_cal=%s",
            twin_id, recall_calendar_id,
        )
        return {"status": "ignored_no_tenant"}

    if event == "calendar.update":
        # Status changes flow through here. If Recall says the calendar is
        # disconnected (user revoked OAuth, refresh-token died, etc.), flip
        # the connector inactive so the booking flow does not try to use it.
        calendar_obj = payload.get("calendar") or {}
        status_value = str(calendar_obj.get("status") or "")
        if status_value == "disconnected":
            try:
                # Defense-in-depth: filter on both recall_calendar_id AND twin_id
                # so a (hypothetically) shared/leaked calendar_id can never flip
                # another tenant's connector inactive. Per
                # feedback_tenant_scope_mutations.md, always scope mutations by
                # tenant/owner even when the primary key is already unique.
                supabase.table("tool_connectors").update({
                    "is_active": False,
                    "last_error": f"Recall calendar marked {status_value}",
                }).eq("recall_calendar_id", recall_calendar_id) \
                  .eq("twin_id", twin_id) \
                  .execute()
                logger.info(
                    "[RecallCalWebhook] deactivated connector twin=%s recall_cal=%s",
                    twin_id, recall_calendar_id,
                )
            except Exception as exc:
                logger.error(
                    "[RecallCalWebhook] connector deactivate failed twin=%s: %s",
                    twin_id, exc,
                )
        return {"status": "calendar_update_processed"}

    if event == "calendar.sync_events":
        # L24: skip sync for connectors the user disconnected. Without this,
        # a late-arriving sync_events webhook (after the user clicked
        # Disconnect, calendar.update disconnected has flipped is_active=False)
        # still enqueues a worker job that upserts meetings into a "disconnected"
        # calendar -- creating ghost rows the user cannot see in the UI.
        if connector_row.get("is_active") is False:
            logger.warning(
                "[RecallCalWebhook] inactive connector — skipping sync twin=%s recall_cal=%s",
                twin_id, recall_calendar_id,
            )
            return {"status": "ignored_inactive"}

        # L25: normalise last_updated_ts=None to a stable string so the
        # idempotency key doesn't become "...:None" (which permanently dedupes
        # every future None-keyed sync to the first one's terminal status).
        # Initial-sync calls (no upper bound on what to fetch) use the literal
        # "initial" -- subsequent None-keyed retries from Recall will dedupe
        # together, but future incremental syncs with a real timestamp get
        # their own key and aren't blocked.
        last_updated_ts = payload.get("last_updated_ts")
        idem_ts = last_updated_ts if last_updated_ts else "initial"
        try:
            get_graph_outbox().submit(
                tenant_id=tenant_id,
                twin_id=twin_id,
                operation=GraphOperationType.RECALL_CALENDAR_SYNC,
                # Idempotency: dedupe by (calendar_id, last_updated_ts). Recall
                # can fire the same sync_events webhook twice with the same
                # last_updated_ts on retry — we only want one fetch+upsert pass.
                idempotency_key=(
                    f"recall_calendar_sync:{recall_calendar_id}:{idem_ts}"
                ),
                payload={
                    "recall_calendar_id": recall_calendar_id,
                    "twin_id": twin_id,
                    "tenant_id": tenant_id,
                    "last_updated_ts": last_updated_ts,
                },
                priority=5,
            )
        except Exception as exc:
            logger.error(
                "[RecallCalWebhook] enqueue RECALL_CALENDAR_SYNC failed twin=%s: %s",
                twin_id, exc,
            )
            # 200 — Recall should not retry on our queue errors.
            return {"status": "deferred_enqueue_error"}
        return {"status": "sync_enqueued"}

    logger.info("[RecallCalWebhook] unhandled event=%s twin=%s", event, twin_id)
    return {"status": "ignored_unknown_event"}
