"""Twins data endpoints — settings, sidebar-config, logs, export, owner-memory."""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from modules.auth_guard import get_current_user, verify_twin_ownership
from modules.observability import supabase
from modules.schemas import TwinSettingsUpdate
from routers.twins_helpers import (
    _require_authenticated_user,
    ensure_twin_owner_or_403,
)

router = APIRouter(tags=["twins"])

logger = logging.getLogger(__name__)



@router.post("/twins/{twin_id}/settings")
async def update_twin_settings(
    twin_id: str,
    update: TwinSettingsUpdate,
    user=Depends(get_current_user)
):
    """Update twin settings with strict ownership verification."""
    user = _require_authenticated_user(user)
    ensure_twin_owner_or_403(twin_id, user)

    try:
        twin_res = supabase.table("twins").select("settings").eq("id", twin_id).single().execute()
        if not twin_res.data:
            raise HTTPException(status_code=404, detail="Twin not found")

        existing_settings = twin_res.data.get("settings") or {}
        updated_settings = {**existing_settings}

        if update.system_prompt is not None:
            updated_settings["system_prompt"] = update.system_prompt
        if update.handle is not None:
            updated_settings["handle"] = update.handle
        if update.tagline is not None:
            updated_settings["tagline"] = update.tagline
        if update.expertise is not None:
            updated_settings["expertise"] = update.expertise
        if update.personality is not None:
            updated_settings["personality"] = update.personality
        if update.intent_profile is not None:
            updated_settings["intent_profile"] = update.intent_profile

        response = supabase.table("twins").update({
            "settings": updated_settings
        }).eq("id", twin_id).execute()

        if not response.data:
            raise HTTPException(status_code=404, detail="Twin not found or update failed")

        return response.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TWINS] ERROR updating settings: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/twins/{twin_id}/settings")
async def get_twin_settings(twin_id: str, user=Depends(get_current_user)):
    """Get current twin settings."""
    user = _require_authenticated_user(user)
    ensure_twin_owner_or_403(twin_id, user)

    try:
        twin_res = supabase.table("twins").select("settings").eq("id", twin_id).single().execute()
        if not twin_res.data:
            raise HTTPException(status_code=404, detail="Twin not found")

        return {"settings": twin_res.data.get("settings") or {}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TWINS] ERROR getting settings: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/twins/{twin_id}/logs")
async def get_twin_logs(
    twin_id: str,
    limit: int = Query(50, ge=1, le=500),
    user=Depends(get_current_user),
):
    """Return recent access logs for a twin.

    Combines conversation starts (from adk_conversations) and action
    executions (from action_executions) into a unified, date-sorted list
    the Privacy & Data page can display.
    """
    user = _require_authenticated_user(user)
    verify_twin_ownership(twin_id, user)

    logs: list[dict[str, Any]] = []

    # 1. Conversation starts from adk_conversations
    try:
        convo_res = (
            supabase.table("adk_conversations")
            .select("id, surface, user_id, created_at")
            .eq("twin_id", twin_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        for row in convo_res.data or []:
            surface = row.get("surface", "unknown")
            logs.append({
                "id": str(row.get("id", "")),
                "action": f"conversation_started ({surface})",
                "event_type": "conversation",
                "timestamp": row.get("created_at", ""),
                "created_at": row.get("created_at", ""),
            })
    except Exception as exc:
        logger.warning("get_twin_logs: adk_conversations query failed for twin %s: %s", twin_id, exc)

    # 2. Action executions from action_executions
    try:
        action_res = (
            supabase.table("action_executions")
            .select("id, action_type, status, executed_at")
            .eq("twin_id", twin_id)
            .order("executed_at", desc=True)
            .limit(limit)
            .execute()
        )
        for row in action_res.data or []:
            action_type = row.get("action_type", "action")
            status = row.get("status", "")
            logs.append({
                "id": str(row.get("id", "")),
                "action": f"{action_type} ({status})",
                "event_type": "action_execution",
                "timestamp": row.get("executed_at", ""),
                "created_at": row.get("executed_at", ""),
            })
    except Exception as exc:
        logger.warning("get_twin_logs: action_executions query failed for twin %s: %s", twin_id, exc)

    logs.sort(key=lambda entry: entry.get("timestamp", ""), reverse=True)
    logs = logs[:limit]

    return {"logs": logs}


@router.get("/twins/{twin_id}/export")
async def export_twin_data(
    twin_id: str,
    user=Depends(get_current_user),
):
    """Export a JSON blob containing the twin's profile, settings, and stats.

    Returns a downloadable JSON response with Content-Disposition header so
    the frontend can trigger a file save via blob URL.
    """
    user = _require_authenticated_user(user)
    verify_twin_ownership(twin_id, user)

    twin_res = (
        supabase.table("twins")
        .select("*")
        .eq("id", twin_id)
        .single()
        .execute()
    )
    if not twin_res.data:
        raise HTTPException(status_code=404, detail="Twin not found")

    twin_data = twin_res.data

    conversations_count = 0
    try:
        convo_res = (
            supabase.table("adk_conversations")
            .select("id", count="exact")
            .eq("twin_id", twin_id)
            .execute()
        )
        conversations_count = convo_res.count or 0
    except Exception:
        pass

    messages_count = 0
    try:
        msg_res = (
            supabase.table("adk_messages")
            .select("id", count="exact")
            .eq("twin_id", twin_id)
            .execute()
        )
        messages_count = msg_res.count or 0
    except Exception:
        pass

    sources_list: list[dict[str, Any]] = []
    try:
        src_res = (
            supabase.table("sources")
            .select("id, filename, source_type, status, created_at")
            .eq("twin_id", twin_id)
            .order("created_at", desc=True)
            .execute()
        )
        sources_list = src_res.data or []
    except Exception:
        pass

    export_payload = {
        "twin_id": twin_id,
        "name": twin_data.get("name"),
        "description": twin_data.get("description"),
        "status": twin_data.get("status"),
        "specialization": twin_data.get("specialization"),
        "settings": twin_data.get("settings", {}),
        "created_at": twin_data.get("created_at"),
        "updated_at": twin_data.get("updated_at"),
        "conversations_count": conversations_count,
        "messages_count": messages_count,
        "sources": sources_list,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }

    json_bytes = json.dumps(export_payload, indent=2, default=str).encode("utf-8")
    filename = f"twin_{twin_id}_export.json"

    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/twins/{twin_id}/owner-memory")
async def get_owner_memory(
    twin_id: str,
    status: str = Query("all"),
    user=Depends(get_current_user),
):
    """Return structured memory entries for a twin.

    Queries the owner_beliefs table first.  If the table does not exist or is
    empty, falls back to synthesising entries from the twin's
    settings.persona_profile (identity) and settings FAQ (policy).

    The Publish Controls page uses this to let the owner cherry-pick which
    identity and policy topics are exposed to public share users.
    """
    user = _require_authenticated_user(user)
    verify_twin_ownership(twin_id, user)

    memories: list[dict[str, Any]] = []

    try:
        query = (
            supabase.table("owner_beliefs")
            .select("id, topic_normalized, memory_type, value, status")
            .eq("twin_id", twin_id)
            .order("created_at", desc=True)
        )
        if status != "all":
            query = query.eq("status", status)

        beliefs_res = query.execute()
        beliefs_data = beliefs_res.data or []

        for row in beliefs_data:
            memories.append({
                "id": str(row.get("id", "")),
                "topic_normalized": row.get("topic_normalized", ""),
                "memory_type": row.get("memory_type", "belief"),
                "value": row.get("value", ""),
                "status": row.get("status", "active"),
            })
    except Exception as exc:
        logger.warning(
            "get_owner_memory: owner_beliefs query failed for twin %s: %s",
            twin_id, exc,
        )

    if not memories:
        twin_res = (
            supabase.table("twins")
            .select("settings")
            .eq("id", twin_id)
            .single()
            .execute()
        )
        if twin_res.data:
            settings = twin_res.data.get("settings") or {}
            persona_profile = settings.get("persona_profile") or {}

            identity_fields = [
                ("name", "Name"),
                ("headline", "Headline"),
                ("bio", "Bio"),
                ("expertise", "Expertise"),
                ("location", "Location"),
            ]
            for field_key, label in identity_fields:
                value = persona_profile.get(field_key)
                if value:
                    display_value = value if isinstance(value, str) else str(value)
                    memories.append({
                        "id": f"profile_{field_key}",
                        "topic_normalized": label,
                        "memory_type": "belief",
                        "value": display_value,
                        "status": "active",
                    })

            faq_list = settings.get("faq") or persona_profile.get("faq") or []
            if isinstance(faq_list, list):
                for idx, faq in enumerate(faq_list):
                    question = faq.get("question", faq.get("q", "")) if isinstance(faq, dict) else str(faq)
                    answer = faq.get("answer", faq.get("a", "")) if isinstance(faq, dict) else ""
                    if question:
                        memories.append({
                            "id": f"faq_{idx}",
                            "topic_normalized": question,
                            "memory_type": "stance",
                            "value": answer or question,
                            "status": "active",
                        })

    return memories
