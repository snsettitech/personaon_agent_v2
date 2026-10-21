# backend/modules/_core/scribe_engine.py
"""Scribe Engine: Extracts structured knowledge from conversation.

Integrates with OpenAI Structured Outputs (beta) to parse user/assistant
messages into Graph Nodes and Edges, then persists them to Supabase
using secure RPCs.

Refactored to support Strict Mode (extra="forbid") and explicit Property models.
"""

from pydantic import BaseModel, Field
from typing import Any
import logging
import hashlib
import os

from modules.clients import get_async_openai_client
from modules.observability import supabase
from modules.jobs import create_job, JobType, JobStatus, start_job, complete_job, fail_job, append_log, LogLevel
from modules.job_queue import enqueue_job

logger = logging.getLogger(__name__)

# --- Structured Output Schema (Strict Mode) ---

class Property(BaseModel):
    key: str = Field(description="Property name (e.g., 'value', 'unit', 'sector').")
    value: str = Field(description="Property value as string.")

    # Strict mode requires forbidding extra fields
    # Using model_config for Pydantic v2 or class Config for v1.
    # Assumes environment supports standard Pydantic.
    class Config:
        extra = "forbid"

class NodeUpdate(BaseModel):
    name: str = Field(description="Unique name of the concept, entity, or topic. Use Title Case.")
    type: str = Field(description="Type of entity (e.g., Company, Person, Statistic, Market, Product, Concept, Goal).")
    description: str = Field(description="Concise description or definition based on the context.")
    # OpenAI Strict Mode does NOT support Dict[str, Any]. Must use List of objects.
    properties: list[Property] = Field(default_factory=list, description="List of key-value properties.")

    class Config:
        extra = "forbid"

class EdgeUpdate(BaseModel):
    from_node: str = Field(description="Name of the source node.")
    to_node: str = Field(description="Name of the target node.")
    type: str = Field(description="Relationship type (e.g., FOUNDED, LOCATED_IN, HAS_METRIC, TARGETS, MENTIONS).")
    description: str | None = Field(None, description="Context for why this relationship exists.")

    class Config:
        extra = "forbid"

class GraphUpdates(BaseModel):
    nodes: list[NodeUpdate] = Field(default_factory=list, description="List of nodes to create or update.")
    edges: list[EdgeUpdate] = Field(default_factory=list, description="List of relationships to create.")
    confidence: float = Field(description="Confidence score (0.0 to 1.0) in the extraction accuracy.")

    class Config:
        extra = "forbid"

# --- Core Functions ---

# Import observe decorator for tracing
try:
    from langfuse import observe
    _observe_available = True
except ImportError:
    _observe_available = False
    def observe(*args, **kwargs):
        def decorator(func):
            return func
        return decorator


@observe(name="scribe_extraction")
async def process_interaction(
    twin_id: str,
    user_message: str,
    assistant_message: str,
    history: list[dict[str, Any]] = None,
    tenant_id: str = None,
    conversation_id: str = None
) -> dict[str, Any]:
    """
    Analyzes the interaction and updates the cognitive graph.
    Creates MemoryEvent BEFORE persist for audit trail.
    """
    from modules.memory_events import create_memory_event, update_memory_event

    memory_event = None

    try:
        client = get_async_openai_client()

        # Construct context
        messages = [
            {"role": "system", "content": (
                "You are an expert Knowledge Graph Scribe. "
                "Your goal is to extract structured entities (Nodes) and relationships (Edges) "
                "from the latest user-assistant interaction. "
                "Focus on factual claims, metrics, definitions, and proper nouns. "
                "Do NOT create generic nodes like 'User' or 'Assistant'. "
                "Ensure node names are canonical (Title Case)."
            )}
        ]

        if history:
            # Flatten history (limit last 6 turns)
            for msg in history[-6:]:
                if hasattr(msg, "content"): # LangChain Object
                    role = "user"
                    if hasattr(msg, "type") and msg.type == "ai":
                         role = "assistant"
                    elif hasattr(msg, "role"):
                         role = msg.role
                    content = msg.content
                elif isinstance(msg, dict): # Check dict last
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                else:
                    continue

                messages.append({"role": role, "content": content})

        # Add current turn
        messages.append({"role": "user", "content": user_message})
        messages.append({"role": "assistant", "content": assistant_message})

        # Call OpenAI with Pydantic Schema
        response = await client.beta.chat.completions.parse(
            model="gpt-4o-2024-08-06",
            messages=messages,
            response_format=GraphUpdates,
            temperature=0.0
        )

        updates = response.choices[0].message.parsed

        if not updates:
            logger.warning("Scribe returned no parsed structure.")
            return {"nodes": [], "edges": []}

        logger.info(f"Scribe extracted: {len(updates.nodes)} nodes, {len(updates.edges)} edges, conf={updates.confidence}")

        # 1. Create MemoryEvent BEFORE persist (audit trail)
        if tenant_id:
            memory_event = await create_memory_event(
                twin_id=twin_id,
                tenant_id=tenant_id,
                event_type="auto_extract",
                payload={
                    "raw_nodes": [n.model_dump() for n in updates.nodes],
                    "raw_edges": [e.model_dump() for e in updates.edges],
                    "confidence": updates.confidence
                },
                status="applied",
                source_type="chat_turn",
                source_id=conversation_id
            )

        # 2. Persist to Supabase
        created_nodes = await _persist_nodes(twin_id, updates.nodes)

        # Create map for Edges
        node_map = {n['name']: n['id'] for n in created_nodes}

        # Persist Edges
        valid_edges = []
        for edge in updates.edges:
            from_id = node_map.get(edge.from_node)
            to_id = node_map.get(edge.to_node)

            if from_id and to_id:
                valid_edges.append(edge)
            else:
                # In strict mode, log partial edges
                pass

        created_edges = await _persist_edges(twin_id, valid_edges, node_map)

        # 3. Update MemoryEvent with resolved IDs
        if memory_event:
            await update_memory_event(memory_event['id'], {
                "nodes_created": [n['id'] for n in created_nodes],
                "edges_created": [e['id'] for e in created_edges],
                "node_count": len(created_nodes),
                "edge_count": len(created_edges)
            })

        return {
            "nodes": created_nodes,
            "edges": created_edges,
            "confidence": updates.confidence,
            "memory_event_id": memory_event['id'] if memory_event else None
        }

    except Exception as e:
        logger.error(f"Scribe Engine Error: {e}", exc_info=True)
        logger.error("Scribe Engine Critical Failure: %s", e)

        # Create failed MemoryEvent for audit trail
        if tenant_id:
            await create_memory_event(
                twin_id=twin_id,
                tenant_id=tenant_id,
                event_type="auto_extract",
                payload={"error": str(e)},
                status="failed",
                source_type="chat_turn",
                source_id=conversation_id
            )

        return {"nodes": [], "edges": [], "error": str(e)}


async def extract_for_slot(
    twin_id: str,
    user_message: str,
    assistant_message: str,
    slot_id: str,
    target_node_type: str | None = None,
    current_question: str | None = None,
    history: list[dict[str, Any]] = None,
    tenant_id: str = None,
    conversation_id: str = None
) -> dict[str, Any]:
    """
    Extract structured data from user response for a specific slot.

    Slot-aware extraction that focuses on extracting information relevant
    to the current slot being filled.

    Args:
        twin_id: Twin ID
        user_message: User's response message
        assistant_message: Assistant's question
        slot_id: Current slot ID being filled
        target_node_type: Expected node type for this slot (optional)
        current_question: Current question text (optional)
        history: Conversation history (optional)
        tenant_id: Tenant ID (optional)
        conversation_id: Conversation ID (optional)

    Returns:
        Dict with nodes, edges, confidence, and slot_relevance
    """
    from modules.memory_events import create_memory_event, update_memory_event

    memory_event = None

    try:
        client = get_async_openai_client()

        # Build slot-aware system prompt
        slot_context = f"Current slot: {slot_id}"
        if target_node_type:
            slot_context += f"\nExpected node type: {target_node_type}"
        if current_question:
            slot_context += f"\nQuestion asked: {current_question}"

        system_content = f"""You are an expert Knowledge Graph Scribe focused on extracting information for a specific interview slot.

{slot_context}

Your goal is to extract structured entities (Nodes) and relationships (Edges) from the user's response that are relevant to this slot.

Focus on:
- Information directly answering the current question
- Entities, concepts, and facts mentioned in the response
- Relationships between entities
- Metrics, values, and specific details

Do NOT create generic nodes like 'User' or 'Assistant'.
Ensure node names are canonical (Title Case).
Only extract information that is relevant to the current slot/question."""

        messages = [
            {"role": "system", "content": system_content}
        ]

        if history:
            # Flatten history (limit last 6 turns)
            for msg in history[-6:]:
                if hasattr(msg, "content"):  # LangChain Object
                    role = "user"
                    if hasattr(msg, "type") and msg.type == "ai":
                        role = "assistant"
                    elif hasattr(msg, "role"):
                        role = msg.role
                    content = msg.content
                elif isinstance(msg, dict):  # Check dict last
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                else:
                    continue

                messages.append({"role": role, "content": content})

        # Add current turn
        messages.append({"role": "user", "content": user_message})
        if assistant_message:
            messages.append({"role": "assistant", "content": assistant_message})

        # Call OpenAI with Pydantic Schema
        response = await client.beta.chat.completions.parse(
            model="gpt-4o-2024-08-06",
            messages=messages,
            response_format=GraphUpdates,
            temperature=0.0
        )

        updates = response.choices[0].message.parsed

        if not updates:
            logger.warning(f"Scribe returned no parsed structure for slot {slot_id}")
            return {"nodes": [], "edges": [], "confidence": 0.0, "slot_relevance": 0.0}

        logger.info(f"Scribe extracted for slot {slot_id}: {len(updates.nodes)} nodes, {len(updates.edges)} edges, conf={updates.confidence}")

        # Calculate slot relevance (check if extracted nodes match target type)
        slot_relevance = updates.confidence
        if target_node_type and updates.nodes:
            # Check if any node type matches target
            matching_nodes = [
                n for n in updates.nodes
                if target_node_type.lower() in n.type.lower() or n.type.lower() in target_node_type.lower()
            ]
            if matching_nodes:
                slot_relevance = min(1.0, updates.confidence + 0.2)
            else:
                slot_relevance = max(0.0, updates.confidence - 0.1)

        # Create MemoryEvent BEFORE persist (audit trail)
        if tenant_id:
            memory_event = await create_memory_event(
                twin_id=twin_id,
                tenant_id=tenant_id,
                event_type="slot_extract",
                payload={
                    "slot_id": slot_id,
                    "target_node_type": target_node_type,
                    "raw_nodes": [n.model_dump() for n in updates.nodes],
                    "raw_edges": [e.model_dump() for e in updates.edges],
                    "confidence": updates.confidence,
                    "slot_relevance": slot_relevance
                },
                status="applied",
                source_type="chat_turn",
                source_id=conversation_id
            )

        # Persist to Supabase
        created_nodes = await _persist_nodes(twin_id, updates.nodes)

        # Create map for Edges
        node_map = {n['name']: n['id'] for n in created_nodes}

        # Persist Edges
        valid_edges = []
        for edge in updates.edges:
            from_id = node_map.get(edge.from_node)
            to_id = node_map.get(edge.to_node)

            if from_id and to_id:
                valid_edges.append(edge)

        created_edges = await _persist_edges(twin_id, valid_edges, node_map)

        # Update MemoryEvent with resolved IDs
        if memory_event:
            await update_memory_event(memory_event['id'], {
                "nodes_created": [n['id'] for n in created_nodes],
                "edges_created": [e['id'] for e in created_edges],
                "node_count": len(created_nodes),
                "edge_count": len(created_edges)
            })

        return {
            "nodes": created_nodes,
            "edges": created_edges,
            "confidence": updates.confidence,
            "slot_relevance": slot_relevance,
            "memory_event_id": memory_event['id'] if memory_event else None
        }

    except Exception as e:
        logger.error(f"Scribe Engine Error (slot {slot_id}): {e}", exc_info=True)
        logger.error("Scribe Engine Critical Failure (slot %s): %s", slot_id, e)

        # Create failed MemoryEvent for audit trail
        if tenant_id:
            await create_memory_event(
                twin_id=twin_id,
                tenant_id=tenant_id,
                event_type="slot_extract",
                payload={"slot_id": slot_id, "error": str(e)},
                status="failed",
                source_type="chat_turn",
                source_id=conversation_id
            )

        return {"nodes": [], "edges": [], "confidence": 0.0, "slot_relevance": 0.0, "error": str(e)}


async def _persist_nodes(twin_id: str, nodes: list[NodeUpdate]) -> list[dict[str, Any]]:
    """Persist nodes using system RPC."""
    results = []
    for node in nodes:
        try:
            # Convert List[Property] back to Dict for JSON storage
            props_dict = {p.key: p.value for p in node.properties}

            res = supabase.rpc("create_node_system", {
                "t_id": twin_id,
                "n_name": node.name,
                "n_type": node.type,
                "n_desc": node.description,
                "n_props": props_dict
            }).execute()

            if res.data:
                results.append(res.data[0])

        except Exception as e:
            logger.error(f"Failed to create node {node.name}: {e}")

    return results

async def _persist_edges(twin_id: str, edges: list[EdgeUpdate], node_map: dict[str, str]) -> list[dict[str, Any]]:
    """Persist edges using system RPC."""
    results = []
    for edge in edges:
        try:
            from_id = node_map.get(edge.from_node)
            to_id = node_map.get(edge.to_node)

            res = supabase.rpc("create_edge_system", {
                "t_id": twin_id,
                "from_id": from_id,
                "to_id": to_id,
                "e_type": edge.type,
                "e_desc": edge.description,
                "e_props": {}
            }).execute()

            if res.data:
                results.append(res.data[0])

        except Exception as e:
            logger.error(f"Failed to create edge {edge.from_node}->{edge.to_node}: {e}")

    return results


# --- Job Queue Integration (P0-D) ---

def _generate_idempotency_key(conversation_id: str, user_message: str, assistant_message: str) -> str:
    """
    Generate idempotency key for graph extraction job.
    Format: conversation_id:hash(user_message + assistant_message)
    """
    content_hash = hashlib.sha256(
        (user_message + assistant_message).encode('utf-8')
    ).hexdigest()[:16]
    return f"{conversation_id}:{content_hash}"


def enqueue_graph_extraction_job(
    twin_id: str,
    user_message: str,
    assistant_message: str,
    history: list[dict[str, Any]] = None,
    tenant_id: str = None,
    conversation_id: str = None
) -> str:
    """
    Enqueue a graph extraction job instead of fire-and-forget.
    Makes extraction observable and reliable with retries.

    Returns:
        Job ID (UUID)
    """
    if not conversation_id:
        # Can't create idempotency key without conversation_id
        logger.warning("[Graph Extraction] No conversation_id, skipping job enqueue")
        return None

    # Generate idempotency key
    idempotency_key = _generate_idempotency_key(conversation_id, user_message, assistant_message)

    # Check if already processed (idempotency check)
    from modules.observability import supabase
    try:
        # Check for existing job with same idempotency key
        # Query jobs and filter in Python (Supabase client JSONB query is limited)
        existing_jobs_result = supabase.table("jobs").select("id, status, metadata").eq("twin_id", twin_id).eq("job_type", JobType.GRAPH_EXTRACTION.value).order("created_at", desc=True).limit(50).execute()
        if existing_jobs_result.data:
            for existing_job in existing_jobs_result.data:
                job_metadata = existing_job.get("metadata", {})
                if isinstance(job_metadata, dict) and job_metadata.get("idempotency_key") == idempotency_key:
                    if existing_job["status"] in [JobStatus.COMPLETE.value, JobStatus.PROCESSING.value]:
                        logger.info("[Graph Extraction] Job already processed (idempotency_key=%s, job_id=%s)", idempotency_key, existing_job['id'])
                        return existing_job["id"]
    except Exception as e:
        logger.warning("[Graph Extraction] Error checking idempotency: %s", e)

    # Create job metadata
    metadata = {
        "idempotency_key": idempotency_key,
        "user_message": user_message,
        "assistant_message": assistant_message,
        "conversation_id": conversation_id,
        "tenant_id": tenant_id,
        "history_count": len(history) if history else 0
    }

    # Create job in database
    job = create_job(
        job_type=JobType.GRAPH_EXTRACTION,
        twin_id=twin_id,
        priority=0,  # Normal priority
        metadata=metadata
    )

    # Enqueue to Redis/queue
    enqueue_job(job.id, JobType.GRAPH_EXTRACTION.value, priority=0, metadata=metadata)

    logger.info("[Graph Extraction] Enqueued job %s for twin %s, conversation %s", job.id, twin_id, conversation_id)
    return job.id


def _infer_source_type_from_filename(filename: str) -> str:
    name = (filename or "").lower()
    if "youtube" in name or "youtu.be" in name:
        return "youtube"
    if "podcast" in name or "rss" in name or "anchor.fm" in name or "podbean" in name:
        return "podcast"
    if "x thread" in name or "twitter.com" in name or "x.com" in name:
        return "twitter"
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith(".docx"):
        return "docx"
    if name.endswith(".xlsx"):
        return "xlsx"
    if name.startswith("http://") or name.startswith("https://"):
        return "url"
    return "ingested_content"


def enqueue_content_extraction_job(
    twin_id: str,
    source_id: str,
    tenant_id: str = None,
    source_type: str = None,
    max_chunks: int = None
) -> str:
    """
    Enqueue a content extraction job for ingested sources.
    This runs extract_from_content asynchronously to build the graph.
    """
    if not source_id:
        logger.warning("[Content Extraction] Missing source_id, skipping enqueue")
        return None

    # Simple idempotency: avoid duplicates for the same source_id
    try:
        existing = supabase.table("jobs").select("id,status").eq(
            "job_type", JobType.CONTENT_EXTRACTION.value
        ).eq("source_id", source_id).order("created_at", desc=True).limit(1).execute()
        if existing.data:
            status = existing.data[0].get("status")
            if status in [JobStatus.QUEUED.value, JobStatus.PROCESSING.value, JobStatus.COMPLETE.value]:
                logger.info("[Content Extraction] Job already exists for source %s (status=%s)", source_id, status)
                return existing.data[0]["id"]
    except Exception as e:
        logger.warning("[Content Extraction] Idempotency check failed: %s", e)

    metadata = {
        "source_id": source_id,
        "tenant_id": tenant_id,
        "source_type": source_type,
        "max_chunks": max_chunks
    }

    job = create_job(
        job_type=JobType.CONTENT_EXTRACTION,
        twin_id=twin_id,
        source_id=source_id,
        priority=0,
        metadata=metadata
    )
    enqueue_job(job.id, JobType.CONTENT_EXTRACTION.value, priority=0, metadata=metadata)
    logger.info("[Content Extraction] Enqueued job %s for source %s", job.id, source_id)
    return job.id


async def process_graph_extraction_job(job_id: str) -> bool:
    """
    Process a graph extraction job (called by worker).
    Includes retry logic and error handling.

    Returns:
        True if successful, False otherwise
    """
    from modules.observability import supabase

    # Get job details
    job_result = supabase.table("jobs").select("*").eq("id", job_id).single().execute()
    if not job_result.data:
        logger.warning("[Graph Extraction] Job %s not found", job_id)
        return False

    job = job_result.data
    metadata = job.get("metadata", {})
    twin_id = job["twin_id"]
    _ = metadata.get("idempotency_key")
    user_message = metadata.get("user_message", "")
    assistant_message = metadata.get("assistant_message", "")
    conversation_id = metadata.get("conversation_id")
    tenant_id = metadata.get("tenant_id")
    _ = metadata.get("history_count", 0)

    # Mark as processing
    try:
        start_job(job_id)
        append_log(job_id, f"Starting graph extraction for conversation {conversation_id}", LogLevel.INFO)
    except Exception as e:
        logger.error("[Graph Extraction] Error starting job %s: %s", job_id, e)
        return False

    # Retry logic
    max_retries = 3
    retry_delay = 1.0  # seconds

    for attempt in range(max_retries):
        try:
            # Call process_interaction (core extraction logic)
            result = await process_interaction(
                twin_id=twin_id,
                user_message=user_message,
                assistant_message=assistant_message,
                history=None,  # History is not stored in job metadata
                tenant_id=tenant_id,
                conversation_id=conversation_id
            )

            # Check for errors
            if result.get("error"):
                raise Exception(result["error"])

            # Mark as complete
            complete_job(job_id, metadata={
                "nodes_created": len(result.get("nodes", [])),
                "edges_created": len(result.get("edges", [])),
                "confidence": result.get("confidence", 0.0)
            })
            append_log(job_id, f"Graph extraction completed: {len(result.get('nodes', []))} nodes, {len(result.get('edges', []))} edges", LogLevel.INFO)
            return True

        except Exception as e:
            error_msg = str(e)
            logger.warning("[Graph Extraction] Attempt %s/%s failed for job %s: %s", attempt + 1, max_retries, job_id, error_msg)
            append_log(job_id, f"Attempt {attempt + 1} failed: {error_msg}", LogLevel.ERROR, metadata={"attempt": attempt + 1})

            if attempt < max_retries - 1:
                # Wait before retry (exponential backoff)
                import asyncio
                await asyncio.sleep(retry_delay * (2 ** attempt))
            else:
                # All retries exhausted
                fail_job(job_id, f"Failed after {max_retries} attempts: {error_msg}")
                append_log(job_id, f"Job failed after {max_retries} attempts", LogLevel.ERROR)
                return False

    return False


async def process_content_extraction_job(job_id: str) -> bool:
    """
    Process a content extraction job (called by worker).
    Extracts graph nodes/edges from ingested source content.
    """
    job_result = supabase.table("jobs").select("*").eq("id", job_id).single().execute()
    if not job_result.data:
        logger.warning("[Content Extraction] Job %s not found", job_id)
        return False

    job = job_result.data
    metadata = job.get("metadata", {}) or {}
    twin_id = job.get("twin_id")
    source_id = metadata.get("source_id") or job.get("source_id")
    tenant_id = metadata.get("tenant_id")
    max_chunks = metadata.get("max_chunks")

    if not source_id or not twin_id:
        fail_job(job_id, "Missing source_id or twin_id")
        return False

    try:
        start_job(job_id)
        append_log(job_id, f"Starting content extraction for source {source_id}", LogLevel.INFO)

        source_res = supabase.table("sources").select(
            "id, content_text, filename"
        ).eq("id", source_id).single().execute()
        if not source_res.data:
            raise ValueError("Source not found")

        source = source_res.data
        content_text = source.get("content_text") or ""
        filename = source.get("filename") or ""

        if not content_text or len(content_text.strip()) < 50:
            complete_job(job_id, metadata={"nodes_created": 0, "edges_created": 0, "chunks_processed": 0})
            append_log(job_id, "Content too short for extraction", LogLevel.WARNING)
            return True

        source_type = metadata.get("source_type") or _infer_source_type_from_filename(filename)
        if not max_chunks:
            try:
                max_chunks = int(os.getenv("CONTENT_EXTRACT_MAX_CHUNKS", "6"))
            except Exception:
                max_chunks = 6

        result = await extract_from_content(
            twin_id=twin_id,
            content_text=content_text,
            source_id=source_id,
            source_type=source_type,
            max_chunks=max_chunks,
            tenant_id=tenant_id
        )

        if result.get("error"):
            raise ValueError(result.get("error"))

        nodes_created = len(result.get("all_nodes", []))
        edges_created = len(result.get("all_edges", []))
        chunks_processed = result.get("chunks_processed", 0)
        confidence = result.get("total_confidence", 0.0)

        complete_job(job_id, metadata={
            "nodes_created": nodes_created,
            "edges_created": edges_created,
            "chunks_processed": chunks_processed,
            "confidence": confidence
        })
        append_log(job_id, f"Content extraction complete: {nodes_created} nodes, {edges_created} edges", LogLevel.INFO)
        return True

    except Exception as e:
        fail_job(job_id, f"Content extraction failed: {e}")
        append_log(job_id, f"Content extraction failed: {e}", LogLevel.ERROR)
        return False


# --- Content Ingestion Integration ---

@observe(name="scribe_content_extraction")
async def extract_from_content(
    twin_id: str,
    content_text: str,
    source_id: str = None,
    source_type: str = "ingested_content",
    chunk_size: int = 4000,
    max_chunks: int = 10,
    tenant_id: str = None
) -> dict[str, Any]:
    """
    Extract graph nodes and edges from ingested content (YouTube, podcasts, PDFs, etc.).

    Unlike process_interaction() which handles conversation turns, this function
    processes longer-form content by chunking it and extracting entities.

    Args:
        twin_id: Twin ID
        content_text: Full text content to extract from
        source_id: UUID of the source (for attribution)
        source_type: Type of source (youtube, podcast, pdf, etc.)
        chunk_size: Characters per chunk (default 4000)
        max_chunks: Maximum chunks to process (to limit API costs)
        tenant_id: Tenant ID for memory events

    Returns:
        Dict with all_nodes, all_edges, chunks_processed, total_confidence
    """
    from modules.memory_events import create_memory_event

    if not content_text or len(content_text.strip()) < 50:
        logger.warning(f"Content too short for extraction: {len(content_text) if content_text else 0} chars")
        return {"all_nodes": [], "all_edges": [], "chunks_processed": 0, "total_confidence": 0.0}

    try:
        client = get_async_openai_client()

        # Chunk the content
        chunks = []
        for i in range(0, len(content_text), chunk_size):
            chunk = content_text[i:i + chunk_size]
            if len(chunk.strip()) > 50:  # Skip tiny chunks
                chunks.append(chunk)

        # Limit chunks to process
        chunks = chunks[:max_chunks]

        logger.info(f"Extracting from content: {len(content_text)} chars -> {len(chunks)} chunks")

        all_nodes = []
        all_edges = []
        node_map = {}
        total_confidence = 0.0

        for idx, chunk in enumerate(chunks):
            try:
                # Build content-focused extraction prompt
                messages = [
                    {"role": "system", "content": (
                        "You are an expert Knowledge Graph Scribe extracting information from content. "
                        "Your goal is to extract structured entities (Nodes) and relationships (Edges) "
                        "from this text content. "
                        "\n\nFocus on:"
                        "\n- Named entities (people, companies, products, places)"
                        "\n- Key concepts, ideas, and topics"
                        "\n- Metrics, statistics, and numbers"
                        "\n- Opinions, beliefs, and viewpoints"
                        "\n- Relationships between entities"
                        "\n\nDo NOT create generic nodes like 'Content' or 'Author'. "
                        "Use Title Case for node names. Be selective - extract only meaningful entities."
                    )},
                    {"role": "user", "content": f"Extract entities and relationships from this content:\n\n{chunk}"}
                ]

                # Call OpenAI with structured output
                response = await client.beta.chat.completions.parse(
                    model="gpt-4o-2024-08-06",
                    messages=messages,
                    response_format=GraphUpdates,
                    temperature=0.0
                )

                updates = response.choices[0].message.parsed

                if updates and updates.nodes:
                    # Persist nodes and track for edge resolution
                    created_nodes = await _persist_nodes(twin_id, updates.nodes)

                    for node in created_nodes:
                        if node.get('name') and node.get('id'):
                            node_map[node['name']] = node['id']
                            all_nodes.append(node)

                    # Persist edges
                    if updates.edges:
                        valid_edges = [
                            edge for edge in updates.edges
                            if node_map.get(edge.from_node) and node_map.get(edge.to_node)
                        ]
                        created_edges = await _persist_edges(twin_id, valid_edges, node_map)
                        all_edges.extend(created_edges)

                    total_confidence += updates.confidence
                    logger.info(f"Chunk {idx+1}/{len(chunks)}: {len(updates.nodes)} nodes, {len(updates.edges)} edges")

            except Exception as chunk_error:
                logger.warning(f"Error extracting chunk {idx+1}: {chunk_error}")
                continue

        # Create memory event for audit
        if tenant_id and all_nodes:
            await create_memory_event(
                twin_id=twin_id,
                tenant_id=tenant_id,
                event_type="content_extract",
                payload={
                    "source_id": source_id,
                    "source_type": source_type,
                    "chunks_processed": len(chunks),
                    "nodes_created": len(all_nodes),
                    "edges_created": len(all_edges)
                },
                status="applied",
                source_type=source_type,
                source_id=source_id
            )

        avg_confidence = total_confidence / len(chunks) if chunks else 0.0

        # Phase 8: Emit event for Action Engine
        from modules.actions_engine import EventEmitter
        EventEmitter.emit(
            twin_id=twin_id,
            event_type="source_ingested",
            payload={
                "source_id": source_id,
                "source_type": source_type,
                "node_count": len(all_nodes),
                "edge_count": len(all_edges),
                "confidence": avg_confidence,
                "content_preview": content_text[:1000] # For trigger matching (keywords)
            },
            source_context={
                "source": "scribe_engine",
                "method": "extract_from_content",
                "tenant_id": tenant_id
            }
        )

        return {
            "all_nodes": all_nodes,
            "all_edges": all_edges,
            "chunks_processed": len(chunks),
            "total_confidence": avg_confidence,
            "source_id": source_id
        }

    except Exception as e:
        logger.error(f"Content extraction error: {e}", exc_info=True)
        return {"all_nodes": [], "all_edges": [], "chunks_processed": 0, "error": str(e)}


# --- Legacy Support ---

def extract_structured_output(text: str, schema: dict) -> dict:
    return {}

def score_confidence(data: dict) -> float:
    return data.get("confidence", 0.0)

def detect_contradictions(new_data: dict, existing_data: dict) -> list:
    return []
