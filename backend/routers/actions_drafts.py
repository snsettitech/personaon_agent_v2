"""Owner-scoped action drafts API (Home v1 "Respond").

Drafts are pending action proposals (e.g. a follow-up email the assistant
wrote) awaiting the owner's approval. Listing / approve / discard are
owner-only. Approve ENQUEUES the send via graph_outbox — it never executes
inline (the SSE chat stream must stay fast; SMTP/Resend happens in the worker).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from modules.auth_guard import require_tenant, verify_twin_ownership
from modules.graph_outbox import GraphOperationType, get_graph_outbox
from modules.observability import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["actions"])

_DRAFT_COLUMNS = "id, twin_id, status, proposed_action, context, created_at, expires_at"


class DraftSummary(BaseModel):
    id: str
    twin_id: str
    status: str
    proposed_action: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    expires_at: str | None = None


class DraftListData(BaseModel):
    drafts: list[DraftSummary]


class DraftListResponse(BaseModel):
    status: str = "ok"
    data: DraftListData


class DraftActionData(BaseModel):
    draft_id: str
    status: str
    job_id: str | None = None


class DraftActionResponse(BaseModel):
    status: str = "ok"
    data: DraftActionData


def _load_owned_draft(twin_id: str, draft_id: str, tenant_id: str) -> dict[str, Any]:
    """Load a draft scoped to twin + tenant, or raise 404.

    The service-role client bypasses RLS, so the tenant_id filter here is the
    real ownership boundary — never rely on RLS alone for these queries.
    """
    sb = get_supabase_client()
    resp = (
        sb.table("action_drafts")
        .select(_DRAFT_COLUMNS)
        .eq("id", draft_id)
        .eq("twin_id", twin_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    draft = getattr(resp, "data", None)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@router.get("/v2/actions/{twin_id}/drafts", response_model=DraftListResponse)
async def list_drafts(
    twin_id: str,
    user: dict = Depends(require_tenant),
) -> DraftListResponse:
    """List pending drafts for the owner's twin."""
    verify_twin_ownership(twin_id, user)
    tenant_id = user["tenant_id"]

    sb = get_supabase_client()
    resp = (
        sb.table("action_drafts")
        .select(_DRAFT_COLUMNS)
        .eq("twin_id", twin_id)
        .eq("tenant_id", tenant_id)
        .eq("status", "pending")
        .order("created_at", desc=True)
        .execute()
    )
    rows = resp.data if resp.data else []
    return DraftListResponse(data=DraftListData(drafts=[DraftSummary(**row) for row in rows]))


@router.post("/v2/actions/{twin_id}/drafts/{draft_id}/approve", response_model=DraftActionResponse)
async def approve_draft(
    twin_id: str,
    draft_id: str,
    user: dict = Depends(require_tenant),
) -> DraftActionResponse:
    """Approve a pending draft and ENQUEUE the send (never inline)."""
    verify_twin_ownership(twin_id, user)
    tenant_id = user["tenant_id"]

    draft = _load_owned_draft(twin_id, draft_id, tenant_id)
    if draft.get("status") != "pending":
        raise HTTPException(status_code=409, detail="Draft is not pending")

    sb = get_supabase_client()
    sb.table("action_drafts").update({"status": "approved"}).eq(
        "id", draft_id
    ).eq("tenant_id", tenant_id).execute()

    job_id = get_graph_outbox().submit(
        tenant_id=tenant_id,
        twin_id=twin_id,
        operation=GraphOperationType.SEND_FOLLOWUP_DRAFT,
        idempotency_key=f"send_followup:{draft_id}",
        payload={"draft_id": draft_id, "tenant_id": tenant_id},
    )

    logger.info(
        "[Drafts] approved draft_id=%s twin_id=%s job_id=%s", draft_id, twin_id, job_id
    )
    return DraftActionResponse(
        data=DraftActionData(draft_id=draft_id, status="approved", job_id=job_id)
    )


@router.post("/v2/actions/{twin_id}/drafts/{draft_id}/discard", response_model=DraftActionResponse)
async def discard_draft(
    twin_id: str,
    draft_id: str,
    user: dict = Depends(require_tenant),
) -> DraftActionResponse:
    """Discard a pending draft (owner-scoped)."""
    verify_twin_ownership(twin_id, user)
    tenant_id = user["tenant_id"]

    _load_owned_draft(twin_id, draft_id, tenant_id)  # 404 if not owned/found

    sb = get_supabase_client()
    sb.table("action_drafts").update({"status": "rejected"}).eq(
        "id", draft_id
    ).eq("tenant_id", tenant_id).execute()

    logger.info("[Drafts] discarded draft_id=%s twin_id=%s", draft_id, twin_id)
    return DraftActionResponse(
        data=DraftActionData(draft_id=draft_id, status="rejected")
    )
