"""
Phase B — Memory Candidates router.

Two endpoints, owner-only:
  GET   /v2/twins/{twin_id}/memory-candidates        — list with optional filters
  PATCH /v2/twins/{twin_id}/memory-candidates/{id}   — approve or dismiss
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from modules.auth_guard import verify_owner, verify_twin_ownership
from modules.observability import supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2/twins/{twin_id}/memory-candidates", tags=["memory"])


def _resolve_tenant(user: dict[str, Any]) -> str:
    return str(user.get("tenant_id") or user.get("user_id") or "")


class CandidateOut(BaseModel):
    id: str
    meeting_id: str | None = None
    contact_id: str | None = None
    kind: Literal["fact", "preference", "context"]
    subject: str
    predicate: str
    text: str
    confidence: float
    status: Literal["pending", "approved", "dismissed", "superseded"]
    created_at: str


class CandidateDecision(BaseModel):
    decision: Literal["approved", "dismissed"]
    notes: str | None = None


@router.get("", response_model=list[CandidateOut])
async def list_candidates(
    twin_id: str,
    status: Literal["pending", "approved", "dismissed", "all"] = Query("pending"),
    contact_id: str | None = Query(None),
    user: dict[str, Any] = Depends(verify_owner),
) -> list[CandidateOut]:
    """List memory candidates for a twin, with optional status/contact filters."""
    verify_twin_ownership(twin_id, user)

    q = supabase.table("memory_candidates").select("*").eq("twin_id", twin_id)
    if status != "all":
        q = q.eq("status", status)
    if contact_id:
        q = q.eq("contact_id", contact_id)

    rows: list[dict[str, Any]] = (
        q.order("created_at", desc=True).execute().data or []
    )

    return [CandidateOut(**r) for r in rows]


@router.patch("/{candidate_id}", response_model=CandidateOut)
async def decide_candidate(
    twin_id: str,
    candidate_id: str,
    body: CandidateDecision,
    user: dict[str, Any] = Depends(verify_owner),
) -> CandidateOut:
    """Approve or dismiss a single memory candidate."""
    verify_twin_ownership(twin_id, user)
    tenant_id = _resolve_tenant(user)

    ts_col = "approved_at" if body.decision == "approved" else "dismissed_at"
    res = (
        supabase.table("memory_candidates")
        .update(
            {
                "status": body.decision,
                ts_col: datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", candidate_id)
        .eq("twin_id", twin_id)          # tenant_scope_mutations rule
        .eq("tenant_id", tenant_id)
        .execute()
    )

    if not res.data:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # Log decision audit record; non-fatal if it fails
    try:
        supabase.table("memory_candidate_decisions").insert(
            {
                "tenant_id": tenant_id,
                "candidate_id": candidate_id,
                "decision": body.decision,
                "notes": body.notes,
            }
        ).execute()
    except Exception:
        logger.exception(
            "[MemCand] decision audit insert failed candidate_id=%s", candidate_id
        )

    return CandidateOut(**res.data[0])
