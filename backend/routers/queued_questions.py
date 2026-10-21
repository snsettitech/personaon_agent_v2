"""CRUD endpoints for queued visitor questions (Phase 19 — Three-Bucket Agent)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from modules.auth_guard import require_tenant, verify_twin_ownership
from modules.observability import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["queued-questions"])


@router.get("/v2/queued-questions")
async def list_queued_questions(
    twin_id: str = Query(..., description="Twin ID to list questions for"),
    status: str = Query("pending", description="Filter by status: pending, answered, dismissed"),
    limit: int = Query(20, le=100, ge=1),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """List queued questions for a twin, sorted by ask_count DESC."""
    verify_twin_ownership(twin_id, user)

    sb = get_supabase_client()
    query = (
        sb.table("queued_questions")
        .select("*")
        .eq("twin_id", twin_id)
        .eq("status", status)
        .order("ask_count", desc=True)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    result = query.execute()
    return {"questions": result.data or [], "count": len(result.data or [])}


@router.post("/v2/queued-questions/{question_id}/answer")
async def answer_queued_question(
    question_id: str,
    request: Request,
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """Owner answers a queued question -> ingests to Pinecone + marks answered."""
    from adk_core.services.vector_store import upsert_faq
    from adk_core.services.agent_service import invalidate_agent

    sb = get_supabase_client()

    # Fetch the question row with tenant validation
    row = (
        sb.table("queued_questions")
        .select("*")
        .eq("id", question_id)
        .eq("tenant_id", user["tenant_id"])
        .limit(1)
        .execute()
    )
    if not row.data:
        raise HTTPException(status_code=404, detail="Question not found")

    question_row = row.data[0]

    body = await request.json()
    answer = (body.get("answer") or "").strip()
    if not answer:
        raise HTTPException(status_code=400, detail="answer is required")

    twin_id = str(question_row["twin_id"])
    question_text = question_row["question"]

    # Ingest the Q&A pair to Pinecone
    await upsert_faq(question=question_text, answer=answer, twin_id=twin_id)
    invalidate_agent(twin_id)

    # Mark as answered
    sb.table("queued_questions").update(
        {
            "status": "answered",
            "owner_answer": answer,
            "answered_at": "now()",
            "updated_at": "now()",
        }
    ).eq("id", question_id).execute()

    logger.info("[QueuedQ] answered question %s for twin %s", question_id, twin_id)
    return {"status": "answered", "question_id": question_id}


@router.post("/v2/queued-questions/{question_id}/dismiss")
async def dismiss_queued_question(
    question_id: str,
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """Owner dismisses a queued question."""
    sb = get_supabase_client()

    row = (
        sb.table("queued_questions")
        .select("id, twin_id, tenant_id")
        .eq("id", question_id)
        .eq("tenant_id", user["tenant_id"])
        .limit(1)
        .execute()
    )
    if not row.data:
        raise HTTPException(status_code=404, detail="Question not found")

    sb.table("queued_questions").update(
        {"status": "dismissed", "updated_at": "now()"}
    ).eq("id", question_id).execute()

    logger.info("[QueuedQ] dismissed question %s", question_id)
    return {"status": "dismissed", "question_id": question_id}
