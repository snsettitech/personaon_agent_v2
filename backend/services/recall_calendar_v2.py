"""Recall.ai Calendar V2 client.

Wraps the calendar create/delete/list endpoints. We pass the refresh_token
captured in our own OAuth flow — Recall doesn't do its own OAuth dance.

Docs: https://docs.recall.ai/docs/calendar-v2-integration-guide
"""

from __future__ import annotations

import logging
import os
from typing import Literal

import httpx

logger = logging.getLogger(__name__)

RECALL_API_KEY = os.getenv("RECALL_API_KEY", "")
RECALL_API_REGION = os.getenv("RECALL_API_REGION", "us-east-1")
RECALL_BASE_URL = f"https://{RECALL_API_REGION}.recall.ai/api/v2"
_TIMEOUT = 15.0

Platform = Literal["google_calendar", "microsoft_outlook"]


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Token {RECALL_API_KEY}",
        "Content-Type": "application/json",
    }


async def register_calendar(
    *,
    twin_id: str,
    platform: Platform,
    oauth_refresh_token: str,
    oauth_client_id: str,
    oauth_client_secret: str,
    webhook_url: str | None = None,
) -> dict:
    """Register a user's calendar with Recall V2 using their captured refresh_token.

    Args:
        twin_id: Internal twin identifier; stored on the calendar metadata so
            webhooks can be routed back to the owning twin.
        platform: One of ``google_calendar`` or ``microsoft_outlook``.
        oauth_refresh_token: Refresh token captured by our own OAuth flow.
        oauth_client_id: OAuth client ID Recall will use to refresh access tokens.
        oauth_client_secret: OAuth client secret paired with ``oauth_client_id``.
        webhook_url: Optional override for calendar event notifications.

    Returns:
        Raw Recall response (includes ``id`` = recall_calendar_id, ``status``).
    """
    payload: dict = {
        "platform": platform,
        "oauth_refresh_token": oauth_refresh_token,
        "oauth_client_id": oauth_client_id,
        "oauth_client_secret": oauth_client_secret,
        "metadata": {"twin_id": twin_id},
    }
    if webhook_url:
        payload["webhook_url"] = webhook_url

    # Do not log `payload`: it contains oauth credentials.
    logger.info(
        "[RecallCal] register twin_id=%s platform=%s", twin_id, platform
    )
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{RECALL_BASE_URL}/calendars/",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        result = resp.json()
        logger.info(
            "[RecallCal] registered recall_calendar_id=%s twin_id=%s",
            result.get("id"),
            twin_id,
        )
        return result


async def disconnect_calendar(recall_calendar_id: str) -> None:
    """Tell Recall to disconnect a calendar; future-event bots are unscheduled."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(
            f"{RECALL_BASE_URL}/calendars/{recall_calendar_id}/",
            headers=_headers(),
        )
        resp.raise_for_status()
        logger.info(
            "[RecallCal] disconnected recall_calendar_id=%s", recall_calendar_id
        )


async def get_calendar_event(recall_event_id: str) -> dict:
    """Fetch a single calendar event (used to enrich webhook data)."""
    logger.debug("[RecallCal] get_calendar_event id=%s", recall_event_id)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{RECALL_BASE_URL}/calendar-events/{recall_event_id}/",
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


# Hard cap on number of paginated pages we follow during a single sync call.
# Recall returns up to 200 events per page; 100 pages = ~20,000 events. That
# covers multi-year calendar histories for power users. Anything beyond that
# is either a runaway loop or a degenerate calendar -- we surface the cap
# differently depending on whether this is an incremental sync (soft warn,
# return partial results) or an initial full sync (raise
# CalendarSyncTruncatedError so the caller can mark the connector with
# last_error and the UI can prompt the user that the sync was truncated).
_MAX_LIST_PAGES = 100


class CalendarSyncTruncatedError(RuntimeError):
    """Raised when an INITIAL full calendar sync hits the page cap.

    The worker caller (``_process_recall_calendar_sync`` in
    ``modules/graph_outbox_worker.py``) catches this and persists the failure
    on the ``tool_connectors.last_error`` column so the UI can surface a
    "calendar partially synced -- please contact support" message instead
    of silently missing events.

    Incremental syncs (where ``updated_at__gte`` is provided) do NOT raise;
    they log a warning and return what they have, on the assumption that
    the missed events will surface on the next webhook-driven sync.
    """

    def __init__(self, recall_calendar_id: str, pages: int, events_fetched: int) -> None:
        self.recall_calendar_id = recall_calendar_id
        self.pages = pages
        self.events_fetched = events_fetched
        super().__init__(
            f"calendar event sync truncated after {pages} pages "
            f"({events_fetched} events fetched, recall_calendar_id={recall_calendar_id})"
        )


async def list_calendar_events(
    recall_calendar_id: str,
    *,
    updated_at__gte: str | None = None,
) -> list[dict]:
    """Fetch calendar events for a Recall calendar, following pagination.

    Used after a ``calendar.sync_events`` webhook fires (or after an initial
    OAuth connect when we enqueue a manual sync). ``updated_at__gte`` is an
    ISO8601 timestamp from the webhook's ``last_updated_ts`` field; passing
    it asks Recall to return only events changed since the last sync.

    Pagination: Recall returns up to 200 events per page with a ``next``
    cursor URL. We follow ``next`` until exhausted (or ``_MAX_LIST_PAGES``
    safety cap). Without this loop, users with >200 events would silently
    lose the overflow on every sync.

    Args:
        recall_calendar_id: Recall-side calendar id.
        updated_at__gte: ISO8601 lower bound for incremental sync.

    Returns:
        List of Recall calendar-event dicts (may be empty).
    """
    params: dict[str, str] = {"calendar_id": recall_calendar_id}
    if updated_at__gte:
        params["updated_at__gte"] = updated_at__gte

    logger.info(
        "[RecallCal] list_events recall_calendar_id=%s updated_at__gte=%s",
        recall_calendar_id, updated_at__gte,
    )

    results: list[dict] = []
    url: str | None = f"{RECALL_BASE_URL}/calendar-events/"
    request_params: dict[str, str] | None = params
    pages = 0
    more_pages_remaining = False

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        while url and pages < _MAX_LIST_PAGES:
            resp = await client.get(url, headers=_headers(), params=request_params)
            resp.raise_for_status()
            data = resp.json()
            pages += 1

            if isinstance(data, list):
                # Non-paginated shape (no `next`): single batch, exit loop.
                results.extend(data)
                break

            if isinstance(data, dict):
                page = data.get("results", [])
                if isinstance(page, list):
                    results.extend(page)
                # ``next`` is an absolute URL with the cursor already encoded,
                # so on subsequent iterations we drop our query params.
                nxt = data.get("next")
                if isinstance(nxt, str) and nxt:
                    if pages >= _MAX_LIST_PAGES:
                        # We're about to break out of the loop because we hit
                        # the cap, but Recall told us there are still more
                        # pages -- record that so we can either warn or raise.
                        more_pages_remaining = True
                        break
                    url = nxt
                    request_params = None
                    continue
            break

    if more_pages_remaining:
        if updated_at__gte is None:
            # Initial full sync -- raise so the worker caller can stamp
            # last_error on the tool_connectors row. Silently dropping a
            # power user's multi-year history is unacceptable.
            logger.error(
                "[RecallCal] initial sync truncated at page cap recall_calendar_id=%s "
                "pages=%d events=%d -- raising for caller to surface in UI",
                recall_calendar_id, pages, len(results),
            )
            raise CalendarSyncTruncatedError(
                recall_calendar_id=recall_calendar_id,
                pages=pages,
                events_fetched=len(results),
            )

        # Incremental sync -- soft warning. The next webhook-driven sync will
        # pick up the events we missed (Recall fires sync_events on every
        # change, so the lag converges to zero quickly).
        logger.warning(
            "[RecallCal] incremental sync hit page cap recall_calendar_id=%s pages=%d "
            "events=%d updated_at__gte=%s -- returning partial; next webhook sync will catch up",
            recall_calendar_id, pages, len(results), updated_at__gte,
        )
    return results
