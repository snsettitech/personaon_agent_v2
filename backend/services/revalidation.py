"""Best-effort on-demand revalidation of persona SEO surfaces.

When a persona is published or its handle/public profile changes, ping the
frontend so the SSR persona page + sitemap refresh immediately instead of
waiting for the 1h ISR window. Fire-and-forget: never raises into the caller.

Active in prod: REVALIDATE_TOKEN is set on both this service and the frontend
(shared revalidate-token secret). See frontend/app/api/revalidate/route.ts.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 5.0


async def revalidate_persona(handle: str) -> None:
    """Tell the frontend to refresh /p/{handle} + the sitemap. Best-effort."""
    normalized = (handle or "").strip().lower()
    if not normalized:
        return

    token = os.getenv("REVALIDATE_TOKEN", "").strip()
    if not token:
        logger.info(
            "[Revalidate] REVALIDATE_TOKEN unset; skipping handle=%s", normalized
        )
        return

    frontend_url = os.getenv("FRONTEND_URL", "https://personaon.com").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{frontend_url}/api/revalidate",
                json={"handle": normalized},
                headers={"x-revalidate-token": token},
            )
        logger.info(
            "[Revalidate] triggered handle=%s status=%s",
            normalized,
            response.status_code,
        )
    except Exception as exc:
        # Never let a revalidation hiccup break the publish/claim flow.
        logger.warning("[Revalidate] failed handle=%s: %s", normalized, exc)
