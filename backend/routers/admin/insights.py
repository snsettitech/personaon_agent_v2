"""Admin: quality insights (response audits, review queue, learning inputs)."""
from fastapi import APIRouter, Depends, Query

from modules.auth_guard import require_admin

from ._common import _safe_query, _supabase

router = APIRouter()


@router.get("/insights/conversation-quality")
def get_conversation_quality(
    limit: int = Query(default=50, le=200),
    user: dict = Depends(require_admin),
) -> list:
    """Response audits showing quality signals."""
    sb = _supabase()
    return _safe_query(
        sb.table("conversation_response_audits")
        .select(
            "id, twin_id, intent_label, workflow_intent, response_action, "
            "confidence_score, refusal_reason, escalation_reason, created_at"
        )
        .order("created_at", desc=True)
        .limit(limit)
    )


@router.get("/insights/review-queue")
def get_review_queue(
    limit: int = Query(default=50, le=200),
    user: dict = Depends(require_admin),
) -> list:
    """Items pending owner review."""
    sb = _supabase()
    return _safe_query(
        sb.table("owner_review_queue")
        .select("id, twin_id, reason, priority, status, created_at, resolved_at")
        .order("created_at", desc=True)
        .limit(limit)
    )


@router.get("/insights/learning-inputs")
def get_learning_inputs(
    limit: int = Query(default=50, le=200),
    user: dict = Depends(require_admin),
) -> list:
    """Feedback/learning inputs submitted by users."""
    sb = _supabase()
    return _safe_query(
        sb.table("learning_inputs")
        .select("id, twin_id, input_type, status, created_at, updated_at, applied_at")
        .order("created_at", desc=True)
        .limit(limit)
    )
