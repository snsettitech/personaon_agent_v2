from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from modules.auth_guard import verify_owner, verify_twin_ownership
from modules.observability import supabase
from modules.posthog_analytics import ph_capture
from services.recap_sanitizer import sanitize_meeting

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v2/twins/{twin_id}/preview", tags=["preview"])


class PreviewOut(BaseModel):
    twin_name: str
    public_meetings: list[dict]
    visitor_questions: list[str]
    public_share_enabled: bool
    handle: str | None = None


@router.get("", response_model=PreviewOut)
async def preview_twin(twin_id: str, user=Depends(verify_owner)):
    verify_twin_ownership(twin_id, user)
    twin_resp = (
        supabase.table("twins")
        .select("display_name, public_share_enabled, settings")
        .eq("id", twin_id)
        .maybe_single()
        .execute()
    )
    twin = getattr(twin_resp, "data", None) or {}
    if not twin:
        raise HTTPException(404, "Twin not found")
    rows = (
        supabase.table("meetings")
        .select("id, title, summary_json, recap_extras_json, public_share_enabled")
        .eq("twin_id", twin_id)
        .eq("public_share_enabled", True)
        .neq("status", "deleted")
        .order("meeting_start", desc=True)
        .limit(20)
        .execute()
        .data
    ) or []
    public_meetings = [sanitize_meeting(m) for m in rows]
    # Derive sample visitor questions from topics in recent meetings
    visitor_questions: list[str] = []
    for m in rows[:3]:
        topics = (m.get("summary_json") or {}).get("topics") or []
        for t in (topics or [])[:2]:
            if isinstance(t, str) and t.strip():
                visitor_questions.append(f"Can you tell me about {t.strip()}?")
    # Telemetry — fire-and-forget, never propagate failures
    try:
        ph_capture(
            user_id=user.get("user_id") or twin_id,
            event="persona.preview_mode_entered",
            properties={"twin_id": twin_id},
        )
    except Exception:
        logger.exception("[Preview] ph_capture failed twin_id=%s", twin_id)
    settings = twin.get("settings") or {}
    handle = str(settings.get("handle") or "").strip() or None
    return PreviewOut(
        twin_name=twin.get("display_name") or "your twin",
        public_meetings=public_meetings,
        visitor_questions=visitor_questions[:6],
        public_share_enabled=bool(twin.get("public_share_enabled")),
        handle=handle,
    )
