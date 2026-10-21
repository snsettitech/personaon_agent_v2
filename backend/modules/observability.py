import logging
from supabase import create_client, Client
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _init_supabase() -> Client:
    """Create Supabase client from environment variables."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    # Fall back to anon key if service key is missing or a placeholder. This is a
    # foot-gun: the anon key is subject to RLS, so owner writes whose twin
    # tenant_id != auth.uid() silently match 0 rows (root cause of #228/#229).
    # Log loudly so the misconfiguration is visible instead of corrupting writes.
    if not key or "your_supabase_service_role_key" in key:
        logger.warning(
            "[Observability] SUPABASE_SERVICE_KEY missing/placeholder — falling back to "
            "anon key. RLS will silently drop owner writes (e.g. Publish-tab saves). "
            "Set a real service_role key."
        )
        key = os.getenv("SUPABASE_KEY")
    if not url:
        raise ValueError("SUPABASE_URL environment variable is not set.")
    if not key:
        raise ValueError("SUPABASE_KEY or SUPABASE_SERVICE_KEY environment variable is not set.")
    return create_client(url, key)


try:
    supabase: Client = _init_supabase()
except Exception as e:
    logger.error("[Observability] Failed to initialize Supabase: %s", e)
    supabase = None  # Will be re-initialized on first use via get_supabase_client()


def get_supabase_client() -> Client:
    """Get Supabase client, initializing if needed."""
    global supabase
    if supabase is None:
        supabase = _init_supabase()
    return supabase

def create_conversation(
    twin_id: str,
    user_id: str = None,
    group_id: str = None,
    interaction_context: str = None,
    origin_endpoint: str = None,
    share_link_id: str = None,
    training_session_id: str = None,
):
    data = {"twin_id": twin_id}
    if user_id:
        data["user_id"] = user_id
    if group_id:
        data["group_id"] = group_id
    if interaction_context:
        data["interaction_context"] = interaction_context
    if origin_endpoint:
        data["origin_endpoint"] = origin_endpoint
    if share_link_id:
        data["share_link_id"] = share_link_id
    if training_session_id:
        data["training_session_id"] = training_session_id

    try:
        response = supabase.table("conversations").insert(data).execute()
    except Exception:
        # Compatibility fallback for environments where context columns are not migrated yet.
        fallback = {"twin_id": twin_id}
        if user_id:
            fallback["user_id"] = user_id
        if group_id:
            fallback["group_id"] = group_id
        response = supabase.table("conversations").insert(fallback).execute()
    return response.data[0] if response.data else None

def log_interaction(
    conversation_id: str,
    role: str,
    content: str,
    citations: list = None,
    answerability_state: str = None,
    source_tier: str = None,
    review_required: bool = None,
    review_reason: str = None,
    interaction_context: str = None,
):
    data = {
        "conversation_id": conversation_id,
        "role": role,
        "content": content
    }
    if citations:
        data["citations"] = citations
    if answerability_state:
        data["answerability_state"] = answerability_state
    if source_tier:
        data["source_tier"] = source_tier
    if review_required is not None:
        data["review_required"] = review_required
    if review_reason:
        data["review_reason"] = review_reason
    if interaction_context:
        data["interaction_context"] = interaction_context

    try:
        response = supabase.table("messages").insert(data).execute()
    except Exception:
        # Compatibility fallback for environments where message context column is not migrated yet.
        fallback = {
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
        }
        if citations:
            fallback["citations"] = citations
        response = supabase.table("messages").insert(fallback).execute()
    return response.data[0] if response.data else None

def get_conversations(twin_id: str):
    response = supabase.table("conversations").select("*").eq("twin_id", twin_id).order("created_at", desc=True).execute()
    return response.data

def get_messages(conversation_id: str):
    """Get messages for a conversation with error handling."""
    if not conversation_id:
        return []

    try:
        # BUG #10 FIX: add secondary sort by id so messages with the same
        # created_at timestamp return in a deterministic, stable order
        response = (
            supabase.table("messages")
            .select("*")
            .eq("conversation_id", conversation_id)
            .order("created_at", desc=False)
            .order("id", desc=False)
            .execute()
        )
        return response.data if response.data else []
    except Exception as e:
        logger.warning("Error fetching messages for conversation %s: %s", conversation_id, e)
        # Return empty list on error to prevent chat from failing completely
        return []

def get_sources(twin_id: str):
    response = supabase.table("sources").select("*").eq("twin_id", twin_id).order("created_at", desc=True).execute()
    return response.data

async def get_knowledge_profile(twin_id: str):
    """
    Analyzes the twin's knowledge base to generate stats on facts vs opinions and tone.
    """
    total_chunks = 0
    fact_count = 0
    opinion_count = 0
    tone_distribution = {}

    # Sum chunk_count from Supabase sources (fast, no Pinecone round-trip needed)
    try:
        chunks_res = supabase.table("sources").select("chunk_count").eq("twin_id", twin_id).execute()
        for row in (chunks_res.data or []):
            total_chunks += row.get("chunk_count") or 0
    except Exception as e:
        logger.warning("[Knowledge Profile] Error summing chunk counts: %s", e)

    # Get top tone
    top_tone = "Neutral"
    if tone_distribution:
        try:
            top_tone = max(tone_distribution, key=tone_distribution.get)
        except Exception:
            top_tone = "Neutral"

    # Get total sources from Supabase
    total_sources = 0
    try:
        sources_res = supabase.table("sources").select("id", count="exact").eq("twin_id", twin_id).execute()
        total_sources = sources_res.count if hasattr(sources_res, 'count') else len(sources_res.data or [])
    except Exception as e:
        logger.warning("[Knowledge Profile] Error fetching sources count: %s", e)

    return {
        "total_chunks": total_chunks,
        "total_sources": total_sources,
        "fact_count": fact_count,
        "opinion_count": opinion_count,
        "tone_distribution": tone_distribution,
        "top_tone": top_tone
    }

# Phase 6: Ingestion Logging Functions

def log_ingestion_event(source_id: str, twin_id: str, level: str, message: str, metadata: dict = None):
    """
    Logs ingestion event to ingestion_logs table.

    Args:
        source_id: Source UUID
        twin_id: Twin UUID
        level: Log level ('info', 'warning', 'error')
        message: Log message
        metadata: Optional context/metadata
    """
    try:
        supabase.table("ingestion_logs").insert({
            "source_id": source_id,
            "twin_id": twin_id,
            "log_level": level,
            "message": message,
            "metadata": metadata or {}
        }).execute()
    except Exception as e:
        logger.warning("Error logging ingestion event: %s", e)

def get_ingestion_logs(source_id: str, limit: int = 100):
    """
    Retrieves logs for a source.

    Args:
        source_id: Source UUID
        limit: Maximum number of logs to return

    Returns:
        List of log entries
    """
    try:
        response = supabase.table("ingestion_logs").select("*").eq(
            "source_id", source_id
        ).order("created_at", desc=True).limit(limit).execute()
        return response.data if response.data else []
    except Exception as e:
        logger.warning("Error fetching ingestion logs: %s", e)
        return []

def get_dead_letter_queue(twin_id: str):
    """
    Lists sources in error state that need attention.

    Args:
        twin_id: Twin UUID

    Returns:
        List of sources needing attention
    """
    try:
        response = supabase.table("sources").select("*").eq(
            "twin_id", twin_id
        ).in_("status", ["error", "needs_attention"]).order("created_at", desc=True).execute()
        return response.data if response.data else []
    except Exception as e:
        logger.warning("Error fetching dead letter queue: %s", e)
        return []

def retry_failed_ingestion(source_id: str, twin_id: str):
    """
    Resets status and recreates training job for failed ingestion.

    Args:
        source_id: Source UUID
        twin_id: Twin UUID

    Returns:
        New training job ID
    """
    from modules.training_jobs import create_training_job

    # Reset source status
    supabase.table("sources").update({
        "status": "processing",
        "health_status": "healthy"
    }).eq("id", source_id).execute()

    # Create new training job
    job_id = create_training_job(source_id, twin_id, job_type="ingestion", priority=0)

    log_ingestion_event(source_id, twin_id, "info", f"Retry initiated, training job {job_id} created")

    return job_id
