"""Phase I notification agent observe/generate/send bridge."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from pydantic import BaseModel

from modules.audience import AudienceSpec, RecipientRow, resolve_audience
from modules.graph_outbox import GraphOperationType, get_graph_outbox
from modules.notification_events import (
    NotificationEvent,
    mark_notification_event_failed,
    mark_notification_event_processed,
    mark_notification_event_processing,
)
from modules.notification_flows import (
    FlowGuardrails,
    NotificationFlowCreate,
    NotificationFlow,
    close_run,
    create_flow,
    create_run,
    get_flow_by_key,
    update_flow_status,
)
from services.notification_memory import retrieve_prior_outcomes
from services.notification_outcomes import schedule_notification_outcome_measurement

logger = logging.getLogger(__name__)

SYSTEM_TWIN_ID = "00000000-0000-4000-8000-000000000000"
GENERATED_EMAIL_TYPE = "agent_generated_notification"
EVENT_FLOW_KEYS = {
    "account.access_granted": "agent_account_access_granted",
    "account.suspended": "agent_account_suspended",
    "feature.launched": "agent_feature_launched",
    "lead.captured": "lead_captured",
}


class GeneratedNotification(BaseModel):
    subject: str
    body: str
    cta_label: str
    cta_path: str
    help_path: str = "/help/product-updates"


class ObservedNotification(BaseModel):
    mode: Literal["transactional", "broadcast"]
    audience_spec: AudienceSpec
    category: Literal["account", "announcements"]
    cta_label: str
    cta_path: str
    help_path: str


def observe_notification_event(event: NotificationEvent) -> ObservedNotification | None:
    if event.event_type == "account.access_granted":
        return ObservedNotification(
            mode="transactional",
            audience_spec=AudienceSpec(segment="user_list", user_ids=[event.subject_id]),
            category="account",
            cta_label="Open PersonaOn",
            cta_path="/dashboard",
            help_path="/help/get-started",
        )
    if event.event_type == "account.suspended":
        return ObservedNotification(
            mode="transactional",
            audience_spec=AudienceSpec(segment="user_list", user_ids=[event.subject_id]),
            category="account",
            cta_label="Contact Support",
            cta_path="mailto:support@personaon.com",
            help_path="/help/account-access",
        )
    if event.event_type == "feature.launched":
        flag = str(event.context_json.get("flag") or event.subject_id)
        return ObservedNotification(
            mode="broadcast",
            audience_spec=AudienceSpec(segment="flag_not_used", flag=flag),
            category="announcements",
            cta_label="Try it now",
            cta_path=str(event.context_json.get("cta_path") or "/dashboard"),
            help_path="/help/product-updates",
        )
    if event.event_type == "lead.captured":
        return ObservedNotification(
            mode="transactional",
            audience_spec=AudienceSpec(segment="user_list", user_ids=[event.tenant_id]),
            category="account",
            cta_label="View Lead",
            cta_path="/dashboard/widget/leads",
            help_path="/help/get-started",
        )
    logger.warning(
        "[notification_agent] unhandled event_type=%s event_id=%s — no observer registered",
        event.event_type,
        event.id,
    )
    return None


def generate_notification_content(
    *,
    event: NotificationEvent,
    recipient: RecipientRow | None,
    observed: ObservedNotification,
    memory_context: list[str] | None = None,
) -> GeneratedNotification:
    """Generate copy from event/recipient context.

    Phase I keeps memory_context empty, but the signature is the Phase II seam
    where retrieved agent_memory outcomes become generation context.
    """
    memories = memory_context or []
    feature_name = str(event.context_json.get("feature_name") or event.context_json.get("flag") or event.subject_id)
    recipient_hint = f" for {recipient.email}" if recipient else ""
    if event.event_type == "account.access_granted":
        subject = "Your PersonaOn access is ready"
        body = "Your PersonaOn workspace has been unlocked. Sign in to start using the features now available to you."
    elif event.event_type == "account.suspended":
        subject = "Your PersonaOn account access changed"
        body = "Your PersonaOn account has been suspended. If this looks wrong, contact support and include the email on your account."
    elif event.event_type == "feature.launched":
        subject = f"New in PersonaOn: {feature_name}"
        summary = str(event.context_json.get("description") or event.context_json.get("summary") or "")
        body = summary or f"{feature_name} is now available in PersonaOn. Open your workspace to try it."
    elif event.event_type == "lead.captured":
        visitor_name = str(event.context_json.get("visitor_name") or "").strip()
        visitor_email = str(event.context_json.get("visitor_email") or "").strip()
        intent = str(event.context_json.get("inferred_intent") or "").strip()
        visitor_type = str(event.context_json.get("inferred_visitor_type") or "").strip()
        display = visitor_name or visitor_email or "Someone"
        type_hint = f" ({visitor_type})" if visitor_type else ""
        intent_hint = f": {intent}" if intent else ""
        subject = f"New lead: {display}"
        body = (
            f"{display}{type_hint} just connected with your PersonaOn persona{intent_hint}. "
            f"Their email is {visitor_email}."
            if visitor_email else
            f"{display}{type_hint} just connected with your PersonaOn persona{intent_hint}."
        )
    else:
        subject = "PersonaOn update"
        body = f"There's a new PersonaOn update{recipient_hint}. Open your workspace for details."
    if memories and event.event_type == "feature.launched" and "try" not in body.lower():
        body = f"{body} Try it from your workspace when you're ready."
    return GeneratedNotification(
        subject=subject,
        body=body,
        cta_label=observed.cta_label,
        cta_path=observed.cta_path,
        help_path=observed.help_path,
    )


async def process_notification_event(sb: Any, event_id: str) -> bool:
    from modules.notification_events import get_notification_event

    event = get_notification_event(sb, event_id)
    if not event:
        logger.error("[notification_agent] event missing id=%s", event_id)
        return True

    try:
        mark_notification_event_processing(sb, event.id)
        observed = observe_notification_event(event)
        if not observed:
            mark_notification_event_processed(sb, event.id)
            return True

        if observed.mode == "broadcast":
            _create_broadcast_proposal(sb, event, observed)
            mark_notification_event_processed(sb, event.id)
            return True

        resolved = await resolve_audience(sb, observed.audience_spec)
        outbox = get_graph_outbox()
        flow = _ensure_generated_flow(sb, event, observed)
        flow_run_id = _stable_event_run_id(event.id, "run")
        create_run(
            sb,
            flow.id,
            "event",
            len(resolved.recipients),
            run_id=flow_run_id,
            tenant_id=event.tenant_id,
            flow_run_key=f"{flow.id}:event:{event.id}",
        )
        enqueued = 0
        skipped = 0
        for recipient in resolved.recipients:
            try:
                memory_context = [
                    item.content
                    for item in retrieve_prior_outcomes(
                        sb,
                        tenant_id=recipient.tenant_id,
                        event_type=event.event_type,
                        audience_label=resolved.segment_label,
                        category=observed.category,
                    )
                ]
                generated = generate_notification_content(
                    event=event,
                    recipient=recipient,
                    observed=observed,
                    memory_context=memory_context,
                )
                outbox.submit(
                    tenant_id=recipient.tenant_id,
                    twin_id=SYSTEM_TWIN_ID,
                    operation=GraphOperationType.SEND_LIFECYCLE_EMAIL,
                    idempotency_key=f"notif-event-{event.id}-{recipient.user_id}",
                    scope_id=flow_run_id,
                    payload={
                        "user_id": recipient.user_id,
                        "tenant_id": recipient.tenant_id,
                        "twin_id": SYSTEM_TWIN_ID,
                        "email_type": GENERATED_EMAIL_TYPE,
                        "category": observed.category,
                        "scope_type": "user",
                        "scope_id": flow_run_id,
                        "period_key": recipient.user_id,
                        "recipient_email": recipient.email,
                        "payload": {
                            "generated_email": True,
                            "notification_event_id": event.id,
                            "event_type": event.event_type,
                            "category": observed.category,
                            "memory_context_count": len(memory_context),
                            **generated.model_dump(mode="json"),
                        },
                    },
                )
                enqueued += 1
            except Exception as exc:
                logger.exception(
                    "[notification_agent] enqueue failed event_id=%s user_id=%s err=%r",
                    event.id,
                    recipient.user_id,
                    exc,
                )
                skipped += 1
        close_run(
            sb,
            flow_run_id,
            status="completed",
            enqueued=enqueued,
            skipped=skipped,
            summary={"segment": resolved.segment_label, "event_type": event.event_type},
        )
        if enqueued > 0:
            schedule_notification_outcome_measurement(
                outbox=outbox,
                tenant_id=event.tenant_id,
                flow_run_id=flow_run_id,
                flow_id=flow.id,
            )
        mark_notification_event_processed(sb, event.id)
        return True
    except Exception as exc:
        logger.exception("[notification_agent] event processing failed id=%s", event_id)
        mark_notification_event_failed(sb, event.id, str(exc))
        return False


def _stable_event_run_id(event_id: str, run_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"personaon:notification-event:{event_id}:{run_key}"))


def _ensure_generated_flow(sb: Any, event: NotificationEvent, observed: ObservedNotification) -> NotificationFlow:
    key = EVENT_FLOW_KEYS.get(event.event_type) or f"agent_{event.event_type.replace('.', '_')}"
    existing = get_flow_by_key(sb, key)
    if existing:
        if existing.status != "active":
            logger.info("[notification_agent] re-activating proposed flow key=%s id=%s", key, existing.id)
            return update_flow_status(sb, existing.id, "active", approved_by="system:notification_agent")
        return existing
    created = create_flow(
        sb,
        NotificationFlowCreate(
            key=key,
            name=event.event_type.replace(".", " ").title(),
            kind="transactional" if observed.mode == "transactional" else "announcement",
            trigger_type="event",
            audience_spec=observed.audience_spec,
            email_type=GENERATED_EMAIL_TYPE,
            category=observed.category,
            context_overrides={
                "generated_email": True,
                "event_type": event.event_type,
                "category": observed.category,
                **event.context_json,
            },
            guardrails=FlowGuardrails(max_recipients=1, throttle_per_min=0, exempt_from_caps=True),
            created_by="agent:notification_agent",
            tenant_id=event.tenant_id,
        ),
    )
    return update_flow_status(sb, created.id, "active", approved_by="system:notification_agent")


def _create_broadcast_proposal(sb: Any, event: NotificationEvent, observed: ObservedNotification) -> None:
    memory_context = [
        item.content
        for item in retrieve_prior_outcomes(
            sb,
            tenant_id=event.tenant_id,
            event_type=event.event_type,
            audience_label=observed.audience_spec.segment,
            category=observed.category,
        )
    ]
    generated = generate_notification_content(
        event=event,
        recipient=None,
        observed=observed,
        memory_context=memory_context,
    )
    key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"personaon:broadcast:{event.event_type}:{event.subject_id}:{event.id}"))
    existing = get_flow_by_key(sb, key)
    if existing:
        return
    create_flow(
        sb,
        NotificationFlowCreate(
            key=key,
            name=str(event.context_json.get("feature_name") or event.subject_id),
            kind="announcement",
            trigger_type="event",
            audience_spec=observed.audience_spec,
            email_type=GENERATED_EMAIL_TYPE,
            category=observed.category,
            context_overrides={
                "generated_email": True,
                "notification_event_id": event.id,
                "event_type": event.event_type,
                "category": observed.category,
                "memory_context_count": len(memory_context),
                **event.context_json,
                **generated.model_dump(mode="json"),
            },
            guardrails=FlowGuardrails(max_recipients=500, throttle_per_min=30),
            created_by="agent:notification_agent",
            tenant_id=event.tenant_id,
        ),
    )
