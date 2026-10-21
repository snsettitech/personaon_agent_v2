"""PostHog Query API client for the admin control center.

The backend already captures events with the PostHog *project* key
(modules/posthog_analytics.py). Reading aggregates (DAU/MAU, funnels, retention)
requires a *personal* API key with read scope — a separate secret.

This client degrades gracefully: if ``POSTHOG_PERSONAL_API_KEY`` is not set, every
method returns ``None`` (and logs once), so the dashboard renders without
engagement numbers rather than erroring.

Docs: POST https://<host>/api/projects/<project_id>/query  with a HogQL body.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_HOST = "https://us.posthog.com"
_TIMEOUT_SECONDS = 15.0
# Event names are interpolated into HogQL; allow only safe identifier chars.
_EVENT_RE = re.compile(r"^[A-Za-z0-9_$.\-]+$")


def _config() -> tuple[str | None, str, str | None]:
    """Return (personal_api_key, host, project_id) from env."""
    key = (os.getenv("POSTHOG_PERSONAL_API_KEY") or "").strip() or None
    # The ingest host (us.i.posthog.com) differs from the API host (us.posthog.com).
    host = (os.getenv("POSTHOG_API_HOST") or _DEFAULT_HOST).rstrip("/")
    project_id = (os.getenv("POSTHOG_PROJECT_ID") or "").strip() or None
    return key, host, project_id


def is_configured() -> bool:
    key, _host, project_id = _config()
    return bool(key and project_id)


def run_hogql(query: str) -> list[list[Any]] | None:
    """Execute a HogQL query. Returns the ``results`` rows, or None if unavailable."""
    key, host, project_id = _config()
    if not key or not project_id:
        logger.warning(
            "[posthog_query] not configured (need POSTHOG_PERSONAL_API_KEY + "
            "POSTHOG_PROJECT_ID) — engagement metrics unavailable"
        )
        return None

    url = f"{host}/api/projects/{project_id}/query"
    payload = {"query": {"kind": "HogQLQuery", "query": query}}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return data.get("results")
    except Exception as exc:
        logger.exception("[posthog_query] HogQL query failed err=%r", exc)
        return None


def _scalar(results: list[list[Any]] | None) -> int | None:
    if not results or not results[0]:
        return None
    try:
        return int(results[0][0])
    except (TypeError, ValueError):
        return None


def get_active_users(days: int) -> int | None:
    """Distinct active persons over the trailing ``days`` window (DAU=1, MAU=30)."""
    days = max(1, int(days))
    query = (
        "SELECT count(DISTINCT person_id) FROM events "
        f"WHERE timestamp >= now() - INTERVAL {days} DAY"
    )
    return _scalar(run_hogql(query))


def get_dau() -> int | None:
    return get_active_users(1)


def get_mau() -> int | None:
    return get_active_users(30)


def get_event_counts(events: list[str], days: int = 30) -> dict[str, int] | None:
    """Distinct persons per event over the window (funnel step reach)."""
    safe = [e for e in events if _EVENT_RE.match(e)]
    if not safe:
        return {} if is_configured() else None
    in_list = ", ".join(f"'{e}'" for e in safe)
    query = (
        f"SELECT event, count(DISTINCT person_id) FROM events "
        f"WHERE event IN ({in_list}) AND timestamp >= now() - INTERVAL {max(1, int(days))} DAY "
        f"GROUP BY event"
    )
    results = run_hogql(query)
    if results is None:
        return None
    out: dict[str, int] = {}
    for row in results:
        if row and len(row) >= 2:
            try:
                out[str(row[0])] = int(row[1])
            except (TypeError, ValueError):
                continue
    return out


def get_weekly_active(weeks: int = 8) -> list[dict[str, Any]] | None:
    """Weekly active persons for the last ``weeks`` weeks as a {date,count} series."""
    weeks = max(1, min(int(weeks), 26))
    query = (
        "SELECT toStartOfWeek(timestamp) AS wk, count(DISTINCT person_id) AS c FROM events "
        f"WHERE timestamp >= now() - INTERVAL {weeks * 7} DAY GROUP BY wk ORDER BY wk"
    )
    results = run_hogql(query)
    if results is None:
        return None
    series: list[dict[str, Any]] = []
    for row in results:
        if row and len(row) >= 2:
            try:
                series.append({"date": str(row[0])[:10], "count": int(row[1])})
            except (TypeError, ValueError):
                continue
    return series
