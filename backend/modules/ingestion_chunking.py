"""
Text chunking, embedding, and indexing pipeline.

Extracted from ingestion.py -- contains chunk_text, chunk_text_with_metadata,
_build_embedding_text, analyze_chunk_content, and process_and_index_text.
"""

import inspect
import json
import logging
import uuid as uuid_mod
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

from modules.embeddings import get_embedding
from modules.clients import get_openai_client, get_pgvector_pool
from modules.observability import supabase, log_ingestion_event
from modules.ingestion_diagnostics import start_step, finish_step, build_error
from modules.access_groups import get_default_group, add_content_permission
from modules.twin_namespace import get_primary_namespace_for_twin, resolve_creator_id_for_twin
from modules.doc_sectioning import extract_section_blocks
try:
    from modules.persona_extraction_service import run_persona_extraction_for_source
except ImportError:
    def run_persona_extraction_for_source(*args, **kwargs):  # type: ignore[misc]
        return {"enabled": False}

from modules.ingestion_config import _to_bool


# -- helpers ------------------------------------------------------------------


def _normalize(vec: list[float]) -> list[float]:
    """L2-normalize a vector. Gemini MRL 768d is NOT pre-normalized."""
    arr = np.array(vec, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm == 0.0:
        return vec
    return (arr / norm).tolist()


def _vec_to_str(vec: list[float]) -> str:
    """Convert vector to pgvector text format: '[0.1,0.2,...]'."""
    return "[" + ",".join(str(v) for v in vec) + "]"


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    chunks = []
    for i in range(0, len(text), chunk_size - overlap):
        chunks.append(text[i:i + chunk_size])
    return chunks


def _build_embedding_text(entry: dict[str, Any], chunk_text_value: str) -> str:
    """
    Build embedding text for a chunk entry.
    For prompt_question blocks we prefix the section descriptor so the vector
    carries context about which section the Q&A belongs to, while keeping the
    full chunk text for semantic retrieval quality.
    """
    block_type = str(entry.get("block_type") or "").strip().lower()
    if block_type == "prompt_question":
        section_title = str(entry.get("section_title") or "").strip()
        section_path = str(entry.get("section_path") or "").strip()
        descriptor = section_title or section_path
        if descriptor and chunk_text_value:
            # BUG #22 FIX: include chunk text so the full Q&A is searchable
            return f"{descriptor}: {chunk_text_value}"
    return chunk_text_value


def chunk_text_with_metadata(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 200,
) -> list[dict[str, Any]]:
    """
    Chunk text while preserving best-effort section metadata.
    """
    blocks = extract_section_blocks(text)
    entries: list[dict[str, Any]] = []

    if blocks:
        for block in blocks:
            block_text = str(block.get("text") or "").strip()
            if not block_text:
                continue
            for chunk in chunk_text(block_text, chunk_size=chunk_size, overlap=overlap):
                if not chunk or not chunk.strip():
                    continue
                entries.append(
                    {
                        "text": chunk,
                        "section_title": block.get("section_title"),
                        "section_path": block.get("section_path"),
                        "chunk_type": block.get("chunk_type"),
                        "block_type": block.get("block_type"),
                        "is_answer_text": _to_bool(block.get("is_answer_text"), default=True),
                    }
                )

    if entries:
        return entries

    for chunk in chunk_text(text, chunk_size=chunk_size, overlap=overlap):
        if chunk and chunk.strip():
            entries.append({"text": chunk, "block_type": "answer_text", "is_answer_text": True})
    return entries


async def analyze_chunk_content(text: str) -> dict:
    """
    Analyzes a chunk to generate synthetic questions, category (Fact/Opinion), and tone.

    Primary: Gemini 2.5 Flash (fast, no OpenAI key required).
    Fallback: GPT-4o-mini (if Gemini fails and OPENAI_API_KEY is set).

    SECURITY: Sanitizes input before sending to LLM to prevent prompt injection.
    """
    from modules.llm_safety import sanitize_for_llm, PromptInjectionError

    _safe_defaults = {"questions": [], "category": "FACT", "tone": "Neutral", "opinion_map": None}

    try:
        sanitized_result = sanitize_for_llm(text, strict_mode=False)
        if sanitized_result.warnings:
            logger.warning("[LLM Safety] Warnings for chunk analysis: %s", sanitized_result.warnings)
        safe_text = sanitized_result.sanitized_text
    except PromptInjectionError as e:
        logger.warning("[LLM Safety] Prompt injection detected in chunk: %s", e)
        return _safe_defaults

    # --- Primary: Gemini 2.5 Flash ---
    try:
        from modules.gemini_extraction import gemini_analyze_chunk
        result = await gemini_analyze_chunk(safe_text)
        if result:
            return result
    except Exception as e:
        logger.warning("[ChunkAnalysis] Gemini analysis failed, trying fallback: %s", e)

    # --- Fallback: GPT-4o-mini ---
    try:
        import os
        if not os.getenv("OPENAI_API_KEY"):
            return _safe_defaults
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "Analyze the text chunk provided. Return a JSON object with: "
                    "'questions' (3 brief questions), 'category' (FACT or OPINION), "
                    "'tone' (single word), 'opinion_map' (object or null)."
                )},
                {"role": "user", "content": safe_text},
            ],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.warning("[ChunkAnalysis] GPT fallback also failed: %s", e)
        return _safe_defaults


async def process_and_index_text(
    source_id: str,
    twin_id: str,
    text: str,
    metadata_override: dict = None,
    provider: str = "unknown",
    correlation_id: str | None = None,
    chunk_entries_override: list[dict[str, Any]] | None = None,
    privacy_level: str = "public",
):
    # Step: chunked
    chunk_event_id = start_step(
        source_id=source_id,
        twin_id=twin_id,
        provider=provider,
        step="chunked",
        correlation_id=correlation_id,
        message="Chunking text",
    )
    _MAX_CHUNK_ENTRIES = 5000  # BUG #8 FIX: guard against unbounded overrides
    try:
        chunk_entries = (
            [entry for entry in (chunk_entries_override or [])[:_MAX_CHUNK_ENTRIES] if isinstance(entry, dict)]
            if chunk_entries_override is not None
            else chunk_text_with_metadata(text)
        )
        chunks = [entry.get("text", "") for entry in chunk_entries if isinstance(entry, dict)]
        finish_step(
            event_id=chunk_event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="chunked",
            status="completed",
            correlation_id=correlation_id,
            metadata={"chunks": len(chunks)},
        )
    except Exception as e:
        err = build_error(
            code="CHUNKING_FAILED",
            message=str(e),
            provider=provider,
            step="chunked",
            correlation_id=correlation_id,
            raw={"text_len": len(text) if text else 0},
            exc=e,
        )
        finish_step(
            event_id=chunk_event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="chunked",
            status="error",
            correlation_id=correlation_id,
            error=err,
        )
        raise

    # Step: embedded — generate Gemini embeddings + enrich metadata per chunk
    embed_event_id = start_step(
        source_id=source_id,
        twin_id=twin_id,
        provider=provider,
        step="embedded",
        correlation_id=correlation_id,
        message="Generating embeddings",
        metadata={"chunks": len(chunks)},
    )

    db_chunks: list[dict[str, Any]] = []

    try:
        for entry in chunk_entries:
            chunk = str(entry.get("text") or "")
            if not chunk:
                continue
            chunk_id = str(uuid_mod.uuid4())

            # Analyze chunk for enrichment
            analysis = await analyze_chunk_content(chunk)
            synth_questions = analysis.get("questions", [])

            metadata = {
                "source_id": source_id,
                "twin_id": twin_id,
                "chunk_id": chunk_id,
                "text": chunk,  # Keep original text for grounding
                "synthetic_questions": synth_questions,
                "category": analysis.get("category", "FACT"),
                "tone": analysis.get("tone", "Neutral"),
                "is_verified": False,  # Explicitly mark regular sources as not verified
            }

            # Add opinion mapping if present
            opinion_map = analysis.get("opinion_map")
            if opinion_map and isinstance(opinion_map, dict):
                metadata["opinion_topic"] = opinion_map.get("topic")
                metadata["opinion_stance"] = opinion_map.get("stance")
                metadata["opinion_intensity"] = opinion_map.get("intensity")

            for section_key in ("section_title", "section_path", "chunk_type", "block_type"):
                section_value = entry.get(section_key)
                if isinstance(section_value, str) and section_value.strip():
                    metadata[section_key] = section_value.strip()
            metadata["is_answer_text"] = _to_bool(entry.get("is_answer_text"), default=True)
            page_number = entry.get("page_number")
            if isinstance(page_number, int):
                metadata["page_number"] = page_number
            elif isinstance(page_number, str) and page_number.strip().isdigit():
                metadata["page_number"] = int(page_number.strip())

            if metadata_override:
                metadata.update(metadata_override)
                # BUG #13 FIX: re-assert security fields so metadata_override
                # cannot silently overwrite them with attacker-controlled values
                metadata["twin_id"] = twin_id
                metadata["source_id"] = source_id
                metadata["chunk_id"] = chunk_id

            # Generate embedding via Gemini and normalize
            embedding_text = _build_embedding_text(entry, chunk)
            raw_vec = get_embedding(embedding_text)
            if not raw_vec:
                raise ValueError(
                    f"Embedding returned None/empty for chunk "
                    f"(source_id={source_id}, chunk_id={chunk_id})"
                )
            embedding = _normalize(raw_vec)

            db_chunks.append({
                "id": chunk_id,
                "twin_id": twin_id,
                "source_id": source_id,
                "content": chunk,
                "embedding": embedding,
                "metadata": metadata,
                "privacy_level": privacy_level,
                # Carry synth questions so synthetic rows can be built at index time.
                "_synth_questions": synth_questions,
            })

        finish_step(
            event_id=embed_event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="embedded",
            status="completed",
            correlation_id=correlation_id,
            metadata={"chunks": len(chunks), "vectors": len(db_chunks)},
        )
    except Exception as e:
        err = build_error(
            code="EMBEDDINGS_FAILED",
            message=str(e),
            provider=provider,
            step="embedded",
            correlation_id=correlation_id,
            raw={"chunks": len(chunks)},
            exc=e,
        )
        finish_step(
            event_id=embed_event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="embedded",
            status="error",
            correlation_id=correlation_id,
            error=err,
        )
        raise

    # Step: indexed (asyncpg upsert with embeddings + permissions)
    index_event_id = start_step(
        source_id=source_id,
        twin_id=twin_id,
        provider=provider,
        step="indexed",
        correlation_id=correlation_id,
        message="Persisting chunks with embeddings to pgvector",
        metadata={"vectors": len(db_chunks)},
    )
    try:
        # Delete old DB chunks before inserting new ones
        try:
            supabase.table("chunks").delete().eq("source_id", source_id).execute()
        except Exception as del_err:
            logger.warning("[Ingestion] Failed to clean old chunks for source %s: %s", source_id, del_err)

        # Insert chunks with embeddings via asyncpg
        if db_chunks:
            pool_result = get_pgvector_pool()
            if inspect.isawaitable(pool_result):
                pool_result = await pool_result
            synth_total = 0
            async with pool_result.acquire() as conn:
                for db_chunk in db_chunks:
                    vec_str = _vec_to_str(db_chunk["embedding"])
                    await conn.execute(
                        """
                        INSERT INTO chunks (id, twin_id, source_id, content, embedding, metadata, privacy_level)
                        VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5::vector, $6::jsonb, $7)
                        ON CONFLICT (id) DO UPDATE SET
                            content = EXCLUDED.content,
                            embedding = EXCLUDED.embedding,
                            metadata = EXCLUDED.metadata,
                            privacy_level = EXCLUDED.privacy_level,
                            updated_at = NOW()
                        """,
                        db_chunk["id"], twin_id, source_id,
                        db_chunk["content"], vec_str,
                        json.dumps(db_chunk["metadata"]),
                        db_chunk["privacy_level"],
                    )

                    # Embed each synthetic question as its own searchable vector row.
                    # Deterministic UUID5 so re-indexing the same source is idempotent.
                    for i, question in enumerate(db_chunk.get("_synth_questions") or []):
                        if not question or not str(question).strip():
                            continue
                        q_text = str(question).strip()
                        q_id = str(uuid_mod.uuid5(
                            uuid_mod.NAMESPACE_DNS,
                            f"{db_chunk['id']}:q{i}",
                        ))
                        q_raw_vec = get_embedding(q_text)
                        if not q_raw_vec:
                            continue
                        q_vec_str = _vec_to_str(_normalize(q_raw_vec))
                        q_metadata = {
                            "type": "synthetic_question",
                            "parent_chunk_id": db_chunk["id"],
                            "source_id": source_id,
                            "twin_id": twin_id,
                            "text": q_text,
                        }
                        await conn.execute(
                            """
                            INSERT INTO chunks (id, twin_id, source_id, content, embedding, metadata, privacy_level)
                            VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5::vector, $6::jsonb, $7)
                            ON CONFLICT (id) DO UPDATE SET
                                content = EXCLUDED.content,
                                embedding = EXCLUDED.embedding,
                                metadata = EXCLUDED.metadata,
                                privacy_level = EXCLUDED.privacy_level,
                                updated_at = NOW()
                            """,
                            q_id, twin_id, source_id,
                            q_text, q_vec_str,
                            json.dumps(q_metadata),
                            db_chunk["privacy_level"],
                        )
                        synth_total += 1

            logger.info(
                "[pgvector] Upserted %s chunks + %s synthetic question vectors for source_id=%s",
                len(db_chunks), synth_total, source_id,
            )

        # Ensure default group has access to this source (required for retrieval filtering)
        try:
            default_group = await get_default_group(twin_id)
            if default_group and default_group.get("id"):
                await add_content_permission(default_group["id"], "source", source_id, twin_id)
                log_ingestion_event(source_id, twin_id, "info", "Default group permission granted for source")
        except Exception as e:
            log_ingestion_event(source_id, twin_id, "warning", f"Failed to grant default group permission: {e}")
            logger.warning("[Ingestion] Failed to grant default group permission for source %s: %s", source_id, e)

        finish_step(
            event_id=index_event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="indexed",
            status="completed",
            correlation_id=correlation_id,
            metadata={"vectors": len(db_chunks), "chunks": len(db_chunks)},
        )
    except Exception as e:
        err = build_error(
            code="INDEXING_FAILED",
            message=str(e),
            provider=provider,
            step="indexed",
            correlation_id=correlation_id,
            raw={"vectors": len(db_chunks), "chunks": len(db_chunks)},
            exc=e,
        )
        finish_step(
            event_id=index_event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="indexed",
            status="error",
            correlation_id=correlation_id,
            error=err,
        )
        raise

    # Optional persona extraction path (safe, non-fatal, flag-gated).
    try:
        extraction_summary = run_persona_extraction_for_source(
            twin_id=twin_id,
            source_id=source_id,
            text=text,
            provider=provider,
        )
        if extraction_summary.get("enabled"):
            logger.info(
                "[Ingestion] Persona extraction summary source_id=%s twin_id=%s outcome=%s",
                source_id, twin_id, extraction_summary,
            )
    except Exception as e:
        logger.warning("[Ingestion] Persona extraction hook failed (non-fatal): %s", e)

    return len(db_chunks)
