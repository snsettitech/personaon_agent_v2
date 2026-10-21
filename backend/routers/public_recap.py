"""Unauthenticated public recap endpoint. Returns a SANITIZED recap for an
enabled share token. No signed media URLs, no tenant/user identifiers."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from modules.observability import supabase
from services.recap_sanitizer import (
    pick as _pick,
    sanitize_action_items as _sanitize_action_items,
    PUBLIC_ACTION_KEYS as _PUBLIC_ACTION_KEYS,
    PUBLIC_SUMMARY_KEYS as _PUBLIC_SUMMARY_KEYS,
    PUBLIC_EXTRAS_KEYS as _PUBLIC_EXTRAS_KEYS,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v2/public", tags=["public-recap"])


class PublicRecap(BaseModel):
    title: str
    meeting_start: str | None = None
    duration_seconds: int | None = None
    platform: str | None = None
    summary_json: dict[str, Any] | None = None
    recap_extras_json: dict[str, Any] | None = None
    action_items: list[dict[str, Any]] | None = None



@router.get("/recap/{token}")
async def get_public_recap(token: str) -> dict[str, Any]:
    if not token or len(token) < 16:
        raise HTTPException(status_code=404, detail="Recording not found")
    try:
        resp = (
            supabase.table("meetings")
            .select("title,meeting_start,duration_seconds,platform,summary_json,recap_extras_json,action_items,public_share_enabled,status")
            .eq("public_share_token", token)
            .maybe_single()
            .execute()
        )
    except Exception as exc:
        logger.info("[public_recap] lookup failed err=%s", type(exc).__name__)
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    row = getattr(resp, "data", None)
    if not row or not row.get("public_share_enabled") or row.get("status") == "deleted":
        raise HTTPException(status_code=404, detail="Recording not found")
    payload = PublicRecap(
        title=row.get("title") or "Shared meeting",
        meeting_start=row.get("meeting_start"),
        duration_seconds=row.get("duration_seconds"),
        platform=row.get("platform"),
        summary_json=_pick(row.get("summary_json"), _PUBLIC_SUMMARY_KEYS),
        recap_extras_json=_pick(row.get("recap_extras_json"), _PUBLIC_EXTRAS_KEYS),
        action_items=_sanitize_action_items(row.get("action_items")),
    )
    return {"status": "ok", "data": payload.model_dump()}
