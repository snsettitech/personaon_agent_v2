"""Audience resolution for notification flows."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from pydantic import BaseModel

from modules.notification_flows import AudienceSpec

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 600
_flag_used_cache: dict[str, tuple[float, set[str]]] = {}
_flag_audience_cache: dict[str, tuple[float, ResolvedAudience]] = {}
_SAFE_FLAG_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _evict_stale_cache() -> None:
    now = time.monotonic()
    stale_cutoff = _CACHE_TTL_SECONDS * 2
    for cache in (_flag_used_cache, _flag_audience_cache):
        stale_keys = [k for k, (ts, _) in list(cache.items()) if now - ts > stale_cutoff]
        for k in stale_keys:
            cache.pop(k, None)


class RecipientRow(BaseModel):
    user_id: str
    email: str
    tenant_id: str


class ResolvedAudience(BaseModel):
    recipients: list[RecipientRow]
    count: int
    segment_label: str


def _recipient_from_row(row: dict[str, Any]) -> RecipientRow | None:
    user_id = str(row.get("id") or row.get("user_id") or "").strip()
    email = str(row.get("email") or "").strip()
    tenant_id = str(row.get("tenant_id") or user_id).strip()
    if not user_id or not email:
        return None
    return RecipientRow(user_id=user_id, email=email, tenant_id=tenant_id)


def _recipients(rows: list[dict[str, Any]]) -> list[RecipientRow]:
    out: list[RecipientRow] = []
    seen: set[str] = set()
    for row in rows:
        recipient = _recipient_from_row(row)
        if recipient and recipient.user_id not in seen:
            seen.add(recipient.user_id)
            out.append(recipient)
    return out


def _dict_from_auth_user(user: Any) -> dict[str, Any]:
    if isinstance(user, dict):
        data = dict(user)
    else:
        data = {
            "id": getattr(user, "id", None),
            "email": getattr(user, "email", None),
            "user_metadata": getattr(user, "user_metadata", None),
        }
    metadata = data.get("user_metadata") if isinstance(data.get("user_metadata"), dict) else {}
    data["user_metadata"] = metadata
    data["tenant_id"] = data.get("tenant_id") or data.get("id")
    return data


def _response_users(resp: Any) -> list[Any]:
    users = getattr(resp, "users", None)
    if users is None and isinstance(resp, dict):
        users = resp.get("users") or resp.get("data")
    if users is None:
        users = getattr(resp, "data", None)
    return list(users or [])


def _auth_users(sb: Any) -> list[dict[str, Any]]:
    """List Supabase Auth users in 100-row pages; return [] when unavailable."""
    list_users = getattr(getattr(getattr(sb, "auth", None), "admin", None), "list_users", None)
    if not callable(list_users):
        return []

    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        try:
            resp = list_users(page=page, per_page=100)
        except TypeError:
            resp = list_users({"page": page, "per_page": 100})
        users = _response_users(resp)
        if not users:
            break
        rows.extend(_dict_from_auth_user(user) for user in users)
        if len(users) < 100:
            break
        page += 1
    return rows


def _query_users(sb: Any, *, select: str = "id,email,tenant_id,plan,user_metadata") -> list[dict[str, Any]]:
    resp = sb.table("users").select(select).execute()
    return list(resp.data or [])


_ALL_ACTIVE_LIMIT = 10_000

def _all_active(sb: Any) -> ResolvedAudience:
    try:
        rows = (
            sb.table("users")
            .select("id,email,tenant_id,deleted_at")
            .is_("deleted_at", "null")
            .limit(_ALL_ACTIVE_LIMIT)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        logger.warning("[audience] deleted_at active filter unavailable; using all users: %s", exc)
        rows = _query_users(sb, select="id,email,tenant_id")
    if len(rows) >= _ALL_ACTIVE_LIMIT:
        logger.warning("[audience] all_active hit query cap of %d rows — results may be incomplete", _ALL_ACTIVE_LIMIT)
    recipients = _recipients(rows)
    return ResolvedAudience(recipients=recipients, count=len(recipients), segment_label="all_active")


def _by_plan(sb: Any, plan: str | None) -> ResolvedAudience:
    if not plan:
        return ResolvedAudience(recipients=[], count=0, segment_label="plan:missing")
    rows = _auth_users(sb) or _query_users(sb)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        raw_metadata = row.get("user_metadata")
        metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
        if row.get("plan") == plan or metadata.get("plan") == plan:
            filtered.append(row)
    recipients = _recipients(filtered)
    return ResolvedAudience(recipients=recipients, count=len(recipients), segment_label=f"plan:{plan}")


def _posthog_used_user_ids(flag: str) -> set[str]:
    if not _SAFE_FLAG_RE.match(flag):
        logger.warning("[audience] refusing unsafe flag name flag=%s", flag)
        return set()
    cache_key = f"flag_not_used:{flag}"
    now = time.monotonic()
    cached = _flag_used_cache.get(cache_key)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return set(cached[1])

    event_name = f"flag_{flag}_used"
    used: set[str] = set()
    try:
        from modules.posthog_query import run_hogql

        results = run_hogql(
            "SELECT DISTINCT person.properties.user_id FROM events "
            f"WHERE event = '{event_name}' AND timestamp >= now() - INTERVAL 30 DAY"
        )
        for row in results or []:
            if row:
                used.add(str(row[0]))
    except Exception as exc:
        logger.warning("[audience] PostHog flag-used query failed flag=%s: %s", flag, exc)

    _flag_used_cache[cache_key] = (now, used)
    return used


def _flag_not_used(sb: Any, flag: str | None) -> ResolvedAudience:
    _evict_stale_cache()
    if not flag:
        return ResolvedAudience(recipients=[], count=0, segment_label="flag_not_used:missing")
    cache_key = f"flag_not_used:{flag}:audience"
    now = time.monotonic()
    cached = _flag_audience_cache.get(cache_key)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1].model_copy(deep=True)

    rows = _auth_users(sb) or _query_users(sb)
    used_user_ids = _posthog_used_user_ids(flag)
    filtered: list[dict[str, Any]] = []
    flag_key = f"flag_{flag}"
    for row in rows:
        raw_metadata = row.get("user_metadata")
        metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
        enabled = bool(metadata.get(flag_key))
        user_id = str(row.get("id") or "")
        if not enabled and user_id not in used_user_ids:
            filtered.append(row)
    if len(filtered) > 1000:
        logger.warning("[audience] flag_not_used matched expensive segment flag=%s count=%d", flag, len(filtered))
    recipients = _recipients(filtered)
    audience = ResolvedAudience(recipients=recipients, count=len(recipients), segment_label=f"flag_not_used:{flag}")
    _flag_audience_cache[cache_key] = (now, audience.model_copy(deep=True))
    return audience


def _single_user(sb: Any, user_ids: list[str]) -> ResolvedAudience:
    if not user_ids:
        return ResolvedAudience(recipients=[], count=0, segment_label="single_user:missing")
    user_id = user_ids[0]
    rows = (
        sb.table("users")
        .select("id,email,tenant_id")
        .eq("id", user_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    recipients = _recipients(rows)
    return ResolvedAudience(recipients=recipients, count=len(recipients), segment_label="single_user")


def _user_list(sb: Any, user_ids: list[str]) -> ResolvedAudience:
    if not user_ids:
        return ResolvedAudience(recipients=[], count=0, segment_label="user_list:empty")
    rows = (
        sb.table("users")
        .select("id,email,tenant_id")
        .in_("id", user_ids)
        .execute()
        .data
        or []
    )
    recipients = _recipients(rows)
    return ResolvedAudience(recipients=recipients, count=len(recipients), segment_label="user_list")


async def resolve_audience(sb: Any, spec: AudienceSpec) -> ResolvedAudience:
    """Resolve recipients for a notification flow without sending or mutating."""
    if spec.segment == "all_active":
        return _all_active(sb)
    if spec.segment == "plan":
        return _by_plan(sb, spec.plan)
    if spec.segment == "flag_not_used":
        return _flag_not_used(sb, spec.flag)
    if spec.segment == "single_user":
        return _single_user(sb, spec.user_ids)
    if spec.segment == "user_list":
        return _user_list(sb, spec.user_ids)
    return ResolvedAudience(recipients=[], count=0, segment_label="unknown")
