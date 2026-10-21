-- =============================================================================
-- Phase 30-A: KB Privacy Tier Schema
-- Adds privacy_level and content_date to chunks table.
-- Enables per-tier access filtering in search_chunks() (see next migration).
-- =============================================================================

-- COL-01: Privacy tier — controls which agents can read this chunk.
--   'public'  → any requester (widget, external meetings, marketplace)
--   'team'    → authenticated org members only
--   'private' → twin owner only (personal notes, drafts, confidential)
-- Default 'public' so all existing chunks remain searchable with no backfill needed.
ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS privacy_level TEXT NOT NULL DEFAULT 'public'
    CHECK (privacy_level IN ('public', 'team', 'private'));

-- COL-02: When the source content was created/published.
-- Used for recency-weighted search and time-scoped queries (e.g. "last 30 days").
-- Nullable — populated during ingestion when source provides a date.
ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS content_date TIMESTAMPTZ;

-- INDEX-01: Privacy level filter — used in search_chunks() WHERE clause.
-- Partial index on non-public chunks to keep index small (most chunks are public).
CREATE INDEX IF NOT EXISTS idx_chunks_privacy_level
    ON chunks (twin_id, privacy_level)
    WHERE privacy_level != 'public';

-- INDEX-02: Content date — for recency filtering and time-scoped queries.
CREATE INDEX IF NOT EXISTS idx_chunks_content_date
    ON chunks (twin_id, content_date)
    WHERE content_date IS NOT NULL;

-- BACKFILL: All existing chunks are public knowledge — set explicitly.
-- The DEFAULT above handles new rows; this covers the existing corpus.
UPDATE chunks SET privacy_level = 'public' WHERE privacy_level IS NULL;
