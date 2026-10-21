"""Interview stats — how many interview Q&A exchanges a twin has saved.

Split out of ``routers/interview.py`` to keep that router under the size limit.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from adk_core.services.vector_store import count_faqs
from modules.auth_guard import require_tenant, verify_twin_ownership
from routers.interview import INTERVIEW_FAQ_ORIGIN

logger = logging.getLogger(__name__)

router = APIRouter(tags=["interview"])


@router.get("/v2/interview/{twin_id}/stats")
async def interview_stats(
    twin_id: str,
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """Return interview stats — how many Q&A pairs have been saved."""
    verify_twin_ownership(twin_id, user)

    # Each saved interview exchange is an FAQ chunk tagged origin="interview"
    # (see upsert_faq in interview_stream). Re-answering the same question
    # overwrites its chunk, so this counts distinct saved questions.
    try:
        exchange_count = await count_faqs(twin_id, origin=INTERVIEW_FAQ_ORIGIN)
    except Exception:
        logger.exception("[InterviewStats] count failed twin_id=%s", twin_id)
        raise HTTPException(status_code=503, detail="Interview stats temporarily unavailable")

    return {
        "status": "ok",
        "data": {"twin_id": twin_id, "exchange_count": exchange_count},
    }
