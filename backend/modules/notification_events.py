"""Notification event bus models and persistence helpers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class NotificationEventCreate(BaseModel):
    tenant_id: str
    event_type: str
    subject_id: str
    actor_id: str | None = None
    context_json: dict[str, Any] = Field(default_factory=dict)


class NotificationEvent(NotificationEventCreate):
    id: str
    status: Literal["pending", "processing", "processed", "failed"] = "pending"
    error_message: str | None = None
    processed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_from_row(row: dict[str, Any]) -> NotificationEvent:
    data = dict(row)
    data["context_json"] = data.get("context_json") or {}
    return NotificationEvent.model_validate(data)


def emit_notification_event(sb: Any, data: NotificationEventCreate) -> NotificationEvent:
    now = _utcnow_iso()
    payload = data.model_dump(mode="json")
    payload["created_at"] = now
    payload["updated_at"] = now
    try:
        resp = sb.table("notification_events").insert(payload).execute()
        rows = resp.data or []
        if not rows:
            raise RuntimeError("notification event insert returned no rows")
        return _event_from_row(rows[0])
    except Exception as exc:
        logger.exception("[notification_events] emit failed type=%s subject=%s", data.event_type, data.subject_id)
        raise RuntimeError("emit notification event failed") from exc


def get_notification_event(sb: Any, event_id: str) -> NotificationEvent | None:
    resp = (
        sb.table("notification_events")
        .select("*")
        .eq("id", event_id)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    return _event_from_row(rows[0]) if rows else None


def mark_notification_event_processing(sb: Any, event_id: str) -> None:
    sb.table("notification_events").update({"status": "processing", "updated_at": _utcnow_iso()}).eq("id", event_id).execute()


def mark_notification_event_processed(sb: Any, event_id: str) -> None:
    now = _utcnow_iso()
    sb.table("notification_events").update({"status": "processed", "processed_at": now, "updated_at": now}).eq("id", event_id).execute()


def mark_notification_event_failed(sb: Any, event_id: str, error_message: str) -> None:
    sb.table("notification_events").update(
        {"status": "failed", "error_message": error_message[:2000], "updated_at": _utcnow_iso()}
    ).eq("id", event_id).execute()
