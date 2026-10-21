"""Candidate selection for lifecycle education and activity emails."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from services.lifecycle_email_service import (
    DAILY_ACTIVITY,
    PRODUCT_EDUCATION,
    WEEKLY_REPORT,
)

logger = logging.getLogger(__name__)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _date_key(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).date().isoformat()


def _first(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return rows[0] if rows else {}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _allowed_user_ids() -> set[str]:
    raw = os.getenv("LIFECYCLE_EMAIL_ALLOWED_USER_IDS", "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def _is_rollout_eligible(user: dict[str, Any], *, category: str) -> bool:
    """Return whether a user can enter lifecycle email selection.

    `LIFECYCLE_EMAIL_START_AT` prevents old users from suddenly receiving
    onboarding/product emails at launch. `LIFECYCLE_EMAIL_ALLOWED_USER_IDS`
    narrows selection to explicit internal users for staged testing.
    """
    user_id = str(user.get("id") or "").strip()
    allowed = _allowed_user_ids()
    if allowed:
        return user_id in allowed

    start_at = _parse_dt(os.getenv("LIFECYCLE_EMAIL_START_AT"))
    if start_at is None:
        return True

    created_at = _parse_dt(str(user.get("created_at") or ""))
    if created_at and created_at >= start_at:
        return True

    if category in {DAILY_ACTIVITY, WEEKLY_REPORT}:
        return _env_bool("LIFECYCLE_EMAIL_INCLUDE_EXISTING_USERS", default=False)
    return False


def _existing_event_keys(sb, *, user_id: str) -> set[str]:
    try:
        resp = (
            sb.table("lifecycle_email_events")
            .select("email_type,scope_type,scope_id,period_key,status")
            .eq("user_id", user_id)
            .in_("status", ["sending", "sent", "skipped"])
            .execute()
        )
        return {
            f"{row.get('email_type')}:{row.get('scope_type')}:{row.get('scope_id')}:{row.get('period_key')}"
            for row in (resp.data or [])
        }
    except Exception:
        return set()


def _candidate(
    *,
    user: dict[str, Any],
    twin: dict[str, Any],
    email_type: str,
    category: str,
    period_key: str,
    candidate_reason: str,
    metrics: list[str] | None = None,
    cta_path: str | None = None,
) -> dict[str, Any] | None:
    recipient = str(user.get("email") or "").strip()
    user_id = str(user.get("id") or "").strip()
    tenant_id = str(user.get("tenant_id") or user_id).strip()
    twin_id = str(twin.get("id") or "").strip()
    if not recipient or not user_id or not tenant_id or not twin_id:
        return None
    payload: dict[str, Any] = {
        "metrics": metrics or [],
        "candidate_reason": candidate_reason,
    }
    if cta_path:
        payload["cta_path"] = cta_path
    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "twin_id": twin_id,
        "recipient_email": recipient,
        "email_type": email_type,
        "category": category,
        "candidate_reason": candidate_reason,
        "scope_type": "user" if email_type.startswith("welcome") else "twin",
        "scope_id": user_id if email_type.startswith("welcome") else twin_id,
        "period_key": period_key,
        "cta_path": cta_path,
        "payload": payload,
    }


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def _weekly_candidate_context(
    *,
    conversation_count: int,
    lead_count: int,
    queued_question_count: int,
    source_count: int,
    is_public: bool,
    has_widget_activity: bool,
) -> dict[str, Any] | None:
    actions: list[str] = []
    reasons: list[str] = []
    cta_path = "/dashboard/knowledge"

    def add_action(reason: str, action: str, target: str) -> None:
        nonlocal cta_path
        if not reasons:
            cta_path = target
        reasons.append(reason)
        actions.append(action)

    if source_count <= 0:
        add_action("no_sources", "Add your first source", "/dashboard/knowledge")

    if queued_question_count > 0:
        add_action(
            "queued_questions",
            f"Answer {_plural(queued_question_count, 'queued question')}",
            "/dashboard/queued-questions",
        )

    if conversation_count > 0 or lead_count > 0:
        parts = []
        if conversation_count > 0:
            parts.append(_plural(conversation_count, "recent chat"))
        if lead_count > 0:
            parts.append(_plural(lead_count, "new lead"))
        add_action("recent_activity", f"Review {' and '.join(parts)}", "/dashboard/conversations")

    if not is_public:
        add_action("not_published", "Publish your persona link", "/dashboard/share")
    elif not has_widget_activity:
        add_action("widget_not_adopted", "Install the website widget", "/dashboard/widget")

    if not actions:
        return None

    return {
        "candidate_reason": reasons[0],
        "metrics": actions[:4],
        "cta_path": cta_path,
    }


def _count_rows(sb, table_name: str, *, twin_id: str, since_iso: str | None = None, status: str | None = None) -> int:
    try:
        query = sb.table(table_name).select("id").eq("twin_id", twin_id)
        if since_iso:
            query = query.gte("created_at", since_iso)
        if status:
            query = query.eq("status", status)
        resp = query.execute()
        return len(resp.data or [])
    except Exception:
        return 0


def collect_daily_lifecycle_candidates(now: datetime | None = None) -> list[dict[str, Any]]:
    """Return candidates for the daily lifecycle cron.

    The selector is intentionally deterministic. It uses existing product state
    and does not depend on PostHog events so sends remain auditable.
    """
    from modules.observability import get_supabase_client

    now = now or datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    sb = get_supabase_client()

    try:
        users = sb.table("users").select("id,tenant_id,email,created_at").execute().data or []
        twins = sb.table("twins").select("id,tenant_id,name,status,settings,created_at").execute().data or []
    except Exception as exc:
        logger.warning("[LifecycleDigest] failed to load users/twins: %s", exc)
        return []

    twins_by_tenant: dict[str, list[dict[str, Any]]] = {}
    for twin in twins:
        twins_by_tenant.setdefault(str(twin.get("tenant_id")), []).append(twin)

    candidates: list[dict[str, Any]] = []
    for user in users:
        user_id = str(user.get("id") or "")
        tenant_id = str(user.get("tenant_id") or user_id)
        tenant_twins = twins_by_tenant.get(tenant_id) or twins_by_tenant.get(user_id) or []
        twin = _first(tenant_twins)
        if not twin:
            continue

        existing = _existing_event_keys(sb, user_id=user_id)
        twin_id = str(twin.get("id"))
        created_at = _parse_dt(str(twin.get("created_at") or user.get("created_at") or ""))
        period_today = _date_key(now)

        welcome_key = f"welcome_first_persona:user:{user_id}:once"
        if welcome_key not in existing and _is_rollout_eligible(user, category=PRODUCT_EDUCATION):
            item = _candidate(
                user=user,
                twin=twin,
                email_type="welcome_first_persona",
                category=PRODUCT_EDUCATION,
                period_key="once",
                candidate_reason="first_persona_created",
                metrics=["Add one source", "Ask three test questions", "Review what visitors will see"],
                cta_path="/dashboard",
            )
            if item:
                candidates.append(item)
            continue

        # Day 1 source nudge.
        if created_at and (now - created_at) >= timedelta(hours=24):
            try:
                sources = (
                    sb.table("sources")
                    .select("id")
                    .eq("twin_id", twin_id)
                    .in_("status", ["live", "completed"])
                    .limit(1)
                    .execute()
                    .data
                    or []
                )
            except Exception:
                sources = []
            key = f"day1_add_sources:twin:{twin_id}:once"
            if not sources and key not in existing and _is_rollout_eligible(user, category=PRODUCT_EDUCATION):
                item = _candidate(
                    user=user,
                    twin=twin,
                    email_type="day1_add_sources",
                    category=PRODUCT_EDUCATION,
                    period_key="once",
                    candidate_reason="no_sources_after_24h",
                    metrics=["No live sources found", "Start with a resume, FAQ, website, or writing sample"],
                    cta_path="/dashboard/knowledge",
                )
                if item:
                    candidates.append(item)
                continue

        # Daily meaningful activity.
        try:
            convos = (
                sb.table("adk_conversations")
                .select("id,surface,created_at")
                .eq("twin_id", twin_id)
                .gte("created_at", yesterday.isoformat())
                .execute()
                .data
                or []
            )
            leads = (
                sb.table("widget_leads")
                .select("id,visitor_email,source_domain,created_at")
                .eq("twin_id", twin_id)
                .gte("created_at", yesterday.isoformat())
                .execute()
                .data
                or []
            )
        except Exception:
            convos = []
            leads = []
        if (convos or leads) and _is_rollout_eligible(user, category=DAILY_ACTIVITY):
            key = f"daily_persona_activity:twin:{twin_id}:{period_today}"
            if key not in existing:
                item = _candidate(
                    user=user,
                    twin=twin,
                    email_type="daily_persona_activity",
                    category=DAILY_ACTIVITY,
                    period_key=period_today,
                    candidate_reason="persona_activity_yesterday",
                    metrics=[
                        f"New conversations: {len(convos)}",
                        f"New leads: {len([lead for lead in leads if lead.get('visitor_email')])}",
                    ],
                    cta_path="/dashboard/conversations",
                )
                if item:
                    candidates.append(item)

    return candidates


def collect_weekly_lifecycle_candidates(now: datetime | None = None) -> list[dict[str, Any]]:
    from modules.observability import get_supabase_client

    now = now or datetime.now(timezone.utc)
    week_start = now.date().fromordinal(now.date().toordinal() - now.date().weekday())
    week_start_dt = datetime.combine(week_start, datetime.min.time(), tzinfo=timezone.utc)
    week_start_iso = week_start_dt.isoformat()
    sb = get_supabase_client()

    try:
        users = sb.table("users").select("id,tenant_id,email,created_at").execute().data or []
        twins = sb.table("twins").select("id,tenant_id,name,status,settings").execute().data or []
    except Exception as exc:
        logger.warning("[LifecycleDigest] failed to collect weekly candidates: %s", exc)
        return []

    twins_by_tenant: dict[str, list[dict[str, Any]]] = {}
    for twin in twins:
        twins_by_tenant.setdefault(str(twin.get("tenant_id")), []).append(twin)

    candidates: list[dict[str, Any]] = []
    for user in users:
        user_id = str(user.get("id") or "")
        tenant_id = str(user.get("tenant_id") or user_id)
        if not _is_rollout_eligible(user, category=WEEKLY_REPORT):
            continue
        for twin in twins_by_tenant.get(tenant_id, [])[:1]:
            twin_id = str(twin.get("id") or "")
            existing = _existing_event_keys(sb, user_id=user_id)
            key = f"weekly_improvement_report:twin:{twin_id}:{week_start.isoformat()}"
            if key in existing:
                continue
            settings = twin.get("settings") if isinstance(twin.get("settings"), dict) else {}
            widget_settings = settings.get("widget_settings") if isinstance(settings.get("widget_settings"), dict) else {}
            is_public = bool(settings.get("is_public") or widget_settings.get("public_share_enabled"))
            conversation_count = _count_rows(sb, "adk_conversations", twin_id=twin_id, since_iso=week_start_iso)
            lead_count = _count_rows(sb, "widget_leads", twin_id=twin_id, since_iso=week_start_iso)
            queued_question_count = _count_rows(sb, "queued_questions", twin_id=twin_id, status="pending")
            source_count = _count_rows(sb, "sources", twin_id=twin_id)
            context = _weekly_candidate_context(
                conversation_count=conversation_count,
                lead_count=lead_count,
                queued_question_count=queued_question_count,
                source_count=source_count,
                is_public=is_public,
                has_widget_activity=lead_count > 0,
            )
            if not context:
                continue
            item = _candidate(
                user=user,
                twin=twin,
                email_type="weekly_improvement_report",
                category=WEEKLY_REPORT,
                period_key=week_start.isoformat(),
                candidate_reason=str(context["candidate_reason"]),
                metrics=list(context["metrics"]),
                cta_path=str(context["cta_path"]),
            )
            if item:
                candidates.append(item)
    return candidates
