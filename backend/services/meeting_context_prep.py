"""Pre-session KB context preparation for meeting ADK sessions (Phase 30-D).

Called by the PREP_MEETING_CONTEXT graph_outbox worker when a bot joins a call.
Searches the twin's KB using the meeting title + persona expertise as queries,
deduplicates and ranks the results, then stores them in meetings.context_prep so
_run_adk_live can inject them into the session's system instruction before the
ADK agent starts.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from adk_core.services.vector_store import search as kb_search
from modules.observability import get_supabase_client

logger = logging.getLogger(__name__)

_TOP_K_PER_QUERY = 8
_MAX_CONTEXT_CHUNKS = 10
_MIN_SCORE = 0.50
# Chunks injected into the Gemini Live system instruction are spoken aloud in
# the meeting, so `private` tier chunks (e.g. raw Gmail, Slack DMs) must never
# appear here. Only `public` and `team` tiers are eligible for meeting context.
_ALLOWED_MEETING_TIERS = ["public", "team"]


async def prep_meeting_context(meeting_id: str, twin_id: str) -> bool:
    """Fetch KB chunks relevant to this meeting and store in meetings.context_prep.

    Generates search queries from the meeting title and the twin's persona
    expertise keywords. Deduplicates by source_id, keeps top _MAX_CONTEXT_CHUNKS
    by score, and writes the result as JSONB to meetings.context_prep.

    Returns True on success, False on any error.
    """
    sb = get_supabase_client()

    try:
        meeting_resp, twin_resp = await asyncio.gather(
            asyncio.to_thread(
                lambda: sb.table("meetings").select("id, title, twin_id").eq("id", meeting_id).single().execute()
            ),
            asyncio.to_thread(
                lambda: sb.table("twins").select("name, settings").eq("id", twin_id).single().execute()
            ),
        )
    except Exception as exc:
        logger.exception("[ContextPrep] DB load failed meeting=%s: %s", meeting_id, exc)
        return False

    meeting = meeting_resp.data or {}
    twin = twin_resp.data or {}
    settings = twin.get("settings") or {}
    persona_profile = settings.get("persona_profile") or {}
    if isinstance(persona_profile, str):
        try:
            persona_profile = json.loads(persona_profile)
        except (ValueError, TypeError):
            persona_profile = {}

    # Build search queries: meeting title first, then expertise keywords
    queries: list[str] = []
    title = (meeting.get("title") or "").strip()
    if title:
        queries.append(title)

    for field in ("areas_of_expertise", "expertise_keywords", "expertise", "topics", "skills"):
        val = persona_profile.get(field)
        if isinstance(val, list):
            for item in val[:5]:
                kw = str(item.get("name") if isinstance(item, dict) else item).strip()
                if kw and kw not in queries:
                    queries.append(kw)
            break
        elif isinstance(val, str) and val.strip():
            for kw in val.split(","):
                kw = kw.strip()
                if kw and kw not in queries:
                    queries.append(kw)
            break

    if not queries:
        queries = [twin.get("name") or "expertise"]

    logger.info(
        "[ContextPrep] searching KB meeting=%s twin=%s queries=%s",
        meeting_id, twin_id, queries[:3],
    )

    # Search KB for each query, deduplicate by source_id keeping highest score.
    # Tier filter and similarity floor are enforced in SQL (search_chunks 5-arg
    # form) so private chunks never leave the database for a meeting context.
    seen: dict[str, dict] = {}
    for query in queries[:5]:
        try:
            results = await kb_search(
                query=query,
                twin_id=twin_id,
                top_k=_TOP_K_PER_QUERY,
                allowed_tiers=_ALLOWED_MEETING_TIERS,
                min_similarity=_MIN_SCORE,
            )
            for chunk in results:
                # Python-side floor acts as defense-in-depth: SQL already filters
                # by min_similarity, but this guards against kb_search mocks or
                # future implementations that bypass the server-side check.
                if chunk.get("score", 0) < _MIN_SCORE:
                    continue
                sid = str(chunk.get("source_id") or chunk.get("text", "")[:40])
                if sid not in seen or chunk["score"] > seen[sid]["score"]:
                    seen[sid] = chunk
        except Exception as exc:
            logger.warning("[ContextPrep] KB search failed query=%r: %s", query[:40], exc)

    ranked = sorted(seen.values(), key=lambda c: c.get("score", 0), reverse=True)
    top_chunks = [
        {
            "text": c.get("text", ""),
            "score": round(c.get("score", 0), 4),
            "source_id": str(c.get("source_id") or ""),
            "filename": c.get("filename") or "",
        }
        for c in ranked[:_MAX_CONTEXT_CHUNKS]
    ]

    context_prep: dict[str, Any] = {
        "chunks": top_chunks,
        "queries_used": queries[:5],
        "chunk_count": len(top_chunks),
        "prepped_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        await asyncio.to_thread(
            lambda: sb.table("meetings").update({"context_prep": context_prep}).eq("id", meeting_id).execute()
        )
    except Exception as exc:
        logger.exception("[ContextPrep] DB write failed meeting=%s: %s", meeting_id, exc)
        return False

    logger.info(
        "[ContextPrep] stored %d chunks for meeting=%s queries=%d",
        len(top_chunks), meeting_id, len(queries[:5]),
    )
    return True


def format_context_for_instruction(context_prep: dict | None) -> str:
    """Format context_prep chunks into a snippet for injection into the system instruction.

    Returns an empty string if no useful context is present.
    """
    if not context_prep:
        return ""
    chunks = context_prep.get("chunks") or []
    lines = [c["text"].strip() for c in chunks if c.get("text", "").strip()]
    if not lines:
        return ""
    joined = " | ".join(lines[:6])
    return f"\n\nPre-fetched knowledge base context for this meeting:\n{joined}"
