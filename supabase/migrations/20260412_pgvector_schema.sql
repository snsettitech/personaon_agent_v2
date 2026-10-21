-- =============================================================================
-- pgvector Schema Migration for PersonaOn Vector Search
-- Phase 20: Production Hardening — Pinecone → pgvector migration
-- =============================================================================

-- INFRA-01: Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- INFRA-02: Add embedding column (nullable — backfill populates in Phase 21)
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding vector(768);

-- INFRA-03: Add denormalized twin_id column (nullable — backfill populates in Phase 21)
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS twin_id UUID;

-- Add updated_at column for ON CONFLICT upsert tracking
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- INFRA-05: Create search_chunks RPC function
-- Uses cosine distance operator (<=>), converts to similarity via 1 - distance.
-- Tenant isolation via WHERE clause (not RLS) for HNSW index compatibility.
-- LINT-ALLOW: new-overload  (first definition of search_chunks; no prior to drop)
CREATE OR REPLACE FUNCTION search_chunks(
    query_embedding vector(768),
    query_twin_id UUID,
    match_count INT DEFAULT 5
)
RETURNS TABLE (
    id UUID,
    content TEXT,
    source_id UUID,
    metadata JSONB,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    SET LOCAL hnsw.ef_search = 200;

    RETURN QUERY
    SELECT
        c.id,
        c.content,
        c.source_id,
        c.metadata,
        (1 - (c.embedding <=> query_embedding))::FLOAT AS similarity
    FROM chunks c
    WHERE c.twin_id = query_twin_id
      AND c.embedding IS NOT NULL
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- NOTE: HNSW index is NOT created here. It is created in Phase 22 after Phase 21
-- backfill. Building HNSW before bulk insert causes ~10x slowdown per INSERT.
