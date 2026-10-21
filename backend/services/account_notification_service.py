"""Best-effort account notification enqueue helpers."""

from __future__ import annotations

import logging
import uuid

from modules.graph_outbox import GraphOperationType, get_graph_outbox
from modules.notification_events import NotificationEventCreate, emit_notification_event

logger = logging.getLogger(__name__)

SYSTEM_TWIN_ID = "00000000-0000-4000-8000-000000000000"
FLOW_EVENT_TYPES = {
    "access_granted": "account.access_granted",
    "account_suspended": "account.suspended",
}


def _stable_flow_run_id(idempotency_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"personaon:account-notification:{idempotency_key}"))


def enqueue_account_notification(
    sb,
    *,
    user_id: str,
    flow_key: str,
    idempotency_key: str,
    actor_id: str | None = None,
) -> None:
    """Emit and enqueue an account notification event without blocking the admin mutation."""
    try:
        event_type = FLOW_EVENT_TYPES.get(flow_key)
        if not event_type:
            logger.warning(
                "[account_notifications] unknown flow_key=%s user_id=%s",
                flow_key,
                user_id,
            )
            return
        event = emit_notification_event(
            sb,
            NotificationEventCreate(
                tenant_id=user_id,
                event_type=event_type,
                subject_id=user_id,
                actor_id=actor_id,
                context_json={"source": "admin.users", "legacy_flow_key": flow_key},
            ),
        )
        scope_id = _stable_flow_run_id(idempotency_key)
        get_graph_outbox().submit(
            tenant_id=user_id,
            twin_id=SYSTEM_TWIN_ID,
            operation=GraphOperationType.PROCESS_NOTIFICATION_EVENT,
            idempotency_key=idempotency_key,
            scope_id=scope_id,
            payload={
                "event_id": event.id,
                "event_type": event.event_type,
                "subject_id": event.subject_id,
            },
        )
    except Exception as exc:
        logger.exception(
            "[account_notifications] enqueue failed key=%s user_id=%s err=%r",
            flow_key,
            user_id,
            exc,
        )
