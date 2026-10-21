-- =============================================================================
-- HNSW index on chunks.embedding (cosine)
-- =============================================================================
-- Deferred from 20260412_pgvector_schema.sql ("HNSW index is created in Phase 22
-- after backfill"). That follow-up migration was never written: the index was
-- hand-created on PROD only, so it lived outside version control. Staging and any
-- fresh environment therefore lacked it — validate_index() reports
-- "hnsw_index": false and vector_search falls back to a sequential scan
-- (O(n) per query). PROD: hnsw_index true (1492 vec); STAGING: false (2749 vec).
--
-- This codifies the index so every environment converges. Idempotent — a no-op
-- on prod where it already exists.
--
-- - cosine ops (vector_cosine_ops) to match search_chunks: ORDER BY embedding <=> q
-- - name contains "embedding" + "hnsw" so validate_index()'s health probe
--   ('%embedding%hnsw%') flips to true once applied
-- - m / ef_construction are pgvector defaults; safe for the current corpus size
--
-- NOTE: plain CREATE INDEX takes a brief ACCESS EXCLUSIVE lock while building.
-- The corpus is small (<3k rows) so this is sub-second. For a very large future
-- table, prefer CREATE INDEX CONCURRENTLY (which cannot run inside a txn).

CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
