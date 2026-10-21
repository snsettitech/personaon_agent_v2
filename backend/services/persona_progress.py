"""Compute persona completion checkpoints (0-6) for the progress rail."""
from __future__ import annotations
import asyncio
import logging
from typing import Any

from modules.observability import supabase

logger = logging.getLogger(__name__)

CHECKPOINTS = [
    "twin_created",
    "profile_filled",
    "first_meeting",
    "first_commitment_closed",
    "first_memory_approved",
    "public_share_enabled",
]


async def compute_progress(twin_id: str) -> dict[str, Any]:
    """Compute the 6-checkpoint progress for a twin. Always returns twin_created=True."""
    def _fetch():
        twin = (
            supabase.table("twins")
            .select("display_name, bio, public_share_enabled")
            .eq("id", twin_id)
            .maybe_single()
            .execute()
            .data
        ) or {}
        def _safe_count(val: Any) -> int:
            try:
                return int(val) if val is not None else 0
            except (TypeError, ValueError):
                return 0

        meeting_count = _safe_count(
            supabase.table("meetings")
            .select("id", count="exact")
            .eq("twin_id", twin_id)
            .limit(1)
            .execute()
            .count
        )
        closed = _safe_count(
            supabase.table("meeting_commitments")
            .select("id", count="exact")
            .eq("twin_id", twin_id)
            .eq("status", "done")
            .limit(1)
            .execute()
            .count
        )
        approved = _safe_count(
            supabase.table("memory_candidates")
            .select("id", count="exact")
            .eq("twin_id", twin_id)
            .eq("status", "approved")
            .limit(1)
            .execute()
            .count
        )
        return twin, meeting_count, closed, approved

    twin, meeting_count, closed, approved = await asyncio.to_thread(_fetch)
    checkpoints = {
        "twin_created": True,
        "profile_filled": bool(twin.get("display_name") and twin.get("bio")),
        "first_meeting": meeting_count > 0,
        "first_commitment_closed": closed > 0,
        "first_memory_approved": approved > 0,
        "public_share_enabled": bool(twin.get("public_share_enabled")),
    }
    completed = sum(1 for v in checkpoints.values() if v)
    return {"completed": completed, "total": 6, "checkpoints": checkpoints}
