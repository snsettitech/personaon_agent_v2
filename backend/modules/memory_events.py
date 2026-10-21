# backend/modules/memory_events.py
"""Memory Events Service - Audit trail for all memory operations.

Creates MemoryEvent records BEFORE node/edge persist operations.
Every Scribe run creates exactly one MemoryEvent (success or failure).
"""

from typing import Any
import logging

from modules.observability import supabase

logger = logging.getLogger(__name__)


async def create_memory_event(
    twin_id: str,
    tenant_id: str,
    event_type: str,
    payload: dict[str, Any],
    status: str = "applied",
    source_type: str | None = None,
    source_id: str | None = None
) -> dict[str, Any] | None:
    """
    Create a memory event audit record.

    Args:
        twin_id: Twin UUID
        tenant_id: Tenant UUID
        event_type: One of 'auto_extract', 'manual_edit', 'confirm', 'delete'
        payload: Event data (extracted nodes, edges, etc)
        status: One of 'applied', 'failed', 'pending_review'
        source_type: Optional source type ('chat_turn', 'file_upload')
        source_id: Optional source identifier

    Returns:
        Created event record or None on failure
    """
    try:
        result = supabase.rpc("create_memory_event_system", {
            "p_tenant_id": tenant_id,
            "p_twin_id": twin_id,
            "p_event_type": event_type,
            "p_payload": payload,
            "p_status": status,
            "p_source_type": source_type,
            "p_source_id": source_id
        }).execute()

        if result.data and len(result.data) > 0:
            logger.info(f"Created MemoryEvent {result.data[0]['id']} for twin {twin_id}")
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Failed to create MemoryEvent: {e}")
        return None


async def update_memory_event(
    event_id: str,
    payload_update: dict[str, Any]
) -> dict[str, Any] | None:
    """
    Update a memory event with additional payload data.

    Args:
        event_id: Event UUID to update
        payload_update: Data to merge into existing payload

    Returns:
        Updated event record or None on failure
    """
    try:
        result = supabase.rpc("update_memory_event_system", {
            "p_event_id": event_id,
            "p_payload": payload_update
        }).execute()

        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Failed to update MemoryEvent {event_id}: {e}")
        return None


async def get_memory_events(
    twin_id: str,
    limit: int = 50,
    event_type: str | None = None
) -> list[dict[str, Any]]:
    """
    Get memory events for a twin (for TIL feed).

    Args:
        twin_id: Twin UUID
        limit: Max events to return
        event_type: Optional filter by event type

    Returns:
        List of memory event records
    """
    try:
        result = supabase.rpc("get_memory_events_system", {
            "p_twin_id": twin_id,
            "p_limit": limit,
            "p_event_type": event_type
        }).execute()

        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Failed to get MemoryEvents for {twin_id}: {e}")
        return []


async def get_til_feed(twin_id: str, days: int = 1) -> list[dict[str, Any]]:
    """
    Get TIL feed - recent memory events grouped by day.

    Args:
        twin_id: Twin UUID
        days: Number of days to include (default 1)

    Returns:
        List of memory events with human-readable summaries
    """
    try:
        # Get recent events
        events = await get_memory_events(twin_id, limit=50)

        # Filter to relevant event types for TIL
        til_events = [
            e for e in events
            if e.get("event_type") in ("auto_extract", "confirm", "manual_edit")
            and e.get("status") == "applied"
        ]

        # Enrich with human-readable summaries
        for event in til_events:
            payload = event.get("payload", {})
            nodes_created = payload.get("nodes_created", [])
            edges_created = payload.get("edges_created", [])
            confidence = payload.get("confidence", 0)

            # Build summary
            parts = []
            if nodes_created:
                parts.append(f"Learned {len(nodes_created)} new concept(s)")
            if edges_created:
                parts.append(f"Found {len(edges_created)} connection(s)")

            event["summary"] = " and ".join(parts) if parts else "Memory updated"
            event["confidence_display"] = f"{int(confidence * 100)}%"

        return til_events
    except Exception as e:
        logger.error(f"Failed to get TIL feed for {twin_id}: {e}")
        return []
