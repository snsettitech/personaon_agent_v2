"""
Phase 28: Proactive Notifications — CRON Router

Provides CRON endpoints for triggering meeting notification pipelines.
All CRON endpoints are authenticated via either:
  - GCP OIDC token (production, CLOUD_RUN_SERVICE_URL set)
  - X-Cron-Secret header (local dev / non-GCP deployments, CRON_SECRET set)

If neither CLOUD_RUN_SERVICE_URL nor CRON_SECRET is configured, all CRON
requests are rejected with 401 — there is no open door.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from modules.graph_outbox import GraphOperationType, get_graph_outbox

logger = logging.getLogger(__name__)
router = APIRouter(tags=["notifications"])

CLOUD_RUN_SERVICE_URL = os.getenv("CLOUD_RUN_SERVICE_URL", "")
CRON_SECRET = os.getenv("CRON_SECRET", "")


def _verify_cron_request(request: Request) -> bool:
    """Verify that the incoming request is authorised as a CRON caller.

    Auth strategy:
      1. If NEITHER env var is set — reject immediately (no open door).
      2. If only CRON_SECRET is set — verify X-Cron-Secret header.
      3. If CLOUD_RUN_SERVICE_URL is set — verify GCP OIDC Bearer token.
    """
    # GUARD: reject immediately if no auth mechanism is configured
    if not CLOUD_RUN_SERVICE_URL and not CRON_SECRET:
        logger.warning("[CronAuth] no auth configured — rejecting request")
        return False

    # Path 1: shared secret (local dev / environments without OIDC)
    if not CLOUD_RUN_SERVICE_URL and CRON_SECRET:
        return request.headers.get("X-Cron-Secret") == CRON_SECRET

    # Path 2: GCP OIDC token verification
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        return False
    token = authorization[7:]
    try:
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_requests
        google_id_token.verify_oauth2_token(
            token, google_requests.Request(), audience=CLOUD_RUN_SERVICE_URL
        )
        return True
    except Exception as exc:
        logger.warning("[CronAuth] OIDC verification failed: %s", exc)
        return False


@router.post("/v2/cron/pre-meeting-check")
async def pre_meeting_check(request: Request) -> dict:
    """Scan for meetings starting in ~30 min and enqueue briefing jobs.

    Queries meetings with start_time in the window [now+15min, now+45min]
    and enqueues a GENERATE_MEETING_BRIEFING job for each.

    Returns:
        {"status": "ok", "data": {"enqueued": N}}
    """
    if not _verify_cron_request(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    from modules.observability import supabase

    now = datetime.now(timezone.utc)
    window_start = (now + timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S")
    window_end = (now + timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%S")

    meetings_resp = (
        supabase.table("meetings")
        # Note: previous version selected `attendees` (no such column) — the
        # canonical column is `attendees_json`. The cron loop only needs
        # id/twin/tenant for enqueue; the worker fetches `select("*")` later
        # so it gets the real attendee data. Dropped from SELECT to avoid
        # confusion + unnecessary payload.
        .select("id,twin_id,tenant_id,title,meeting_start")
        .gte("meeting_start", window_start)
        .lte("meeting_start", window_end)
        .execute()
    )
    meetings = meetings_resp.data or []

    outbox = get_graph_outbox()
    enqueued = 0
    for m in meetings:
        outbox.submit(
            tenant_id=str(m["tenant_id"]),
            twin_id=str(m["twin_id"]),
            operation=GraphOperationType.GENERATE_MEETING_BRIEFING,
            idempotency_key=f"meeting_briefing:{m['id']}",
            payload={"meeting_id": str(m["id"])},
            priority=2,
        )
        enqueued += 1

    logger.info(
        "[PreMeetingCron] scanned window=%s..%s enqueued=%d",
        window_start,
        window_end,
        enqueued,
    )
    return {"status": "ok", "data": {"enqueued": enqueued}}


@router.post("/v2/cron/weekly-digest")
async def weekly_digest_cron(request: Request) -> dict:
    """Cloud Scheduler endpoint: enqueue weekly digest for all active twins.

    Runs every Monday. Queries all twins with weekly_digest preference enabled
    (default True) and enqueues a GENERATE_WEEKLY_DIGEST job per twin.

    Uses service-role Supabase client for cross-tenant query (anon key would
    return 0 rows due to RLS).

    Returns:
        {"status": "ok", "data": {"enqueued": N}}
    """
    if not _verify_cron_request(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Use service-role client for cross-tenant query (RLS would return 0 rows)
    from modules.observability import get_supabase_client
    sb_admin = get_supabase_client()

    twins_resp = sb_admin.table("twins").select("id,tenant_id,settings").execute()
    twins = twins_resp.data or []

    outbox = get_graph_outbox()
    enqueued = 0
    for twin in twins:
        twin_id = str(twin["id"])
        tenant_id = str(twin["tenant_id"])

        # Check prefs before enqueuing to reduce worker load
        settings = twin.get("settings") or {}
        prefs = settings.get("meeting_notifications") or {}
        if prefs.get("weekly_digest", True) is False:
            continue

        outbox.submit(
            tenant_id=tenant_id,
            twin_id=twin_id,
            operation=GraphOperationType.GENERATE_WEEKLY_DIGEST,
            idempotency_key=f"weekly_digest:{twin_id}:{datetime.now(timezone.utc).strftime('%Y-W%W')}",
            payload={"twin_id": twin_id},
            priority=1,
        )
        enqueued += 1

    logger.info("[WeeklyDigestCron] enqueued=%d", enqueued)
    return {"status": "ok", "data": {"enqueued": enqueued}}
