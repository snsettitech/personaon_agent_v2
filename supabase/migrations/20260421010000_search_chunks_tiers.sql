-- =============================================================================
-- Phase 30-A: search_chunks() — privacy tier filtering + similarity threshold
-- Backwards compatible: all new params are optional with safe defaults.
--   allowed_tiers  NULL  → no tier filter (same behaviour as before)
--   min_similarity 0.0   → no threshold (same behaviour as before)
--
-- HISTORICAL NOTE: this migration originally shipped without these DROPs,
-- which left the 3-arg search_chunks and 4-arg search_chunks_global from
-- earlier migrations live alongside the new 5-arg forms and produced
-- AmbiguousFunctionError on the first live meeting. The DROPs below were
-- added retroactively; a separate idempotent cleanup also exists as
-- 20260422_drop_legacy_search_chunks_overloads.sql. Either path lands the
-- DB in the same correct state (only 5-arg overloads).
-- =============================================================================

DROP FUNCTION IF EXISTS search_chunks(vector, uuid, integer);
DROP FUNCTION IF EXISTS search_chunks_global(vector, uuid[], integer, integer);

-- FUNC-01: Per-twin search with optional privacy tier filter and similarity floor.
--
-- HNSW compatibility note:
--   pgvector's HNSW index is optimised for ORDER BY embedding <=> $vec LIMIT n.
--   Adding WHERE privacy_level = ANY(...) is a post-filter; ef_search=200 gives
--   enough candidates that the filter rarely degrades result count in practice.
--   The overfetch (LIMIT match_count * 3) then re-limits after similarity floor
--   so callers reliably receive up to match_count results.
CREATE OR REPLACE FUNCTION search_chunks(
    query_embedding  vector(768),
    query_twin_id    UUID,
    match_count      INT     DEFAULT 5,
    min_similarity   FLOAT   DEFAULT 0.0,
    allowed_tiers    TEXT[]  DEFAULT NULL
)
RETURNS TABLE (
    id            UUID,
    content       TEXT,
    source_id     UUID,
    metadata      JSONB,
    similarity    FLOAT,
    privacy_level TEXT
)
LANGUAGE plpgsql
AS $$
BEGIN
    -- Increase HNSW candidate pool to compensate for privacy post-filter.
    SET LOCAL hnsw.ef_search = 200;

    RETURN QUERY
    SELECT q.id, q.content, q.source_id, q.metadata, q.similarity, q.privacy_level
    FROM (
        SELECT
            c.id,
            c.content,
            c.source_id,
            c.metadata,
            (1 - (c.embedding <=> query_embedding))::FLOAT AS similarity,
            c.privacy_level
        FROM chunks c
        WHERE c.twin_id = query_twin_id
          AND c.embedding IS NOT NULL
          AND (allowed_tiers IS NULL OR c.privacy_level = ANY(allowed_tiers))
        ORDER BY c.embedding <=> query_embedding
        -- Overfetch 3× to ensure match_count survive the similarity floor below.
        LIMIT match_count * 3
    ) q
    WHERE q.similarity >= min_similarity
    ORDER BY q.similarity DESC
    LIMIT match_count;
END;
$$;

-- FUNC-02: Cross-twin global search — add privacy tier filter.
-- Used by the marketplace "Ask" feature; only public chunks should be searched.
-- allowed_tiers defaults to ARRAY['public'] here (unlike per-twin search where
-- the caller controls the tier based on requester relationship).
CREATE OR REPLACE FUNCTION search_chunks_global(
    query_embedding  vector(768),
    tenant_ids       UUID[],
    per_tenant_limit INT     DEFAULT 3,
    global_limit     INT     DEFAULT 30,
    allowed_tiers    TEXT[]  DEFAULT ARRAY['public']
)
RETURNS TABLE (
    twin_id       UUID,
    chunk_id      UUID,
    content       TEXT,
    metadata      JSONB,
    similarity    FLOAT
)
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
    RETURN QUERY
    SELECT q.twin_id, q.chunk_id, q.content, q.metadata, q.similarity
    FROM unnest(tenant_ids) AS t(tid)
    CROSS JOIN LATERAL (
        SELECT
            c.twin_id,
            c.id AS chunk_id,
            c.content,
            c.metadata,
            (1 - (c.embedding <=> query_embedding))::FLOAT AS similarity
        FROM chunks c
        WHERE c.twin_id = t.tid
          AND c.embedding IS NOT NULL
          AND c.privacy_level = ANY(allowed_tiers)
        ORDER BY c.embedding <=> query_embedding
        LIMIT per_tenant_limit
    ) q
    ORDER BY q.similarity DESC
    LIMIT global_limit;
END;
$$;
