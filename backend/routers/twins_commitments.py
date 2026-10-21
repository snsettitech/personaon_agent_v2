"""
Phase A — Commitments router.

Two endpoints, owner-only:
  GET   /v2/twins/{twin_id}/commitments        — list grouped by direction
  PATCH /v2/twins/{twin_id}/commitments/{id}   — update status
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from modules.auth_guard import verify_owner, verify_twin_ownership
from modules.observability import supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2/twins/{twin_id}/commitments", tags=["commitments"])


def _resolve_tenant(user: dict[str, Any]) -> str:
    return str(user.get("tenant_id") or user.get("user_id") or "")


class CommitmentOut(BaseModel):
    id: str
    meeting_id: str
    contact_id: str | None = None
    direction: Literal["you_owe", "they_owe", "unknown"]
    text: str
    assignee_name: str | None = None
    due_at: str | None = None
    status: Literal["open", "done", "dismissed"]
    created_at: str


class CommitmentListOut(BaseModel):
    you_owe: list[CommitmentOut] = Field(default_factory=list)
    they_owe: list[CommitmentOut] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)


class CommitmentUpdate(BaseModel):
    status: Literal["open", "done", "dismissed"]


@router.get("", response_model=CommitmentListOut)
async def list_commitments(
    twin_id: str,
    contact_id: str | None = Query(default=None),
    status: Literal["open", "done", "dismissed", "all"] = Query(default="open"),
    user: dict[str, Any] = Depends(verify_owner),
) -> CommitmentListOut:
    """List commitments for a twin, grouped by direction."""
    verify_twin_ownership(twin_id, user)

    q = supabase.table("meeting_commitments").select("*").eq("twin_id", twin_id)
    if contact_id:
        q = q.eq("contact_id", contact_id)
    if status != "all":
        q = q.eq("status", status)

    rows: list[dict[str, Any]] = (
        q.order("created_at", desc=True).execute().data or []
    )

    you_owe = [r for r in rows if r["direction"] == "you_owe"]
    they_owe = [r for r in rows if r["direction"] == "they_owe"]

    return CommitmentListOut(
        you_owe=[CommitmentOut(**r) for r in you_owe],
        they_owe=[CommitmentOut(**r) for r in they_owe],
        counts={
            "you_owe": len(you_owe),
            "they_owe": len(they_owe),
            "total": len(rows),
        },
    )


@router.patch("/{commitment_id}", response_model=CommitmentOut)
async def update_commitment(
    twin_id: str,
    commitment_id: str,
    body: CommitmentUpdate,
    user: dict[str, Any] = Depends(verify_owner),
) -> CommitmentOut:
    """Update the status of a single commitment."""
    verify_twin_ownership(twin_id, user)
    tenant_id = _resolve_tenant(user)

    res = (
        supabase.table("meeting_commitments")
        .update(
            {
                "status": body.status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", commitment_id)
        .eq("twin_id", twin_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )

    if not res.data:
        raise HTTPException(status_code=404, detail="Commitment not found")

    return CommitmentOut(**res.data[0])
