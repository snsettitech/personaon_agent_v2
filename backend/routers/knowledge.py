import logging
from fastapi import APIRouter, Depends, HTTPException
from modules.auth_guard import verify_owner, get_current_user, verify_twin_ownership

logger = logging.getLogger(__name__)
from modules.schemas import (
    KnowledgeProfile, VerifiedQnASchema, VerifiedQnACreateRequest, VerifiedQnAUpdateRequest
)
from modules.observability import get_knowledge_profile, supabase
from modules.verified_qna import (
    create_verified_qna, list_verified_qna, get_verified_qna, edit_verified_qna
)

router = APIRouter(tags=["knowledge"])
VALID_VISIBILITY_VALUES = {"private", "shared", "public"}

@router.get("/twins/{twin_id}/knowledge-profile", response_model=KnowledgeProfile)
async def knowledge_profile(twin_id: str, user=Depends(get_current_user)):
    # First verify the twin exists
    from modules.observability import supabase
    twin_check = supabase.table("twins").select("id").eq("id", twin_id).limit(1).execute()
    if not twin_check.data:
        raise HTTPException(status_code=404, detail=f"Twin {twin_id} not found")

    # Verify user has access to this twin
    verify_twin_ownership(twin_id, user)

    try:
        profile = await get_knowledge_profile(twin_id)
        return profile
    except Exception as e:
        logger.error("[Knowledge Profile] Error fetching knowledge profile for twin %s: %s", twin_id, e, exc_info=True)

        # Return a safe fallback response instead of 500
        # This ensures the UI doesn't break
        return {
            "total_chunks": 0,
            "total_sources": 0,
            "fact_count": 0,
            "opinion_count": 0,
            "tone_distribution": {},
            "top_tone": "Neutral"
        }

@router.get("/twins/{twin_id}/verified-qa")
@router.get("/twins/{twin_id}/verified-qna")
async def list_twin_verified_qna(twin_id: str, visibility: str | None = None, user=Depends(get_current_user)):
    # Verify user has access to this twin
    verify_twin_ownership(twin_id, user)
    """
    List all verified QnA entries for a twin.
    Optional visibility filter: 'private', 'shared', 'public'
    """
    try:
        qna_list = await list_verified_qna(twin_id, visibility, group_id=None)
        # Format with citations and patches for each entry
        result = []
        for qna in qna_list:
            try:
                full_qna = await get_verified_qna(qna["id"])
                if full_qna:
                    result.append(full_qna)
            except Exception as e:
                # Log error but continue processing other entries
                logger.warning("Error fetching full QnA for %s: %s", qna.get('id'), e)
                # Still include the basic QnA entry even if fetching full details fails
                result.append(qna)
        return result
    except Exception as e:
        logger.error("Error listing verified QnA: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/twins/{twin_id}/verified-qa", response_model=VerifiedQnASchema)
@router.post("/twins/{twin_id}/verified-qna", response_model=VerifiedQnASchema)
async def create_twin_verified_qna(
    twin_id: str,
    request: VerifiedQnACreateRequest,
    user=Depends(verify_owner),
):
    """
    Create a verified QnA entry for a twin.
    """
    verify_twin_ownership(twin_id, user)

    visibility = (request.visibility or "private").strip().lower()
    if visibility not in VALID_VISIBILITY_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid visibility. Allowed values: {', '.join(sorted(VALID_VISIBILITY_VALUES))}",
        )

    try:
        qna_id = await create_verified_qna(
            question=request.question,
            answer=request.answer,
            owner_id=user.get("user_id"),
            citations=request.citations or [],
            twin_id=twin_id,
        )

        # Create path defaults to private visibility; apply requested visibility explicitly.
        if visibility != "private":
            supabase.table("verified_qna").update({"visibility": visibility}).eq("id", qna_id).execute()

        created_qna = await get_verified_qna(qna_id)
        if not created_qna:
            raise HTTPException(status_code=500, detail="Failed to load created verified QnA")
        return created_qna
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/verified-qa/{qna_id}", response_model=VerifiedQnASchema)
@router.get("/verified-qna/{qna_id}", response_model=VerifiedQnASchema)
async def get_verified_qna_endpoint(qna_id: str, user=Depends(verify_owner)):
    """Get specific verified QnA with citations and patch history."""
    try:
        qna = await get_verified_qna(qna_id)
        if not qna:
            raise HTTPException(status_code=404, detail="Verified QnA not found")
        twin_id = qna.get("twin_id")
        if twin_id:
            verify_twin_ownership(twin_id, user)
        return qna
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/verified-qa/{qna_id}")
@router.patch("/verified-qna/{qna_id}")
async def update_verified_qna(qna_id: str, request: VerifiedQnAUpdateRequest, user=Depends(verify_owner)):
    """
    Edit verified answer (creates patch entry for version history).
    Body: { "answer": "...", "reason": "..." }
    """
    try:
        # Verify the QnA belongs to a twin owned by this user before editing
        qna_row = supabase.table("verified_qna").select("twin_id").eq("id", qna_id).single().execute()
        if not qna_row.data:
            raise HTTPException(status_code=404, detail="Verified QnA not found")
        twin_id = qna_row.data.get("twin_id")
        if twin_id:
            verify_twin_ownership(twin_id, user)

        await edit_verified_qna(
            qna_id=qna_id,
            new_answer=request.answer,
            reason=request.reason,
            owner_id=user.get("user_id")
        )
        return {"status": "success", "message": "Verified QnA updated"}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/verified-qa/{qna_id}")
@router.delete("/verified-qna/{qna_id}")
async def delete_verified_qna(qna_id: str, user=Depends(verify_owner)):
    """
    Soft delete verified QnA (set is_active = false).
    """
    try:
        # Check if QnA exists
        qna_res = supabase.table("verified_qna").select("twin_id, twins(tenant_id)").eq("id", qna_id).single().execute()
        if not qna_res.data:
            raise HTTPException(status_code=404, detail="Verified QnA not found")

        # Verify the QnA belongs to a twin in the user's tenant
        twin_tenant_id = qna_res.data.get("twins", {}).get("tenant_id")
        if twin_tenant_id and twin_tenant_id != user.get("tenant_id"):
            raise HTTPException(status_code=403, detail="Verified QnA does not belong to your tenant")

        # Soft delete
        supabase.table("verified_qna").update({"is_active": False}).eq("id", qna_id).execute()

        return {"status": "success", "message": "Verified QnA deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
