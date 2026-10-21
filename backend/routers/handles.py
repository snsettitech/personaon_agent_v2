"""Handle management for persona public URLs (/p/{handle})."""

from __future__ import annotations

import logging
import random
import re
import unicodedata
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from modules.auth_guard import require_tenant, verify_twin_ownership
from modules.observability import supabase
from modules.share_links import ensure_share_token, is_publicly_accessible_twin_record
from services.revalidation import revalidate_persona

logger = logging.getLogger(__name__)

router = APIRouter(tags=["handles"])


# =============================================================================
# Constants
# =============================================================================

RESERVED_HANDLES = frozenset([
    # Existing app auth/product route segments
    "admin", "api", "app", "auth", "dashboard", "login", "signup",
    "settings", "help", "support", "about", "terms", "privacy", "p",
    # Every other top-level route segment under frontend/app/
    "blog", "experience", "legal", "m", "marketplace", "onboarding",
    "pricing", "share", "v2", "widget",
    # Conventional reserved infra words. Keep in sync with the CHECK
    # constraint `twins_handle_not_reserved` added in
    # supabase/migrations/20260703000000_twins_handle_unique_constraint.sql
    "www", "static", "assets", "null", "undefined", "favicon",
    "robots", "sitemap",
])

# Bounded retry cap for the unique-violation race path in claim_handle. Each
# attempt re-reads the current "taken" set and re-picks a candidate, so a
# transient race resolves within a couple of retries; this cap exists purely
# to guarantee termination if something is persistently wrong.
MAX_HANDLE_CLAIM_ATTEMPTS = 5


# =============================================================================
# Schemas
# =============================================================================

class HandleClaimRequest(BaseModel):
    twin_id: str
    handle: str


class HandleClaimResponse(BaseModel):
    handle: str
    url: str


# =============================================================================
# Helpers
# =============================================================================

def _sanitize_handle(raw: str) -> str:
    """Sanitize a raw string into a URL-safe handle."""
    normalized = unicodedata.normalize("NFD", raw.lower())
    stripped = re.sub(r"[\u0300-\u036f]", "", normalized)  # remove diacritics
    cleaned = re.sub(r"[^a-z0-9\s-]", "", stripped).strip()
    hyphenated = re.sub(r"\s+", "-", cleaned)
    collapsed = re.sub(r"-+", "-", hyphenated)
    return collapsed[:30]


def _find_available_handle(
    base_handle: str,
    exclude_twin_id: str,
    all_twins: list,
    attempt: int = 0,
) -> str:
    """Find an available handle, appending -2, -3, etc. if base is taken.

    On retry attempts (attempt > 0) the numeric-suffix scan starts from a
    randomized offset instead of always restarting at -2. Without this, every
    concurrent claimant racing for the same base handle would probe the
    identical candidate sequence on every retry round, converge in lockstep,
    and only one claimant per round could win via the DB unique-violation --
    even when a handle further out in the sequence (e.g. -6) was free the
    whole time. Jittering the start spreads concurrent losers across
    different candidates so more of them succeed within the retry cap.
    """
    taken = set()
    for row in all_twins:
        if row.get("id") == exclude_twin_id:
            continue
        s = row.get("settings")
        if isinstance(s, dict):
            h = str(s.get("handle") or "").strip().lower()
            if h:
                taken.add(h)

    if attempt == 0 and base_handle not in taken:
        return base_handle

    suffix_count = 98  # candidates -2 through -99
    start = 2 if attempt == 0 else random.randint(2, 2 + suffix_count - 1)
    for offset in range(suffix_count):
        n = 2 + (start - 2 + offset) % suffix_count
        candidate = f"{base_handle}-{n}"
        if candidate not in taken:
            return candidate

    # Fallback: append timestamp suffix (extremely unlikely to be needed)
    import time
    return f"{base_handle}-{int(time.time()) % 10000}"


# =============================================================================
# Endpoints
# =============================================================================

def _is_unique_violation(exc: Exception) -> bool:
    """True if `exc` looks like a Postgres unique-constraint violation (23505)."""
    msg = str(exc).lower()
    return "duplicate" in msg or "unique" in msg or "23505" in msg


@router.post("/handles/claim", response_model=HandleClaimResponse)
async def claim_handle(
    request: HandleClaimRequest,
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """
    Claim a handle for a twin. Sanitizes input, rejects reserved handles,
    resolves collisions by appending -2/-3/..., and stores in twins.settings.handle.

    The application-layer collision check (_find_available_handle) is a
    fast-path optimization only — reading the full twins table and picking a
    free candidate is NOT atomic, so two concurrent claims for the identical
    handle can both read the same "taken" set and both attempt to write it.
    The actual race-safety guarantee is the DB-level unique index
    `idx_twins_handle_unique` on lower(settings->>'handle') (see
    supabase/migrations/20260703000000_twins_handle_unique_constraint.sql):
    at most one concurrent UPDATE can commit. The loser's UPDATE raises a
    unique-violation, which is caught below and retried with a freshly
    re-picked handle — never a raw 500, and never a silent duplicate.
    """
    verify_twin_ownership(request.twin_id, user)

    sanitized = _sanitize_handle(request.handle)

    if len(sanitized) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Handle must be at least 2 characters after sanitization.",
        )

    if sanitized in RESERVED_HANDLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{sanitized}' is a reserved handle and cannot be claimed.",
        )

    tenant_id = user.get("tenant_id", "")

    twin_row_result = (
        supabase.table("twins")
        .select("id, settings")
        .eq("id", request.twin_id)
        .eq("tenant_id", tenant_id)
        .single()
        .execute()
    )
    if not twin_row_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Twin not found.",
        )

    for attempt in range(MAX_HANDLE_CLAIM_ATTEMPTS):
        # Fetch all twins to check uniqueness (app-layer fast path; see
        # docstring above for why this alone doesn't prevent the race).
        all_twins_result = (
            supabase.table("twins")
            .select("id, settings")
            .execute()
        )
        all_twins = all_twins_result.data or []

        claimed_handle = _find_available_handle(
            sanitized, request.twin_id, all_twins, attempt=attempt
        )

        # Re-read this twin's settings from the same all_twins snapshot just
        # fetched above (fresh every retry) rather than reusing the one-time
        # pre-loop fetch. Reusing the stale pre-loop snapshot here would
        # silently clobber any concurrent write to an unrelated settings
        # field (e.g. a bio-edit PATCH) that landed while this request was
        # mid-retry, since the eventual UPDATE writes the whole settings blob.
        current_twin_row = next(
            (t for t in all_twins if t.get("id") == request.twin_id),
            None,
        )
        settings_source = current_twin_row or twin_row_result.data
        settings = dict(settings_source.get("settings") or {})
        settings["handle"] = claimed_handle

        try:
            supabase.table("twins").update({"settings": settings}).eq(
                "id", request.twin_id
            ).eq("tenant_id", tenant_id).execute()
        except Exception as exc:
            if _is_unique_violation(exc):
                logger.info(
                    "[Handles] unique-violation race claiming handle=%s twin_id=%s "
                    "attempt=%d/%d, retrying with a fresh candidate",
                    claimed_handle, request.twin_id, attempt + 1, MAX_HANDLE_CLAIM_ATTEMPTS,
                )
                continue
            logger.exception(
                "[Handles] claim_handle update failed twin_id=%s handle=%s",
                request.twin_id, claimed_handle,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to claim handle. Please try again.",
            ) from exc

        # Refresh the persona's SSR page + sitemap now that its handle is set/changed.
        await revalidate_persona(claimed_handle)

        return {"handle": claimed_handle, "url": f"/p/{claimed_handle}"}

    # Exhausted retries — surface a clean collision response, never a raw 500.
    logger.info(
        "[Handles] exhausted %d claim attempts for twin_id=%s base_handle=%s",
        MAX_HANDLE_CLAIM_ATTEMPTS, request.twin_id, sanitized,
    )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"'{sanitized}' is currently unavailable — please try a different handle.",
    )


@router.get("/handles/check")
async def check_handle(
    handle: str = Query(..., min_length=2, max_length=30),
    twin_id: str = Query(default=""),
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """
    Check if a handle is available. Returns suggestion when taken.
    """
    sanitized = _sanitize_handle(handle)

    if len(sanitized) < 2:
        return {"available": False, "suggestion": None}

    # Exact-match check filters server-side (uses the same expression the
    # unique index covers) instead of fetching every twin.
    exact_query = (
        supabase.table("twins")
        .select("id, settings")
        .eq("settings->>handle", sanitized)
    )
    if twin_id:
        exact_query = exact_query.neq("id", twin_id)
    exact_result = exact_query.limit(1).execute()

    if not exact_result.data:
        return {"available": True}

    # Suggestion scan only needs rows matching the "<sanitized>-N" pattern,
    # not the whole table.
    suffix_result = (
        supabase.table("twins")
        .select("settings")
        .ilike("settings->>handle", f"{sanitized}-%")
        .execute()
    )
    taken_suffixes = set()
    for row in suffix_result.data or []:
        s = row.get("settings")
        if isinstance(s, dict):
            h = str(s.get("handle") or "").strip().lower()
            if h:
                taken_suffixes.add(h)

    for n in range(2, 100):
        candidate = f"{sanitized}-{n}"
        if candidate not in taken_suffixes:
            return {"available": False, "suggestion": candidate}

    return {"available": False, "suggestion": None}


@router.get("/handles/resolve")
async def resolve_handle(
    handle: str = Query(..., min_length=2, max_length=30),
) -> dict[str, Any]:
    """
    Resolve a handle to twin_id and share_token. Public endpoint — no auth.
    """
    handle_lower = handle.strip().lower()

    # Filter server-side on the same expression the unique index covers
    # (lower(settings->>'handle')) instead of fetching every twin — this is
    # the hottest public-facing path (every /p page view resolves through
    # here), so it must not scale linearly with total twin count.
    matched_result = (
        supabase.table("twins")
        .select("id, settings, status")
        .eq("settings->>handle", handle_lower)
        .limit(1)
        .execute()
    )
    matched_twin: dict[str, Any] | None = (matched_result.data or [None])[0]

    if matched_twin is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Handle not found.",
        )

    if not is_publicly_accessible_twin_record(matched_twin):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Handle not found.",
        )

    share_token = ensure_share_token(matched_twin["id"], twin_row=matched_twin)

    return {
        "twin_id": matched_twin["id"],
        "share_token": share_token,
    }
