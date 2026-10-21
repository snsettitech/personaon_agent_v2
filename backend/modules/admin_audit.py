"""Admin audit log — records mutating admin actions to ``admin_audit_log``.

Every write action in the admin control center (plan/flag change, role change,
suspend, delete, persona take-down, …) should call :func:`record_admin_action`
so there is an immutable trail of who did what to whom.

Design note: audit logging is a *side channel*. A failure to write the audit row
must never break the underlying admin action (which has typically already
succeeded). So this module catches, logs with full context, and returns — it does
not re-raise. This is the documented exception to the "never swallow" rule.
"""
from __future__ import annotations

import logging
from typing import Any

from modules.observability import get_supabase_client

logger = logging.getLogger(__name__)

# Canonical action verbs. Keep in sync with the dashboard's audit filters.
ACTION_PLAN_CHANGED = "user_plan_changed"
ACTION_FLAGS_CHANGED = "user_flags_changed"
ACTION_TRIAL_GRANTED = "user_trial_granted"
ACTION_USER_SUSPENDED = "user_suspended"
ACTION_USER_UNSUSPENDED = "user_unsuspended"
ACTION_USER_DELETED = "user_deleted"
ACTION_ROLE_CHANGED = "user_role_changed"
ACTION_STAFF_INVITED = "staff_invited"
ACTION_PERSONA_TAKEDOWN = "persona_takedown"
ACTION_PERSONA_RESTORED = "persona_restored"
ACTION_JOB_RETRIED = "job_retried"
ACTION_NOTIFICATION_FLOW_APPROVED = "notification_flow_approved"
ACTION_NOTIFICATION_FLOW_REJECTED = "notification_flow_rejected"
ACTION_NOTIFICATION_FLOW_PAUSED = "notification_flow_paused"
ACTION_NOTIFICATION_FLOW_RUN = "notification_flow_run"
ACTION_NOTIFICATION_FEATURE_LAUNCHED = "notification_feature_launched"
ACTION_NOTIFICATION_FLOW_DRAFT_UPDATED = "notification_flow_draft_updated"


def record_admin_action(
    *,
    actor: dict[str, Any],
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    target_email: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> bool:
    """Insert one audit row. Best-effort: returns True on success, False on failure.

    Args:
        actor: the authenticated admin dict (from ``require_admin``), expects
            ``user_id``/``email``/``tenant_id``.
        action: one of the ``ACTION_*`` constants above.
        target_type: e.g. ``"user"``, ``"twin"``, ``"job"``.
        target_id: id of the affected entity.
        target_email: convenience denormalization for user targets.
        before/after: state snapshots (kept small — diffs, not full rows).
        details: any extra structured context.
    """
    actor_id = actor.get("user_id") or actor.get("id")
    tenant_id = actor.get("tenant_id") or actor_id
    row = {
        "tenant_id": tenant_id,
        "actor_id": actor_id,
        "actor_email": actor.get("email"),
        "action": action,
        "target_type": target_type,
        "target_id": str(target_id) if target_id is not None else None,
        "target_email": target_email,
        "before": before,
        "after": after,
        "details": details or {},
    }
    try:
        get_supabase_client().table("admin_audit_log").insert(row).execute()
        logger.info(
            "[admin_audit] action=%s actor=%s target=%s/%s",
            action, actor_id, target_type, target_id,
        )
        return True
    except Exception as exc:
        # Do not propagate: the underlying action already happened. Log loudly.
        logger.exception(
            "[admin_audit] FAILED to record action=%s actor=%s target=%s/%s err=%r",
            action, actor_id, target_type, target_id, exc,
        )
        return False
