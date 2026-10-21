import logging
# Use centralized Supabase client from observability module
from modules.observability import supabase

logger = logging.getLogger(__name__)

async def create_escalation(message_id: str):
    """
    Creates an escalation for a specific message.
    Automatically resolves and stores tenant_id and twin_id for strict scoping.
    """
    # 1. Resolve scope IDs from the message hierarchy
    # Path: messages -> conversations -> twins -> tenant_id
    try:
        msg_res = supabase.table("messages").select(
            "id, conversation_id, conversations(twin_id, twins(tenant_id))"
        ).eq("id", message_id).single().execute()

        if not msg_res.data:
            logger.error("[ERROR] Cannot create escalation: Message %s not found", message_id)
            return None

        conv_data = msg_res.data.get("conversations", {})
        twin_id = conv_data.get("twin_id")
        twin_data = conv_data.get("twins", {})
        tenant_id = twin_data.get("tenant_id")

        if not twin_id or not tenant_id:
            logger.error("[ERROR] Cannot create escalation: Scope identifiers missing for message %s", message_id)
            # Fallback: try to find any twin_id if join failed (some schemas might vary)
            if not twin_id:
                # Direct check if conversation exists
                conv_id = msg_res.data.get("conversation_id")
                fallback_conv = supabase.table("conversations").select("twin_id").eq("id", conv_id).single().execute()
                twin_id = fallback_conv.data.get("twin_id") if fallback_conv.data else None

            if twin_id and not tenant_id:
                fallback_twin = supabase.table("twins").select("tenant_id").eq("id", twin_id).single().execute()
                tenant_id = fallback_twin.data.get("tenant_id") if fallback_twin.data else None

        # 2. Insert escalation with scope
        escalation_data = {
            "message_id": message_id,
            "status": "open"
        }
        if tenant_id:
            escalation_data["tenant_id"] = tenant_id
        if twin_id:
            escalation_data["twin_id"] = twin_id

        response = supabase.table("escalations").insert(escalation_data).execute()
        return response.data

    except Exception as e:
        logger.error("[ERROR] Failed to create scoped escalation: %s", e)
        # Fallback to unscoped insert if metadata fails (Phase 2 backfill will catch it)
        response = supabase.table("escalations").insert({
            "message_id": message_id,
            "status": "open"
        }).execute()
        return response.data


async def resolve_escalation(escalation_id: str, owner_answer: str, owner_id: str):
    """
    Resolve an escalation with owner's answer.

    Args:
        escalation_id: ID of the escalation to resolve
        owner_answer: The owner's answer/reply
        owner_id: ID of the owner resolving the escalation

    Returns:
        dict: Updated escalation data
    """
    # Add reply
    supabase.table("escalation_replies").insert({
        "escalation_id": escalation_id,
        "owner_id": owner_id,
        "content": owner_answer
    }).execute()

    # Mark escalation as resolved
    # Note: Only setting status since resolved_by and resolved_at may not exist in all database schemas
    result = supabase.table("escalations").update({
        "status": "resolved"
    }).eq("id", escalation_id).execute()

    # Return the updated escalation data
    if result.data:
        return result.data[0]
    # Fallback: fetch the escalation
    fetch_result = supabase.table("escalations").select("*").eq("id", escalation_id).single().execute()
    return fetch_result.data if fetch_result.data else {}
