"""Monitoring helpers for lifecycle email delivery state."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


def find_stale_sending_lifecycle_email_events(
    sb: Any | None = None,
    *,
    stale_after_minutes: int = 30,
    limit: int = 100,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return lifecycle email claims that appear stuck before provider send."""
    if sb is None:
        from modules.observability import supabase

        client: Any = supabase
    else:
        client = sb

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = (current - timedelta(minutes=stale_after_minutes)).isoformat()

    try:
        resp = (
            client.table("lifecycle_email_events")
            .select(
                "id,user_id,tenant_id,email_type,category,scope_type,scope_id,"
                "period_key,recipient_email,status,resend_message_id,error_message,"
                "created_at,updated_at"
            )
            .eq("status", "sending")
            .is_("resend_message_id", "null")
            .lt("created_at", cutoff)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return list(resp.data or [])
    except Exception as exc:
        logger.warning("[LifecycleEmail] stale sending lookup failed: %s", exc)
        return []
