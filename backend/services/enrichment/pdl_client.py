"""Thin People Data Labs (PDL) client.

Used by the pre-meeting brief engine (``persona_core.brief``) to enrich a
meeting attendee from their email or LinkedIn URL. The client intentionally
keeps the response shape as a raw ``dict[str, Any]`` — downstream code
picks the fields it needs (full_name, job_title, job_company_name, summary,
headline, experience, location_name, ...).

Behaviour notes:

* When ``PDL_API_KEY`` is not configured, every function returns ``None``
  and logs a single debug line. This keeps the brief flow alive on
  staging / local where the key isn't always present.
* A 404 from PDL ("no person matches") returns ``None``. Other 4xx/5xx
  errors propagate as ``httpx.HTTPStatusError`` so the caller can decide
  whether to swallow them.

Mirrors the style of ``services.recall_calendar_v2``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

PDL_BASE_URL = "https://api.peopledatalabs.com/v5"
_TIMEOUT = 15.0


def _api_key() -> str | None:
    """Read the PDL API key at call time so tests can monkeypatch env vars."""
    key = (os.getenv("PDL_API_KEY") or "").strip()
    return key or None


def _headers(api_key: str) -> dict[str, str]:
    return {
        "X-Api-Key": api_key,
        "Accept": "application/json",
    }


async def _make_request(params: dict[str, str]) -> dict[str, Any] | None:
    """Issue a GET to ``/person/enrich`` and return the ``data`` payload.

    Returns:
        The raw PDL person record on a 200 hit.
        ``None`` when no key is configured or PDL returns 404 (no match).

    Raises:
        ``httpx.HTTPStatusError`` for any other non-2xx response.
    """
    api_key = _api_key()
    if not api_key:
        logger.debug("[PDL] no PDL_API_KEY configured; skipping enrich params=%s", list(params.keys()))
        return None

    url = f"{PDL_BASE_URL}/person/enrich"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, headers=_headers(api_key), params=params)

    # 404 = no match for this email / linkedin URL. Treat as "no enrichment"
    # rather than an error — that's the common case for unknown attendees.
    if resp.status_code == 404:
        logger.info("[PDL] no person match params=%s", list(params.keys()))
        return None

    # PDL sometimes responds 200 with status=200 + data, or 4xx with an error
    # block. raise_for_status handles the non-404 error path cleanly.
    resp.raise_for_status()
    body = resp.json() or {}
    data = body.get("data")
    if not isinstance(data, dict):
        logger.warning("[PDL] unexpected response shape keys=%s", list(body.keys()))
        return None
    return data


async def enrich_by_email(email: str) -> dict[str, Any] | None:
    """Enrich a person by email address.

    Returns ``None`` on missing key, blank input, or no PDL match.
    """
    if not email or not isinstance(email, str):
        return None
    cleaned = email.strip().lower()
    if not cleaned:
        return None
    logger.info("[PDL] enrich_by_email email_domain=%s", cleaned.split("@")[-1] if "@" in cleaned else "?")
    return await _make_request({"email": cleaned})


async def enrich_by_linkedin(url: str) -> dict[str, Any] | None:
    """Enrich a person by their LinkedIn profile URL.

    Returns ``None`` on missing key, blank input, or no PDL match.
    """
    if not url or not isinstance(url, str):
        return None
    cleaned = url.strip()
    if not cleaned:
        return None
    logger.info("[PDL] enrich_by_linkedin")
    return await _make_request({"profile": cleaned})
