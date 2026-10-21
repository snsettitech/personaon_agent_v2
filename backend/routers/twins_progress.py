from __future__ import annotations
import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from modules.auth_guard import verify_owner, verify_twin_ownership
from services.persona_progress import compute_progress

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v2/twins/{twin_id}/progress", tags=["progress"])


class ProgressOut(BaseModel):
    completed: int
    total: int
    checkpoints: dict[str, bool]


@router.get("", response_model=ProgressOut)
async def get_progress(twin_id: str, user=Depends(verify_owner)):
    verify_twin_ownership(twin_id, user)
    return ProgressOut(**await compute_progress(twin_id))
