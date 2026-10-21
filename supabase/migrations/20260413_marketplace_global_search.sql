-- =============================================================================
-- Marketplace Global Search — cross-twin semantic vector search
-- Enables "Ask the Marketplace" feature: user asks a question, system finds
-- the best persona to answer it by searching all public twins' chunks.
-- =============================================================================

-- INDEX-01: B-tree index on twin_id for fast per-twin filtering in LATERAL join
CREATE INDEX IF NOT EXISTS idx_chunks_twin_id ON chunks (twin_id);

-- INDEX-02: Composite index for the LATERAL subquery pattern:
-- WHERE twin_id = $exact AND embedding IS NOT NULL ORDER BY embedding <=> $vec
-- Without HNSW, this at least skips NULL embeddings and filters by twin_id quickly.
CREATE INDEX IF NOT EXISTS idx_chunks_twin_embedding
    ON chunks (twin_id)
    WHERE embedding IS NOT NULL;

-- FUNC-01: Cross-twin search using LATERAL join pattern.
-- Fires one cosine-distance scan per twin_id, returns top matches per twin,
-- then ranks globally. This avoids the pgvector HNSW post-filter problem
-- where WHERE twin_id = ANY(array) can return fewer than K results.
-- LINT-ALLOW: new-overload  (first definition of search_chunks_global; no prior to drop)
CREATE OR REPLACE FUNCTION search_chunks_global(
    query_embedding vector(768),
    tenant_ids UUID[],
    per_tenant_limit INT DEFAULT 3,
    global_limit INT DEFAULT 30
)
RETURNS TABLE (
    twin_id UUID,
    chunk_id UUID,
    content TEXT,
    metadata JSONB,
    similarity FLOAT
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
        ORDER BY c.embedding <=> query_embedding
        LIMIT per_tenant_limit
    ) q
    ORDER BY q.similarity DESC
    LIMIT global_limit;
END;
$$;
