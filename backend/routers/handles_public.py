"""Public, unauthenticated handle endpoints that power SEO surfaces.

- GET /handles/public            → paginated index-eligible handles (sitemap)
- GET /handles/public/count      → count of index-eligible handles (shard math)
- GET /handles/{handle}/profile  → server-friendly public profile for SSR
                                    (resolves handle in one call + the SEO gate)

All read-only, no auth. `is_indexable` is the SEO quality gate, computed once in
``services.seo_indexability`` and reused here so the sitemap and the per-page
metadata agree on what is index-eligible. See
docs/architecture/track0-seo-rollout-plan.md.

These are crawler-facing reads, so they never write to the DB: the share token
is read from ``settings`` (never minted here — that would be a write side-effect
on a public GET). The chat island resolves a missing token lazily via
``/handles/resolve`` when the visitor actually opens chat.

Security posture (reviewed): every path is gated by
``is_publicly_accessible_twin_record`` and the profile is passed through
``redact_public_profile_pack_for_public_response`` — private/unpublished twins
and PII never appear. These endpoints are unauthenticated and NOT rate-limited,
consistent with the sibling public endpoints (``/handles/resolve``,
``/share/{twin}/{token}/profile``, ``/public/marketplace``); rate limiting is a
project-wide concern tracked separately. The list/count responses are
CDN-cacheable; the profile endpoint fans out several queries, so prefer caching
it at the edge / CDN.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Path, Query, status
from pydantic import BaseModel

from modules.observability import supabase
from modules.public_profile_pack import (
    build_public_profile_pack,
    redact_public_profile_pack_for_public_response,
)
from modules.share_links import is_publicly_accessible_twin_record
from services.seo_indexability import is_twin_indexable

logger = logging.getLogger(__name__)

router = APIRouter(tags=["handles-public"])

# Only columns needed to enumerate + gate handles (keep the scan light).
_TWIN_SELECT = "id, name, settings, status, created_at, updated_at"
_DEFAULT_LIMIT = 1000
# Intentional: a sitemap generator may pull the full corpus in one request.
# Handles are public once published, so a bulk read is not a privacy concern.
_MAX_LIMIT = 50000
# Handles are sanitized to [a-z0-9-], max 30 chars, at claim time.
_HANDLE_PATTERN = r"^[A-Za-z0-9-]+$"


# =============================================================================
# Schemas
# =============================================================================


class PublicHandleItem(BaseModel):
    handle: str
    last_modified: str
    is_indexable: bool


class PublicHandlePage(BaseModel):
    items: list[PublicHandleItem]
    offset: int
    limit: int
    returned: int
    next_offset: int | None


class PublicHandleCount(BaseModel):
    count: int


class PublicHandleProfile(BaseModel):
    twin_id: str
    handle: str
    # May be None when the twin has no share token yet — the chat island mints
    # one lazily via /handles/resolve. The page itself renders without it.
    share_token: str | None
    is_indexable: bool
    last_modified: str
    profile: dict[str, Any]


# =============================================================================
# Helpers
# =============================================================================


def _twin_rows() -> list[dict[str, Any]]:
    """Fetch the twin rows. `.data` is an untyped JSON value at the Supabase
    boundary; we cast to the row shape we know it has (per CLAUDE.md, Dict[str,
    Any] is allowed at this boundary)."""
    result = supabase.table("twins").select(_TWIN_SELECT).execute()
    return cast("list[dict[str, Any]]", result.data or [])


def _handle_of(twin: dict[str, Any]) -> str:
    settings = twin.get("settings")
    if isinstance(settings, dict):
        return str(settings.get("handle") or "").strip().lower()
    return ""


def _last_modified(twin: dict[str, Any]) -> str:
    return str(twin.get("updated_at") or twin.get("created_at") or "")


def _existing_share_token(settings: dict[str, Any]) -> str | None:
    """Read an already-minted share token from settings (never mints — this is
    a public read path and must not write).

    Returns the token for marketplace-public twins regardless of the legacy
    ``public_share_enabled`` flag — consistent with ``/handles/resolve``. Only
    reached after the public-access gate passes.
    """
    widget_settings = settings.get("widget_settings")
    if isinstance(widget_settings, dict):
        return widget_settings.get("share_token") or None
    return None


def _fetch_public_twins_with_handles() -> list[dict[str, Any]]:
    """All publicly-accessible twins that have a handle, sorted by handle.

    Mirrors the full-table scan + visibility filter used by
    ``/handles/resolve``. Offset pagination over this stable, sorted list keeps
    the sitemap shards aligned. NOTE: full-table scan, no cache — acceptable at
    current scale; add a short TTL cache before traffic grows.
    """
    public = [
        row
        for row in _twin_rows()
        if _handle_of(row) and is_publicly_accessible_twin_record(row)
    ]
    public.sort(key=_handle_of)
    return public


def _index_eligible_twins() -> list[dict[str, Any]]:
    """Public twins that also clear the SEO quality gate, sorted by handle."""
    return [t for t in _fetch_public_twins_with_handles() if is_twin_indexable(t)]


def _resolve_public_twin(handle: str) -> dict[str, Any] | None:
    # NOTE: full-table scan (same as /handles/resolve) — no handle index exists.
    # Acceptable at current scale; revisit with a cache/index before growth.
    handle_lower = handle.strip().lower()
    for twin in _twin_rows():
        if _handle_of(twin) == handle_lower:
            return twin if is_publicly_accessible_twin_record(twin) else None
    return None


# =============================================================================
# Endpoints
#
# Route order matters: the literal /handles/public[/count] paths are declared
# BEFORE the parametric /handles/{handle}/profile so FastAPI does not shadow
# them. Add any new LITERAL /handles/... endpoint ABOVE the parametric route.
# =============================================================================


@router.get("/handles/public", response_model=PublicHandlePage)
async def list_public_handles(
    offset: int = Query(0, ge=0),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
) -> PublicHandlePage:
    """Paginated list of index-eligible public persona handles for the sitemap."""
    eligible = _index_eligible_twins()
    window = eligible[offset : offset + limit]
    items = [
        PublicHandleItem(
            handle=_handle_of(twin),
            last_modified=_last_modified(twin),
            is_indexable=True,
        )
        for twin in window
    ]
    next_offset = offset + limit if offset + limit < len(eligible) else None
    return PublicHandlePage(
        items=items,
        offset=offset,
        limit=limit,
        returned=len(items),
        next_offset=next_offset,
    )


@router.get("/handles/public/count", response_model=PublicHandleCount)
async def count_public_handles() -> PublicHandleCount:
    """Count of index-eligible public handles (for sitemap shard math)."""
    return PublicHandleCount(count=len(_index_eligible_twins()))


@router.get("/handles/{handle}/profile", response_model=PublicHandleProfile)
async def get_handle_profile(
    handle: str = Path(..., min_length=2, max_length=30, pattern=_HANDLE_PATTERN),
) -> PublicHandleProfile:
    """Resolve a handle and return its public profile + SEO gate in one call.

    Server-friendly contract for SSR (`app/p/[handle]/page.tsx`): one round trip
    instead of `/handles/resolve` + `/share/.../profile`, carrying `twin_id` and
    the (read-only) `share_token` for the chat island, and `is_indexable` for
    the page's `noindex` metadata.
    """
    twin = _resolve_public_twin(handle)
    if twin is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Handle not found."
        )

    twin_id = str(twin.get("id") or "")
    raw_settings = twin.get("settings")
    settings: dict[str, Any] = raw_settings if isinstance(raw_settings, dict) else {}

    try:
        profile_pack = redact_public_profile_pack_for_public_response(
            build_public_profile_pack(twin),
            settings,
        )
    except Exception:
        logger.exception(
            "[handles_public] profile pack build failed handle=%s twin=%s",
            handle,
            twin_id,
        )
        # Full traceback is logged above; do not leak internals to the client.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile temporarily unavailable.",
        ) from None

    return PublicHandleProfile(
        twin_id=twin_id,
        handle=_handle_of(twin),
        share_token=_existing_share_token(settings),
        is_indexable=is_twin_indexable(twin),
        last_modified=_last_modified(twin),
        profile=profile_pack,
    )
