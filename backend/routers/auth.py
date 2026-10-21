import logging
import os
import time as _time_module
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)
import contextlib

from supabase import create_client as create_supabase_client
from supabase_auth.errors import AuthApiError

from modules.api_keys import (
    create_api_key,
    list_api_keys,
    revoke_api_key,
    update_api_key,
)
from modules.auth_guard import (
    ensure_twin_active,
    get_current_user,
    require_tenant,
    resolve_tenant_id,
    verify_owner,
)
from modules.observability import supabase
from modules.posthog_analytics import ph_capture, ph_identify
from modules.profile_selection import (
    build_creator_candidates,
    select_profile_twin_from_rows,
)
from modules.profile_utils import (
    is_synthesized_linkedin_url,
    normalize_linkedin_profile_url,
    normalize_social_links,
    select_best_linkedin_account,
    user_has_linkedin_provider,
)
from modules.runtime_kill_switches import signups_enabled
from modules.schemas import (
    ApiKeyCreateRequest,
    ApiKeyUpdateRequest,
    UserInvitationCreateRequest,
)
from modules.share_links import (
    get_share_link_info,
    regenerate_share_token,
    toggle_public_sharing,
)
from modules.user_management import (
    accept_invitation,
    delete_user,
    invite_user,
    list_users,
)

router = APIRouter(tags=["auth"])


def _require_auth_user(user: Any) -> dict[str, Any]:
    if not isinstance(user, dict) or not user.get("user_id"):
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _model_to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _select_profile_twin_for_user(
    *,
    user: dict[str, Any],
    tenant_id: str,
    twins: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """
    Select canonical single profile twin for a user inside tenant.
    """
    user_id = user.get("user_id")
    creator_candidates = build_creator_candidates(
        user=user,
        user_id=str(user_id or ""),
        tenant_id=str(tenant_id or ""),
    )

    rows = twins
    if rows is None:
        query = (
            supabase.table("twins")
            .select("*")
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
        )
        if hasattr(query, "limit"):
            query = query.limit(50)
        result = query.execute()
        rows = result.data if result.data else []

    return select_profile_twin_from_rows(
        rows=rows or [],
        user_id=str(user_id or ""),
        creator_candidates=creator_candidates,
        allow_single_legacy_fallback=True,
    )


_anon_supabase_client = None

def _get_anon_supabase_client():
    global _anon_supabase_client
    if _anon_supabase_client is None:
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_anon_key = os.getenv("SUPABASE_KEY")
        if not supabase_url or not supabase_anon_key:
            raise HTTPException(status_code=503, detail="Supabase auth client not configured")
        _anon_supabase_client = create_supabase_client(supabase_url, supabase_anon_key)
    return _anon_supabase_client

# ============================================================================
# User Registration & Profile
# ============================================================================

class UserProfile(BaseModel):
    id: str
    email: str
    full_name: str | None = None
    avatar_url: str | None = None
    tenant_id: str | None = None
    onboarding_completed: bool = False
    dashboard_walkthrough_completed_at: str | None = None
    created_at: str | None = None

class SyncUserResponse(BaseModel):
    status: str  # 'created' or 'exists'
    user: UserProfile
    needs_onboarding: bool = False
    twin_count: int = 0


class DashboardWalkthroughStatusResponse(BaseModel):
    completed_at: str | None = None


class DashboardWalkthroughCompleteResponse(BaseModel):
    completed_at: str


class InvitationValidationResponse(BaseModel):
    email: str
    role: str
    expires_at: str | None = None
    status: str = "pending"
    invited_by: str | None = None
    tenant_id: str | None = None


class AcceptInvitationRequest(BaseModel):
    token: str
    password: str
    name: str | None = None


class AcceptInvitationResponse(BaseModel):
    status: str
    user: dict[str, Any]
    token: str | None = None
    session: dict[str, Any] | None = None


def _fetch_invitation_record(token: str) -> dict[str, Any] | None:
    token = str(token or "").strip()
    if not token:
        return None
    try:
        response = (
            supabase.table("user_invitations")
            .select("id, tenant_id, email, role, invited_by, status, expires_at")
            .eq("invitation_token", token)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]
    except Exception:
        return None


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


def _require_pending_invitation_or_raise(token: str) -> dict[str, Any]:
    record = _fetch_invitation_record(token)
    if not record:
        raise HTTPException(status_code=404, detail="Invalid invitation token")

    status_value = str(record.get("status") or "").strip().lower()
    if status_value == "accepted":
        raise HTTPException(status_code=409, detail="Invitation already accepted")
    if status_value == "expired":
        raise HTTPException(status_code=410, detail="Invitation has expired")
    if status_value and status_value != "pending":
        raise HTTPException(status_code=400, detail=f"Invitation status '{status_value}' is not valid for this action")

    expires_at_raw = record.get("expires_at")
    expires_at = _parse_iso_datetime(expires_at_raw)
    if expires_at and datetime.now(timezone.utc) > expires_at:
        with contextlib.suppress(Exception):
            supabase.table("user_invitations").update({"status": "expired"}).eq("id", record["id"]).execute()
        raise HTTPException(status_code=410, detail="Invitation has expired")

    return record


def _sync_connected_accounts(user_id: str, correlation_id: str) -> None:
    """
    Upsert connected_accounts from Supabase auth identities (e.g. LinkedIn).
    Best-effort; failures are logged but do not block sync.
    """
    try:
        auth_user = supabase.auth.admin.get_user_by_id(user_id)
        if not auth_user or not hasattr(auth_user, "user"):
            return
        user_obj = _model_to_dict(getattr(auth_user, "user", None))
        existing_rows = (
            supabase.table("connected_accounts")
            .select("id, provider, provider_user_id, profile_snapshot")
            .eq("user_id", user_id)
            .in_("provider", ["linkedin", "linkedin_oidc"])
            .execute()
        )
        existing_accounts = existing_rows.data or []
        identities = user_obj.get("identities") or []
        for ident in identities:
            if not isinstance(ident, dict):
                ident = _model_to_dict(ident) if hasattr(ident, "model_dump") else {}
            provider = (ident.get("provider") or "").strip().lower()
            if provider not in {"linkedin", "linkedin_oidc"}:
                continue
            provider_user_id = ident.get("provider_id") or ident.get("id")
            identity_data = ident.get("identity_data") or {}
            same_provider = next(
                (row for row in existing_accounts if str(row.get("provider") or "").strip().lower() == provider),
                None,
            )
            legacy_provider = next(
                (row for row in existing_accounts if str(row.get("provider") or "").strip().lower() != provider),
                None,
            )
            existing_snapshot = (same_provider or legacy_provider or {}).get("profile_snapshot") or {}

            profile_url = normalize_linkedin_profile_url(
                identity_data.get("profile_url") or identity_data.get("url")
            )
            existing_profile_url = normalize_linkedin_profile_url(existing_snapshot.get("profile_url"))
            if not profile_url and existing_profile_url and not is_synthesized_linkedin_url(existing_profile_url, provider_user_id):
                profile_url = existing_profile_url
            display_name = identity_data.get("name") or identity_data.get("full_name")
            image_url = identity_data.get("picture") or identity_data.get("avatar_url") or identity_data.get("image_url")
            headline = (
                identity_data.get("headline")
                or identity_data.get("title")
                or identity_data.get("position")
            )
            profile_snapshot = {
                **existing_snapshot,
                "profile_url": profile_url,
                "display_name": display_name,
                "first_name": identity_data.get("given_name") or existing_snapshot.get("first_name"),
                "last_name": identity_data.get("family_name") or existing_snapshot.get("last_name"),
                "image_url": image_url,
                "headline": headline,
                "email": identity_data.get("email") or existing_snapshot.get("email"),
                "email_verified": identity_data.get("email_verified", existing_snapshot.get("email_verified")),
                "locale": identity_data.get("locale") or existing_snapshot.get("locale"),
            }

            payload = {
                "user_id": user_id,
                "provider": provider,
                "provider_user_id": provider_user_id,
                "profile_snapshot": profile_snapshot,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if same_provider and same_provider.get("id"):
                supabase.table("connected_accounts").update(payload).eq("id", same_provider["id"]).execute()
            elif legacy_provider and legacy_provider.get("id"):
                supabase.table("connected_accounts").update(payload).eq("id", legacy_provider["id"]).execute()
            else:
                supabase.table("connected_accounts").upsert(
                    payload,
                    on_conflict="user_id,provider",
                ).execute()
            logger.info("[SYNC %s] Upserted connected_accounts for provider=%s", correlation_id, provider)
            break
    except Exception as e:
        logger.warning("[SYNC %s] connected_accounts sync skipped: %s", correlation_id, e)


@router.post("/auth/sync-user", response_model=SyncUserResponse)
async def sync_user(request: Request, response: Response, user=Depends(get_current_user)):
    """
    Sync Supabase auth user to our users table.

    Called after OAuth/magic link login to ensure user exists in our DB.
    Creates user record and default tenant if first login.
    """
    user = _require_auth_user(user)
    correlation_id = request.headers.get("x-correlation-id") or request.headers.get("x-request-id") or "none"
    response.headers["x-correlation-id"] = correlation_id

    logger.info("[SYNC %s] Starting sync for user_id: %s", correlation_id, user.get('user_id'))
    user_id = user.get("user_id")
    email = (user.get("email", "") or "").strip().lower()
    logger.info("[SYNC %s] email: %s", correlation_id, email)

    # Validate email before any DB writes — empty or malformed emails break tenant linking
    import re as _re
    if not email or not _re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid or missing email in auth token. Got: '{email}'"
        )

    # Check if user already exists in our users table
    logger.info("[SYNC %s] Checking if user exists...", correlation_id)
    existing = supabase.table("users").select("*, tenants(id, name)").eq("id", user_id).execute()
    if getattr(existing, "error", None):
        logger.error("[SYNC %s] ERROR user lookup: %s", correlation_id, existing.error)
        raise HTTPException(status_code=503, detail="User sync temporarily unavailable")

    if existing.data and len(existing.data) > 0:
        # User exists - check if they have a tenant
        user_data = existing.data[0]
        tenant_id = user_data.get("tenant_id")

        # Recover tenant mapping if missing.
        if not tenant_id:
            logger.info("[SYNC %s] User exists but has no tenant_id, recovering...", correlation_id)
            try:
                tenant_id = resolve_tenant_id(user_id, email, create_if_missing=True)
                supabase.table("users").upsert({
                    "id": user_id,
                    "email": email,
                    "tenant_id": tenant_id
                }).execute()
                logger.info("[SYNC %s] Recovered tenant %s for existing user", correlation_id, tenant_id)
            except Exception as e:
                logger.error("[SYNC %s] ERROR recovering tenant: %s", correlation_id, e)

        # Backfill full_name / avatar_url from OAuth metadata if columns are NULL.
        # Never overwrite values the user has explicitly set on their own profile.
        oauth_full_name = user.get("name") or user.get("user_metadata", {}).get("full_name")
        oauth_avatar_url = user.get("avatar_url") or user.get("user_metadata", {}).get("avatar_url")
        backfill: dict[str, str] = {}
        if oauth_full_name and not user_data.get("full_name"):
            backfill["full_name"] = oauth_full_name
        if oauth_avatar_url and not user_data.get("avatar_url"):
            backfill["avatar_url"] = oauth_avatar_url
        if backfill:
            try:
                supabase.table("users").update(backfill).eq("id", user_id).execute()
                user_data.update(backfill)
                logger.info(
                    "[SYNC %s] Backfilled identity fields for existing user: %s",
                    correlation_id, list(backfill.keys()),
                )
            except Exception as e:
                logger.warning("[SYNC %s] identity backfill skipped: %s", correlation_id, e)

        # Single-profile mode: onboarding complete only if canonical profile twin exists.
        has_twins = False
        if tenant_id:
            has_twins = _select_profile_twin_for_user(
                user=user,
                tenant_id=tenant_id,
            ) is not None

        _sync_connected_accounts(user_id, correlation_id)

        ph_capture(user_id=user_id, event="user_login", properties={
            "status": "returning",
            "has_twins": has_twins,
            "email": email,
        })

        return SyncUserResponse(
            status="exists",
            user=UserProfile(
                id=user_id,
                email=user_data.get("email", email),
                full_name=user_data.get("full_name"),
                avatar_url=user_data.get("avatar_url"),
                tenant_id=tenant_id,
                onboarding_completed=has_twins,
                dashboard_walkthrough_completed_at=user_data.get("dashboard_walkthrough_completed_at"),
                created_at=user_data.get("created_at")
            ),
            needs_onboarding=not has_twins,
            twin_count=1 if has_twins else 0,
        )

    # First login - create user record
    # Runtime kill-switch (execution-board 0.10 / PRD NFR-3): only gates the
    # NEW-account branch below — existing users above already returned, so
    # login/sync for current users is never affected by this flag.
    if not signups_enabled():
        logger.info("[SYNC %s] New-account creation paused (SIGNUPS_ENABLED=false)", correlation_id)
        raise HTTPException(
            status_code=503,
            detail="Signups are temporarily paused. Please check back soon.",
        )
    logger.info("[SYNC %s] User doesn't exist, creating...", correlation_id)
    # Get additional metadata from the auth token
    full_name = user.get("name") or user.get("user_metadata", {}).get("full_name") or email.split("@")[0]
    avatar_url = user.get("avatar_url") or user.get("user_metadata", {}).get("avatar_url")
    logger.info("[SYNC %s] full_name: %s, avatar_url: %s", correlation_id, full_name, avatar_url)

    # Resolve tenant via canonical resolver.
    logger.info("[SYNC %s] Resolving tenant via canonical resolver...", correlation_id)
    try:
        tenant_id = resolve_tenant_id(user_id, email, create_if_missing=True)
        logger.info("[SYNC %s] Tenant resolved with id: %s", correlation_id, tenant_id)
    except Exception as e:
        logger.error("[SYNC %s] ERROR resolving tenant: %s", correlation_id, e)
        raise

    # Ensure user record exists with the resolved tenant_id.
    # Persist full_name and avatar_url from OAuth metadata so internal tools
    # (admin, billing, lead capture) see real identity instead of NULLs.
    logger.info("[SYNC %s] Upserting user row with tenant_id...", correlation_id)
    user_payload: dict[str, str | None] = {
        "id": user_id,
        "email": email,
        "tenant_id": tenant_id,
    }
    if full_name:
        user_payload["full_name"] = full_name
    if avatar_url:
        user_payload["avatar_url"] = avatar_url
    try:
        user_insert = supabase.table("users").upsert(user_payload).execute()
        if getattr(user_insert, "error", None):
            logger.error("[SYNC %s] ERROR user upsert: %s", correlation_id, user_insert.error)
            raise HTTPException(status_code=503, detail="User creation unavailable")
        logger.info(
            "[SYNC %s] User created successfully with tenant_id (identity_fields=%s)",
            correlation_id,
            [k for k in ("full_name", "avatar_url") if k in user_payload],
        )
    except Exception as e:
        logger.error("[SYNC %s] ERROR creating user: %s", correlation_id, e)
        raise

    has_twins = _select_profile_twin_for_user(
        user=user,
        tenant_id=tenant_id,
    ) is not None

    _sync_connected_accounts(user_id, correlation_id)

    ph_identify(user_id=user_id, properties={
        "email": email,
        "name": full_name,
        "avatar_url": avatar_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    ph_capture(user_id=user_id, event="user_signup", properties={
        "status": "new",
        "has_twins": has_twins,
        "email": email,
    })

    return SyncUserResponse(
        status="created",
        user=UserProfile(
            id=user_id,
            email=email,
            full_name=full_name,
            avatar_url=avatar_url,
            tenant_id=tenant_id,
            onboarding_completed=has_twins,
            dashboard_walkthrough_completed_at=None,
            created_at=datetime.now(timezone.utc).isoformat()
        ),
        needs_onboarding=not has_twins,
        twin_count=1 if has_twins else 0,
    )


@router.get("/auth/whoami")
async def whoami(user=Depends(get_current_user)):
    """
    Debug/instrumentation endpoint: Return resolved user identity.

    Use this to verify auth is working and tenant_id is correctly resolved.
    This endpoint uses resolve_tenant_id to ensure tenant always exists.
    """
    user = _require_auth_user(user)
    user_id = user.get("user_id")
    email = user.get("email", "")

    # Resolve tenant without mutating tenant mappings.
    try:
        tenant_id = resolve_tenant_id(user_id, email, create_if_missing=False)
    except Exception:
        tenant_id = None

    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "email": email,
        "role": user.get("role"),
        "has_tenant": tenant_id is not None,
        "auth_method": "api_key" if user.get("api_key_id") else "jwt"
    }

@router.get("/auth/connected-accounts")
async def get_connected_accounts(user=Depends(get_current_user)):
    """Get current user's OAuth-connected accounts (e.g. LinkedIn)."""
    user = _require_auth_user(user)
    user_id = user.get("user_id")
    try:
        result = supabase.table("connected_accounts").select("*").eq("user_id", user_id).execute()
        return {"accounts": result.data or []}
    except Exception as e:
        logger.warning("[auth] connected_accounts fetch error: %s", e)
        return {"accounts": []}


@router.post("/auth/session-init")
async def session_init(user=Depends(require_tenant)):
    """Bootstrap the onboarding page in a single round-trip.

    Aggregates /onboarding/status + /auth/identity-status + user metadata into
    one call so the onboarding page never needs three sequential HTTP requests.

    Requires the calling user to already exist in the DB (/auth/sync-user must
    have been called at least once, which the OAuth callback handles).
    """
    # Local import avoids a module-level circular dependency.
    from routers.onboarding import (
        _consent_gate_enabled,
        _consent_state,
        _fetch_profile_twin,
    )

    user_id = user.get("user_id")

    # ── Onboarding status ─────────────────────────────────────────────
    consent = _consent_state(user_id)
    twin = _fetch_profile_twin(user)
    has_persona = bool(twin)
    consent_required = _consent_gate_enabled() and not consent.accepted
    if consent_required:
        next_route = "/legal/accept"
    elif has_persona:
        next_route = "/dashboard"
    else:
        next_route = "/onboarding"

    # ── Identity status (LinkedIn) ────────────────────────────────────
    identity: dict = {"verified": False, "provider": None, "display_name": "", "headline": "", "profile_url": "", "image_url": ""}
    if user_has_linkedin_provider(user):
        try:
            result = (
                supabase.table("connected_accounts")
                .select("provider, profile_snapshot, provider_user_id")
                .eq("user_id", user_id)
                .in_("provider", ["linkedin", "linkedin_oidc"])
                .execute()
            )
            best_account = select_best_linkedin_account(result.data or [])
            if best_account:
                snapshot = best_account.get("profile_snapshot") or {}
                profile_url = normalize_linkedin_profile_url(snapshot.get("profile_url"))
                if is_synthesized_linkedin_url(profile_url, best_account.get("provider_user_id")):
                    profile_url = ""
                identity = {
                    "verified": True,
                    "provider": best_account.get("provider"),
                    "display_name": snapshot.get("display_name", ""),
                    "headline": snapshot.get("headline", ""),
                    "profile_url": profile_url or "",
                    "image_url": snapshot.get("image_url", ""),
                }
        except Exception as exc:
            logger.warning("[auth] session-init identity error: %s", exc)

    # ── User metadata from JWT (replaces supabase.auth.getUser() on client) ─
    user_metadata = user.get("user_metadata") or {}

    # Actual Supabase auth provider (google/linkedin_oidc/email) — distinct from
    # `identity.provider` above, which only ever reflects a verified LinkedIn
    # profile used for form pre-fill, not how the user actually authenticated.
    app_metadata = user.get("app_metadata") or {}
    auth_provider = app_metadata.get("provider")

    return {
        "consent_required": consent_required,
        "has_persona": has_persona,
        "next_route": next_route,
        "display_name": user.get("name") or user_metadata.get("full_name") or user_metadata.get("name"),
        "email": user.get("email"),
        "avatar_url": user.get("avatar_url") or user_metadata.get("avatar_url") or user_metadata.get("picture"),
        "identity": identity,
        "auth_provider": auth_provider,
    }


@router.get("/auth/identity-status")
async def get_identity_status(user=Depends(get_current_user)):
    """Check if user has a verified LinkedIn identity for persona creation."""
    user = _require_auth_user(user)
    user_id = user.get("user_id")
    if not user_has_linkedin_provider(user):
        return {"verified": False, "provider": None}
    try:
        result = (
            supabase.table("connected_accounts")
            .select("provider, profile_snapshot, provider_user_id")
            .eq("user_id", user_id)
            .in_("provider", ["linkedin", "linkedin_oidc"])
            .execute()
        )
        best_account = select_best_linkedin_account(result.data or [])
        if best_account:
            snapshot = best_account.get("profile_snapshot") or {}
            profile_url = normalize_linkedin_profile_url(snapshot.get("profile_url"))
            if is_synthesized_linkedin_url(profile_url, best_account.get("provider_user_id")):
                profile_url = ""
            return {
                "verified": True,
                "provider": best_account.get("provider"),
                "display_name": snapshot.get("display_name", ""),
                "headline": snapshot.get("headline", ""),
                "profile_url": profile_url,
                "image_url": snapshot.get("image_url", ""),
            }
        return {"verified": False, "provider": None}
    except Exception as e:
        logger.warning("[auth] identity-status error: %s", e)
        return {"verified": False, "provider": None}


_prefill_cache: dict[str, tuple[float, dict]] = {}  # cache_key → (timestamp, result)
_PREFILL_CACHE_TTL = 3600  # 1 hour
_PREFILL_CACHE_MAX = 500   # evict oldest when exceeded

_prefill_rate_limits: dict[str, list[float]] = defaultdict(list)
_PREFILL_RATE_LIMIT = 5    # calls per window
_PREFILL_RATE_WINDOW = 600  # 10 minutes


def _check_prefill_rate_limit(user_id: str) -> bool:
    now = _time_module.time()
    window_start = now - _PREFILL_RATE_WINDOW
    _prefill_rate_limits[user_id] = [t for t in _prefill_rate_limits[user_id] if t > window_start]
    if len(_prefill_rate_limits[user_id]) >= _PREFILL_RATE_LIMIT:
        return False
    _prefill_rate_limits[user_id].append(now)
    return True


def _prefill_cache_set(key: str, value: dict) -> None:
    if len(_prefill_cache) >= _PREFILL_CACHE_MAX:
        # Evict the oldest entry
        oldest_key = min(_prefill_cache, key=lambda k: _prefill_cache[k][0])
        del _prefill_cache[oldest_key]
    _prefill_cache[key] = (_time_module.time(), value)


class PrefillProfileRequest(BaseModel):
    linkedin_url: str | None = None
    linkedin_token: str | None = None  # LinkedIn OAuth provider_token for instant identityMe prefill


def _call_identity_me(linkedin_token: str) -> dict:
    """Call LinkedIn identityMe and return normalized profile fields (instant, ~1s)."""
    import requests as _req

    def _localized(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            loc = value.get("localized") or {}
            if loc:
                return str(next(iter(loc.values()), "")).strip()
            return str(value.get("value") or "").strip()
        return ""

    try:
        resp = _req.get(
            "https://api.linkedin.com/rest/identityMe",
            headers={"Authorization": f"Bearer {linkedin_token}", "LinkedIn-Version": "202501"},
            timeout=8,
        )
        if not resp.ok:
            logger.warning("[auth] identityMe returned %s", resp.status_code)
            return {}
        body = resp.json()
        basic = body.get("basicInfo") or {}
        first = _localized(basic.get("firstName"))
        last = _localized(basic.get("lastName"))
        display_name = " ".join(p for p in [first, last] if p).strip()
        headline = _localized(basic.get("headline"))
        profile_url = normalize_linkedin_profile_url(basic.get("profileUrl") or "")
        image_url = ""
        pic = basic.get("profilePicture")
        if isinstance(pic, dict):
            image_url = (pic.get("croppedImage") or {}).get("downloadUrl") or ""
        current_pos = body.get("primaryCurrentPosition") or {}
        org = _localized(current_pos.get("companyName"))
        title = _localized(current_pos.get("title"))
        education = body.get("mostRecentEducation") or {}
        school = _localized(education.get("schoolName"))
        degree = _localized(education.get("degreeName"))
        return {
            "display_name": display_name,
            "headline": headline or title,
            "organization": org,
            "job_title": title,
            "profile_url": profile_url,
            "image_url": image_url,
            "education_school": school,
            "education_degree": degree,
        }
    except Exception as exc:
        logger.warning("[auth] identityMe call failed: %s", exc)
        return {}


@router.post("/auth/prefill-profile")
async def prefill_profile_from_linkedin(request: PrefillProfileRequest, user=Depends(get_current_user)):
    """Scrape the user's LinkedIn profile URL via Firecrawl for fast pre-fill.

    Returns structured profile fields (headline, bio, company, job title)
    in ~5-10 seconds. Used during onboarding to populate the "Tell us about
    yourself" form before the full persona build.
    Rate-limited: cached per user for 1 hour to prevent Firecrawl abuse.
    """
    import asyncio
    user = _require_auth_user(user)

    user_id = user.get("user_id")
    if not _check_prefill_rate_limit(user_id):
        raise HTTPException(status_code=429, detail="Too many prefill requests. Please wait a few minutes.")
    requested_url = normalize_linkedin_profile_url(request.linkedin_url)
    if request.linkedin_url and not requested_url:
        raise HTTPException(status_code=400, detail="Please enter a valid LinkedIn profile URL.")

    uid = user.get("user_id", "")
    display_name = (
        user.get("name")
        or (user.get("user_metadata") or {}).get("full_name")
        or user.get("email", "").split("@")[0]
        or ""
    )
    snapshot: dict[str, Any] = {}
    best_account: dict[str, Any] | None = None
    if user_has_linkedin_provider(user):
        result = (
            supabase.table("connected_accounts")
            .select("id, provider, profile_snapshot, provider_user_id")
            .eq("user_id", user_id)
            .in_("provider", ["linkedin", "linkedin_oidc"])
            .execute()
        )
        if result.data:
            best_account = select_best_linkedin_account(result.data or [])
            if best_account:
                snapshot = best_account.get("profile_snapshot") or {}
                display_name = snapshot.get("display_name", "") or display_name

    if not best_account and not requested_url:
        raise HTTPException(status_code=404, detail="No LinkedIn account connected")
    stored_profile_url = normalize_linkedin_profile_url(snapshot.get("profile_url"))
    if best_account and is_synthesized_linkedin_url(stored_profile_url, best_account.get("provider_user_id")):
        stored_profile_url = ""
    profile_url = requested_url or stored_profile_url
    prefill_method = "submitted_linkedin_url" if requested_url else "stored_linkedin_url"
    warnings: list[str] = []

    cache_key = f"{uid}:{profile_url or 'oidc_only'}"
    cached = _prefill_cache.get(cache_key)
    if cached and (_time_module.time() - cached[0]) < _PREFILL_CACHE_TTL:
        return cached[1]

    # ── Fast path: LinkedIn token provided → call identityMe instantly (~1s) ──
    # Also enqueue a background Firecrawl job so the rich full_profile is ready
    # by the time the user finishes the remaining onboarding steps.
    if request.linkedin_token:
        identity_me = _call_identity_me(request.linkedin_token)
        if identity_me.get("display_name"):
            display_name = identity_me["display_name"]
        resolved_profile_url = identity_me.get("profile_url") or profile_url or ""
        resolved_headline = identity_me.get("headline") or snapshot.get("headline", "")
        resolved_org = identity_me.get("organization", "")
        resolved_image = identity_me.get("image_url") or snapshot.get("image_url", "")

        # Enqueue background Firecrawl extraction — worker picks it up immediately.
        # Result stored in job payload['extraction_result'] once complete.
        extraction_id: str | None = None
        try:
            from modules.graph_outbox import GraphOperationType, GraphOutbox
            tenant_id = str(user.get("tenant_id") or uid)
            context_parts = []
            if resolved_headline:
                context_parts.append(resolved_headline)
            if resolved_profile_url:
                context_parts.append(f"LinkedIn: {resolved_profile_url}")
            outbox = GraphOutbox()
            extraction_id = str(outbox.submit(
                tenant_id=tenant_id,
                twin_id=uid,  # no twin yet — use user_id as scope key
                operation=GraphOperationType.FIRECRAWL_EXTRACT,
                idempotency_key=f"firecrawl_extract:{uid}:{profile_url or display_name}",
                payload={
                    "person_name": display_name,
                    "context": ", ".join(context_parts) or None,
                    "linkedin_url": resolved_profile_url,
                    "user_id": uid,
                },
                priority=2,  # higher priority than enrichment
            ))
        except Exception as exc:
            logger.warning("[auth] failed to enqueue firecrawl_extract job: %s", exc)

        response_payload = {
            "name": display_name,
            "headline": resolved_headline,
            "bio": "",
            "organization": resolved_org,
            "job_title": identity_me.get("job_title", ""),
            "image_url": resolved_image,
            "source": "identity_me",
            "prefill_method": "linkedin_token",
            "matched_profile_url": resolved_profile_url,
            "warnings": [],
            "extraction_id": extraction_id,
            "extraction_status": "pending" if extraction_id else "unavailable",
        }
        _prefill_cache_set(cache_key, response_payload)
        return response_payload

    if requested_url and requested_url != stored_profile_url and best_account and best_account.get("id"):
        updated_snapshot = {**snapshot, "profile_url": requested_url}
        try:
            supabase.table("connected_accounts").update(
                {
                    "profile_snapshot": updated_snapshot,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            ).eq("id", best_account["id"]).execute()
        except Exception as exc:
            logger.warning("[auth] failed to persist confirmed LinkedIn URL: %s", exc)

    if not profile_url:
        # No LinkedIn URL — try name-based Firecrawl agent search as fallback
        if display_name:
            try:
                import re as _re
                # Strip HTML and prompt-injection patterns before sending to Firecrawl
                safe_name = _re.sub(r"<[^>]+>", "", display_name.strip())[:120]
                _injection_patterns = ["ignore previous", "system prompt", "you are now", "act as"]
                if any(p in safe_name.lower() for p in _injection_patterns):
                    safe_name = ""
                if not safe_name:
                    raise ValueError("display_name failed sanitization")
                from adk_core.services.firecrawl_service import extract_profile
                context = snapshot.get("headline") or None
                extracted = await asyncio.wait_for(
                    asyncio.to_thread(extract_profile, safe_name, context),
                    timeout=30,
                )
                work_exp = extracted.get("work_experience") or []
                first_company = (
                    work_exp[0].get("company", "") if work_exp and isinstance(work_exp[0], dict) else ""
                )
                response_payload = {
                    "name": display_name,
                    "headline": extracted.get("short_description") or snapshot.get("headline", ""),
                    "bio": extracted.get("short_description", ""),
                    "organization": first_company,
                    "job_title": extracted.get("occupation", ""),
                    "image_url": snapshot.get("image_url", ""),
                    "source": "firecrawl_name_search",
                    "prefill_method": "name_search",
                    "matched_profile_url": "",
                    "warnings": warnings,
                }
                _prefill_cache_set(cache_key, response_payload)
                return response_payload
            except Exception as exc:
                logger.warning("[auth] prefill name-search fallback failed: %s", exc)
                warnings.append("Could not automatically find your profile. Fill in the details below.")

        response_payload = {
            "name": display_name,
            "headline": snapshot.get("headline", ""),
            "bio": "",
            "organization": "",
            "job_title": "",
            "image_url": snapshot.get("image_url", ""),
            "source": "oidc_only",
            "prefill_method": "oidc_only",
            "matched_profile_url": "",
            "warnings": warnings,
        }
        _prefill_cache_set(cache_key, response_payload)
        return response_payload

    # Use Firecrawl agent to extract profile (handles LinkedIn login wall via agent browsing)
    try:
        import re as _re
        safe_name = _re.sub(r"<[^>]+>", "", display_name.strip())[:120]
        _injection_patterns = ["ignore previous", "system prompt", "you are now", "act as"]
        if any(p in safe_name.lower() for p in _injection_patterns):
            safe_name = display_name.split("@")[0][:120]
        if not safe_name:
            raise ValueError("display_name failed sanitization")

        from adk_core.services.firecrawl_service import extract_profile
        context_parts = []
        if snapshot.get("headline"):
            context_parts.append(snapshot["headline"])
        context = ", ".join(context_parts) or None

        extracted = await asyncio.wait_for(
            asyncio.to_thread(extract_profile, safe_name, context, profile_url or None),
            timeout=45,
        )

        work_exp = extracted.get("work_experience") or []
        first_work = work_exp[0] if work_exp and isinstance(work_exp[0], dict) else {}
        first_company = first_work.get("company", "")
        first_role = first_work.get("role", "")

        job_title = extracted.get("occupation", "") or first_role
        bio = extracted.get("short_description", "")
        headline = snapshot.get("headline", "") or job_title
        social_links: dict[str, str] = extracted.get("social_links") or {}

        response_payload = {
            "name": display_name,
            "headline": headline,
            "bio": bio,
            "organization": first_company,
            "job_title": job_title,
            "image_url": snapshot.get("image_url", ""),
            "social_links": normalize_social_links(social_links),
            "source": "firecrawl_agent",
            "prefill_method": prefill_method,
            "matched_profile_url": profile_url,
            "warnings": warnings,
            # Full Firecrawl extraction — preserved for twin creation + Pinecone vectorization
            "full_profile": {
                "education": extracted.get("education", []),
                "work_experience": extracted.get("work_experience", []),
                "personality_traits": extracted.get("personality_traits", []),
                "speaking_style": extracted.get("speaking_style"),
                "key_achievements": extracted.get("key_achievements", []),
                "areas_of_expertise": extracted.get("areas_of_expertise", []),
                "contributions": extracted.get("contributions", []),
                "nationality": extracted.get("nationality"),
            },
        }
        _prefill_cache_set(cache_key, response_payload)
        return response_payload
    except Exception as exc:
        logger.warning("[auth] prefill agent extraction failed: %s", exc)
        warnings.append("LinkedIn could not be scraped. Review the prefilled details manually.")
        response_payload = {
            "name": display_name,
            "headline": snapshot.get("headline", ""),
            "bio": "",
            "organization": "",
            "job_title": "",
            "image_url": snapshot.get("image_url", ""),
            "source": "oidc_fallback",
            "prefill_method": "oidc_fallback",
            "matched_profile_url": profile_url,
            "warnings": warnings,
        }
        _prefill_cache_set(cache_key, response_payload)
        return response_payload


@router.get("/auth/extraction/{extraction_id}")
async def get_extraction_status(extraction_id: str, user=Depends(get_current_user)):
    """Poll for the result of a background Firecrawl extraction job.

    Returns:
        { status: "pending"|"completed"|"failed", full_profile: {...} }

    Frontend polls this every 3s after /auth/prefill-profile returns an extraction_id.
    When status == "completed", full_profile contains the rich Firecrawl data.
    """
    user = _require_auth_user(user)
    uid = user.get("user_id", "")

    try:
        result = (
            supabase.table("graph_outbox")
            .select("id, status, payload, error_message")
            .eq("id", extraction_id)
            .single()
            .execute()
        )
    except Exception as exc:
        logger.warning("[auth] extraction status lookup failed: %s", exc)
        raise HTTPException(status_code=404, detail="Extraction job not found")

    if not result.data:
        raise HTTPException(status_code=404, detail="Extraction job not found")

    job = result.data
    # Security: verify the job belongs to this user (payload.user_id)
    job_payload = job.get("payload") or {}
    if str(job_payload.get("user_id") or "") != uid:
        raise HTTPException(status_code=403, detail="Not your extraction job")

    status = str(job.get("status") or "pending")
    if status == "completed":
        extracted = job_payload.get("extraction_result") or {}
        if not extracted:
            return {"status": "completed", "full_profile": None}

        work_exp = extracted.get("work_experience") or []
        first_work = work_exp[0] if work_exp and isinstance(work_exp[0], dict) else {}

        full_profile = {
            "education": extracted.get("education", []),
            "work_experience": work_exp,
            "personality_traits": extracted.get("personality_traits", []),
            "speaking_style": extracted.get("speaking_style"),
            "key_achievements": extracted.get("key_achievements", []),
            "areas_of_expertise": extracted.get("areas_of_expertise", []),
            "contributions": extracted.get("contributions", []),
            "nationality": extracted.get("nationality"),
        }
        return {
            "status": "completed",
            "full_profile": full_profile,
            "bio": extracted.get("short_description", ""),
            "organization": first_work.get("company", ""),
            "job_title": extracted.get("occupation", ""),
            "social_links": extracted.get("social_links") or {},
        }

    if status == "failed":
        return {"status": "failed", "full_profile": None, "error": job.get("error_message")}

    return {"status": "pending", "full_profile": None}


@router.get("/auth/me", response_model=UserProfile)
async def get_current_user_profile(user=Depends(get_current_user)):
    """Get current user's profile including tenant and onboarding status."""
    user = _require_auth_user(user)
    user_id = user.get("user_id")

    # Get user with tenant
    result = supabase.table("users").select("*, tenants(id, name)").eq("id", user_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="User profile not found. Please call /auth/sync-user first.")

    user_data = result.data[0]
    tenant_id = None
    if user_data.get("tenants"):
        tenant_id = user_data["tenants"].get("id") if isinstance(user_data["tenants"], dict) else None

    # Single-profile mode: onboarding complete only if canonical profile twin exists.
    has_twins = False
    if tenant_id:
        has_twins = _select_profile_twin_for_user(
            user=user,
            tenant_id=tenant_id,
        ) is not None

    return UserProfile(
        id=user_id,
        email=user_data.get("email", ""),
        full_name=user_data.get("full_name"),
        avatar_url=user_data.get("avatar_url"),
        tenant_id=tenant_id,
        onboarding_completed=has_twins,
        dashboard_walkthrough_completed_at=user_data.get("dashboard_walkthrough_completed_at"),
        created_at=user_data.get("created_at")
    )


@router.get("/auth/dashboard-walkthrough", response_model=DashboardWalkthroughStatusResponse)
async def get_dashboard_walkthrough_status(user=Depends(get_current_user)):
    """Return whether the current user has dismissed the dashboard tour."""
    user = _require_auth_user(user)
    user_id = user.get("user_id")

    result = (
        supabase.table("users")
        .select("dashboard_walkthrough_completed_at")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    completed_at = (result.data or {}).get("dashboard_walkthrough_completed_at")
    return DashboardWalkthroughStatusResponse(completed_at=completed_at)


@router.post("/auth/dashboard-walkthrough/complete", response_model=DashboardWalkthroughCompleteResponse)
async def complete_dashboard_walkthrough(user=Depends(get_current_user)):
    """Persist dashboard tour completion/dismissal at account level."""
    user = _require_auth_user(user)
    user_id = user.get("user_id")
    completed_at = datetime.now(timezone.utc).isoformat()

    try:
        (
            supabase.table("users")
            .update({"dashboard_walkthrough_completed_at": completed_at})
            .eq("id", user_id)
            .execute()
        )
    except Exception:
        logger.exception("[dashboard-walkthrough] completion update failed user_id=%s", user_id)
        raise HTTPException(status_code=503, detail="Unable to save dashboard walkthrough status")

    return DashboardWalkthroughCompleteResponse(completed_at=completed_at)

@router.get("/auth/my-twins")
async def get_my_twins(user=Depends(get_current_user)):
    """
    Get all twins owned by the current user.

    Uses resolve_tenant_id to ensure tenant is always resolved,
    auto-creating if necessary. Also includes auto-repair for orphaned twins.
    """
    user = _require_auth_user(user)
    user_id = user.get("user_id")
    email = user.get("email", "")

    # Resolve tenant, auto-creating if necessary to prevent 403 for new users
    try:
        tenant_id = resolve_tenant_id(user_id, email, create_if_missing=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[AUTH] ERROR resolving tenant for user %s: %s", user_id, e)
        raise HTTPException(status_code=503, detail="Unable to resolve tenant for this user")

    logger.info("[AUTH] get_my_twins: user=%s, tenant=%s", user_id, tenant_id)

    # Query twins by tenant_id (bounded) and rank for current user first.
    twins_query = (
        supabase.table("twins")
        .select("*")
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True)
    )
    # Some query adapters used in tests/legacy integrations do not expose limit().
    if hasattr(twins_query, "limit"):
        twins_query = twins_query.limit(50)
    result = twins_query.execute()
    twins = result.data if result.data else []

    # NOTE: orphaned-twin repair is intentionally NOT performed in this read API.
    # Use backend/scripts/check_orphaned_twins.py and explicit migration scripts for repair.

    # Single-profile mode: return canonical twin only.
    canonical = _select_profile_twin_for_user(
        user=user,
        tenant_id=tenant_id,
        twins=twins,
    )
    if not canonical:
        logger.debug("[MY-TWINS DEBUG] Returning 0 twins for tenant %s", tenant_id)
        return []

    logger.debug("[MY-TWINS DEBUG] Returning canonical twin %s for tenant %s", canonical.get('id'), tenant_id)
    return [canonical]


@router.get("/connectors")
async def get_connectors(user=Depends(get_current_user)):
    """
    Stub endpoint for connectors to stop 404 logging noise.
    Future: Will return active integrations for the tenant.
    """
    return []


# API Keys (legacy twin-scoped endpoints)
# NOTE: Canonical tenant-scoped API key endpoints live in routers/api_keys.py under /api-keys.
# These auth-scoped routes are retained for backward compatibility without path collisions.
@router.post("/auth/api-keys")
async def create_api_key_endpoint(request: ApiKeyCreateRequest, user=Depends(verify_owner)):
    """Create a new API key for a twin"""
    try:
        return create_api_key(
            twin_id=request.twin_id,
            group_id=request.group_id,
            name=request.name,
            allowed_domains=request.allowed_domains
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/auth/api-keys")
async def list_api_keys_endpoint(twin_id: str, user=Depends(verify_owner)):
    """List all API keys for a twin"""
    return list_api_keys(twin_id)

@router.delete("/auth/api-keys/{key_id}")
async def revoke_api_key_endpoint(key_id: str, user=Depends(verify_owner)):
    """Revoke an API key"""
    success = revoke_api_key(key_id)
    if not success:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"status": "success"}

@router.patch("/auth/api-keys/{key_id}")
async def update_api_key_endpoint(key_id: str, request: ApiKeyUpdateRequest, user=Depends(verify_owner)):
    """Update API key metadata"""
    success = update_api_key(
        key_id=key_id,
        name=request.name,
        allowed_domains=request.allowed_domains
    )
    if not success:
        raise HTTPException(status_code=404, detail="API key not found or no changes")
    return {"status": "success"}

# Sharing
@router.get("/twins/{twin_id}/share-link")
async def get_share_link_endpoint(twin_id: str, user=Depends(verify_owner)):
    """Get share link info for a twin"""
    try:
        ensure_twin_active(twin_id)
        return get_share_link_info(twin_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/twins/{twin_id}/share-link")
async def generate_share_link_endpoint(twin_id: str, user=Depends(verify_owner)):
    """Regenerate share token for a twin"""
    try:
        ensure_twin_active(twin_id)
        _ = regenerate_share_token(twin_id, tenant_id=user.get("tenant_id", ""))
        return get_share_link_info(twin_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.patch("/twins/{twin_id}/sharing")
async def toggle_sharing_endpoint(twin_id: str, request: dict, user=Depends(verify_owner)):
    """Enable or disable public sharing"""
    ensure_twin_active(twin_id)
    enabled = request.get("is_public", False)
    success = toggle_public_sharing(twin_id, enabled, tenant_id=user.get("tenant_id", ""))
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update sharing settings")
    return {"status": "success", "is_public": enabled}

# Users & Invitations
@router.get("/users")
async def list_users_endpoint(user=Depends(verify_owner)):
    """List all users in the tenant"""
    tenant_id = user.get("tenant_id")
    return list_users(tenant_id)

@router.post("/users/invite")
async def invite_user_endpoint(request: UserInvitationCreateRequest, user=Depends(verify_owner)):
    """Invite a new user to the tenant"""
    tenant_id = user.get("tenant_id")
    invited_by = user.get("user_id")
    try:
        return invite_user(tenant_id, request.email, request.role, invited_by)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/users/{user_id}")
async def delete_user_endpoint(user_id: str, user=Depends(verify_owner)):
    """Delete a user from the tenant"""
    deleted_by = user.get("user_id")
    if user_id == deleted_by:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    _ = delete_user(user_id, deleted_by)
    return {"status": "success"}


@router.get("/auth/invitation/{token}", response_model=InvitationValidationResponse)
async def validate_invitation_endpoint(token: str):
    """Validate a pending invitation token."""
    invitation = _require_pending_invitation_or_raise(token)
    return InvitationValidationResponse(
        email=invitation["email"],
        role=invitation["role"],
        expires_at=invitation.get("expires_at"),
        status="pending",
        invited_by=invitation.get("invited_by"),
        tenant_id=invitation.get("tenant_id"),
    )


@router.post("/auth/accept-invitation", response_model=AcceptInvitationResponse)
async def accept_invitation_endpoint(request: AcceptInvitationRequest):
    """Accept invitation token and create user in tenant."""
    if not request.token or not request.token.strip():
        raise HTTPException(status_code=400, detail="Invitation token is required")
    if not request.password or not request.password.strip():
        raise HTTPException(status_code=400, detail="Password is required")

    invitation = _require_pending_invitation_or_raise(request.token)
    invited_email = invitation.get("email")
    if not invited_email:
        raise HTTPException(status_code=400, detail="Invitation is missing email")
    full_name = (request.name or invited_email.split("@")[0]).strip()

    auth_user_id: str | None = None
    try:
        # Create auth identity for invited user when not present yet.
        try:
            created_auth_user = supabase.auth.admin.create_user({
                "email": invited_email,
                "password": request.password,
                "email_confirm": True,
                "user_metadata": {"full_name": full_name},
            })
            created_user_payload = _model_to_dict(getattr(created_auth_user, "user", None))
            auth_user_id = created_user_payload.get("id")
        except AuthApiError as create_err:
            err_text = str(create_err).lower()
            if "already" not in err_text and "registered" not in err_text and "exists" not in err_text:
                raise HTTPException(status_code=400, detail=str(create_err))

        # Sign in with anon client to mint a real browser session.
        anon_supabase = _get_anon_supabase_client()
        auth_response = anon_supabase.auth.sign_in_with_password({
            "email": invited_email,
            "password": request.password,
        })
        auth_response_payload = _model_to_dict(auth_response)
        session_payload = _model_to_dict(getattr(auth_response, "session", None)) or auth_response_payload.get("session", {})
        signed_in_user_payload = _model_to_dict(getattr(auth_response, "user", None)) or auth_response_payload.get("user", {})

        access_token = session_payload.get("access_token")
        refresh_token = session_payload.get("refresh_token")
        if not access_token or not refresh_token:
            raise HTTPException(status_code=500, detail="Failed to create authenticated session")

        auth_user_id = auth_user_id or signed_in_user_payload.get("id")
        created_user = accept_invitation(
            request.token,
            {"password": request.password, "name": full_name},
            auth_user_id=auth_user_id,
        )
        return AcceptInvitationResponse(
            status="success",
            user=created_user,
            token=access_token,
            session={
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": session_payload.get("expires_in"),
                "expires_at": session_payload.get("expires_at"),
                "token_type": session_payload.get("token_type", "bearer"),
            },
        )
    except AuthApiError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        detail = str(e)
        lowered = detail.lower()
        if "already exists" in lowered:
            raise HTTPException(status_code=409, detail=detail)
        if "expired" in lowered:
            raise HTTPException(status_code=410, detail=detail)
        if "invalid" in lowered:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Public Validation
@router.get("/public/validate-share/{twin_id}/{token}")
async def validate_share_token_endpoint(twin_id: str, token: str):
    """Validate a public share token and return twin info"""
    from modules.public_profile_pack import (
        build_public_profile_pack,
        redact_public_profile_pack_for_public_response,
    )
    from modules.share_links import validate_share_token

    if not validate_share_token(token, twin_id):
        raise HTTPException(status_code=404, detail="Invalid or expired share link")

    payload = {
        "valid": True,
        "twin_id": twin_id,
        "twin_name": "AI Assistant",
    }

    try:
        twin_response = (
            supabase.table("twins")
            .select("id, name, settings, status, created_at, updated_at")
            .eq("id", twin_id)
            .single()
            .execute()
        )
        if twin_response.data:
            profile_pack = redact_public_profile_pack_for_public_response(
                build_public_profile_pack(twin_response.data),
                twin_response.data.get("settings") if isinstance(twin_response.data, dict) else {},
            )
            payload.update(profile_pack)
            payload["twin_name"] = profile_pack.get("name") or twin_response.data.get("name") or "AI Assistant"
    except Exception:
        pass

    return payload


# ============================================================================
# Account Deletion
# ============================================================================

class DeleteAccountRequest(BaseModel):
    """Request body for account deletion."""
    confirmation: str  # Must be "DELETE" or the user's email


class DeleteAccountResponse(BaseModel):
    """Response for account deletion."""
    status: str  # "deleted" | "queued" | "error"
    message: str
    cleanup_status: str = "done"  # "done" | "pending"


@router.post("/account/delete", response_model=DeleteAccountResponse)
async def delete_account(request: DeleteAccountRequest, user=Depends(verify_owner)):
    """
    Delete the current user's account.

    This is an irreversible action that:
    1. Hard-deletes profile/twin data where possible
    2. Purges vector namespaces best-effort
    3. Removes or anonymizes user identity records
    4. Leaves cleanup_status='pending' if any best-effort step fails

    Requires typed confirmation ("DELETE" or user's email).
    Uses verify_owner (NOT get_current_user) so an auth failure returns 401
    immediately instead of letting the destructive code run with user=None
    and leaking a 500 stack trace. Audit 2026-05-31 second pass.
    """
    from modules.governance import AuditLogger

    user_id = user.get("user_id")
    user_email = user.get("email", "")
    tenant_id = user.get("tenant_id")

    # Validate confirmation
    if request.confirmation not in ["DELETE", user_email]:
        raise HTTPException(
            status_code=400,
            detail="Invalid confirmation. Type 'DELETE' or your email address to confirm."
        )

    try:
        # Log the deletion request
        AuditLogger.log(
            tenant_id=tenant_id,
            twin_id=None,
            event_type="ACCOUNT_ACTION",
            action="ACCOUNT_DELETE_REQUESTED",
            actor_id=user_id,
            metadata={"email": user_email}
        )

        # SECURITY: Only allow deletion of twins this user owns (owner_user_id match)
        # or twins they created. Never delete twins owned by other users in the same tenant.
        all_twins_res = supabase.table("twins").select("id, name, settings, creator_id").eq("tenant_id", tenant_id).execute()
        all_twins = all_twins_res.data or []

        twins_to_delete = []
        for twin in all_twins:
            settings = twin.get("settings") or {}
            owner_uid = str(settings.get("owner_user_id") or "").strip()
            creator = str(twin.get("creator_id") or "").strip()
            # Only include twins that belong to THIS user
            if owner_uid == user_id or creator == user_id or creator == f"tenant_{tenant_id}":
                twins_to_delete.append(twin)

        # If user has no own twins but there are tenant twins owned by others, deny full deletion
        if all_twins and not twins_to_delete:
            raise HTTPException(
                status_code=403,
                detail="Cannot delete tenant data owned by other users. Contact the tenant owner."
            )
        total_twins = len(twins_to_delete)

        deleted_count = 0
        archived_fallback_count = 0
        cleanup_pending = False

        # Revoke tenant-level API keys up front
        try:
            supabase.table("tenant_api_keys").update({"is_active": False}).eq("tenant_id", tenant_id).execute()
        except Exception as e:
            logger.warning("[ACCOUNT] Error revoking tenant API keys: %s", e)
            cleanup_pending = True

        for twin in twins_to_delete:
            twin_id = twin["id"]
            settings = twin.get("settings") or {}

            # Revoke twin-scoped API keys
            try:
                supabase.table("twin_api_keys").delete().eq("twin_id", twin_id).execute()
            except Exception as e:
                logger.warning("[ACCOUNT] Error revoking twin API keys for %s: %s", twin_id, e)
                cleanup_pending = True

            # Best-effort pgvector chunk purge
            try:
                from adk_core.services.vector_store import delete_namespace
                await delete_namespace(twin_id)
            except Exception as e:
                logger.warning("[ACCOUNT] pgvector cleanup failed for %s: %s", twin_id, e)
                cleanup_pending = True

            # Hard-delete twin row (most tables should cascade via FK).
            deleted = False
            try:
                supabase.table("twins").delete().eq("id", twin_id).execute()
                exists_after_delete = (
                    supabase.table("twins").select("id").eq("id", twin_id).limit(1).execute()
                )
                if not (exists_after_delete.data or []):
                    deleted = True
                    deleted_count += 1
            except Exception as e:
                logger.error("[ACCOUNT] Hard delete failed for twin %s: %s", twin_id, e)

            # Fallback for environments where FK constraints block hard delete:
            # archive the twin so it is inaccessible while cleanup is completed.
            if not deleted:
                cleanup_pending = True
                archived_fallback_count += 1
                try:
                    settings["deleted_at"] = datetime.now(timezone.utc).isoformat()
                    settings["deleted_by"] = user_id
                    settings["deleted_reason"] = "account_deletion_pending_cleanup"
                    settings["is_public"] = False
                    widget_settings = settings.get("widget_settings")
                    if isinstance(widget_settings, dict):
                        widget_settings["public_share_enabled"] = False
                        widget_settings.pop("share_token", None)
                        widget_settings.pop("share_token_expires_at", None)
                    supabase.table("twins").update({"settings": settings}).eq("id", twin_id).execute()
                except Exception as archive_err:
                    logger.error("[ACCOUNT] Archive fallback failed for twin %s: %s", twin_id, archive_err)
                    cleanup_pending = True

        # 2. Delete auth user first (Supabase auth layer)
        try:
            supabase.auth.admin.delete_user(user_id)
        except Exception as e:
            # Not fatal; some Supabase clients don't expose admin.delete_user
            logger.warning("[ACCOUNT] Auth admin delete failed or unsupported: %s", e)
            cleanup_pending = True

        # 2b. Hard-delete the public.users row — do NOT just anonymize.
        # Anonymizing leaves orphaned ghost records that break re-registration and GDPR compliance.
        try:
            supabase.table("users").delete().eq("id", user_id).execute()
            logger.info("[ACCOUNT] Deleted users row for %s", user_id)
        except Exception as e:
            logger.error("[ACCOUNT] Error deleting user row: %s", e)
            # Fallback: anonymize so PII is not retained if hard-delete fails
            try:
                supabase.table("users").update({
                    "email": f"deleted_{user_id}@deleted.local",
                    "avatar_url": None,
                    "full_name": None,
                    "last_active_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", user_id).execute()
            except Exception as anon_err:
                logger.error("[ACCOUNT] Anonymization fallback also failed: %s", anon_err)
            cleanup_pending = True

        # 3. Log the completed deletion
        AuditLogger.log(
            tenant_id=tenant_id,
            twin_id=None,
            event_type="ACCOUNT_ACTION",
            action="ACCOUNT_DELETED",
            actor_id=user_id,
            metadata={
                "twins_deleted": deleted_count,
                "twins_archived_fallback": archived_fallback_count,
                "cleanup_pending": cleanup_pending
            }
        )

        logger.info(
            "[ACCOUNT] Deleted account %s: deleted=%s, archived_fallback=%s, total=%s",
            user_id, deleted_count, archived_fallback_count, total_twins
        )

        return DeleteAccountResponse(
            status="deleted",
            message=(
                f"Account deleted. {deleted_count} profiles deleted."
                + (
                    f" {archived_fallback_count} profile(s) archived pending cleanup."
                    if archived_fallback_count > 0
                    else ""
                )
            ),
            cleanup_status="pending" if cleanup_pending else "done"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("[ACCOUNT] Error deleting account: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
