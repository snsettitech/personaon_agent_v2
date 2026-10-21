-- ============================================================================
-- Deep Research: Phase 1B.1 - Recrawl Idempotency
-- ============================================================================
-- Adds url_hash column and indexes for canonical URL-based deduplication
--
-- Created: 2026-02-23
-- Phase: 1B.1
-- Depends On: migration_phase_deep_research_crawl_tables.sql
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Add url_hash column to crawl_pages (canonical_url already exists from Phase 1A)
-- ----------------------------------------------------------------------------
ALTER TABLE crawl_pages 
ADD COLUMN IF NOT EXISTS url_hash TEXT;

-- ----------------------------------------------------------------------------
-- Add previous_page_id for version chaining (Phase 1B+)
-- ----------------------------------------------------------------------------
ALTER TABLE crawl_pages 
ADD COLUMN IF NOT EXISTS previous_page_id UUID REFERENCES crawl_pages(id);

-- ----------------------------------------------------------------------------
-- Add removed_at for tracking removed pages
-- ----------------------------------------------------------------------------
ALTER TABLE crawl_pages 
ADD COLUMN IF NOT EXISTS removed_at TIMESTAMPTZ;

-- ----------------------------------------------------------------------------
-- Create indexes for idempotency lookups
-- ----------------------------------------------------------------------------

-- Index for looking up pages by URL hash (fast dedup checks)
CREATE INDEX IF NOT EXISTS idx_crawl_pages_url_hash 
ON crawl_pages(url_hash);

-- Composite index for twin-scoped canonical URL lookups
-- Used when checking if a URL was already crawled for a specific twin
CREATE INDEX IF NOT EXISTS idx_crawl_pages_twin_canonical 
ON crawl_pages(crawl_id, canonical_url);

-- Index for finding pages by content hash (for unchanged detection)
CREATE INDEX IF NOT EXISTS idx_crawl_pages_content_hash 
ON crawl_pages(content_hash) 
WHERE content_hash IS NOT NULL;

-- Index for previous_page_id (for version chain traversal)
CREATE INDEX IF NOT EXISTS idx_crawl_pages_previous 
ON crawl_pages(previous_page_id) 
WHERE previous_page_id IS NOT NULL;

-- ----------------------------------------------------------------------------
-- Add index on crawl_runs for previous_crawl_id lookups
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_crawl_runs_previous 
ON crawl_runs(previous_crawl_id) 
WHERE previous_crawl_id IS NOT NULL;

-- ----------------------------------------------------------------------------
-- Comments for documentation
-- ----------------------------------------------------------------------------
COMMENT ON COLUMN crawl_pages.url_hash IS 'SHA-256 hash of canonical_url for fast deduplication lookups';
COMMENT ON COLUMN crawl_pages.previous_page_id IS 'Reference to previous version of this page (for version chaining)';
COMMENT ON COLUMN crawl_pages.removed_at IS 'Timestamp when page was detected as removed during recrawl';

-- ============================================================================
-- End of Migration
-- ============================================================================
