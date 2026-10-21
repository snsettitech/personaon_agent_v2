"""Scalable onboarding endpoints.

These endpoints make first-run persona creation a single backend-owned action:
consent, one-profile-per-user reuse, public handle setup, and async enrichment.
"""

from __future__ import annotations

import logging
import os
import re
import time as _time_module
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from modules.auth_guard import require_tenant
from modules.observability import get_supabase_client
from modules.profile_selection import (
    build_creator_candidates,
    select_profile_twin_from_rows,
)
from modules.share_links import ensure_share_token
from modules.tenant_guard import derive_creator_ids
from modules.text_quality import validate_headline_text, validate_meaningful_text
from modules.theme_lookup import infer_default_theme_id
from routers.auto_create import _enqueue_enrichment, _sanitize_context, _sanitize_name
from routers.handles import RESERVED_HANDLES, _find_available_handle, _sanitize_handle

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

PENDING_LEGAL_VERSION = "pending-v0"
PENDING_CONSENT_TEXT = (
    "I agree to the temporary PersonaOn platform terms and privacy notice "
    "while final legal documents are being versioned."
)


def _consent_gate_enabled() -> bool:
    """Whether the temporary consent gate is required.

    Defaults to False so production ships without a placeholder T&C page.
    Set PENDING_CONSENT_ENABLED=true once real Terms and Privacy versions are
    live.
    """
    raw = os.getenv("PENDING_CONSENT_ENABLED", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


# Per-user rate limit on persona creation. Each call queues a Firecrawl job;
# unlimited calls would let any authenticated user drain Firecrawl quota.
#
# Limitations of this implementation (acceptable for current single-replica
# staging; revisit before scaling beyond ~1k DAU):
#   - In-memory per-process: multiple Cloud Run replicas have independent
#     buckets, so a user can technically get 3 * N_replicas hits per hour.
#     Move to Redis (or reuse the existing _check_prefill_rate_limit pattern
#     once that itself moves to Redis) for fair multi-replica enforcement.
#   - Counts every call, not just enrichment-producing ones. The endpoint
#     skips this check on idempotent retries (existing persona + already-queued
#     enrichment) so legitimate refresh/retry doesn't burn quota.
_persona_create_rate_limits: dict[str, list[float]] = defaultdict(list)
_PERSONA_RATE_LIMIT = 3      # calls per window
_PERSONA_RATE_WINDOW = 3600  # 1 hour


def _check_persona_create_rate_limit(user_id: str) -> bool:
    """Returns True if the call is allowed, False if it exceeds the window."""
    now = _time_module.time()
    window_start = now - _PERSONA_RATE_WINDOW
    bucket = _persona_create_rate_limits[user_id]
    bucket[:] = [t for t in bucket if t > window_start]
    if len(bucket) >= _PERSONA_RATE_LIMIT:
        return False
    bucket.append(now)
    return True


def _is_idempotent_from_twin(existing: dict[str, Any] | None) -> bool:
    """True if the caller already has a persona with enrichment queued/done.

    Safe retries (refresh, double-click submit, reload) should not consume
    rate-limit budget because they don't kick off a new Firecrawl job — the
    existing-twin update path skips re-enqueue when enrichment_status is
    already 'queued' or 'completed' (see _queue_enrichment).
    """
    if not existing:
        return False
    settings = (existing.get("settings") or {})
    status_value = str(settings.get("enrichment_status") or "").strip().lower()
    return status_value in ("queued", "completed")


class ConsentAcceptRequest(BaseModel):
    accepted: bool = Field(..., description="User must explicitly accept temporary consent.")


class ConsentState(BaseModel):
    accepted: bool
    terms_version: str | None = None
    privacy_version: str | None = None
    accepted_at: str | None = None


class PersonaSummary(BaseModel):
    twin_id: str
    handle: str | None = None
    public_url: str | None = None
    persona_quality: str = "basic"
    enrichment_status: str = "not_queued"


class OnboardingStatusResponse(BaseModel):
    consent_required: bool
    consent: ConsentState
    has_persona: bool
    persona: PersonaSummary | None = None
    next_route: str


_FORBIDDEN_URL_SCHEMES = ("javascript:", "data:", "vbscript:", "file:")


class CreatePersonaRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=120)
    # min_length here is just "non-empty" — the real meaningfulness bar
    # (length, single-word, whitespace, repeated-character/low-entropy) is
    # enforced by `_meaningful_headline` below via modules.text_quality, the
    # single source of truth shared with UpdateProfileRequest and patch_twin.
    headline: str = Field(..., min_length=1, max_length=180)
    short_intro: str | None = Field(default=None, max_length=800)
    linkedin_url: str | None = Field(default=None, max_length=500)
    website_url: str | None = Field(default=None, max_length=500)
    avatar_url: str | None = Field(default=None, max_length=2048)

    @field_validator("headline")
    @classmethod
    def _meaningful_headline(cls, v: str) -> str:
        """Reject near-nothing headlines (root cause: PRD R1 "software engineer"
        headline problem was compounded by a garbage bio slipping past the old
        min_length=2 check with no meaningfulness validation at all)."""
        return validate_headline_text(v)

    @field_validator("short_intro")
    @classmethod
    def _meaningful_short_intro(cls, v: str | None) -> str | None:
        """Reject "nill", single words, all-whitespace, and repeated-character
        filler when a bio IS provided. Omitting the field entirely (None) is
        still allowed — this only validates what's actually submitted."""
        if v is None:
            return None
        return validate_meaningful_text(v)

    @field_validator("linkedin_url", "website_url", "avatar_url")
    @classmethod
    def _safe_url_scheme(cls, v: str | None) -> str | None:
        """Reject dangerous URL schemes that could trigger XSS when rendered.

        These fields flow into public_profile (rendered on /p/<handle>) and
        email-signature HTML (pasted into Gmail/Outlook). A `javascript:` URL
        in a social link or avatar src is a stored XSS vector.
        """
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            return None
        lower = cleaned.lower()
        for bad in _FORBIDDEN_URL_SCHEMES:
            if lower.startswith(bad):
                raise ValueError("URL scheme not allowed")
        # If a scheme is present, only http(s) is acceptable.
        # _normalize_public_url() will prepend https:// when no scheme is given.
        if "://" in cleaned:
            if not (lower.startswith("http://") or lower.startswith("https://")):
                raise ValueError("URLs must use http or https")
        return cleaned


class CreatePersonaResponse(BaseModel):
    twin_id: str
    handle: str
    public_url: str
    persona_quality: str
    enrichment_status: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_optional_text(value: str | None, *, max_length: int) -> str:
    cleaned = re.sub(r"<[^>]+>", "", str(value or "").strip())
    return cleaned[:max_length]


def _auth_provider(user: dict[str, Any]) -> str:
    app_metadata = user.get("app_metadata") if isinstance(user.get("app_metadata"), dict) else {}
    provider = str(app_metadata.get("provider") or "").strip()
    providers = app_metadata.get("providers")
    if not provider and isinstance(providers, list) and providers:
        provider = str(providers[0] or "").strip()
    return provider or "unknown"


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    if request.client:
        return request.client.host
    return None


def _safe_settings(twin: dict[str, Any] | None) -> dict[str, Any]:
    settings = (twin or {}).get("settings")
    return settings if isinstance(settings, dict) else {}


def _public_url(handle: str | None) -> str | None:
    return f"/p/{handle}" if handle else None


def _persona_summary(twin: dict[str, Any] | None) -> PersonaSummary | None:
    if not twin:
        return None
    settings = _safe_settings(twin)
    handle = str(settings.get("handle") or "").strip() or None
    return PersonaSummary(
        twin_id=str(twin.get("id")),
        handle=handle,
        public_url=_public_url(handle),
        persona_quality=str(settings.get("persona_quality") or "basic"),
        enrichment_status=str(settings.get("enrichment_status") or "not_queued"),
    )


def _get_pending_consent(user_id: str) -> dict[str, Any] | None:
    if not _consent_gate_enabled():
        return None
    sb = get_supabase_client()
    try:
        result = (
            sb.table("user_agreements")
            .select("id, terms_version, privacy_version, accepted_at")
            .eq("user_id", user_id)
            .eq("terms_version", PENDING_LEGAL_VERSION)
            .eq("privacy_version", PENDING_LEGAL_VERSION)
            .order("accepted_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.warning("[Onboarding] consent lookup failed: %s", exc)
        return None
    rows = result.data or []
    return rows[0] if rows else None


def _consent_state(user_id: str) -> ConsentState:
    row = _get_pending_consent(user_id)
    if not row:
        return ConsentState(accepted=False)
    return ConsentState(
        accepted=True,
        terms_version=row.get("terms_version"),
        privacy_version=row.get("privacy_version"),
        accepted_at=row.get("accepted_at"),
    )


def _require_pending_consent(user_id: str) -> None:
    # When the consent gate is disabled at the env level, skip enforcement
    # entirely. Production default. See _consent_gate_enabled above.
    if not _consent_gate_enabled():
        return
    if not _get_pending_consent(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Temporary Terms and Privacy consent is required before creating a persona.",
        )


def _fetch_profile_twin(user: dict[str, Any]) -> dict[str, Any] | None:
    tenant_id = str(user.get("tenant_id") or "").strip()
    user_id = str(user.get("user_id") or "").strip()
    if not tenant_id or not user_id:
        return None

    sb = get_supabase_client()
    result = (
        sb.table("twins")
        .select("id, tenant_id, creator_id, name, description, status, settings, created_at")
        .eq("tenant_id", tenant_id)
        .execute()
    )
    return select_profile_twin_from_rows(
        rows=result.data or [],
        user_id=user_id,
        creator_candidates=build_creator_candidates(user=user),
    )


def _extract_linkedin_snapshot(user_id: str, user: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    try:
        from modules.profile_utils import (
            select_best_linkedin_account,
            user_has_linkedin_provider,
        )

        if not user_has_linkedin_provider(user):
            return {}, None
        sb = get_supabase_client()
        result = (
            sb.table("connected_accounts")
            .select("provider, profile_snapshot, provider_user_id")
            .eq("user_id", user_id)
            .in_("provider", ["linkedin", "linkedin_oidc"])
            .execute()
        )
        account = select_best_linkedin_account(result.data or []) or {}
        return account.get("profile_snapshot") or {}, account.get("provider_user_id")
    except Exception as exc:
        logger.warning("[Onboarding] LinkedIn snapshot lookup failed: %s", exc)
        return {}, None


def _normalize_linkedin_url(raw_url: str | None, provider_user_id: str | None) -> str | None:
    if not raw_url:
        return None
    try:
        from modules.profile_utils import (
            is_synthesized_linkedin_url,
            normalize_linkedin_profile_url,
        )

        if is_synthesized_linkedin_url(raw_url, provider_user_id or ""):
            return None
        return normalize_linkedin_profile_url(raw_url) or None
    except Exception:
        return raw_url.strip() or None


def _normalize_public_url(raw_url: str | None) -> str | None:
    value = str(raw_url or "").strip()
    if not value:
        return None
    if not re.match(r"^https?://", value, flags=re.IGNORECASE):
        value = f"https://{value}"
    return value[:500]


def _check_linkedin_uniqueness(linkedin_url: str | None, current_user_id: str) -> None:
    """Reject if another user already owns a persona for this LinkedIn URL.

    The product premise is one persona per real person. A canonicalized LinkedIn
    URL identifies a real person, so the same URL must not appear on personas
    owned by different users (even across tenants). This is enforced at the
    application layer because the URL lives inside settings JSONB and there's
    no UNIQUE constraint at the schema level.

    Long-term: add a UNIQUE partial index on the canonicalized URL column or
    a dedicated linkedin_canonical_url column on twins.
    """
    if not linkedin_url:
        return
    sb = get_supabase_client()
    try:
        result = (
            sb.table("twins")
            .select("id, settings")
            .filter("settings->public_profile->social_links->>linkedin", "eq", linkedin_url)
            .execute()
        )
    except Exception as exc:
        # Don't block creation if the lookup fails; log for follow-up.
        logger.warning("[Onboarding] LinkedIn uniqueness check failed: %s", exc)
        return
    for row in result.data or []:
        settings = row.get("settings") or {}
        owner = str(settings.get("owner_user_id") or "").strip()
        if owner and owner != current_user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "LINKEDIN_ALREADY_CLAIMED",
                    "message": (
                        "A persona for this LinkedIn profile already exists. "
                        "If this is your account, sign in with the original email."
                    ),
                },
            )


def _build_profiles(
    *,
    full_name: str,
    headline: str,
    short_intro: str,
    avatar_url: str | None,
    linkedin_url: str | None,
    website_url: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    public_profile = {
        "display_name": full_name,
        "role": headline,
        "headline": headline,
        "bio": short_intro,
        "short_description": short_intro,
        "avatar_url": avatar_url,
        "image_url": avatar_url,
        "social_links": {
            "linkedin": linkedin_url,
            "website": website_url,
        },
    }
    persona_profile = {
        "name": full_name,
        "headline": headline,
        "occupation": headline,
        "short_description": short_intro,
        "image_url": avatar_url,
        "social_links": {
            "linkedin": linkedin_url,
            "website": website_url,
        },
    }
    return public_profile, persona_profile


def _resolve_handle(full_name: str, twin_id: str, tenant_id: str | None = None) -> str:
    """Resolve an available public handle.

    Handles are GLOBAL (one /p/<handle> per system, cross-tenant) so we cannot
    scope by tenant. To keep the scan size bounded as twin count grows, we filter
    to twins that have actually claimed a handle — the sentinel is
    settings->>'handle' being non-null. NOTE: TOCTOU race exists between this
    SELECT and the subsequent UPDATE; the duplicate-key retry on the twins INSERT
    handles 99% of cases. Long-term fix: dedicated twins.handle TEXT UNIQUE
    column + partial index.

    The tenant_id parameter is accepted for future use when handles become
    tenant-scoped or for correlation logging.
    """
    base = _sanitize_handle(full_name)
    if len(base) < 2 or base in RESERVED_HANDLES:
        base = _sanitize_handle(f"{full_name}-persona")
    if len(base) < 2 or base in RESERVED_HANDLES:
        base = "persona"

    sb = get_supabase_client()
    # Only scan twins that have already claimed a handle. This still returns
    # the relevant collision set without pulling every twin in the database.
    query = sb.table("twins").select("id, settings").not_.is_("settings->>handle", "null")
    all_twins = query.execute().data or []
    return _find_available_handle(base, twin_id, all_twins)


def _update_twin_settings(twin_id: str, tenant_id: str, settings: dict[str, Any], payload: dict[str, Any] | None = None) -> None:
    update_payload = {"settings": settings}
    if payload:
        update_payload.update(payload)
    q = get_supabase_client().table("twins").update(update_payload).eq("id", twin_id)
    if tenant_id:
        q = q.eq("tenant_id", tenant_id)
    q.execute()


def _create_or_update_persona(
    *,
    request: CreatePersonaRequest,
    user: dict[str, Any],
    linkedin_snapshot: dict[str, Any],
    provider_user_id: str | None,
    prefetched_twin: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str, str]:
    user_id = str(user["user_id"])
    tenant_id = str(user["tenant_id"])
    email = str(user.get("email") or "")

    snapshot_name = str(linkedin_snapshot.get("display_name") or "").strip()
    full_name = _sanitize_name(snapshot_name or request.full_name)
    headline = _sanitize_context(
        str(linkedin_snapshot.get("headline") or request.headline or "").strip()
    )
    # Apply prompt-injection sanitization to short_intro since it flows into
    # persona_profile.short_description which is read by the chat agent.
    raw_intro = _clean_optional_text(request.short_intro, max_length=800)
    short_intro = _sanitize_context(raw_intro) if raw_intro else ""
    avatar_url = (
        str(linkedin_snapshot.get("image_url") or "").strip()
        or str(request.avatar_url or user.get("avatar_url") or "").strip()
        or None
    )
    raw_linkedin_url = (
        str(linkedin_snapshot.get("profile_url") or "").strip()
        or str(linkedin_snapshot.get("linkedin_url") or "").strip()
        or str(request.linkedin_url or "").strip()
    )
    linkedin_url = _normalize_linkedin_url(raw_linkedin_url, provider_user_id)
    website_url = _normalize_public_url(request.website_url)

    # Reject if another user already owns a persona for this LinkedIn URL.
    # One persona per real person.
    _check_linkedin_uniqueness(linkedin_url, user_id)
    public_profile, persona_profile = _build_profiles(
        full_name=full_name,
        headline=headline,
        short_intro=short_intro,
        avatar_url=avatar_url,
        linkedin_url=linkedin_url,
        website_url=website_url,
    )
    # execution-board 0.3: this is the LIVE persona-creation path (see the
    # lead_capture_enabled comment below -- auto_create_twin is not currently
    # called by the frontend), so the same "non-customizing signup never
    # silently lands on Classic" fix applied in routers/auto_create.py must
    # live here too, not just there.
    default_theme_id = infer_default_theme_id(headline, short_intro)

    existing = prefetched_twin if prefetched_twin is not None else _fetch_profile_twin(user)
    sb = get_supabase_client()
    creator_ids = derive_creator_ids(user) or [f"tenant_{tenant_id}"]

    # auto_create_state lifecycle:
    #   - 'generating' if any enrichment will run (Pinecone vectors not ready yet)
    #   - 'active' if no enrichment queued (persona is as good as it'll get)
    # The training_jobs.profile_enrichment worker flips 'generating' -> 'indexing' -> 'active'
    # and flips widget_settings.public_share_enabled -> True after KB is populated.
    # Enrichment always runs with whatever the user provided (name + headline + optional URLs);
    # extract_profile handles linkedin_url=None by searching by name+context alone.
    initial_auto_state = "generating"

    if existing:
        twin_id = str(existing["id"])
        settings = dict(existing.get("settings") or {})

        # Ownership check: the canonical profile twin in this tenant must belong
        # to the calling user. Prevents teammates clobbering each other's profile.
        existing_owner = settings.get("owner_user_id")
        if existing_owner and existing_owner != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This persona belongs to another user.",
            )

        handle = str(settings.get("handle") or "").strip() or _resolve_handle(full_name, twin_id, tenant_id)
        widget_settings = dict(settings.get("widget_settings") or {})
        # Preserve existing public_share_enabled if explicitly set; default False for new ones.
        if "public_share_enabled" not in widget_settings:
            widget_settings["public_share_enabled"] = False
        # Only fall back to the inferred default if no theme_id was ever set —
        # never clobber a theme the owner (or a prior run of this fix) already
        # chose, since _build_profiles' public_profile fully replaces the old one.
        existing_theme_id = dict(settings.get("public_profile") or {}).get("theme_id")
        public_profile = {**public_profile, "theme_id": existing_theme_id or default_theme_id}
        settings.update({
            "owner_user_id": user_id,
            "creation_mode": settings.get("creation_mode") or "onboarding",
            "handle": handle,
            "public_profile": public_profile,
            "persona_profile": {**dict(settings.get("persona_profile") or {}), **persona_profile},
            "persona_quality": settings.get("persona_quality") or "basic",
            "enrichment_status": settings.get("enrichment_status") or "not_queued",
            "onboarding_completed_at": settings.get("onboarding_completed_at") or _utc_now_iso(),
            "widget_settings": widget_settings,
            # Only set initial auto_create_state if absent. Don't reset a twin that's
            # already 'active' or 'indexing' from a previous enrichment run.
            "auto_create_state": settings.get("auto_create_state") or initial_auto_state,
        })
        _update_twin_settings(
            twin_id,
            tenant_id,
            settings,
            {"name": full_name, "description": short_intro or f"{full_name}'s persona", "status": "active"},
        )
        return {**existing, "name": full_name, "settings": settings, "status": "active"}, linkedin_url or "", website_url or ""

    insert_data: dict[str, Any] = {
        "name": full_name,
        "tenant_id": tenant_id,
        "creator_id": creator_ids[0],
        "description": short_intro or f"{full_name}'s persona",
        "status": "active",
        "settings": {
            "owner_user_id": user_id,
            "owner_email": email,
            "creation_mode": "onboarding",
            "public_profile": {**public_profile, "theme_id": default_theme_id},
            "persona_profile": persona_profile,
            "persona_quality": "basic",
            "enrichment_status": "not_queued",
            "onboarding_completed_at": _utc_now_iso(),
            # public_share_enabled stays False until the worker flips it after enrichment
            # completes (training_jobs.py:231) or until the user toggles visibility.
            "widget_settings": {"public_share_enabled": False},
            "auto_create_state": initial_auto_state,
            # Default ON for new signups (founder decision 2026-07-03, see
            # routers/auto_create.py insert_data): the Page pillar's core
            # differentiator (visitor chats -> shares contact -> owner
            # notified) was silently opt-in and 0/27 live personas had ever
            # enabled it. This is the live /onboarding/persona creation path
            # (auto_create_twin is not currently called by the frontend) so
            # the default must live here too. Owners can still turn it off
            # in dashboard/widget/settings.
            "lead_capture_enabled": True,
        },
    }

    while True:
        try:
            response = sb.table("twins").insert(insert_data).execute()
            break
        except Exception as exc:
            message = str(exc).lower()
            if "duplicate" in message or "unique" in message or "23505" in message:
                race_winner = _fetch_profile_twin(user)
                if race_winner:
                    settings = dict(race_winner.get("settings") or {})
                    handle = str(settings.get("handle") or "").strip() or _resolve_handle(full_name, str(race_winner["id"]), tenant_id)
                    settings["handle"] = handle
                    _update_twin_settings(str(race_winner["id"]), tenant_id, settings)
                    return race_winner, linkedin_url or "", website_url or ""
            stripped = None
            for column in ("status", "creation_mode"):
                if column in insert_data and "column" in message and column in message:
                    stripped = column
                    break
            if stripped:
                insert_data.pop(stripped, None)
                continue
            raise

    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to create persona.")

    twin = response.data[0]
    twin_id = str(twin["id"])
    settings = dict(twin.get("settings") or insert_data["settings"])
    handle = _resolve_handle(full_name, twin_id, tenant_id)
    settings["handle"] = handle
    _update_twin_settings(twin_id, tenant_id, settings)
    return {**twin, "settings": settings}, linkedin_url or "", website_url or ""


def _queue_website_import(twin_id: str, website_url: str) -> bool:
    if not website_url:
        return False
    try:
        import uuid

        from modules.training_jobs import create_training_job

        sb = get_supabase_client()
        source_id = str(uuid.uuid4())
        sb.table("sources").insert({
            "id": source_id,
            "twin_id": twin_id,
            "filename": "Website Import",
            "content_text": "",
            "extracted_text_length": 0,
            "status": "pending",
            "last_step": "queued",
            "health_status": "healthy",
            "last_provider": "web",
            "citation_url": website_url,
        }).execute()
        create_training_job(
            source_id=source_id,
            twin_id=twin_id,
            job_type="ingestion",
            priority=4,
            metadata={"provider": "web", "url": website_url},
        )
        return True
    except Exception as exc:
        logger.warning("[Onboarding] website import queue failed (non-fatal): %s", exc)
        return False


def _queue_enrichment(twin: dict[str, Any], name: str, headline: str, linkedin_url: str, website_url: str, tenant_id: str) -> str:
    """Queue Firecrawl + website enrichment jobs for a freshly-created persona.

    Idempotent: if the twin's enrichment_status is already 'queued' or 'completed',
    skip re-enqueuing so a user clicking submit twice (or a retry) doesn't duplicate
    Firecrawl jobs and burn quota. Returns the resulting enrichment_status.
    """
    settings = dict(twin.get("settings") or {})
    current_status = str(settings.get("enrichment_status") or "").strip().lower()
    if current_status in ("queued", "completed"):
        # Idempotency: enrichment is already in flight or done. Don't re-queue.
        logger.info(
            "[Onboarding] enrichment already %s for twin %s — skipping re-enqueue",
            current_status, twin.get("id"),
        )
        return current_status

    queued_any = False
    # Always enqueue profile enrichment with whatever info is available.
    # extract_profile handles linkedin_url=None by searching by name+context alone.
    try:
        _enqueue_enrichment(
            twin_id=str(twin["id"]),
            name=name,
            context=headline,
            linkedin_url=linkedin_url or None,
            linkedin_snapshot={},
            tenant_id=tenant_id,
        )
        queued_any = True
    except Exception as exc:
        logger.warning("[Onboarding] profile enrichment queue failed (non-fatal): %s", exc)

    if _queue_website_import(str(twin["id"]), website_url):
        queued_any = True

    if not queued_any:
        return "not_queued"

    settings["enrichment_status"] = "queued"
    settings["persona_quality"] = "enhancing"
    _update_twin_settings(str(twin["id"]), tenant_id, settings)
    twin["settings"] = settings
    return "queued"


@router.get("/status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(user: dict[str, Any] = Depends(require_tenant)) -> OnboardingStatusResponse:
    user_id = str(user["user_id"])
    consent = _consent_state(user_id)
    twin = _fetch_profile_twin(user)
    has_persona = bool(twin)
    # Consent only blocks the flow when the env-level gate is enabled.
    consent_required = _consent_gate_enabled() and not consent.accepted
    if consent_required:
        next_route = "/legal/accept"
    elif has_persona:
        next_route = "/dashboard"
    else:
        next_route = "/onboarding"
    return OnboardingStatusResponse(
        consent_required=consent_required,
        consent=consent,
        has_persona=has_persona,
        persona=_persona_summary(twin),
        next_route=next_route,
    )


@router.post("/consent", response_model=ConsentState)
async def accept_onboarding_consent(
    payload: ConsentAcceptRequest,
    request: Request,
    user: dict[str, Any] = Depends(require_tenant),
) -> ConsentState:
    if not payload.accepted:
        raise HTTPException(status_code=400, detail="Consent must be accepted to continue.")

    user_id = str(user["user_id"])
    existing = _get_pending_consent(user_id)
    if existing:
        return _consent_state(user_id)

    sb = get_supabase_client()
    accepted_at = _utc_now_iso()
    record = {
        "user_id": user_id,
        "terms_version": PENDING_LEGAL_VERSION,
        "privacy_version": PENDING_LEGAL_VERSION,
        "consent_text": PENDING_CONSENT_TEXT,
        "accepted_at": accepted_at,
        "ip_address": _client_ip(request),
        "user_agent": request.headers.get("user-agent"),
        "auth_provider": _auth_provider(user),
    }
    try:
        sb.table("user_agreements").insert(record).execute()
    except Exception as exc:
        message = str(exc).lower()
        if "user_agreements" in message and ("could not find" in message or "pgrst205" in message):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Consent storage is not ready. Apply the user_agreements migration before enabling onboarding.",
            ) from exc
        if "duplicate" not in message and "unique" not in message and "23505" not in message:
            raise
    return _consent_state(user_id)


@router.post("/persona", response_model=CreatePersonaResponse)
async def create_onboarding_persona(
    payload: CreatePersonaRequest,
    user: dict[str, Any] = Depends(require_tenant),
) -> CreatePersonaResponse:
    user_id = str(user["user_id"])
    tenant_id = str(user["tenant_id"])
    _require_pending_consent(user_id)
    existing_twin = _fetch_profile_twin(user)

    # Rate limit: 3 persona-creation calls per hour per user. Skip the check
    # on idempotent retries so refresh / double-submit / reload doesn't 429
    # legitimate users — only "would-actually-run-Firecrawl" attempts count.
    if not _is_idempotent_from_twin(existing_twin):
        if not _check_persona_create_rate_limit(user_id):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "PERSONA_CREATE_RATE_LIMITED",
                    "message": "Too many persona creation attempts. Try again in an hour.",
                },
            )

    linkedin_snapshot, provider_user_id = _extract_linkedin_snapshot(user_id, user)
    twin, linkedin_url, website_url = _create_or_update_persona(
        request=payload,
        user=user,
        linkedin_snapshot=linkedin_snapshot,
        provider_user_id=provider_user_id,
        prefetched_twin=existing_twin,
    )
    settings = dict(twin.get("settings") or {})
    handle = str(settings.get("handle") or "").strip()
    if not handle:
        handle = _resolve_handle(payload.full_name, str(twin["id"]), tenant_id)
        settings["handle"] = handle
        _update_twin_settings(str(twin["id"]), tenant_id, settings)

    enrichment_status = _queue_enrichment(
        twin,
        name=str(settings.get("public_profile", {}).get("display_name") or payload.full_name),
        headline=payload.headline,
        linkedin_url=linkedin_url,
        website_url=website_url,
        tenant_id=tenant_id,
    )
    settings = dict(twin.get("settings") or settings)
    # Generate the share_token so /p/{handle} can resolve once the worker
    # publishes the persona, but DO NOT flip widget_settings.public_share_enabled
    # here — that's the entire point of Phase 1.3. ensure_share_token with
    # enable_public_share=True would set public_share_enabled=True (see
    # backend/modules/share_links.py:122-123), reintroducing the empty-public-
    # persona window. The training_jobs.profile_enrichment worker is responsible
    # for flipping the flag after Pinecone upsert completes.
    ensure_share_token(
        str(twin["id"]),
        enable_public_share=False,
        twin_row={**twin, "settings": settings},
        tenant_id=tenant_id,
    )

    return CreatePersonaResponse(
        twin_id=str(twin["id"]),
        handle=handle,
        public_url=f"/p/{handle}",
        persona_quality=str(settings.get("persona_quality") or "basic"),
        enrichment_status=enrichment_status if enrichment_status != "not_queued" else str(settings.get("enrichment_status") or "not_queued"),
    )
