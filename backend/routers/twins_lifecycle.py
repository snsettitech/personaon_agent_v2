"""Twins lifecycle endpoints — publish-draft, unpublish, archive, delete."""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from adk_core.services.agent_service import invalidate_agent
from adk_core.services.firecrawl_service import profile_to_text
from adk_core.services.vector_store import upsert_text_chunks
from modules.auth_guard import get_current_user, verify_owner, verify_twin_ownership
from modules.governance import AuditLogger
from modules.observability import supabase
from modules.share_links import is_marketplace_public_twin_record
from routers.twins_helpers import (
    DeleteTwinResponse,
    _require_authenticated_user,
    ensure_twin_owner_or_403,
)

router = APIRouter(tags=["twins"])

logger = logging.getLogger(__name__)


@router.post("/twins/{twin_id}/publish-draft")
async def publish_draft_twin(
    twin_id: str,
    user=Depends(verify_owner),
) -> dict[str, Any]:
    """Activate a draft twin built via the onboarding research flow.

    Sets status=active and enables public sharing so the profile and chat
    endpoints become accessible.

    Execution-board 0.1 (PRD R1): this previously flipped status=active and
    public_share_enabled=True unconditionally on the (false) assumption that
    "the research pipeline already validates data quality" — it does not.
    That is exactly how a live page shipped with headline "software
    engineer" and bio "nill". This now runs the same marketplace-quality
    gate (modules.share_links.is_marketplace_public_twin_record) that
    governs public reachability everywhere else, before making any change,
    so a twin can never be flipped live with a meaningless bio or zero
    populated work_experience/education content.
    """
    user = _require_authenticated_user(user)
    if user.get("role") == "visitor":
        raise HTTPException(status_code=403, detail="Visitor keys cannot modify twin visibility")
    verify_twin_ownership(twin_id, user)
    tenant_id = user.get("tenant_id", "")

    twin_res = (
        supabase.table("twins")
        .select("settings, status")
        .eq("id", twin_id)
        .eq("tenant_id", tenant_id)
        .single()
        .execute()
    )
    if not twin_res.data:
        raise HTTPException(status_code=404, detail="Twin not found")

    current_settings = dict(twin_res.data.get("settings") or {})

    # Quality gate must pass BEFORE status flips to active — checked against
    # what status *would* be post-publish, since the marketplace gate itself
    # requires an active status (chicken-and-egg otherwise).
    quality_check_twin = {**twin_res.data, "status": "active", "settings": current_settings}
    if not is_marketplace_public_twin_record(quality_check_twin):
        raise HTTPException(
            status_code=400,
            detail=(
                "This persona isn't ready to publish yet. Add a real bio "
                "(not a placeholder like 'nill') and at least one work "
                "experience or education entry, then try publishing again."
            ),
        )

    widget_settings = dict(current_settings.get("widget_settings") or {})
    widget_settings["public_share_enabled"] = True
    current_settings["widget_settings"] = widget_settings

    response = (
        supabase.table("twins")
        .update({"status": "active", "settings": current_settings})
        .eq("id", twin_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="Twin not found or update failed")

    # Re-embed persona_profile to Pinecone so the KB reflects any edits the user
    # made on the onboarding preview screen before publishing.
    try:
        persona_profile = current_settings.get("persona_profile") or {}
        profile_text = profile_to_text(persona_profile)
        if profile_text.strip():
            chunk_count = await upsert_text_chunks(
                text=profile_text,
                twin_id=twin_id,
                source="profile",
            )
            logger.info("[publish-draft] re-embedded %d profile chunks for twin %s", chunk_count, twin_id)
    except Exception as _embed_exc:
        logger.warning("[publish-draft] Pinecone re-embed failed (non-fatal): %s", _embed_exc)

    invalidate_agent(twin_id)
    updated = response.data[0]
    return {"id": updated.get("id", twin_id), "status": updated.get("status")}


@router.post("/twins/{twin_id}/unpublish")
async def unpublish_twin(
    twin_id: str,
    user=Depends(verify_owner),
) -> dict[str, Any]:
    """Take a twin offline — sets status=draft and disables public sharing.

    The profile URL, share link, and public chat all return 404 while a twin
    is in draft status. The twin's data is preserved; re-publishing via
    publish-draft restores it instantly.
    """
    user = _require_authenticated_user(user)
    if user.get("role") == "visitor":
        raise HTTPException(status_code=403, detail="Visitor keys cannot modify twin visibility")
    verify_twin_ownership(twin_id, user)
    tenant_id = user.get("tenant_id", "")

    twin_res = (
        supabase.table("twins")
        .select("settings, status")
        .eq("id", twin_id)
        .eq("tenant_id", tenant_id)
        .single()
        .execute()
    )
    if not twin_res.data:
        raise HTTPException(status_code=404, detail="Twin not found")

    current_settings = dict(twin_res.data.get("settings") or {})
    widget_settings = dict(current_settings.get("widget_settings") or {})
    widget_settings["public_share_enabled"] = False
    current_settings["widget_settings"] = widget_settings

    response = (
        supabase.table("twins")
        .update({"status": "draft", "settings": current_settings})
        .eq("id", twin_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="Twin not found or update failed")

    invalidate_agent(twin_id)
    updated = response.data[0]
    return {"id": updated.get("id", twin_id), "status": updated.get("status")}


@router.post("/twins/{twin_id}/archive", response_model=DeleteTwinResponse)
async def archive_twin(twin_id: str, user=Depends(get_current_user)):
    """
    Archive (soft-delete) a twin.
    Sets deleted_at timestamp in settings; twin remains queryable but hidden from listings.
    """
    user = _require_authenticated_user(user)
    ensure_twin_owner_or_403(twin_id, user)

    try:
        twin_res = supabase.table("twins").select("settings").eq("id", twin_id).single().execute()
        if not twin_res.data:
            return DeleteTwinResponse(
                status="not_found",
                twin_id=twin_id,
                message="Twin not found"
            )

        settings = twin_res.data.get("settings") or {}

        if settings.get("deleted_at"):
            return DeleteTwinResponse(
                status="already_archived",
                twin_id=twin_id,
                deleted_at=settings.get("deleted_at"),
                message="Twin is already archived"
            )

        deleted_at = datetime.now(timezone.utc).isoformat()
        settings["deleted_at"] = deleted_at

        update_res = supabase.table("twins").update({
            "settings": settings
        }).eq("id", twin_id).execute()

        if not update_res.data:
            raise HTTPException(status_code=500, detail="Failed to archive twin")

        return DeleteTwinResponse(
            status="archived",
            twin_id=twin_id,
            deleted_at=deleted_at,
            message="Twin archived successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TWINS] ERROR archiving twin: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/twins/{twin_id}", response_model=DeleteTwinResponse)
async def delete_twin(
    twin_id: str,
    hard: bool = Query(False, description="Perform hard delete (permanent)"),
    user=Depends(get_current_user)
):
    """
    Delete a twin.
    - If hard=false (default): Archive (soft-delete) the twin
    - If hard=true: Hard-delete the twin and all associated data
    WARNING: Hard delete is destructive and cannot be undone.
    """
    user = _require_authenticated_user(user)
    ensure_twin_owner_or_403(twin_id, user)

    try:
        twin_res = supabase.table("twins").select("*").eq("id", twin_id).single().execute()
        if not twin_res.data:
            return DeleteTwinResponse(
                status="not_found",
                twin_id=twin_id,
                message="Twin not found"
            )

        twin_name = twin_res.data.get("name", "Unknown")
        twin_tenant_id = twin_res.data.get("tenant_id") or user.get("tenant_id")

        if not hard:
            settings = twin_res.data.get("settings") or {}

            if settings.get("deleted_at"):
                return DeleteTwinResponse(
                    status="already_archived",
                    twin_id=twin_id,
                    deleted_at=settings.get("deleted_at"),
                    message="Twin is already archived"
                )

            deleted_at = datetime.now(timezone.utc).isoformat()
            settings["deleted_at"] = deleted_at

            update_res = supabase.table("twins").update({
                "settings": settings
            }).eq("id", twin_id).execute()

            if not update_res.data:
                raise HTTPException(status_code=500, detail="Failed to archive twin")

            return DeleteTwinResponse(
                status="archived",
                twin_id=twin_id,
                deleted_at=deleted_at,
                message="Twin archived successfully"
            )

        # Hard delete — remove related data first, then the twin
        try:
            # 0. Delete from escalations (does NOT have ON DELETE CASCADE)
            try:
                supabase.table("escalations").delete().eq("twin_id", twin_id).execute()
            except Exception as e:
                logger.warning("[TWINS] Could not delete escalations: %s", e)

            # 1. Delete from persona_specs
            try:
                supabase.table("persona_specs").delete().eq("twin_id", twin_id).execute()
            except Exception as e:
                logger.warning("[TWINS] Could not delete persona_specs: %s", e)

            # 2. Delete from persona_prompt_optimization_runs
            try:
                supabase.table("persona_prompt_optimization_runs").delete().eq("twin_id", twin_id).execute()
            except Exception as e:
                logger.warning("[TWINS] Could not delete optimization runs: %s", e)

            # 3. Delete from persona_prompt_optimization_results
            try:
                supabase.table("persona_prompt_optimization_results").delete().eq("twin_id", twin_id).execute()
            except Exception as e:
                logger.warning("[TWINS] Could not delete optimization results: %s", e)

            # 4. Delete from memory_events
            try:
                supabase.table("memory_events").delete().eq("twin_id", twin_id).execute()
            except Exception as e:
                logger.warning("[TWINS] Could not delete memory events: %s", e)

            # 5. Delete from twin_verifications
            try:
                supabase.table("twin_verifications").delete().eq("twin_id", twin_id).execute()
            except Exception as e:
                logger.warning("[TWINS] Could not delete verifications: %s", e)

            # 6. Delete from access_groups (cascades to memberships and permissions)
            try:
                supabase.table("access_groups").delete().eq("twin_id", twin_id).execute()
            except Exception as e:
                logger.warning("[TWINS] Could not delete access groups: %s", e)

            # 7. Delete from owner memory tables
            try:
                supabase.table("owner_memory_snapshots").delete().eq("twin_id", twin_id).execute()
                supabase.table("owner_memory_entries").delete().eq("twin_id", twin_id).execute()
            except Exception as e:
                logger.warning("[TWINS] Could not delete owner memory: %s", e)

            # 8. Delete from training tables
            try:
                supabase.table("training_decisions").delete().eq("twin_id", twin_id).execute()
                supabase.table("training_interactions").delete().eq("twin_id", twin_id).execute()
                supabase.table("training_sessions").delete().eq("twin_id", twin_id).execute()
            except Exception as e:
                logger.warning("[TWINS] Could not delete training data: %s", e)

            # 9. Delete sources (cascades to chunks via FK)
            try:
                supabase.table("sources").delete().eq("twin_id", twin_id).execute()
            except Exception as e:
                logger.warning("[TWINS] Could not delete sources: %s", e)

            # 10. Delete conversations (cascades to messages)
            try:
                supabase.table("conversations").delete().eq("twin_id", twin_id).execute()
            except Exception as e:
                logger.warning("[TWINS] Could not delete conversations: %s", e)

            # 11. Delete pgvector chunks for this twin
            try:
                from adk_core.services.vector_store import delete_namespace
                await delete_namespace(twin_id)
                logger.info("[TWINS] Deleted pgvector chunks for twin: %s", twin_id)
            except Exception as e:
                logger.warning("[TWINS] Could not delete pgvector chunks: %s", e)

            # 12. Finally delete the twin — scoped by BOTH id AND tenant_id
            delete_res = (
                supabase.table("twins")
                .delete()
                .eq("id", twin_id)
                .eq("tenant_id", twin_tenant_id)
                .execute()
            )

            if not delete_res.data:
                raise HTTPException(status_code=500, detail="Failed to delete twin from database")

            try:
                audit_logger = AuditLogger(supabase)
                await audit_logger.log(
                    event_type="twin_deleted",
                    user_id=user.get("user_id"),
                    twin_id=twin_id,
                    details={"twin_name": twin_name, "hard_delete": True}
                )
            except Exception as e:
                logger.warning("[TWINS] Could not write audit log: %s", e)

            return DeleteTwinResponse(
                status="deleted",
                twin_id=twin_id,
                cleanup_status="done",
                message="Twin permanently deleted"
            )

        except Exception as inner_e:
            error_msg = str(inner_e).lower()
            if "foreign key" in error_msg or "constraint" in error_msg:
                logger.error("[TWINS] Foreign key constraint error deleting twin %s: %s", twin_id, inner_e)
                raise HTTPException(
                    status_code=409,
                    detail="Cannot delete twin: related data exists. Please try archiving instead."
                )
            raise

    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TWINS] ERROR deleting twin %s: %s", twin_id, e)
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")
