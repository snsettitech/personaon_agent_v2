"""Auto-create twin — instant activation with background enrichment.

POST /v2/twins/auto-create
  → Creates twin in Supabase (status: "active") with profile data from form
  → Enqueues background enrichment job (Firecrawl + vector upsert)
  → Returns immediately with {twin_id, status: "active", poll_url}

The twin is immediately usable with the basic profile the user entered.
The background worker enriches the knowledge base asynchronously.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, TypedDict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from adk_core.services.firecrawl_service import (
    extract_profile,
    is_profile_rich,
    profile_to_text,
    validate_profile_against_snapshot,
)
from adk_core.services.vector_store import upsert_text_chunks
from modules.auth_guard import (
    get_current_user,
    require_tenant,
    resolve_tenant_id,
    verify_twin_ownership,
)
from modules.observability import get_supabase_client
from modules.posthog_analytics import ph_capture
from modules.profile_utils import (
    generate_contextual_questions,
    select_best_linkedin_account,
    user_has_linkedin_provider,
)
from modules.runtime_kill_switches import signups_enabled
from modules.tenant_guard import derive_creator_ids
from modules.theme_lookup import infer_default_theme_id

# DB status values allowed by twins_status_check constraint.
# Our logical statuses map to these:
#   "generating" → "draft" (in-progress creation)
#   "needs_input" → "claims_ready" (needs user action)
#   "failed" → "draft" (can retry)
#   "active" → "active"
_STATUS_MAP = {
    "generating": "draft",
    "needs_input": "claims_ready",
    "failed": "draft",
    "active": "active",
}


class ExtractionOutcome(TypedDict):
    state: str
    db_status: str
    chunk_count: int
    vector_indexed: bool
    publishable: bool
    failure_reason: str | None


def _build_extraction_outcome(
    state: str,
    *,
    chunk_count: int,
    vector_indexed: bool,
    failure_reason: str | None = None,
) -> ExtractionOutcome:
    db_status = _STATUS_MAP.get(state, "draft")
    return {
        "state": state,
        "db_status": db_status,
        "chunk_count": chunk_count,
        "vector_indexed": vector_indexed,
        "publishable": (
            state == "active"
            and db_status == "active"
            and vector_indexed
            and chunk_count > 0
            and failure_reason is None
        ),
        "failure_reason": failure_reason,
    }

logger = logging.getLogger(__name__)

router = APIRouter(tags=["twins-v2"])


# ── Request / Response schemas ───────────────────────────────────────


class AutoCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    context: str | None = Field(
        None,
        max_length=500,
        description="Optional context like 'CEO at Acme Corp' to help disambiguation",
    )
    linkedin_url: str | None = Field(
        None,
        max_length=500,
        description="LinkedIn profile URL — used as identity anchor for Firecrawl. "
                    "Overrides snapshot URL if the snapshot has none (e.g. LinkedIn OIDC).",
    )


class AutoCreateResponse(BaseModel):
    twin_id: str
    status: str
    poll_url: str


# ── Handle generation ────────────────────────────────────────────────


def _slugify(name: str) -> str:
    """Convert a name to a URL-safe handle."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s-]+", "-", slug)
    return slug.strip("-")[:60]


def _sanitize_name(name: str) -> str:
    """Strip HTML tags and instruction-like patterns from name input."""
    import re as _re
    # Strip HTML tags (don't html.escape — that breaks O'Brien → O&#x27;Brien for search)
    cleaned = _re.sub(r"<[^>]+>", "", name.strip())
    # Reject obvious prompt injection attempts
    suspicious = ["ignore previous", "system prompt", "you are now", "act as"]
    lower = cleaned.lower()
    for pattern in suspicious:
        if pattern in lower:
            raise HTTPException(
                status_code=400,
                detail="Name contains invalid characters. Please use a real person's name.",
            )
    return cleaned


def _sanitize_context(context: str) -> str:
    """Strip HTML and reject prompt injection patterns from context field."""
    import re as _re
    cleaned = _re.sub(r"<[^>]+>", "", context.strip())
    suspicious = ["ignore previous", "system prompt", "you are now", "act as", "disregard"]
    lower = cleaned.lower()
    for pattern in suspicious:
        if pattern in lower:
            raise HTTPException(
                status_code=400,
                detail="Context contains invalid content. Please describe your professional background.",
            )
    return cleaned[:500]


def _generate_suggested_questions(profile: dict) -> list[str]:
    """Generate contextual starter questions from profile data."""
    return generate_contextual_questions(profile, limit=6)


async def _run_extraction(
    twin_id: str,
    name: str,
    context: str | None,
    linkedin_url: str | None = None,
    linkedin_snapshot: dict | None = None,
    tenant_id: str = "",
) -> ExtractionOutcome:
    """Background task: extract profile via Firecrawl, update twin, embed in vector store."""
    sb = get_supabase_client()
    logical_status = "failed"
    chunk_count = 0
    vector_indexed = False
    failure_reason: str | None = None

    try:
        logger.info(
            "[AutoCreate] starting extraction for twin %s (%s) linkedin=%s",
            twin_id, name, linkedin_url or "none",
        )

        profile = await asyncio.to_thread(extract_profile, name, context, linkedin_url)

        # Validate extracted profile against LinkedIn OAuth snapshot.
        # This discards hallucinated fields (e.g. wrong education, wrong work history)
        # and overwrites name/occupation/image with verified OAuth values.
        if linkedin_snapshot:
            profile = validate_profile_against_snapshot(profile, linkedin_snapshot)

        # Store profile fields inside settings JSON (twins table has no profile columns)
        # First, fetch existing settings
        existing = sb.table("twins").select("settings").eq("id", twin_id).single().execute()
        current_settings = (existing.data or {}).get("settings") or {}

        # Merge profile data into settings — strip internal validation metadata before storing
        profile.pop("_validation", None)
        profile_fields = {}
        for field in (
            "name", "occupation", "birth_year", "death_year", "nationality",
            "short_description", "image_url", "personality_traits",
            "speaking_style", "education", "work_experience",
            "key_achievements", "areas_of_expertise", "contributions",
            "social_links",
        ):
            if field in profile and profile[field]:
                profile_fields[field] = profile[field]

        # Carry through owner-only extraction-review flags. The allow-list above
        # intentionally drops unknown fields, but extraction_review is internal
        # metadata that powers the owner-confirm review card, so persist it
        # explicitly into settings.persona_profile. It is never exposed publicly
        # (stripped by the public-profile redactor).
        if profile.get("extraction_review"):
            profile_fields["extraction_review"] = profile["extraction_review"]

        # Generate suggested questions from extracted profile
        suggested_questions = _generate_suggested_questions(profile_fields)
        if suggested_questions:
            profile_fields["suggested_questions"] = suggested_questions

        # Check quality threshold
        if is_profile_rich(profile):
            logical_status = "active"
        else:
            logical_status = "needs_input"
            failure_reason = "profile_needs_input"

        # ── Write 1: save profile + mark as indexing ──────────────────
        # Keep state as "indexing" (not yet active) while Pinecone upsert runs.
        # This prevents the chat agent being hit with an empty KB if anything
        # polls status between the DB write and the upsert completing.
        # indexing_started_at is recorded so the expiry guard uses this timestamp
        # rather than created_at (which is already 60-120s old by this point).
        from datetime import datetime
        from datetime import timezone as _tz
        indexing_settings = {
            **current_settings,
            "persona_profile": profile_fields,
            "auto_create_state": "indexing",
            "indexing_started_at": datetime.now(_tz.utc).isoformat(),
        }
        q = sb.table("twins").update({"settings": indexing_settings}).eq("id", twin_id)
        if tenant_id:
            q = q.eq("tenant_id", tenant_id)
        q.execute()

        # ── Vector upsert — must finish before we flip to active ────
        profile_text = profile_to_text(profile)
        if profile_text.strip():
            try:
                import uuid as _uuid
                firecrawl_source_id = str(_uuid.uuid4())

                # Create (or replace) the sources row BEFORE upserting chunks,
                # so the FK constraint on chunks.source_id is satisfied.
                # Delete-then-insert guards against duplicate rows on retries.
                # Also clean up the placeholder "Profile Enrichment" row created
                # by _enqueue_enrichment() to avoid orphaned sources entries.
                try:
                    sb.table("sources").delete().eq("twin_id", twin_id).in_("filename", ["Profile.md", "Firecrawl Profile", "Profile Enrichment"]).execute()
                    sb.table("sources").insert({
                        "id": firecrawl_source_id,
                        "twin_id": twin_id,
                        "filename": "Profile.md",
                        "content_text": profile_text,
                        "extracted_text_length": len(profile_text),
                        "status": "pending",
                        "chunk_count": 0,  # updated below once we know the real count
                        "last_step": "indexing",
                        "health_status": "healthy",
                        "last_provider": "firecrawl",
                        "is_verified_content": True,
                    }).execute()
                    logger.info("[AutoCreate] created sources row for Firecrawl profile (twin %s)", twin_id)
                except Exception as src_exc:
                    logger.warning("[AutoCreate] sources row insert failed for twin %s (non-fatal): %s", twin_id, src_exc)

                chunk_count = await upsert_text_chunks(
                    text=profile_text,
                    twin_id=twin_id,
                    source="profile",
                    source_id=firecrawl_source_id,
                )
                logger.info("[AutoCreate] embedded %d profile chunks for twin %s", chunk_count, twin_id)
                vector_indexed = chunk_count > 0
                if chunk_count <= 0:
                    logical_status = "needs_input"
                    failure_reason = "empty_vector_index"

                # Patch the chunk_count now that we know the real value.
                try:
                    sb.table("sources").update({
                        "status": "live" if vector_indexed else "failed",
                        "chunk_count": chunk_count,
                        "last_step": "indexed" if vector_indexed else "needs_input",
                        "health_status": "healthy" if vector_indexed else "unhealthy",
                    }).eq("id", firecrawl_source_id).execute()
                except Exception as patch_exc:
                    logger.debug("[AutoCreate] chunk_count patch skipped (non-fatal): %s", patch_exc)

            except Exception as vector_exc:
                # Save profile fields, but fail closed so the worker can retry
                # instead of publishing a twin with an empty KB.
                logger.error(
                    "[AutoCreate] vector upsert failed for twin %s: %s",
                    twin_id, vector_exc,
                )
                # Override status to needs_input so the user knows to check KB
                logical_status = "needs_input"
                failure_reason = "vector_upsert_failed"
                vector_indexed = False
                if "firecrawl_source_id" in locals():
                    try:
                        sb.table("sources").update({
                            "status": "failed",
                            "last_step": "vector_failed",
                            "health_status": "unhealthy",
                        }).eq("id", firecrawl_source_id).execute()
                    except Exception as patch_exc:
                        logger.debug("[AutoCreate] vector failure source patch skipped: %s", patch_exc)
        else:
            logger.warning("[AutoCreate] profile_text empty after extraction for twin %s — KB will be empty", twin_id)

        # ── Write 2: KB is ready — flip to active/needs_input ────────
        if not profile_text.strip():
            logical_status = "needs_input"
            failure_reason = "empty_profile_text"

        outcome = _build_extraction_outcome(
            logical_status,
            chunk_count=chunk_count,
            vector_indexed=vector_indexed,
            failure_reason=failure_reason,
        )
        final_settings = {**indexing_settings, "auto_create_state": logical_status}
        update_data: dict[str, Any] = {"settings": final_settings, "status": outcome["db_status"]}
        try:
            q = sb.table("twins").update(update_data).eq("id", twin_id)
            if tenant_id:
                q = q.eq("tenant_id", tenant_id)
            q.execute()
        except Exception as update_exc:
            if "status" in str(update_exc).lower():
                update_data.pop("status", None)
                q = sb.table("twins").update(update_data).eq("id", twin_id)
                if tenant_id:
                    q = q.eq("tenant_id", tenant_id)
                q.execute()
            else:
                raise
        logger.info("[AutoCreate] twin %s → %s (KB ready)", twin_id, logical_status)

        # Recompute training metrics now that sources row + Pinecone are populated.
        # This prevents the race where the first GET /twins/{id} poll (during the
        # progress screen, ~3s post-extraction) computes metrics before the sources
        # row exists and caches mind_score=0 for 1 hour.
        try:
            from modules.training_metrics import update_twin_training_metrics
            update_twin_training_metrics(twin_id)
            logger.info("[AutoCreate] training metrics updated for twin %s", twin_id)
        except Exception as metrics_exc:
            logger.warning("[AutoCreate] metrics update failed for twin %s (non-fatal): %s", twin_id, metrics_exc)

        return outcome

    except Exception as _exc:
        import traceback as _tb
        _err_msg = f"{type(_exc).__name__}: {_exc}"
        _err_trace = _tb.format_exc()[-1000:]  # last 1000 chars of traceback
        logger.exception("[AutoCreate] extraction failed for twin %s: %s", twin_id, _err_msg)
        try:
            _fetch = sb.table("twins").select("settings").eq("id", twin_id).single().execute()
            existing_settings = (_fetch.data or {}).get("settings") or {}
            q = sb.table("twins").update({
                "status": "draft",
                "settings": existing_settings | {
                    "auto_create_state": "failed",
                    "extraction_error": _err_msg,
                    "extraction_traceback": _err_trace,
                },
            }).eq("id", twin_id)
            if tenant_id:
                q = q.eq("tenant_id", tenant_id)
            q.execute()
        except Exception:
            logger.exception("[AutoCreate] failed to update twin status to 'failed'")
        return _build_extraction_outcome(
            "failed",
            chunk_count=chunk_count,
            vector_indexed=False,
            failure_reason="extraction_failed",
        )


# ── Status expiry guard ──────────────────────────────────────────────


def _expire_stuck_generating(twin: dict) -> dict:
    """If a twin has been stuck in 'generating' or 'indexing' too long, flip to 'failed'.

    Thresholds:
      'generating' — 150s from created_at. Intentionally larger than the 120s
                     Firecrawl timeout so a running extraction is never expired early.
      'indexing'   — 45s from indexing_started_at (stored by _run_extraction at Write 1).
                     Pinecone upsert is fast; 45s is a generous cap. We cannot use
                     created_at here because by the time we enter indexing state the
                     twin is already 60-120s old, so the 150s guard would fire immediately.
    """
    from datetime import datetime, timedelta, timezone

    settings = twin.get("settings") or {}
    state = settings.get("auto_create_state", "")
    if state not in ("generating", "indexing"):
        return twin

    try:
        now = datetime.now(timezone.utc)

        if state == "indexing":
            # Use indexing_started_at for the indexing window
            raw_ts = settings.get("indexing_started_at", "")
            threshold = timedelta(seconds=45)
        else:
            # Use created_at for the generating window
            raw_ts = twin.get("created_at", "")
            threshold = timedelta(seconds=150)

        if not raw_ts:
            return twin

        if raw_ts.endswith("Z"):
            raw_ts = raw_ts[:-1] + "+00:00"
        ref_dt = datetime.fromisoformat(raw_ts)

        if now - ref_dt > threshold:
            sb = get_supabase_client()
            new_settings = {**settings, "auto_create_state": "failed"}
            q = sb.table("twins").update({"settings": new_settings}).eq("id", twin["id"])
            if twin.get("tenant_id"):
                q = q.eq("tenant_id", twin["tenant_id"])
            q.execute()
            twin = {**twin, "settings": new_settings}
            logger.info("[AutoCreate] expired stuck twin %s (state=%s) → failed", twin["id"], state)
    except Exception:
        pass

    return twin


# ── Enrichment job enqueue ───────────────────────────────────────────


def _enqueue_enrichment(
    twin_id: str,
    name: str,
    context: str | None,
    linkedin_url: str | None,
    linkedin_snapshot: dict | None,
    tenant_id: str = "",
) -> None:
    """Enqueue a background enrichment job for the worker.

    Creates a placeholder source row (type='profile_enrichment') and a
    training_jobs entry so the existing worker picks it up.  The worker
    runs Firecrawl extraction + vector upsert asynchronously.
    """
    import uuid as _uuid

    from modules.training_jobs import create_training_job

    sb = get_supabase_client()
    source_id = str(_uuid.uuid4())

    # Create a placeholder source row the training_jobs FK references.
    try:
        sb.table("sources").insert({
            "id": source_id,
            "twin_id": twin_id,
            "filename": "Profile Enrichment",
            "content_text": f"Pending enrichment for {name}",
            "extracted_text_length": 0,
            "status": "pending",
            "last_step": "queued",
            "health_status": "healthy",
            "last_provider": "firecrawl",
        }).execute()
    except Exception as src_exc:
        logger.warning("[AutoCreate] source row insert failed (non-fatal): %s", src_exc)
        return  # Enrichment will be skipped but twin is still active

    # Create the training job — worker dispatches based on metadata.
    try:
        create_training_job(
            source_id=source_id,
            twin_id=twin_id,
            job_type="ingestion",
            priority=5,  # Higher priority than normal ingestion
            metadata={
                "enrichment_type": "profile_enrichment",
                "name": name,
                "context": _sanitize_context(context) if context else None,
                "linkedin_url": linkedin_url,
                "linkedin_snapshot": linkedin_snapshot or {},
                "tenant_id": tenant_id,
            },
        )
        logger.info("[AutoCreate] enqueued enrichment job for twin %s", twin_id)
    except Exception as job_exc:
        logger.warning("[AutoCreate] enrichment job enqueue failed (non-fatal): %s", job_exc)


# ── Endpoint ─────────────────────────────────────────────────────────


@router.post("/v2/twins/auto-create", response_model=AutoCreateResponse)
async def auto_create_twin(request: AutoCreateRequest, user=Depends(get_current_user)):
    """Create a twin with instant activation.

    Creates the twin row with status=active using profile data the user
    already entered in the frontend form. Enqueues a background enrichment
    job for Firecrawl extraction + vector embedding. Returns immediately
    (< 1 second) so the user never waits.
    """
    # Runtime kill-switch (execution-board 0.10 / PRD NFR-3): checked first,
    # before auth resolution, so an ops-triggered pause is a clean 503 rather
    # than a broken/cryptic failure further down the pipeline.
    if not signups_enabled():
        raise HTTPException(
            status_code=503,
            detail="Signups are temporarily paused. Please check back soon.",
        )
    if not user or not user.get("user_id"):
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = user["user_id"]
    email = user.get("email", "")
    tenant_id = resolve_tenant_id(user_id, email)

    # ── Identity verification: prefer LinkedIn connected account ──────
    best_linkedin_account = None
    if user_has_linkedin_provider(user):
        sb_pre = get_supabase_client()
        linkedin_result = (
            sb_pre.table("connected_accounts")
            .select("provider, profile_snapshot, provider_user_id")
            .eq("user_id", user_id)
            .in_("provider", ["linkedin", "linkedin_oidc"])
            .execute()
        )
        best_linkedin_account = select_best_linkedin_account(linkedin_result.data or [])
    linkedin_snapshot = (best_linkedin_account or {}).get("profile_snapshot") or {}

    if linkedin_snapshot.get("display_name"):
        # Use verified LinkedIn identity — ignore user-supplied name
        name = _sanitize_name(linkedin_snapshot["display_name"])
        identity_verified = True
        identity_source = "linkedin"
    else:
        # No LinkedIn — allow manual name but mark as unverified
        name = _sanitize_name(request.name)
        identity_verified = False
        identity_source = "manual"

    handle = _slugify(name)

    sb = get_supabase_client()

    # Idempotency: check for existing twin with same name
    existing = (
        sb.table("twins")
        .select("id, status, name, settings")
        .eq("tenant_id", tenant_id)
        .eq("name", name)
        .execute()
    )
    for row in existing.data or []:
        settings = row.get("settings") or {}
        if not settings.get("deleted_at"):
            # Return existing twin
            return AutoCreateResponse(
                twin_id=row["id"],
                status=row.get("status", "active"),
                poll_url=f"/v2/twins/{row['id']}",
            )

    # ── Build initial profile from form data ──────────────────────────
    # The persona is usable immediately with this data; Firecrawl
    # enrichment runs in the background via the worker.
    initial_persona_profile: dict[str, Any] = {"name": name}
    if request.context:
        initial_persona_profile["short_description"] = request.context
    if linkedin_snapshot.get("headline"):
        initial_persona_profile["occupation"] = linkedin_snapshot["headline"]
    if linkedin_snapshot.get("image_url"):
        initial_persona_profile["image_url"] = linkedin_snapshot["image_url"]

    # Create twin row with status "active" — immediately usable.
    creator_ids = derive_creator_ids(user) or [f"tenant_{tenant_id}"]

    # execution-board 0.3: pick a role-appropriate default theme so a
    # non-customizing signup never silently lands on Classic (the weakest,
    # least-branded shell). Uses the verified LinkedIn headline when present,
    # else the user-supplied onboarding context.
    default_theme_id = infer_default_theme_id(
        linkedin_snapshot.get("headline"),
        request.context,
    )

    insert_data: dict[str, Any] = {
        "name": name,
        "tenant_id": tenant_id,
        "creator_id": creator_ids[0],
        "description": f"{name}'s AI persona",
        "status": "active",
        "settings": {
            "owner_user_id": user_id,
            "creation_mode": "auto_create",
            "handle": handle,
            "auto_create_state": "active",
            "identity_verified": identity_verified,
            "identity_source": identity_source,
            "widget_settings": {"public_share_enabled": False},
            "public_profile": {"theme_id": default_theme_id},
            # Default ON for new signups (founder decision 2026-07-03): the
            # Page pillar's core differentiator (visitor chats -> shares
            # contact -> owner notified) was silently opt-in and 0/27 live
            # personas had ever enabled it. Owners can still turn it off in
            # dashboard/widget/settings.
            "lead_capture_enabled": True,
        },
    }

    # Insert with retry — strip columns that don't exist in this schema version.
    # On duplicate key (race: two simultaneous requests both passed the idempotency
    # SELECT before either INSERT committed), fetch the winner and return it.
    resp = None
    removed_columns: set[str] = set()
    while True:
        try:
            resp = sb.table("twins").insert(insert_data).execute()
            break
        except Exception as exc:
            exc_msg = str(exc).lower()

            # Duplicate key — a concurrent request won the race; return that twin.
            if "duplicate" in exc_msg or "unique" in exc_msg or "23505" in exc_msg:
                logger.info("[AutoCreate] duplicate key race for user %s, fetching winner", user_id)
                race_existing = (
                    sb.table("twins")
                    .select("id, status, settings")
                    .eq("tenant_id", tenant_id)
                    .eq("name", name)
                    .execute()
                )
                for row in race_existing.data or []:
                    if not (row.get("settings") or {}).get("deleted_at"):
                        return AutoCreateResponse(
                            twin_id=row["id"],
                            status=row.get("status", "active"),
                            poll_url=f"/v2/twins/{row['id']}",
                        )
                raise HTTPException(status_code=500, detail="Failed to create twin")

            stripped = None
            for col in ("status", "creation_mode"):
                if col in insert_data and "column" in exc_msg and col in exc_msg:
                    stripped = col
                    break
            if stripped:
                removed_columns.add(stripped)
                insert_data.pop(stripped, None)
                logger.info("[AutoCreate] stripped missing column '%s', retrying", stripped)
                continue
            raise

    if not resp.data:
        raise HTTPException(status_code=500, detail="Failed to create twin")

    twin = resp.data[0]
    twin_id = twin["id"]
    logger.info("[AutoCreate] created twin %s for user %s (instant-active)", twin_id, user_id)

    # ── Resolve LinkedIn URL for enrichment ───────────────────────────
    from modules.profile_utils import (
        is_synthesized_linkedin_url,
        normalize_linkedin_profile_url,
    )
    raw_linkedin_url = (
        linkedin_snapshot.get("profile_url")
        or linkedin_snapshot.get("linkedin_url")
        or request.linkedin_url
        or ""
    )
    provider_user_id = (best_linkedin_account or {}).get("provider_user_id", "")
    linkedin_url: str | None = None
    if raw_linkedin_url and not is_synthesized_linkedin_url(raw_linkedin_url, provider_user_id):
        linkedin_url = normalize_linkedin_profile_url(raw_linkedin_url) or None

    context_parts: list[str] = []
    if linkedin_snapshot.get("headline"):
        context_parts.append(linkedin_snapshot["headline"])
    if request.context:
        context_parts.append(_sanitize_context(request.context))
    extraction_context = ", ".join(context_parts) or None

    # ── Enqueue background enrichment job ─────────────────────────────
    # The worker will run Firecrawl extraction + vector upsert asynchronously.
    # The twin is already active and chateable with basic profile data.
    _enqueue_enrichment(
        twin_id=twin_id,
        name=name,
        context=extraction_context,
        linkedin_url=linkedin_url,
        linkedin_snapshot=linkedin_snapshot,
        tenant_id=tenant_id,
    )

    ph_capture(user_id=user_id, event="twin_created", properties={
        "twin_id": twin_id,
        "name": name,
        "status": "active",
        "creation_mode": "auto_create_instant",
    })

    return AutoCreateResponse(
        twin_id=twin_id,
        status="active",
        poll_url=f"/twins/{twin_id}",
    )


# ── LinkedIn identity verification ──────────────────────────────────────────

@router.post("/v2/twins/{twin_id}/verify-linkedin")
async def verify_linkedin_identity(
    twin_id: str,
    user: dict = Depends(require_tenant),
):
    """Mark a twin as LinkedIn-verified once the user has a connected LinkedIn account.

    Call this after the user completes LinkedIn OAuth from the dashboard.
    Checks connected_accounts for a linkedin/linkedin_oidc provider and, if
    found, sets settings.identity_verified=True and identity_source='linkedin'.
    """
    verify_twin_ownership(twin_id, user)

    sb = get_supabase_client()

    linkedin_accounts = (
        sb.table("connected_accounts")
        .select("provider, provider_user_id, profile_snapshot")
        .eq("user_id", user["user_id"])
        .in_("provider", ["linkedin", "linkedin_oidc"])
        .execute()
    )
    best_account = select_best_linkedin_account(linkedin_accounts.data or [])
    if not best_account:
        raise HTTPException(
            status_code=400,
            detail="No LinkedIn account connected. Please connect LinkedIn first.",
        )

    twin_resp = sb.table("twins").select("settings").eq("id", twin_id).single().execute()
    if not twin_resp.data:
        raise HTTPException(status_code=404, detail="Twin not found.")

    settings = dict(twin_resp.data.get("settings") or {})
    snapshot = best_account.get("profile_snapshot") or {}
    identity_snapshot = {
        "provider": best_account.get("provider"),
        "provider_user_id": best_account.get("provider_user_id"),
        "display_name": snapshot.get("display_name") or "",
        "first_name": snapshot.get("first_name") or "",
        "last_name": snapshot.get("last_name") or "",
        "image_url": snapshot.get("image_url") or "",
        "email": snapshot.get("email") or "",
        "email_verified": snapshot.get("email_verified"),
        "locale": snapshot.get("locale") or "",
        "profile_url": snapshot.get("profile_url") or "",
        "headline": snapshot.get("headline") or "",
    }
    public_profile = dict(settings.get("public_profile") or {})
    public_profile["verified_profile"] = True
    if identity_snapshot["profile_url"]:
        social_links = dict(public_profile.get("social_links") or {})
        social_links.setdefault("linkedin", identity_snapshot["profile_url"])
        public_profile["social_links"] = social_links

    settings["identity_verified"] = True
    settings["identity_source"] = "linkedin"
    settings["identity_snapshot"] = identity_snapshot
    settings["public_profile"] = public_profile

    q = sb.table("twins").update({"settings": settings}).eq("id", twin_id)
    tenant_id = user.get("tenant_id", "")
    if tenant_id:
        q = q.eq("tenant_id", tenant_id)
    q.execute()
    logger.info("[VerifyLinkedIn] twin %s marked as LinkedIn-verified", twin_id)

    return {
        "verified": True,
        "identity_source": "linkedin",
        "identity_snapshot": identity_snapshot,
    }
