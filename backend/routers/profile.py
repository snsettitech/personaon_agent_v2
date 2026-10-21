"""
Profile Router - Person Completeness v1

Abstraction layer over twins that enforces "one profile per user" semantics.
All endpoints return "profile" terminology externally while using twin_id internally.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from typing import Any
from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timezone
import logging

from modules.auth_guard import require_tenant, verify_twin_ownership
from modules.observability import supabase
from modules.profile_selection import (
    build_creator_candidates,
    select_profile_twin_from_rows,
)
from modules.tenant_guard import derive_creator_ids
from modules.share_links import ensure_share_token, get_publish_gate_status
from modules.public_profile_pack import ALLOWED_ACCENTS, ALLOWED_THEME_IDS
from modules.text_quality import validate_headline_text, validate_meaningful_text
from services.revalidation import revalidate_persona

logger = logging.getLogger(__name__)

router = APIRouter(tags=["profile"])


# =============================================================================
# Schemas
# =============================================================================

class ProfileResponse(BaseModel):
    """Public profile representation (no "twin" terminology)."""
    id: str
    name: str
    headline: str | None = None
    status: str  # 'draft' | 'building' | 'ready' | 'needs_attention'
    answerability_score: int = 0
    bio: str | None = None
    handle: str | None = None
    pinned_questions: list[str] = []
    theme_id: str | None = None
    accent: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    lead_capture_enabled: bool = False
    value_frame: str | None = None
    booking_url: str | None = None


class CreateProfileRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=200)
    headline: str | None = Field(None, max_length=280)
    build_mode: str = Field(..., pattern="^(with_links|name_only)$")


# Built from the single source of truth so the write-validator and the public
# redactor (modules/public_profile_pack.py) can never drift apart.
_THEME_ID_PATTERN = "^(" + "|".join(sorted(ALLOWED_THEME_IDS)) + ")$"
_ACCENT_PATTERN = "^(" + "|".join(sorted(ALLOWED_ACCENTS)) + ")$"


class UpdateProfileRequest(BaseModel):
    headline: str | None = Field(None, max_length=280)
    role: str | None = None
    location: str | None = None
    expertise_tags: list[str] | None = None
    bio: str | None = Field(None, max_length=2000)
    pinned_questions: list[str] | None = None
    theme_id: str | None = Field(None, pattern=_THEME_ID_PATTERN)
    accent: str | None = Field(None, pattern=_ACCENT_PATTERN)
    lead_capture_enabled: bool | None = None
    value_frame: str | None = Field(None, pattern=r'^(opportunity|lead|inquiry|collaboration|interest)$')
    booking_url: str | None = Field(None, max_length=500)

    # Same meaningfulness bar as onboarding's CreatePersonaRequest (shared via
    # modules.text_quality) — the dashboard "Publish" tab is another place a
    # user can set a garbage bio/headline (PRD R1 root cause), so it must be
    # validated here too, not just at onboarding time. `None` (field omitted)
    # is left alone; only an explicitly-submitted value is checked.
    @field_validator("bio")
    @classmethod
    def _meaningful_bio(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return validate_meaningful_text(v)

    @field_validator("headline")
    @classmethod
    def _meaningful_headline(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return validate_headline_text(v)


class BuildStatusResponse(BaseModel):
    """Unified build status for onboarding progress screen."""
    profile_id: str
    status: str  # 'pending' | 'building' | 'ready' | 'needs_attention' | 'failed'
    stage: str
    progress_percent: int
    stats: dict[str, Any]
    quality_tier: str | None = None  # 'strong' | 'with_gaps' | 'needs_review' | 'failed'
    last_updated_at: str | None = None


class ResetProfileResponse(BaseModel):
    profile_id: str
    status: str  # "reset"
    message: str


class PublishRequest(BaseModel):
    twin_id: str


class PublishResponse(BaseModel):
    url: str
    handle: str | None = None
    share_token: str


class PublishGateStatusResponse(BaseModel):
    """execution-board 0.6: dashboard publish-gate banner status."""
    passed: bool
    reasons: list[str] = []


# =============================================================================
# Helpers
# =============================================================================

def map_twin_to_profile(twin: dict[str, Any]) -> dict[str, Any]:
    """Map twin record to profile response (terminology conversion)."""
    settings = twin.get("settings") or {}
    public_profile = settings.get("public_profile") or {}
    persona_profile = settings.get("persona_profile") or {}
    return {
        "id": twin["id"],
        "name": twin["name"],
        "headline": settings.get("headline"),
        "status": map_status(twin.get("status"), twin.get("id")),
        "answerability_score": 0,
        "bio": public_profile.get("bio") or persona_profile.get("bio") or persona_profile.get("short_description"),
        "handle": settings.get("handle"),
        "pinned_questions": public_profile.get("pinned_questions") or [],
        "theme_id": public_profile.get("theme_id"),
        "accent": public_profile.get("accent"),
        "created_at": twin.get("created_at"),
        "updated_at": twin.get("updated_at"),
        "lead_capture_enabled": settings.get("lead_capture_enabled") is True,
        "value_frame": settings.get("value_frame"),
        "booking_url": (settings.get("widget_ui") or {}).get("booking_url"),
    }


def map_status(twin_status: str | None, twin_id: str | None = None) -> str:
    """Map internal twin status to profile status."""
    if not twin_status:
        return "draft"
    status_map = {
        "draft": "draft",
        "ingesting": "building",
        "claims_ready": "building",
        "clarification_pending": "building",
        "persona_built": "ready",
        "active": "ready",
    }
    return status_map.get(twin_status, "draft")


def _normalize_name(value: str | None) -> str:
    cleaned = " ".join((value or "").strip().split())
    if cleaned.lower().endswith(" (draft)"):
        cleaned = cleaned[:-8].strip()
    return cleaned


def _names_conflict(existing_name: str | None, requested_name: str | None) -> bool:
    existing = _normalize_name(existing_name).lower()
    requested = _normalize_name(requested_name).lower()
    if not existing or not requested:
        return False
    return existing != requested


def _select_profile_twin_for_user(user: dict[str, Any]) -> dict[str, Any] | None:
    tenant_id = user.get("tenant_id")
    user_id = user.get("user_id")
    if not tenant_id:
        return None

    # Pull a bounded set then rank locally so legacy rows still work.
    result = (
        supabase.table("twins")
        .select("*")
        .eq("tenant_id", tenant_id)
        .is_("settings->>deleted_at", "null")
        .order("created_at", desc=True)
        .limit(25)
        .execute()
    )
    twins = result.data or []
    creator_candidates = build_creator_candidates(
        user=user,
        user_id=str(user_id or ""),
        tenant_id=str(tenant_id or ""),
    )
    return select_profile_twin_from_rows(
        rows=twins,
        user_id=str(user_id or ""),
        creator_candidates=creator_candidates,
        allow_single_legacy_fallback=True,
    )


def get_or_create_profile_for_user(user: dict[str, Any]) -> dict[str, Any] | None:
    """Get existing profile or return None (doesn't create - creation is explicit)."""
    twin = _select_profile_twin_for_user(user)
    if not twin:
        return None
    return map_twin_to_profile(twin)


def _best_effort_delete_by_twin_id(table: str, twin_id: str) -> None:
    try:
        supabase.table(table).delete().eq("twin_id", twin_id).execute()
    except Exception as e:
        logger.warning("Profile reset: failed deleting %s for twin=%s (%s)", table, twin_id, e)


def _best_effort_purge_vectors(twin_id: str) -> None:
    try:
        import asyncio
        from adk_core.services.vector_store import delete_namespace
        asyncio.run(delete_namespace(twin_id))
    except Exception as e:
        logger.warning("Profile reset: vector purge failed for twin=%s (%s)", twin_id, e)


def _safe_update_twin_row(twin_id: str, payload: dict[str, Any]) -> None:
    mutable_payload = dict(payload)
    removable_columns = {"status", "updated_at", "creation_mode"}

    while True:
        try:
            res = supabase.table("twins").update(mutable_payload).eq("id", twin_id).execute()
        except Exception as e:
            err = str(e).lower()
            removed = None
            for column in list(removable_columns):
                if column in mutable_payload and column in err and (
                    "column" in err or "does not exist" in err or "pgrst204" in err
                ):
                    removed = column
                    break
            if removed:
                mutable_payload.pop(removed, None)
                removable_columns.discard(removed)
                continue
            raise

        # A 0-row UPDATE does not raise in supabase-py. It means the write was
        # silently filtered — most often RLS rejecting a non-service-role client
        # because the twin's tenant_id != the owner's auth.uid() — or the twin
        # is gone. Surface it loudly instead of phantom-confirming the save, which
        # is what silently dropped Publish-tab edits (#228/#229).
        if not res.data:
            logger.error(
                "[Profile] twin update affected 0 rows twin_id=%s — write did not persist "
                "(check SUPABASE_SERVICE_KEY is a real service_role key)",
                twin_id,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "Update did not persist", "code": "TWIN_WRITE_NO_ROWS"},
            )
        return


def _safe_insert_profile_twin(payload: dict[str, Any]) -> dict[str, Any]:
    mutable_payload = dict(payload)
    removable_columns = {"status"}

    while True:
        try:
            result = supabase.table("twins").insert(mutable_payload).execute()
            if not result.data:
                raise RuntimeError("Failed to create twin: no data returned")
            return result.data[0]
        except Exception as e:
            err = str(e).lower()
            removed = None
            for column in list(removable_columns):
                if column in mutable_payload and column in err and (
                    "column" in err or "does not exist" in err or "pgrst204" in err
                ):
                    removed = column
                    break
            if removed:
                mutable_payload.pop(removed, None)
                removable_columns.discard(removed)
                continue
            raise


def _reset_profile_data(twin_id: str) -> None:
    # Child tables first where possible to avoid FK edge cases.
    delete_tables = [
        "verified_qna_grounding_chunks",
        "verified_qna_summaries",
        "verified_qna",
        "training_decisions",
        "training_interactions",
        "training_sessions",
        "owner_memory_snapshots",
        "owner_memory_entries",
        "memory_events",
        "action_executions",
        "action_drafts",
        "action_triggers",
        "events",
        "tool_connectors",
        "products",
        "escalations",
        "conversations",
        "chunks",
        "sources",
    ]

    for table in delete_tables:
        _best_effort_delete_by_twin_id(table, twin_id)

    # Optional tables that may not exist in all environments.
    try:
        supabase.table("name_deep_research_runs").delete().eq("twin_id", twin_id).execute()
    except Exception as e:
        logger.warning("Profile reset: failed deleting name_deep_research_runs for twin=%s (%s)", twin_id, e)

    try:
        supabase.table("twin_api_keys").delete().eq("twin_id", twin_id).execute()
    except Exception as e:
        logger.warning("Profile reset: failed deleting twin_api_keys for twin=%s (%s)", twin_id, e)

    _best_effort_purge_vectors(twin_id)


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/profile", response_model=ProfileResponse)
async def get_profile(user: dict = Depends(require_tenant)):
    """
    Get the current user's single profile.
    Returns 404 if no profile exists (frontend routes to onboarding).
    """
    profile = get_or_create_profile_for_user(user)

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "Profile not found",
                "code": "PROFILE_NOT_FOUND",
                "message": "No profile exists for this user. Please complete onboarding."
            }
        )

    return profile


@router.post("/profile", response_model=ProfileResponse)
async def create_profile(
    request: CreateProfileRequest,
    user: dict = Depends(require_tenant),
    response: Response = None,
):
    """
    Idempotent profile creation.
    If profile already exists, returns it (no duplicate creation).
    """
    tenant_id = user.get("tenant_id")
    user_id = user.get("user_id")

    # Check for existing profile (idempotency)
    existing = get_or_create_profile_for_user(user)
    if existing:
        if response is not None:
            response.headers["x-profile-created"] = "false"
        # Prevent/repair identity drift on stale drafts.
        requested_name = _normalize_name(request.full_name)
        existing_name = _normalize_name(existing.get("name"))
        if _names_conflict(existing_name, requested_name):
            if existing.get("status") == "draft":
                try:
                    twin_row = (
                        supabase.table("twins")
                        .select("settings")
                        .eq("id", existing["id"])
                        .single()
                        .execute()
                    )
                    current_settings = (twin_row.data or {}).get("settings") or {}
                    merged_settings = {
                        **current_settings,
                        "owner_name": requested_name,
                        "owner_user_id": user_id,
                        "build_mode": request.build_mode,
                    }
                    if request.headline:
                        merged_settings["headline"] = request.headline
                    update_payload = {
                        "name": requested_name,
                        "settings": merged_settings,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                    _safe_update_twin_row(existing["id"], update_payload)
                    refreshed = get_or_create_profile_for_user(user)
                    if refreshed:
                        logger.info(
                            "Profile identity updated on existing draft: user=%s old=%s new=%s",
                            user_id,
                            existing_name,
                            requested_name,
                        )
                        if response is not None:
                            response.headers["x-profile-created"] = "false"
                        return refreshed
                except Exception as e:
                    logger.warning("Failed to update stale draft identity: %s", e)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "Profile identity conflict",
                    "code": "PROFILE_IDENTITY_CONFLICT",
                    "message": (
                        f"Existing profile belongs to '{existing_name}'. "
                        "Reset the profile before switching to a different person."
                    ),
                    "existing_name": existing_name,
                    "requested_name": requested_name,
                },
            )

        logger.info(f"Profile already exists for user {user_id}, returning existing")
        return existing

    # Create new twin (internal representation)
    creator_ids = derive_creator_ids(user)
    creator_id = creator_ids[0] if creator_ids else f"tenant_{tenant_id}"

    twin_data = {
        "name": request.full_name.strip(),
        "tenant_id": tenant_id,
        "creator_id": creator_id,
        "status": "draft",
        "specialization": "vanilla",
        "settings": {
            "headline": request.headline,
            "build_mode": request.build_mode,
            "created_via": "profile_api",
            "owner_name": request.full_name.strip(),
            "owner_user_id": user_id,
        },
    }

    try:
        twin = _safe_insert_profile_twin(twin_data)
        if response is not None:
            response.headers["x-profile-created"] = "true"

        logger.info(f"Created profile {twin['id']} for user {user_id}")

        return map_twin_to_profile(twin)

    except Exception as e:
        logger.exception(f"Failed to create profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "Profile creation failed",
                "code": "PROFILE_CREATE_FAILED",
                "message": str(e)
            }
        )


@router.patch("/profile", response_model=ProfileResponse)
async def update_profile(
    request: UpdateProfileRequest,
    user: dict = Depends(require_tenant)
):
    """Update profile settings (headline, hints, etc)."""
    # Get existing profile
    profile = get_or_create_profile_for_user(user)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Profile not found", "code": "PROFILE_NOT_FOUND"}
        )

    # Build update
    update_data = {"updated_at": datetime.now(timezone.utc).isoformat()}
    settings_updates = {}

    if request.headline is not None:
        settings_updates["headline"] = request.headline

    if request.role is not None or request.location is not None or request.expertise_tags is not None:
        hints = {}
        if request.role is not None:
            hints["role"] = request.role
        if request.location is not None:
            hints["location"] = request.location
        if request.expertise_tags is not None:
            hints["expertise_tags"] = request.expertise_tags
        settings_updates["onboarding_hints"] = hints

    # bio + pinned questions live under settings.public_profile (the curated,
    # visitor-facing object), merged into the nested dict rather than top-level.
    pp_updates: dict[str, Any] = {}
    if request.bio is not None:
        pp_updates["bio"] = request.bio
    if request.pinned_questions is not None:
        pp_updates["pinned_questions"] = request.pinned_questions[:3]
    if request.theme_id is not None:
        pp_updates["theme_id"] = request.theme_id
    if request.accent is not None:
        pp_updates["accent"] = request.accent

    if request.lead_capture_enabled is not None:
        settings_updates["lead_capture_enabled"] = request.lead_capture_enabled
    if request.value_frame is not None:
        settings_updates["value_frame"] = request.value_frame

    wu_updates: dict[str, Any] = {}
    if request.booking_url is not None:
        wu_updates["booking_url"] = request.booking_url

    handle: str | None = None
    if settings_updates or pp_updates or wu_updates:
        # Get current settings and merge
        twin_result = supabase.table("twins").select("settings").eq("id", profile["id"]).single().execute()
        current_settings = twin_result.data.get("settings") or {}
        handle = current_settings.get("handle")
        updated_settings = {**current_settings, **settings_updates}
        if pp_updates:
            current_pp = current_settings.get("public_profile") or {}
            updated_settings["public_profile"] = {**current_pp, **pp_updates}
        if wu_updates:
            current_wu = current_settings.get("widget_ui") or {}
            updated_settings["widget_ui"] = {**current_wu, **wu_updates}
        update_data["settings"] = updated_settings

    # Apply update
    _safe_update_twin_row(profile["id"], update_data)
    refreshed_twin = supabase.table("twins").select("*").eq("id", profile["id"]).single().execute()

    # Publish-tab edits (theme/accent/bio/pinned questions) change the public
    # page, so refresh its ISR cache on-demand — visitors see the change right
    # away instead of waiting out the ~1h revalidate window. Best-effort.
    if pp_updates and handle:
        await revalidate_persona(handle)

    return map_twin_to_profile(refreshed_twin.data)


@router.post("/profile/reset", response_model=ResetProfileResponse)
async def reset_profile(user: dict = Depends(require_tenant)):
    """
    Reset the current user's profile data while keeping the account.

    This keeps the twin identity row but clears accumulated research/knowledge/chat data
    so onboarding can be re-run cleanly.
    """
    profile = get_or_create_profile_for_user(user)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Profile not found", "code": "PROFILE_NOT_FOUND"},
        )

    twin_id = profile["id"]

    try:
        twin_row = (
            supabase.table("twins")
            .select("name, settings")
            .eq("id", twin_id)
            .single()
            .execute()
        )
        current = twin_row.data or {}
        settings = current.get("settings") or {}

        _reset_profile_data(twin_id)

        settings.pop("deleted_at", None)
        settings.pop("deleted_by", None)
        settings.pop("deleted_reason", None)
        settings["is_public"] = False
        settings["reset_at"] = datetime.now(timezone.utc).isoformat()
        settings["name_first_state"] = "planning"

        widget_settings = settings.get("widget_settings")
        if not isinstance(widget_settings, dict):
            widget_settings = {}
        widget_settings["public_share_enabled"] = False
        widget_settings.pop("share_token", None)
        widget_settings.pop("share_token_expires_at", None)
        settings["widget_settings"] = widget_settings

        update_payload: dict[str, Any] = {
            "settings": settings,
            "status": "draft",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if current.get("name"):
            update_payload["description"] = f"{current['name']}'s AI persona"

        _safe_update_twin_row(twin_id, update_payload)

        logger.info("Profile reset completed for twin=%s user=%s", twin_id, user.get("user_id"))
        return ResetProfileResponse(
            profile_id=twin_id,
            status="reset",
            message="Profile has been reset. You can run onboarding again.",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to reset profile twin=%s: %s", twin_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Profile reset failed", "code": "PROFILE_RESET_FAILED", "message": str(e)},
        )


@router.post("/profile/publish", response_model=PublishResponse)
async def publish_profile(
    request: PublishRequest,
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """
    Publish a persona: set is_active=True, status=active, ensure share token, return URL.

    If the twin has a handle, returns /p/{handle}. Otherwise returns /share/{twin_id}/{token}.
    Sets subscription_tier to 'free' if not already set.
    """
    verify_twin_ownership(request.twin_id, user)

    # Fetch current twin state
    twin_result = (
        supabase.table("twins")
        .select("id, settings, status")
        .eq("id", request.twin_id)
        .single()
        .execute()
    )
    if not twin_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Twin not found", "code": "TWIN_NOT_FOUND"},
        )

    twin_data = twin_result.data
    settings = dict(twin_data.get("settings") or {})

    # Execution-board 0.1/0.6 (PRD R1): this endpoint used to flip status=active
    # unconditionally — the same OR-bypass class of bug closed elsewhere in
    # modules.share_links/routers.twins_lifecycle. Re-check the same content-
    # quality gate here (against what status *would* be post-publish) so the
    # dashboard's disabled Publish button isn't just cosmetic: a direct API
    # call can't bypass it either.
    gate_check_twin = {**twin_data, "status": "active", "settings": settings}
    gate_status = get_publish_gate_status(gate_check_twin)
    if not gate_status["passed"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Profile not ready to publish",
                "code": "PUBLISH_GATE_FAILED",
                "reasons": gate_status["reasons"],
            },
        )

    # Set subscription_tier default if not present
    if "subscription_tier" not in settings:
        settings["subscription_tier"] = "free"

    # Publish: set active state and updated settings
    _safe_update_twin_row(
        request.twin_id,
        {
            "status": "active",
            "settings": settings,
        },
    )

    # Ensure share token exists
    share_token = ensure_share_token(request.twin_id, tenant_id=user.get("tenant_id", ""))

    # Build URL: handle-first, fallback to share URL
    handle = settings.get("handle") or None
    if handle:
        url = f"/p/{handle}"
    else:
        url = f"/share/{request.twin_id}/{share_token}"

    logger.info(
        "Profile published: twin=%s handle=%s url=%s user=%s",
        request.twin_id,
        handle,
        url,
        user.get("user_id"),
    )

    return {"url": url, "handle": handle, "share_token": share_token}


@router.get("/profile/build-status", response_model=BuildStatusResponse)
async def get_build_status(user: dict = Depends(require_tenant)):
    """Build status based on auto_create_state — the live Firecrawl extraction pipeline."""
    profile = get_or_create_profile_for_user(user)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Profile not found", "code": "PROFILE_NOT_FOUND"}
        )

    twin_id = profile["id"]

    # Read auto_create_state from settings (the live pipeline state)
    try:
        row = supabase.table("twins").select("settings").eq("id", twin_id).single().execute()
        settings = (row.data or {}).get("settings") or {}
    except Exception:
        settings = {}

    ac_state = settings.get("auto_create_state") or {}
    state = ac_state.get("status") if isinstance(ac_state, dict) else None

    state_map = {
        "generating": ("building",  "generating",  50),
        "needs_input": ("needs_attention", "review", 80),
        "active":      ("ready",     "completed",  100),
        "failed":      ("failed",    "failed",       0),
    }
    build_status, stage, progress = state_map.get(state, ("draft", "planning", 0))

    # Ingestion source count is the only live stat we track
    stats: dict[str, Any] = {"sources_count": 0}
    try:
        sources_result = supabase.table("sources") \
            .select("id", count="exact").eq("twin_id", twin_id).execute()
        stats["sources_count"] = sources_result.count or 0
    except Exception:
        pass

    quality_tier = None
    if build_status == "ready":
        quality_tier = "strong" if stats["sources_count"] >= 3 else "with_gaps"

    return {
        "profile_id": twin_id,
        "status": build_status,
        "stage": stage,
        "progress_percent": progress,
        "stats": stats,
        "quality_tier": quality_tier,
        "last_updated_at": ac_state.get("updated_at") if isinstance(ac_state, dict) else None,
    }


@router.get("/profile/publish-gate", response_model=PublishGateStatusResponse)
async def get_publish_gate_status_endpoint(user: dict = Depends(require_tenant)):
    """Read-only publish-gate status for the dashboard banner (execution-board 0.6).

    Reuses modules.share_links.get_publish_gate_status — the same content-
    quality gate that `publish_profile` and `publish_draft_twin` enforce at
    write time — so there is exactly one place that decides "is this profile
    good enough to go public," not a separate frontend check that could drift.
    """
    profile = get_or_create_profile_for_user(user)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Profile not found", "code": "PROFILE_NOT_FOUND"},
        )

    twin_id = profile["id"]
    twin_result = (
        supabase.table("twins")
        .select("id, name, description, settings")
        .eq("id", twin_id)
        .single()
        .execute()
    )
    if not twin_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Twin not found", "code": "TWIN_NOT_FOUND"},
        )

    return get_publish_gate_status(twin_result.data)
