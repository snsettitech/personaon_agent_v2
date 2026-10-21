"""pgvector-backed vector store.

Uses asyncpg + Supabase pgvector for search, upsert, and delete operations.
Gemini 768d embeddings, L2-normalized before storage and query.
Namespace convention: twin_{twin_id} (used for deterministic IDs).
"""

import inspect
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

import numpy as np

from modules.clients import get_pgvector_pool
from modules.embeddings import get_embedding

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 1_000
_CHUNK_OVERLAP = 100


# -- helpers ------------------------------------------------------------------


def namespace_for(twin_id: str) -> str:
    """Return the pgvector namespace string for a twin."""
    return f"twin_{twin_id}"


def _normalize(vec: list[float]) -> list[float]:
    """L2-normalize a vector. Gemini MRL 768d is NOT pre-normalized."""
    arr = np.array(vec, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm == 0.0:
        return vec
    return (arr / norm).tolist()


def _chunk_text(text: str) -> list[str]:
    """Split *text* into overlapping chunks."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + _CHUNK_SIZE
        chunks.append(text[start:end])
        start += _CHUNK_SIZE - _CHUNK_OVERLAP
    return [c for c in chunks if c.strip()]


def _deterministic_id(namespace: str, source: str, index: int) -> str:
    """Generate a deterministic UUID5 for deduplication."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{namespace}:{source}:{index}"))


def _vec_to_str(vec: list[float]) -> str:
    """Convert vector to pgvector text format: '[0.1,0.2,...]'."""
    return "[" + ",".join(str(v) for v in vec) + "]"


async def _get_pool():
    """Resolve the pool, awaiting if get_pgvector_pool is async (production)."""
    result = get_pgvector_pool()
    if inspect.isawaitable(result):
        return await result
    return result


@asynccontextmanager
async def _acquire():
    """Acquire a connection from the pool, compatible with both real asyncpg and mocks."""
    pool = await _get_pool()
    acq = pool.acquire()
    # AsyncMock.acquire() returns a coroutine; real asyncpg returns a context manager
    if inspect.isawaitable(acq) and not hasattr(acq, "__aenter__"):
        acq = await acq
    async with acq as conn:
        yield conn


# -- core operations ----------------------------------------------------------


async def search(
    query: str,
    twin_id: str,
    top_k: int = 5,
    allowed_tiers: list[str] | None = None,
    min_similarity: float = 0.0,
) -> list[dict]:
    """Search a twin's namespace.

    Args:
        allowed_tiers: Privacy tiers to include. None = no filter (returns all tiers).
                       Typical values: ['public'], ['public','team'], ['public','team','private'].
        min_similarity: Cosine similarity floor 0.0–1.0. Results below this score are dropped.
    """
    raw_vec = get_embedding(query)
    vec = _normalize(raw_vec)
    vec_str = _vec_to_str(vec)

    async with _acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM search_chunks($1::vector, $2::uuid, $3, $4, $5::text[])",
            vec_str, twin_id, top_k, min_similarity, allowed_tiers,
        )

    results: list[dict] = []
    for row in rows:
        raw_meta = row["metadata"]
        if isinstance(raw_meta, str):
            meta = json.loads(raw_meta)
        else:
            meta = raw_meta or {}
        results.append({
            "text": row["content"] or "",
            "score": round(float(row["similarity"]), 4),
            "source_id": str(row["source_id"]) if row["source_id"] else "",
            "privacy_level": row["privacy_level"] or "public",
            "filename": meta.get("filename", ""),
            "url": meta.get("url", "") or meta.get("citation_url", ""),
            "type": meta.get("type", ""),
            "source_type": meta.get("source_type", "persona"),
        })

    if not results:
        logger.warning(
            "[VectorStore] zero results query=%r twin_id=%s top_k=%d tiers=%s min_sim=%s",
            query[:80], twin_id, top_k, allowed_tiers, min_similarity,
        )

    return results


async def search_global(
    query: str,
    twin_ids: list[str],
    per_twin_limit: int = 3,
    global_limit: int = 30,
) -> list[dict]:
    """Cross-twin semantic search for marketplace 'Ask' feature.

    Uses the search_chunks_global SQL function (LATERAL join pattern)
    to search across all public twins' chunks in a single call.

    Returns results grouped by twin_id with the best snippet per twin,
    sorted by descending similarity.
    """
    if not twin_ids:
        return []

    raw_vec = get_embedding(query)
    vec = _normalize(raw_vec)
    vec_str = _vec_to_str(vec)

    async with _acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM search_chunks_global($1::vector, $2::uuid[], $3, $4, $5::text[])",
            vec_str, twin_ids, per_twin_limit, global_limit, ["public"],
        )

    results: list[dict] = []
    for row in rows:
        raw_meta = row["metadata"]
        if isinstance(raw_meta, str):
            meta = json.loads(raw_meta)
        else:
            meta = raw_meta or {}
        results.append({
            "twin_id": str(row["twin_id"]),
            "text": row["content"] or "",
            "score": round(float(row["similarity"]), 4),
            "source": meta.get("source", ""),
            "type": meta.get("type", ""),
        })

    logger.info(
        "[VectorStore] search_global query=%r twins=%d results=%d",
        query[:80], len(twin_ids), len(results),
    )

    return results


async def search_meetings(query: str, twin_id: str, top_k: int = 10) -> list[dict]:
    """Search only meeting chunks for a twin using the search_meeting_chunks SQL function."""
    raw_vec = get_embedding(query)
    vec = _normalize(raw_vec)
    vec_str = _vec_to_str(vec)

    async with _acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM search_meeting_chunks($1::vector, $2::uuid, $3)",
            vec_str, twin_id, top_k,
        )

    results: list[dict] = []
    for row in rows:
        raw_meta = row["metadata"]
        if isinstance(raw_meta, str):
            meta = json.loads(raw_meta)
        else:
            meta = raw_meta or {}
        results.append({
            "text": row["content"] or "",
            "score": round(float(row["similarity"]), 4),
            "meeting_id": meta.get("meeting_id", ""),
            "speakers": meta.get("speakers", []),
            "start_time": meta.get("start_time"),
            "end_time": meta.get("end_time"),
            "source_type": "meeting",
        })

    if not results:
        logger.warning(
            "[VectorStore] zero meeting results query=%r twin_id=%s top_k=%d",
            query[:80], twin_id, top_k,
        )

    return results


async def upsert_text_chunks(
    text: str,
    twin_id: str,
    source: str = "profile",
    metadata: dict | None = None,
    source_id: str | None = None,
    privacy_level: str = "public",
) -> int:
    """Chunk text and upsert.

    Args:
        privacy_level: Access tier for these chunks — 'public', 'team', or 'private'.
                       Defaults to 'public' so all existing callers are unaffected.
    """
    chunks = _chunk_text(text)
    if not chunks:
        return 0

    ns = namespace_for(twin_id)
    extra = metadata or {}

    async with _acquire() as conn:
        for i, chunk in enumerate(chunks):
            chunk_id = _deterministic_id(ns, source, i)
            raw_vec = get_embedding(chunk)
            vec = _normalize(raw_vec)
            vec_str = _vec_to_str(vec)

            await conn.execute(
                """
                INSERT INTO chunks (id, twin_id, content, embedding, metadata, source_id, privacy_level)
                VALUES ($1::uuid, $2::uuid, $3, $4::vector, $5::jsonb, $6::uuid, $7)
                ON CONFLICT (id) DO UPDATE SET
                    content = EXCLUDED.content,
                    embedding = EXCLUDED.embedding,
                    metadata = EXCLUDED.metadata,
                    source_id = COALESCE(EXCLUDED.source_id, chunks.source_id),
                    privacy_level = EXCLUDED.privacy_level,
                    updated_at = NOW()
                """,
                chunk_id, twin_id,
                chunk, vec_str,
                json.dumps({**extra, "source": source, "chunk_index": i}),
                source_id,
                privacy_level,
            )

    logger.info(
        "[VectorStore] upserted %d chunk(s) from '%s' for twin_id=%s privacy=%s",
        len(chunks), source, twin_id, privacy_level,
    )
    return len(chunks)


async def upsert_faq(
    question: str, answer: str, twin_id: str, origin: str | None = None
) -> str:
    """Upsert Q&A -- matches legacyupsert_faq() signature.

    ``origin`` optionally tags where the pair came from (e.g. "interview") so
    surface-specific counters can filter on ``metadata->>'origin'``.
    """
    ns = namespace_for(twin_id)
    q, a = question.strip(), answer.strip()
    point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{ns}:faq:{q.lower()}"))

    faq_text = f"Q: {q}\nA: {a}"
    metadata: dict[str, Any] = {"source": "faq", "type": "faq", "question": q, "answer": a}
    if origin:
        metadata["origin"] = origin
    raw_vec = get_embedding(faq_text)
    vec = _normalize(raw_vec)
    vec_str = _vec_to_str(vec)

    async with _acquire() as conn:
        await conn.execute(
            """
            INSERT INTO chunks (id, twin_id, content, embedding, metadata)
            VALUES ($1::uuid, $2::uuid, $3, $4::vector, $5::jsonb)
            ON CONFLICT (id) DO UPDATE SET
                content = EXCLUDED.content,
                embedding = EXCLUDED.embedding,
                metadata = EXCLUDED.metadata,
                updated_at = NOW()
            """,
            point_id, twin_id,
            faq_text, vec_str,
            json.dumps(metadata),
        )

    logger.info("[VectorStore] upserted FAQ twin_id=%s q=%r", twin_id, q[:60])
    return point_id


async def count_faqs(twin_id: str, origin: str | None = None) -> int:
    """Count FAQ chunks for a twin, optionally only those tagged with ``origin``."""
    async with _acquire() as conn:
        if origin:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM chunks WHERE twin_id = $1::uuid"
                " AND metadata->>'source' = 'faq' AND metadata->>'origin' = $2",
                twin_id, origin,
            )
        else:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM chunks WHERE twin_id = $1::uuid"
                " AND metadata->>'source' = 'faq'",
                twin_id,
            )
    return count or 0


async def delete_namespace(twin_id: str) -> None:
    """Delete all chunks for a twin -- matches legacydelete_namespace() signature."""
    async with _acquire() as conn:
        deleted = await conn.execute(
            "DELETE FROM chunks WHERE twin_id = $1::uuid",
            twin_id,
        )
    logger.info("[VectorStore] deleted namespace twin_id=%s result=%s", twin_id, deleted)


async def namespace_stats(twin_id: str) -> dict[str, Any]:
    """Return vector count -- matches legacynamespace_stats() signature."""
    async with _acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM chunks WHERE twin_id = $1::uuid AND embedding IS NOT NULL",
            twin_id,
        )
    return {
        "namespace": namespace_for(twin_id),
        "vector_count": count or 0,
    }


async def validate_index() -> dict[str, Any]:
    """Validate pgvector setup -- matches legacyvalidate_index() signature."""
    async with _acquire() as conn:
        has_ext = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')"
        )
        has_hnsw = await conn.fetchval(
            "SELECT EXISTS("
            "SELECT 1 FROM pg_indexes "
            "WHERE indexname LIKE '%embedding%hnsw%' "
            "OR indexname LIKE '%hnsw%embedding%'"
            ")"
        )

    result: dict[str, Any] = {
        "status": "ok" if has_ext else "error",
        "pgvector_extension": bool(has_ext),
        "hnsw_index": bool(has_hnsw),
    }

    # Total vector count is best-effort (not critical for validation)
    try:
        async with _acquire() as conn:
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL"
            )
        result["total_vectors"] = total or 0
    except Exception:
        result["total_vectors"] = 0

    return result
