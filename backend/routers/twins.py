import logging

from fastapi import APIRouter, Depends, HTTPException, status
from typing import Any
from pydantic import BaseModel
from modules.auth_guard import verify_owner, get_current_user, verify_twin_ownership, resolve_tenant_id

logger = logging.getLogger(__name__)
from modules.schemas import TwinSettingsUpdate, TrainingMetricsSchema
from modules.access_groups import create_group
from modules.observability import supabase
from modules.profile_utils import normalize_social_links
from modules.tenant_guard import derive_creator_ids
from modules.text_quality import HEADLINE_MIN_LENGTH, meaningful_text_error
from services.revalidation import revalidate_persona
from adk_core.services.agent_service import invalidate_agent
from adk_core.services.firecrawl_service import profile_to_text
from datetime import datetime, timezone, timedelta

# =============================================================================
# Training Metrics Imports
# =============================================================================
from modules.training_metrics import (
    get_training_metrics_for_api,
    is_training_metrics_enabled,
    update_twin_training_metrics,
)

# =============================================================================
# Shared helpers (extracted to twins_helpers.py)
# =============================================================================
from routers.twins_helpers import (
    _require_authenticated_user,
    _is_missing_column_error,
    _normalize_twin_status_shape,
)
import contextlib


router = APIRouter(tags=["twins"])


def get_twin_verification_status(twin_id: str) -> dict[str, Any]:
    """
    Return coarse readiness from the latest verification run.

    This is intentionally lightweight and separate from publish quality-gating,
    which requires a full quality-suite record.
    """
    try:
        result = (
            supabase.table("twin_verifications")
            .select("status, created_at, details")
            .eq("twin_id", twin_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        latest = (result.data or [None])[0]
        if not latest:
            return {
                "is_ready": False,
                "issues": ["No verification record found. Run verification before publishing."],
            }
        return {
            "is_ready": latest.get("status") == "PASS",
            "issues": [],
            "latest": latest,
        }
    except Exception as e:
        return {
            "is_ready": False,
            "issues": [f"Verification status check failed: {e}"],
        }


def _is_recent_quality_suite_pass(verification: dict[str, Any], max_age_days: int = 30) -> bool:
    """Check whether a verification row is a PASS from the quality-suite format."""
    if not isinstance(verification, dict):
        return False
    if verification.get("status") != "PASS":
        return False

    details = verification.get("details")
    if not isinstance(details, dict):
        return False

    tests_run = details.get("tests_run")
    tests_passed = details.get("tests_passed")
    test_results = details.get("test_results")
    if not isinstance(tests_run, int) or tests_run <= 0:
        return False
    if tests_passed != tests_run:
        return False
    if not isinstance(test_results, list) or len(test_results) != tests_run:
        return False
    if any(not bool((r or {}).get("passed")) for r in test_results):
        return False

    created_at = verification.get("created_at")
    if created_at:
        try:
            created_dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            now_utc = datetime.now(timezone.utc)
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            if (now_utc - created_dt) > timedelta(days=max_age_days):
                return False
        except Exception:
            return False

    return True


# ============================================================================
# Twin Create Schema (Updated for 5-Layer Persona)
# ============================================================================

class TwinCreateRequest(BaseModel):
    name: str
    tenant_id: str | None = None  # IGNORED: server always resolves tenant_id
    description: str | None = None
    settings: dict[str, Any] | None = None


# ============================================================================
# Profile text builder (for Pinecone vectorization)
# ============================================================================



def _build_persona_profile(
    name: str,
    public_profile: dict,
    full_profile: dict,
    existing_persona_profile: dict | None = None,
) -> dict:
    """Normalize onboarding profile data into the canonical persona_profile shape."""
    persona_profile = dict(existing_persona_profile or {})

    display_name = (
        public_profile.get("name")
        or public_profile.get("display_name")
        or persona_profile.get("name")
        or name
    )
    occupation = (
        public_profile.get("occupation")
        or public_profile.get("headline")
        or persona_profile.get("occupation")
        or ""
    )
    bio = (
        public_profile.get("bio")
        or public_profile.get("short_description")
        or persona_profile.get("bio")
        or persona_profile.get("short_description")
        or ""
    )
    expertise_list = full_profile.get("areas_of_expertise") or persona_profile.get("areas_of_expertise") or []
    achievements = full_profile.get("key_achievements") or persona_profile.get("achievements") or []

    persona_profile.update(
        {
            "name": display_name,
            "display_name": display_name,
            "headline": public_profile.get("headline") or occupation,
            "occupation": occupation,
            "organization": public_profile.get("organization") or persona_profile.get("organization") or "",
            "bio": bio,
            "short_description": public_profile.get("short_description") or bio,
            "social_links": normalize_social_links(
                public_profile.get("social_links") or persona_profile.get("social_links") or {}
            ),
            "image_url": public_profile.get("image_url") or persona_profile.get("image_url") or "",
            "education": full_profile.get("education") or persona_profile.get("education") or [],
            "work_experience": full_profile.get("work_experience") or persona_profile.get("work_experience") or [],
            "achievements": achievements,
            "key_achievements": achievements,
            "areas_of_expertise": expertise_list,
            "expertise": expertise_list,
            "contributions": full_profile.get("contributions") or persona_profile.get("contributions") or [],
            "personality_traits": full_profile.get("personality_traits") or persona_profile.get("personality_traits") or [],
            "speaking_style": full_profile.get("speaking_style") or persona_profile.get("speaking_style") or "",
            "nationality": full_profile.get("nationality") or persona_profile.get("nationality") or "",
        }
    )
    return persona_profile


# ============================================================================
# Twin CRUD Endpoints
# ============================================================================

@router.post("/twins")
async def create_twin(request: TwinCreateRequest, user=Depends(get_current_user)):
    """
    Create a new twin with 5-Layer Persona Spec v2.

    Supports TWO modes:
    1. MANUAL mode (default): Traditional onboarding flow with 6-step persona builder
       - Creates twin with status="active"
       - Auto-bootstraps 5-Layer Persona from onboarding data

    2. LINK-FIRST mode: Ingests external content to build persona from claims
       - Creates twin with status="draft"
       - Skips persona bootstrap (will be built from claims)
       - Links are queued for ingestion via /persona/link-compile endpoints

    SECURITY: Client-provided tenant_id is IGNORED.
    Server uses resolve_tenant_id() to determine the correct tenant.
    """
    try:
        user = _require_authenticated_user(user)
        user_id = user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Not authenticated")

        email = user.get("email", "")

        # CRITICAL: Always use resolve_tenant_id - NEVER trust client tenant_id
        # This auto-creates tenant if missing
        tenant_id = resolve_tenant_id(user_id, email)
        requested_name = (request.name or "").strip()
        if not requested_name:
            raise HTTPException(status_code=400, detail="Twin name is required")

        # Log if client sent a different tenant_id (for debugging)
        if request.tenant_id and request.tenant_id != tenant_id:
            logger.warning("[TWINS] WARNING: Ignoring client tenant_id=%s, using resolved=%s", request.tenant_id, tenant_id)

        def _find_existing_active_twin() -> dict[str, Any] | None:
            existing_res = (
                supabase.table("twins")
                .select("*")
                .eq("tenant_id", tenant_id)
                .eq("name", requested_name)
                .order("created_at", desc=True)
                .limit(25)
                .execute()
            )

            active_rows: list[dict[str, Any]] = []
            for row in existing_res.data or []:
                if not (row.get("settings") or {}).get("deleted_at"):
                    active_rows.append(row)
            if not active_rows:
                return None

            user_owned_rows: list[dict[str, Any]] = []
            for row in active_rows:
                settings = row.get("settings") if isinstance(row.get("settings"), dict) else {}
                owner_user_id = str(settings.get("owner_user_id") or "").strip()
                creator_id = str(row.get("creator_id") or "").strip()
                if owner_user_id == str(user_id) or creator_id == str(user_id):
                    user_owned_rows.append(row)

            if user_owned_rows:
                return user_owned_rows[0]

            # Legacy fallback for tenant-scoped old rows.
            if len(active_rows) == 1:
                only = active_rows[0]
                settings = only.get("settings") if isinstance(only.get("settings"), dict) else {}
                owner_user_id = str(settings.get("owner_user_id") or "").strip()
                creator_id = str(only.get("creator_id") or "").strip()
                if not owner_user_id and creator_id == f"tenant_{tenant_id}":
                    return only
            return None

        # Idempotency guard: retries from onboarding/network should not create duplicates.
        existing = _find_existing_active_twin()
        if existing:
            logger.info("[TWINS] Reusing existing twin %s for tenant=%s, name='%s'", existing.get('id'), tenant_id, requested_name)
            return _normalize_twin_status_shape(existing)

        # ====================================================================
        # STEP 1: Create the twin with 5-Layer Persona enabled
        # ====================================================================

        settings = dict(request.settings or {})

        public_profile = settings.get("public_profile") if isinstance(settings.get("public_profile"), dict) else {}
        full_profile = settings.get("full_profile") if isinstance(settings.get("full_profile"), dict) else {}
        if public_profile or full_profile:
            settings["persona_profile"] = _build_persona_profile(
                requested_name,
                public_profile,
                full_profile,
                settings.get("persona_profile") if isinstance(settings.get("persona_profile"), dict) else None,
            )

        settings["creation_mode"] = "manual"

        data = {
            "name": requested_name,
            "tenant_id": tenant_id,  # Always from resolve_tenant_id
            # Creator ID is the isolation root for creator namespace strategy.
            # Use authenticated creator claim first; fallback is deterministic tenant mapping.
            "creator_id": (derive_creator_ids(user) or [f"tenant_{tenant_id}"])[0],
            "description": request.description or f"{requested_name}'s AI persona",
            "settings": settings,
            "status": "active",  # Preferred: lifecycle column when migrated.
            "creation_mode": "manual",  # Preferred: explicit creation path.
        }

        logger.info("[TWINS] Creating twin '%s' for user=%s, tenant=%s", requested_name, user_id, tenant_id)
        insert_payload = dict(data)
        removed_legacy_columns: set[str] = set()

        while True:
            try:
                response = supabase.table("twins").insert(insert_payload).execute()
                break
            except Exception as insert_error:
                insert_msg = str(insert_error).lower()

                removed_column = None
                for column in ("status", "creation_mode"):
                    if column in insert_payload and _is_missing_column_error(insert_error, column):
                        removed_column = column
                        break

                if removed_column:
                    removed_legacy_columns.add(removed_column)
                    insert_payload.pop(removed_column, None)
                    logger.warning(
                        "[TWINS] Legacy twins schema detected (missing `%s`); retrying insert without that column",
                        removed_column,
                    )
                    continue

                if "duplicate key" in insert_msg or "already exists" in insert_msg:
                    existing_after_race = _find_existing_active_twin()
                    if existing_after_race:
                        logger.warning(
                            "[TWINS] Detected duplicate create race; returning existing twin %s",
                            existing_after_race.get('id'),
                        )
                        return _normalize_twin_status_shape(existing_after_race)
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "A twin with this name already exists for another profile in your tenant. "
                            "Use a distinct name or reuse your existing profile."
                        ),
                    )
                raise

        if response.data:
            twin = response.data[0]
            if removed_legacy_columns:
                # Keep API shape stable regardless of physical table schema.
                twin.setdefault("status", "active")
                twin.setdefault("creation_mode", "manual")
            twin = _normalize_twin_status_shape(twin)
            twin_id = twin.get('id')
            logger.info("[TWINS] Twin created: %s", twin_id)


            # ====================================================================
            # STEP 3: Auto-Create Default Group
            # ====================================================================

            try:
                await create_group(
                    twin_id=twin_id,
                    name="Default Group",
                    description="Standard access group for all content",
                    is_default=True
                )
                logger.info("[TWINS] Default group created for twin: %s", twin_id)
            except Exception as ge:
                logger.warning("[TWINS] WARNING: Failed to create default group for twin %s: %s", twin_id, ge)

            # ====================================================================
            # STEP 4: Vectorize Firecrawl profile into Pinecone (if available)
            # ====================================================================

            full_profile = settings.get("full_profile")
            if full_profile:
                try:
                    merged_profile = {
                        **settings.get("public_profile", {}),
                        **full_profile,
                        "name": settings.get("persona_profile", {}).get("name") or requested_name,
                    }
                    profile_text = profile_to_text(merged_profile)
                    from adk_core.services.vector_store import upsert_text_chunks
                    chunk_count = await upsert_text_chunks(
                        text=profile_text,
                        twin_id=twin_id,
                        source="firecrawl_profile",
                    )
                    logger.info("[TWINS] Firecrawl profile vectorized: %s chunks for twin %s", chunk_count, twin_id)
                except Exception as ve:
                    logger.warning("[TWINS] WARNING: Failed to vectorize profile for twin %s: %s", twin_id, ve)

            return twin
        raise HTTPException(status_code=400, detail="Failed to create twin")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TWINS] ERROR: %s", e)
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/twins")
async def list_twins(user=Depends(get_current_user)):
    """List all twins for the authenticated user's tenant (excludes archived)."""
    try:
        user = _require_authenticated_user(user)
        tenant_id = user.get("tenant_id")
        if not tenant_id:
            # User has no tenant - return empty list (not an error)
            return []

        # Get twins where tenant_id matches user's tenant
        response = supabase.table("twins").select("*").eq("tenant_id", tenant_id).order("created_at", desc=True).execute()

        twins_list = response.data if response.data else []

        # Filter out archived twins (those with deleted_at in settings)
        twins_list = [t for t in twins_list if not (t.get("settings") or {}).get("deleted_at")]
        twins_list = [_normalize_twin_status_shape(t) for t in twins_list]

        logger.info("[TWINS] Listing twins for tenant %s: found %s", tenant_id, len(twins_list))

        return twins_list
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TWINS] ERROR listing twins: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/twins/{twin_id}")
async def get_twin(twin_id: str, include_metrics: bool = True, user=Depends(get_current_user)):
    """
    Get a specific twin. Verifies ownership.

    Args:
        twin_id: Twin ID
        include_metrics: If True, include training metrics in response (default: True)
    """
    user = _require_authenticated_user(user)
    # Verify user has access to this twin
    verify_twin_ownership(twin_id, user)

    # Use RPC to bypass RLS for system lookup
    response = supabase.rpc("get_twin_system", {"t_id": twin_id}).single().execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Twin not found or access denied")

    twin = _normalize_twin_status_shape(response.data)

    # Add training metrics if enabled
    if include_metrics and is_training_metrics_enabled():
        try:
            # Check if cached metrics exist in settings
            settings = twin.get("settings") or {}
            cached_metrics = settings.get("training_metrics")

            # Use cached metrics if available and recent (within 1 hour).
            # GUARD: never trust the cache when:
            #   1. The twin is still generating/indexing (extraction not complete yet)
            #   2. The cache was computed while extraction was still running —
            #      detected by comparing last_computed_at to the twin's
            #      indexing_started_at timestamp. If the cache predates or equals
            #      indexing_started_at, the sources row didn't exist yet when
            #      metrics ran → that zero is stale.
            auto_create_state = (settings.get("auto_create_state") or "").lower()
            indexing_started_at_raw = settings.get("indexing_started_at") or ""

            use_cached = False
            if auto_create_state in ("generating", "indexing"):
                # Extraction in progress — never serve stale zeros
                use_cached = False
            elif cached_metrics and cached_metrics.get("last_computed_at"):
                try:
                    last_computed = datetime.fromisoformat(cached_metrics["last_computed_at"].replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    if last_computed.tzinfo is None:
                        last_computed = last_computed.replace(tzinfo=timezone.utc)

                    # If indexing_started_at is set, reject any cache computed
                    # before or within 10s of indexing completing — sources row
                    # is created after the Pinecone upsert, so early metrics
                    # will have seen 0 sources.
                    cache_valid = (now - last_computed).total_seconds() < 3600
                    # For auto_create twins: reject metrics that were cached within
                    # _INDEXING_GRACE_PERIOD_S seconds of when indexing started.
                    # The sources row + update_twin_training_metrics() both run
                    # after the Pinecone upsert; any cache predating that window
                    # was computed before the sources row existed → 0 words counted.
                    # This heuristic is intentionally scoped to auto_create only
                    # (auto_create_state is not "" or None) to avoid inadvertently
                    # busting the cache for twins built by other pipelines that may
                    # also write indexing_started_at for unrelated reasons.
                    _INDEXING_GRACE_PERIOD_S = 30
                    if cache_valid and indexing_started_at_raw and auto_create_state:
                        try:
                            indexing_started = datetime.fromisoformat(
                                indexing_started_at_raw.replace("Z", "+00:00")
                            )
                            if indexing_started.tzinfo is None:
                                indexing_started = indexing_started.replace(tzinfo=timezone.utc)
                            # Negative when last_computed < indexing_started (stale-zero case).
                            # Positive but small when metrics ran just after indexing began,
                            # before sources row was committed. Both cases are suspect.
                            if (last_computed - indexing_started).total_seconds() < _INDEXING_GRACE_PERIOD_S:
                                cache_valid = False
                        except Exception:
                            pass  # malformed timestamp — leave cache_valid as-is

                    if cache_valid:
                        use_cached = True
                        twin["training_metrics"] = {
                            "words_processed": cached_metrics.get("words_processed", 0),
                            "words_processed_display": cached_metrics.get("words_processed_display", "0"),
                            "questions_answerable_est": cached_metrics.get("questions_answerable_est", 0),
                            "questions_answerable_display": cached_metrics.get("questions_answerable_display", "0"),
                            "mind_score": cached_metrics.get("mind_score", 0),
                            "mind_score_label": cached_metrics.get("mind_score_label", "Early"),
                            "method_version": cached_metrics.get("method_version", "v1_heuristic"),
                            "last_computed_at": cached_metrics.get("last_computed_at"),
                            "notes": cached_metrics.get("notes", ""),
                        }
                except Exception:
                    use_cached = False

            if not use_cached:
                # Compute fresh metrics
                metrics = get_training_metrics_for_api(twin_id)
                twin["training_metrics"] = metrics["training_metrics"]

                # Cache metrics in background (don't await)
                try:
                    update_twin_training_metrics(twin_id)
                except Exception as cache_err:
                    logger.warning("[TWINS] Non-critical error caching metrics: %s", cache_err)

        except Exception as metrics_err:
            # Don't fail the request if metrics computation fails
            logger.warning("[TWINS] Error computing metrics for twin %s: %s", twin_id, metrics_err)
            twin["training_metrics"] = TrainingMetricsSchema().model_dump()

    return twin


async def _sync_bio_to_vectors(twin_id: str, bio_text: str) -> None:
    """
    Fire-and-forget: sync the edited bio as a dedicated pgvector chunk so the
    chat agent can retrieve the latest profile bio from vector search.

    Replaces any previous bio source so there's exactly one bio chunk at a time.
    """
    import uuid
    import logging
    _log = logging.getLogger(__name__)
    try:
        from modules.ingestion import process_and_index_text

        # Read current bio_source_id from profile_meta
        meta_row = (
            supabase.table("twins")
            .select("settings")
            .eq("id", twin_id)
            .single()
            .execute()
        )
        settings = (meta_row.data or {}).get("settings") or {}
        profile_meta = settings.get("public_profile_meta") or {}
        old_bio_source_id: str | None = profile_meta.get("bio_source_id")

        # Remove old bio source from Pinecone + DB
        if old_bio_source_id:
            with contextlib.suppress(Exception):
                supabase.table("sources").delete().eq("id", old_bio_source_id).execute()

        # Create new source row
        source_id = str(uuid.uuid4())
        supabase.table("sources").upsert({
            "id": source_id,
            "twin_id": twin_id,
            "filename": "Profile Bio",
            "file_size": len(bio_text),
            "content_text": bio_text,
            "status": "processing",
        }).execute()

        # Index to pgvector
        num_chunks = await process_and_index_text(
            source_id=source_id,
            twin_id=twin_id,
            text=bio_text,
            metadata_override={
                "filename": "Profile Bio",
                "type": "profile_bio",
                "source_type": "bio",
                "source": "bio",
            },
        )
        supabase.table("sources").update({"status": "live", "chunk_count": num_chunks}).eq("id", source_id).execute()

        # Persist bio_source_id for future replacement — re-use already-fetched settings
        updated_settings = dict(settings)
        updated_meta = dict(updated_settings.get("public_profile_meta") or {})
        updated_meta["bio_source_id"] = source_id
        updated_settings["public_profile_meta"] = updated_meta
        supabase.table("twins").update({"settings": updated_settings}).eq("id", twin_id).execute()

        _log.info("bio_vector_sync: synced bio for twin %s (source %s, %d chunks)", twin_id, source_id, num_chunks)
    except Exception as exc:
        import logging as _logging
        _logging.getLogger(__name__).warning("bio_vector_sync: failed for twin %s: %s", twin_id, exc)


@router.patch("/twins/{twin_id}")
async def patch_twin(
    twin_id: str,
    update: TwinSettingsUpdate,
    user=Depends(verify_owner),
):
    """
    Partial update endpoint used by dashboard profile/settings/share pages.
    Supports top-level name/description and merged settings updates.
    """
    user = _require_authenticated_user(user)
    verify_twin_ownership(twin_id, user)

    update_payload: dict[str, Any] = {}
    if update.name is not None:
        normalized_name = update.name.strip()
        if not normalized_name:
            raise HTTPException(status_code=400, detail="Twin name cannot be empty")
        update_payload["name"] = normalized_name

    if update.description is not None:
        update_payload["description"] = update.description

    settings_changed = False
    merged_settings: dict[str, Any] = {}
    twin_res: Any = None  # populated inside settings_changed block; initialized here for type safety

    if isinstance(update.settings, dict):
        settings_changed = True

    if update.is_public is not None:
        settings_changed = True

    if settings_changed:
        twin_res = (
            supabase.table("twins")
            .select("settings")
            .eq("id", twin_id)
            .single()
            .execute()
        )
        if not twin_res.data:
            raise HTTPException(status_code=404, detail="Twin not found")

        merged_settings = dict(twin_res.data.get("settings") or {})

        if isinstance(update.settings, dict):
            incoming_settings = dict(update.settings)
            public_profile = incoming_settings.get("public_profile")
            if isinstance(public_profile, dict) and "social_links" in public_profile:
                public_profile = {
                    **public_profile,
                    "social_links": normalize_social_links(public_profile.get("social_links")),
                }
                incoming_settings["public_profile"] = public_profile

            persona_profile = incoming_settings.get("persona_profile")
            if isinstance(persona_profile, dict) and "social_links" in persona_profile:
                persona_profile = {
                    **persona_profile,
                    "social_links": normalize_social_links(persona_profile.get("social_links")),
                }
                incoming_settings["persona_profile"] = persona_profile

            # Reject garbage bio/headline saved from the dashboard profile-edit
            # form (PRD R1 root cause: a live page shipped with headline
            # "software engineer" and bio literally "nill" because this raw
            # settings dict had zero meaningfulness validation — only the
            # Pydantic-typed onboarding/profile endpoints did). This is the
            # same check (modules.text_quality) used there, applied here since
            # `TwinSettingsUpdate.settings` is a raw dict[str, Any].
            #
            # The dashboard always resends the *entire* public_profile /
            # persona_profile object on every save (not just the field the
            # user actually touched), so an exactly-empty string ("") here
            # means "this persona has never had a bio/headline" (pre-existing
            # data), not a fresh garbage submission — skip those to avoid
            # blocking unrelated saves for every already-blank persona. A
            # non-empty string that's all whitespace (e.g. "   ") IS a real
            # submission and must still be rejected, matching the
            # "reject all-whitespace" requirement.
            for _profile_key in ("public_profile", "persona_profile"):
                _profile_dict = incoming_settings.get(_profile_key)
                if not isinstance(_profile_dict, dict):
                    continue
                _bio_value = _profile_dict.get("bio")
                if isinstance(_bio_value, str) and _bio_value != "":
                    _bio_error = meaningful_text_error(_bio_value)
                    if _bio_error:
                        raise HTTPException(status_code=400, detail=_bio_error)
                _headline_value = _profile_dict.get("headline")
                if isinstance(_headline_value, str) and _headline_value != "":
                    _headline_error = meaningful_text_error(
                        _headline_value, min_length=HEADLINE_MIN_LENGTH, min_words=1
                    )
                    if _headline_error:
                        raise HTTPException(status_code=400, detail=_headline_error)

            if "social_links" in incoming_settings:
                incoming_settings["social_links"] = normalize_social_links(incoming_settings.get("social_links"))

            merged_settings.update(incoming_settings)

        if update.is_public is not None:
            widget_settings = dict(merged_settings.get("widget_settings") or {})
            widget_settings["public_share_enabled"] = bool(update.is_public)
            merged_settings["widget_settings"] = widget_settings
            merged_settings["is_public"] = bool(update.is_public)

        update_payload["settings"] = merged_settings

    if not update_payload:
        twin_res = supabase.table("twins").select("*").eq("id", twin_id).single().execute()
        if not twin_res.data:
            raise HTTPException(status_code=404, detail="Twin not found")
        return twin_res.data

    # Capture old bio before overwriting (for change detection)
    old_bio: str | None = None
    if settings_changed and twin_res.data:
        old_bio = (
            (twin_res.data.get("settings") or {})
            .get("public_profile") or {}
        ).get("bio")

    response = supabase.table("twins").update(update_payload).eq("id", twin_id).execute()

    if not response.data:
        # Ownership + existence are already proven above (verify_twin_ownership, and
        # the settings_changed branch 404s on a missing twin), so a 0-row UPDATE here
        # is NOT "twin not found" — it's a silently-filtered write, almost always RLS
        # rejecting a non-service-role client because the twin's tenant_id != the
        # owner's auth.uid(). Fail loud with the same diagnostic /profile uses
        # (TWIN_WRITE_NO_ROWS, #228/#229) instead of a misleading 404 that hid the
        # dropped Publish-tab save.
        logger.error(
            "[twins] twin update affected 0 rows twin_id=%s — write did not persist "
            "(twin exists and is owned; check SUPABASE_SERVICE_KEY is a real service_role key)",
            twin_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Update did not persist", "code": "TWIN_WRITE_NO_ROWS"},
        )

    # Invalidate cached agent when settings change (actions, profile, etc.)
    if settings_changed:
        invalidate_agent(twin_id)

    # Sync bio to Pinecone when explicitly edited (inline — Cloud Run kills background tasks)
    if settings_changed:
        new_bio: str | None = (
            merged_settings.get("public_profile") or {}
        ).get("bio")
        if new_bio and new_bio != old_bio:
            try:
                import asyncio
                await asyncio.wait_for(_sync_bio_to_vectors(twin_id, new_bio), timeout=25)
            except Exception as _bio_exc:
                import logging as _logging
                _logging.getLogger(__name__).warning("[twins] bio Pinecone sync failed (non-fatal): %s", _bio_exc)

    # Settings edits from the dashboard (section visibility, public_profile, etc.)
    # change the public page — refresh its ISR cache on-demand so visitors see the
    # change immediately instead of waiting out the ~1h window. Best-effort.
    if settings_changed:
        handle = merged_settings.get("handle")
        if isinstance(handle, str) and handle:
            await revalidate_persona(handle)

    return response.data

