"""
Search router — /v2/twins/{twin_id}/search

Fan-out full-text search across people, meetings, commitments, and memories
via the search_twin_all Postgres RPC (pg_trgm GIN indexes).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, Query

from modules.auth_guard import verify_owner, verify_twin_ownership
from services.search_resolver import search_all

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2/twins/{twin_id}/search", tags=["search"])


@router.get("")
async def search(
    twin_id: str,
    q: str = Query(min_length=1, max_length=80),
    user: dict[str, Any] = Depends(verify_owner),
) -> dict[str, list[dict[str, Any]]]:
    """Fan-out search across all entity types for a twin."""
    verify_twin_ownership(twin_id, user)
    q_clean = q.strip()
    if not q_clean:
        return {"people": [], "meetings": [], "commitments": [], "memories": []}
    return await asyncio.to_thread(search_all, twin_id, q_clean)
