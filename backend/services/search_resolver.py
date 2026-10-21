"""Fan-out search via the search_twin_all Postgres RPC.

Uses pg_trgm word similarity (%> operator) via the GIN indexes created in
migration 20260607000000. Falls back to empty results if the RPC is unavailable.
"""
from __future__ import annotations

import logging
from typing import Any

from modules.observability import supabase

logger = logging.getLogger(__name__)


def search_all(twin_id: str, q: str) -> dict[str, list[dict[str, Any]]]:
    """Call search_twin_all RPC and group results by kind.

    Synchronous — safe to call from a thread pool (asyncio.to_thread).
    Returns an empty dict structure on any error.
    """
    out: dict[str, list[dict[str, Any]]] = {
        "people": [],
        "meetings": [],
        "commitments": [],
        "memories": [],
    }
    if not q.strip():
        return out
    try:
        rows = (
            supabase.rpc("search_twin_all", {"p_twin": twin_id, "p_q": q.strip()})
            .execute()
            .data
        ) or []
    except Exception:
        logger.exception("[Search] RPC failed twin_id=%s", twin_id)
        return out
    for r in rows[:20]:
        kind = r.get("kind")
        if kind == "person":
            out["people"].append(
                {
                    "id": str(r["id"]),
                    "name": r["label"],
                    "email": r.get("hint") or None,
                }
            )
        elif kind == "meeting":
            out["meetings"].append({"id": str(r["id"]), "title": r["label"]})
        elif kind == "commitment":
            out["commitments"].append(
                {
                    "id": str(r["id"]),
                    "text": r["label"],
                    "direction": r.get("hint"),
                    "meeting_id": None,
                }
            )
        elif kind == "memory":
            out["memories"].append(
                {
                    "id": str(r["id"]),
                    "text": r["label"],
                    "subject": r.get("hint"),
                }
            )
    return out
