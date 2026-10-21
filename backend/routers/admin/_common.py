"""Shared helpers + constants for the admin sub-routers.

Patch target for tests: ``routers.admin._common.get_supabase_client``.
"""
from __future__ import annotations

import logging
from typing import Any

from modules.observability import get_supabase_client

logger = logging.getLogger(__name__)

# Plan tiers — mirror of users_plan_check + subscriptions tiers.
PLAN_TIERS = ("free", "pro", "business", "believer")

# User roles — mirror of users_role_check (widened in 20260626000000_admin_roles.sql).
ROLES = ("owner", "admin", "support", "viewer")

# Feature flags — MIRROR of FlagName in packages/core/src/flags/index.ts.
# Keep in sync when flags are added/removed there.
ALL_FLAGS = (
    "workspace_v2",
    "recap_edit_v2",
    "commitments_v1",
    "memory_review_v1",
    "people_v1",
    "preview_mode_v1",
    "heads_up_v1",
    "granola_live_notes",
    "granola_segment_persist",
    "granola_enhanced_notes",
    "granola_realtime",
    "granola_watchdog",
    "transcript_tools_v1",
    "persona_v1",
)


def _supabase():
    """Service-role Supabase client (bypasses RLS — platform-wide admin view)."""
    return get_supabase_client()


def _safe_count(table: str, filters: dict[str, Any] | None = None) -> int:
    """Count rows in a table with optional equality filters."""
    query = _supabase().table(table).select("id", count="exact")
    if filters:
        for col, val in filters.items():
            query = query.eq(col, val)
    result = query.limit(0).execute()
    return result.count or 0


def _safe_query(query):
    """Execute a Supabase query, returning data or [] on error."""
    try:
        result = query.execute()
        return result.data or []
    except Exception as exc:
        logger.warning("Admin query failed: %s", exc)
        return []
