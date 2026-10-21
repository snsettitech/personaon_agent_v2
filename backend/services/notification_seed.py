"""Seed built-in notification flows."""

from __future__ import annotations

import logging
from typing import Any

from modules.notification_flows import (
    AudienceSpec,
    FlowGuardrails,
    NotificationFlowCreate,
    create_flow,
    get_flow_by_key,
    update_flow_status,
)

logger = logging.getLogger(__name__)


SEED_FLOWS = [
    NotificationFlowCreate(
        key="access_granted",
        name="Access Granted",
        kind="transactional",
        trigger_type="event",
        audience_spec=AudienceSpec(segment="single_user"),
        email_type="access_granted",
        category="account",
        guardrails=FlowGuardrails(
            max_recipients=1,
            throttle_per_min=60,
            dry_run_required=False,
            exempt_from_caps=True,
        ),
        created_by="system",
    ),
    NotificationFlowCreate(
        key="account_suspended",
        name="Account Suspended",
        kind="transactional",
        trigger_type="event",
        audience_spec=AudienceSpec(segment="single_user"),
        email_type="account_suspended",
        category="account",
        guardrails=FlowGuardrails(
            max_recipients=1,
            throttle_per_min=60,
            dry_run_required=False,
            exempt_from_caps=True,
        ),
        created_by="system",
    ),
    NotificationFlowCreate(
        key="lead_captured",
        name="New Lead Captured",
        kind="transactional",
        trigger_type="event",
        audience_spec=AudienceSpec(segment="single_user"),
        email_type="lead_captured",
        category="account",
        guardrails=FlowGuardrails(
            max_recipients=1,
            throttle_per_min=60,
            dry_run_required=False,
            exempt_from_caps=True,
        ),
        created_by="system",
    ),
]


async def seed_transactional_flows(sb: Any) -> None:
    """Idempotently create and activate built-in transactional flows.

    Declared async so callers can await it from lifespan hooks; internally
    all Supabase calls are synchronous (short-lived, startup-only path).
    """
    for flow_create in SEED_FLOWS:
        existing = get_flow_by_key(sb, flow_create.key)
        if existing:
            if existing.status != "active":
                update_flow_status(sb, existing.id, "active", approved_by="system:seed")
                logger.info("[notifications] re-activated seeded flow key=%s id=%s", existing.key, existing.id)
            continue
        flow = create_flow(sb, flow_create)
        update_flow_status(sb, flow.id, "active", approved_by="system:seed")
        logger.info("[notifications] seeded flow key=%s id=%s", flow.key, flow.id)
