"""Shared persona profile loading and system instruction building.

Extracted from meeting_adk_session.py so meeting, chat, and future API channels
share a single implementation without duplication.
"""

from __future__ import annotations

import logging
from typing import Any

from modules.access_groups import get_user_group
from modules.observability import get_supabase_client, supabase

logger = logging.getLogger(__name__)


async def load_persona_profile(twin_id: str) -> dict[str, Any]:
    """Load twin name, voice, and persona_profile from Supabase.

    Returns a dict with keys: twin_name, voice_name, persona_profile.
    Returns {} on any DB error.
    """
    sb = get_supabase_client()
    try:
        resp = (
            sb.table("twins")
            .select("name, settings")
            .eq("id", twin_id)
            .single()
            .execute()
        )
    except Exception as exc:
        logger.warning("[PersonaCore] profile load failed twin=%s: %s", twin_id, exc)
        return {}
    if not resp.data:
        return {}
    settings = resp.data.get("settings") or {}
    return {
        "twin_name": resp.data.get("name") or "the presenter",
        "voice_name": settings.get("gemini_voice") or "Kore",
        "persona_profile": settings.get("persona_profile") or {},
    }


def build_system_instruction(
    twin_name: str,
    persona_profile: dict,
    channel: str = "meeting",
) -> str:
    """Build a system instruction string tuned for the given channel.

    channel: "meeting" | "chat"
    """
    role = (
        persona_profile.get("occupation")
        or persona_profile.get("role")
        or persona_profile.get("headline")
        or persona_profile.get("title")
        or ""
    )
    short_desc = persona_profile.get("short_description") or ""

    topics_raw = (
        persona_profile.get("areas_of_expertise")
        or persona_profile.get("expertise_keywords")
        or persona_profile.get("expertise")
        or persona_profile.get("topics")
        or []
    )
    if isinstance(topics_raw, str):
        topics = [t.strip() for t in topics_raw.split(",") if t.strip()]
    elif isinstance(topics_raw, list):
        topics = []
        for t in topics_raw:
            if isinstance(t, dict):
                topics.append(str(t.get("name") or t.get("area") or "").strip())
            else:
                topics.append(str(t).strip())
        topics = [t for t in topics if t]
    else:
        topics = []
    topics_str = ", ".join(topics[:6]) if topics else "general topics"

    role_line = f"{twin_name} is {role}. " if role else ""
    desc_line = f"Background: {short_desc} " if short_desc else ""

    if channel == "meeting":
        return (
            f"You are {twin_name}'s AI digital twin participating in a live meeting. "
            f"{role_line}"
            f"{desc_line}"
            f"Your expertise covers: {topics_str}. "
            "Speak naturally and conversationally — contribute to the discussion, answer questions, and add insights. "
            "NEVER interrupt while someone else is speaking — always wait for a clear pause before you respond. "
            "Keep answers concise: 1-3 sentences unless asked to elaborate. "
            f"Call search_knowledge_base(query) before answering detailed questions about {twin_name}'s specific work, opinions, or background. "
            # Speaker attribution is unavailable — raw audio is mixed across all participants.
            # TODO(Phase 30): Replace with diarized addressing once Recall.ai per-speaker audio
            # or Gemini Live native diarization is available.
            "IMPORTANT: You cannot identify individual speakers from the audio. "
            "Use neutral phrases: 'Great point', 'To add to that', 'Good question'. "
            f"If something is outside your expertise, say '{twin_name} would be better placed to answer that directly'. "
            "Do NOT repeat yourself — if you have already said something, do not say it again."
        )

    # "chat" channel — web / widget / API chat interface
    return (
        f"You are {twin_name}'s AI digital twin. "
        f"{role_line}"
        f"{desc_line}"
        f"Your expertise covers: {topics_str}. "
        "Answer questions accurately and concisely, grounding your answers in the knowledge base. "
        f"Use search_knowledge_base(query) to retrieve {twin_name}'s specific facts before answering."
    )


async def resolve_privacy_tiers(
    requester_id: str | None,
    twin_id: str,
) -> list[str]:
    """Return the privacy tiers the requester can access for this twin.

    - Anonymous (no requester_id) → ["public"]
    - Group member → ["public", "team"]
    - Twin owner → ["public", "team", "private"]
    """
    if not requester_id:
        return ["public"]

    # Owner check — owner_user_id lives in settings JSONB, not as a bare
    # twins.user_id column (which doesn't exist).
    try:
        resp = supabase.table("twins").select("settings").eq("id", twin_id).single().execute()
        settings = (resp.data or {}).get("settings") or {}
        if isinstance(settings, dict):
            owner_uid = str(settings.get("owner_user_id") or "").strip()
            if owner_uid and owner_uid == requester_id:
                return ["public", "team", "private"]
    except Exception as exc:
        logger.warning("[PersonaCore] owner check failed twin=%s: %s", twin_id, exc)

    # Group membership check
    try:
        group = await get_user_group(requester_id, twin_id)
        if group:
            return ["public", "team"]
    except Exception as exc:
        logger.warning("[PersonaCore] group check failed twin=%s: %s", twin_id, exc)

    return ["public"]
