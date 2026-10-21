"""Outcome measurement for the agentic notification loop.

The worker can retry this safely: every run reloads lifecycle rows and Resend
webhooks, recomputes totals, updates the flow run, and upserts one memory row
for that run.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from services.notification_memory import EmbeddingFn, NotificationOutcomeMemory

logger = logging.getLogger(__name__)

SYSTEM_TWIN_ID = "00000000-0000-4000-8000-000000000000"
DEFAULT_OUTCOME_DELAY_DAYS = 5


class NotificationFlowRunForOutcome(BaseModel):
    id: str
    tenant_id: str | None = None
    flow_id: str
    flow_run_key: str = ""
    audience_count: int = 0
    enqueued: int = 0
    skipped: int = 0
    failed: int = 0
    status: str = "pending"
    summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class NotificationFlowForOutcome(BaseModel):
    id: str
    tenant_id: str | None = None
    email_type: str = ""
    category: str = ""
    context_overrides: dict[str, Any] = Field(default_factory=dict)


class LifecycleEmailEventForOutcome(BaseModel):
    id: str
    user_id: str | None = None
    tenant_id: str | None = None
    email_type: str
    category: str
    scope_type: str
    scope_id: str
    period_key: str | None = None
    recipient_email: str | None = None
    status: str
    resend_message_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class ResendWebhookEventForOutcome(BaseModel):
    svix_id: str | None = None
    event_type: str
    resend_message_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    received_at: datetime | None = None


class NotificationOutcomeMeasurement(BaseModel):
    flow_run_id: str
    flow_id: str
    tenant_id: str | None = None
    recipient_count: int
    sent_count: int
    open_count: int
    click_count: int
    conversion_count: int
    conversion_source: Literal["posthog", "not_configured", "error"]
    opened_message_ids: list[str] = Field(default_factory=list)
    clicked_message_ids: list[str] = Field(default_factory=list)
    measured_at: datetime


ConversionCounter = Callable[[list[str], str, datetime, datetime], int | None]
MemoryWriter = Callable[[Any, NotificationOutcomeMemory], Any]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def outcome_delay_at(now: datetime | None = None) -> datetime:
    days_raw = os.getenv("NOTIFICATION_OUTCOME_DELAY_DAYS", str(DEFAULT_OUTCOME_DELAY_DAYS))
    try:
        days = max(1, int(days_raw))
    except ValueError:
        days = DEFAULT_OUTCOME_DELAY_DAYS
    return (now or utc_now()) + timedelta(days=days)


def schedule_notification_outcome_measurement(
    *,
    outbox: Any,
    tenant_id: str,
    flow_run_id: str,
    flow_id: str,
    now: datetime | None = None,
) -> None:
    from modules.graph_outbox import GraphOperationType

    outbox.submit(
        tenant_id=tenant_id,
        twin_id=SYSTEM_TWIN_ID,
        operation=GraphOperationType.MEASURE_NOTIFICATION_OUTCOME,
        idempotency_key=f"measure-notification-outcome-{flow_run_id}",
        scope_id=flow_run_id,
        next_attempt_after=outcome_delay_at(now),
        payload={"flow_run_id": flow_run_id, "flow_id": flow_id},
    )


def load_notification_flow_run(sb: Any, flow_run_id: str) -> NotificationFlowRunForOutcome:
    resp = (
        sb.table("notification_flow_runs")
        .select("*")
        .eq("id", flow_run_id)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        raise ValueError(f"notification_flow_run not found: {flow_run_id}")
    return NotificationFlowRunForOutcome.model_validate(rows[0])


def load_notification_flow(sb: Any, flow_id: str) -> NotificationFlowForOutcome | None:
    try:
        resp = (
            sb.table("notification_flows")
            .select("id,tenant_id,email_type,category,context_overrides")
            .eq("id", flow_id)
            .limit(1)
            .execute()
        )
    except Exception:
        logger.warning("[notification_outcomes] flow lookup unavailable flow_id=%s", flow_id)
        return None
    rows = resp.data or []
    return NotificationFlowForOutcome.model_validate(rows[0]) if rows else None


def load_lifecycle_email_events(sb: Any, scope_id: str) -> list[LifecycleEmailEventForOutcome]:
    resp = (
        sb.table("lifecycle_email_events")
        .select("*")
        .eq("scope_id", scope_id)
        .execute()
    )
    return [LifecycleEmailEventForOutcome.model_validate(row) for row in (resp.data or [])]


def load_resend_webhook_events(
    sb: Any,
    resend_message_ids: Sequence[str],
) -> list[ResendWebhookEventForOutcome]:
    message_ids = sorted({str(value).strip() for value in resend_message_ids if str(value).strip()})
    if not message_ids:
        return []

    resp = (
        sb.table("resend_webhook_events")
        .select("*")
        .in_("resend_message_id", message_ids)
        .execute()
    )
    return [ResendWebhookEventForOutcome.model_validate(row) for row in (resp.data or [])]


def aggregate_resend_engagement(
    lifecycle_events: Sequence[LifecycleEmailEventForOutcome],
    webhook_events: Sequence[ResendWebhookEventForOutcome],
) -> tuple[set[str], set[str]]:
    known_message_ids = {
        event.resend_message_id
        for event in lifecycle_events
        if event.resend_message_id
    }
    opened: set[str] = set()
    clicked: set[str] = set()

    for event in webhook_events:
        message_id = (event.resend_message_id or "").strip()
        if not message_id or message_id not in known_message_ids:
            continue
        event_type = event.event_type.strip().lower().replace("_", ".")
        if event_type in {"opened", "email.opened"} or event_type.endswith(".opened"):
            opened.add(message_id)
        elif event_type in {"clicked", "email.clicked"} or event_type.endswith(".clicked"):
            clicked.add(message_id)

    return opened, clicked


def _conversion_event_name(flow: NotificationFlowForOutcome | None) -> str | None:
    context = flow.context_overrides if flow else {}
    explicit = context.get("posthog_event") or context.get("conversion_event")
    if explicit:
        return str(explicit)
    flag = context.get("flag") or context.get("feature_flag")
    return f"feature_used.{flag}" if flag else None


def _default_conversion_counter(
    user_ids: list[str],
    event_name: str,
    start_at: datetime,
    end_at: datetime,
) -> int | None:
    from modules.posthog_query import count_users_with_event_between

    return count_users_with_event_between(event_name, user_ids, start_at, end_at)


def count_posthog_conversions(
    *,
    flow: NotificationFlowForOutcome | None,
    run: NotificationFlowRunForOutcome,
    lifecycle_events: Sequence[LifecycleEmailEventForOutcome],
    measured_at: datetime,
    conversion_counter: ConversionCounter | None,
) -> tuple[int, Literal["posthog", "not_configured", "error"]]:
    event_name = _conversion_event_name(flow)
    if not event_name:
        return 0, "not_configured"
    user_ids = sorted({event.user_id for event in lifecycle_events if event.user_id})
    if not user_ids:
        return 0, "not_configured"
    start_at = run.created_at or min(
        (event.created_at for event in lifecycle_events if event.created_at),
        default=measured_at,
    )
    counter = conversion_counter or _default_conversion_counter
    try:
        value = counter(user_ids, event_name, start_at, measured_at)
    except Exception:
        logger.exception("[notification_outcomes] PostHog conversion counter failed run_id=%s", run.id)
        return 0, "error"
    if value is None:
        return 0, "not_configured"
    return max(0, int(value)), "posthog"


def _rate(count: int, total: int) -> float:
    return float(count) / float(total) if total > 0 else 0.0


def _first_payload_value(
    lifecycle_events: Sequence[LifecycleEmailEventForOutcome],
    key: str,
    flow: NotificationFlowForOutcome | None,
) -> str:
    for event in lifecycle_events:
        value = event.payload.get(key)
        if value:
            return str(value)
        nested = event.payload.get("payload")
        if isinstance(nested, dict) and nested.get(key):
            return str(nested[key])
    if flow and flow.context_overrides.get(key):
        return str(flow.context_overrides[key])
    return ""


def build_outcome_memory(
    *,
    run: NotificationFlowRunForOutcome,
    flow: NotificationFlowForOutcome | None,
    lifecycle_events: Sequence[LifecycleEmailEventForOutcome],
    measurement: NotificationOutcomeMeasurement,
) -> NotificationOutcomeMemory:
    first_event = lifecycle_events[0] if lifecycle_events else None
    audience_label = str(run.summary.get("segment") or run.summary.get("audience_label") or "unknown")
    email_type = flow.email_type if flow and flow.email_type else (first_event.email_type if first_event else "")
    category = flow.category if flow and flow.category else (first_event.category if first_event else "")
    event_type = str(
        (flow.context_overrides.get("event_type") if flow else None)
        or run.summary.get("event_type")
        or email_type
        or "notification"
    )
    return NotificationOutcomeMemory(
        tenant_id=measurement.tenant_id or run.tenant_id or (first_event.tenant_id if first_event else "") or "",
        flow_run_id=run.id,
        lifecycle_event_id=first_event.id if first_event else None,
        event_type=event_type,
        email_type=email_type,
        category=category,
        audience_label=audience_label,
        subject=_first_payload_value(lifecycle_events, "subject", flow),
        cta_label=_first_payload_value(lifecycle_events, "cta_label", flow),
        audience_count=measurement.recipient_count,
        open_count=measurement.open_count,
        click_count=measurement.click_count,
        conversion_count=measurement.conversion_count,
        open_rate=_rate(measurement.open_count, measurement.recipient_count),
        click_rate=_rate(measurement.click_count, measurement.recipient_count),
        conversion_rate=_rate(measurement.conversion_count, measurement.recipient_count),
        measured_at=measurement.measured_at.isoformat(),
    )


def default_memory_writer(
    sb: Any,
    outcome: NotificationOutcomeMemory,
    *,
    embed: EmbeddingFn | None = None,
) -> Any:
    from services.notification_memory import remember_notification_outcome

    return remember_notification_outcome(sb, outcome, embed=embed)


def update_notification_flow_run(
    sb: Any,
    run: NotificationFlowRunForOutcome,
    measurement: NotificationOutcomeMeasurement,
) -> None:
    summary = dict(run.summary or {})
    summary["outcome"] = measurement.model_dump(mode="json")
    patch = {
        "open_count": measurement.open_count,
        "click_count": measurement.click_count,
        "conversion_count": measurement.conversion_count,
        "outcome_measured_at": measurement.measured_at.isoformat(),
        "status": "measured",
        "summary": summary,
        "updated_at": measurement.measured_at.isoformat(),
    }
    sb.table("notification_flow_runs").update(patch).eq("id", run.id).execute()


def measure_notification_outcome(
    sb: Any,
    flow_run_id: str,
    *,
    conversion_counter: ConversionCounter | None = None,
    memory_writer: MemoryWriter | None = None,
    embed: EmbeddingFn | None = None,
    measured_at: datetime | None = None,
) -> NotificationOutcomeMeasurement:
    run = load_notification_flow_run(sb, flow_run_id)
    flow = load_notification_flow(sb, run.flow_id)
    lifecycle_events = load_lifecycle_email_events(sb, run.id)
    message_ids = [
        event.resend_message_id
        for event in lifecycle_events
        if event.resend_message_id
    ]
    webhook_events = load_resend_webhook_events(sb, message_ids)
    opened_message_ids, clicked_message_ids = aggregate_resend_engagement(
        lifecycle_events,
        webhook_events,
    )
    measured = measured_at or utc_now()
    conversion_count, conversion_source = count_posthog_conversions(
        flow=flow,
        run=run,
        lifecycle_events=lifecycle_events,
        measured_at=measured,
        conversion_counter=conversion_counter,
    )

    measurement = NotificationOutcomeMeasurement(
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id or (flow.tenant_id if flow else None),
        recipient_count=len(lifecycle_events),
        sent_count=sum(1 for event in lifecycle_events if event.status == "sent"),
        open_count=len(opened_message_ids),
        click_count=len(clicked_message_ids),
        conversion_count=conversion_count,
        conversion_source=conversion_source,
        opened_message_ids=sorted(opened_message_ids),
        clicked_message_ids=sorted(clicked_message_ids),
        measured_at=measured,
    )

    update_notification_flow_run(sb, run, measurement)
    memory = build_outcome_memory(
        run=run,
        flow=flow,
        lifecycle_events=lifecycle_events,
        measurement=measurement,
    )
    if memory_writer:
        memory_writer(sb, memory)
    else:
        default_memory_writer(sb, memory, embed=embed)
    return measurement
