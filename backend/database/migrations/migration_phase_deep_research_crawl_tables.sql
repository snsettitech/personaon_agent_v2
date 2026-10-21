-- ============================================================================
-- Deep Research: Phase 1A - Crawl Tables
-- ============================================================================
-- Creates tables for persistent crawl infrastructure with metadata-only storage
-- Large content stored in artifacts, not in DB
--
-- Created: 2026-02-23
-- Phase: 1A.1
-- ============================================================================

-- ----------------------------------------------------------------------------
-- crawl_runs: Tracks crawl operations
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crawl_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    
    -- Configuration
    seed_urls JSONB NOT NULL,
    url_canonicalization_rules JSONB DEFAULT '{}',
    max_pages INT DEFAULT 50,
    max_depth INT DEFAULT 2,
    include_patterns JSONB,
    exclude_patterns JSONB,
    safety_config JSONB DEFAULT '{}',
    
    -- Progress tracking
    pages_found INT DEFAULT 0,
    pages_ingested INT DEFAULT 0,
    pages_unchanged INT DEFAULT 0,
    pages_failed INT DEFAULT 0,
    failed_authentications INT DEFAULT 0,
    
    -- Idempotency (Phase 1B)
    previous_crawl_id UUID REFERENCES crawl_runs(id),
    
    -- Timestamps
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Artifact reference (not the content itself)
    manifest_artifact_path TEXT
);

-- Indexes for crawl_runs
CREATE INDEX IF NOT EXISTS idx_crawl_runs_twin_id ON crawl_runs(twin_id);
CREATE INDEX IF NOT EXISTS idx_crawl_runs_status ON crawl_runs(status);
CREATE INDEX IF NOT EXISTS idx_crawl_runs_created_at ON crawl_runs(created_at);

-- ----------------------------------------------------------------------------
-- crawl_pages: Individual pages discovered/fetched (metadata only)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crawl_pages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    crawl_id UUID NOT NULL REFERENCES crawl_runs(id) ON DELETE CASCADE,
    
    -- URL handling
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    url_hash TEXT,  -- Added in Phase 1B
    
    -- Status tracking
    status VARCHAR(20) NOT NULL DEFAULT 'discovered',
    -- Status values: discovered, fetching, unchanged, changed, ingested, 
    --                failed, blocked, removed
    
    -- Content metadata (not the content itself)
    content_hash TEXT,
    previous_content_hash TEXT,  -- For diff detection (Phase 1B)
    content_length INT,
    snippet TEXT,  -- First 500 chars for preview
    
    -- Artifact paths (actual content stored in filesystem)
    normalized_artifact_path TEXT,
    raw_artifact_path TEXT,
    
    -- Metadata extracted during crawl
    metadata JSONB DEFAULT '{}',
    
    -- Content extraction
    fetched_at TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ,
    removed_at TIMESTAMPTZ,  -- For removed pages (Phase 1B)
    
    -- Error tracking with taxonomy
    error_category TEXT,  -- auth, rate_limit, gating, unavailable, network,
                          -- parser_fail, ssrf_blocked, content_type_blocked,
                          -- size_exceeded, timeout, too_many_redirects, 
                          -- private_ip_blocked
    error_detail TEXT,
    retry_count INT DEFAULT 0,
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for crawl_pages
CREATE INDEX IF NOT EXISTS idx_crawl_pages_crawl_id ON crawl_pages(crawl_id);
CREATE INDEX IF NOT EXISTS idx_crawl_pages_status ON crawl_pages(status);
CREATE INDEX IF NOT EXISTS idx_crawl_pages_canonical_url ON crawl_pages(canonical_url);

-- Index for url_hash will be added in Phase 1B migration

-- ----------------------------------------------------------------------------
-- crawl_failures: Denormalized view of failures for fast querying
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crawl_failures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    crawl_id UUID NOT NULL REFERENCES crawl_runs(id) ON DELETE CASCADE,
    crawl_page_id UUID NOT NULL REFERENCES crawl_pages(id) ON DELETE CASCADE,
    
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    
    -- Failure classification
    failure_type TEXT NOT NULL,  -- Same as error_category
    failure_category TEXT NOT NULL,  -- 'hard_block' or 'soft_fail'
    failure_reason TEXT NOT NULL,
    
    -- Artifact reference
    artifact_path TEXT,
    
    -- Retry handling
    is_retryable BOOLEAN DEFAULT FALSE,
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crawl_failures_crawl_id ON crawl_failures(crawl_id);
CREATE INDEX IF NOT EXISTS idx_crawl_failures_type ON crawl_failures(failure_type);

-- ----------------------------------------------------------------------------
-- Update trigger for updated_at
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_crawl_runs_updated_at 
    BEFORE UPDATE ON crawl_runs 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_crawl_pages_updated_at 
    BEFORE UPDATE ON crawl_pages 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- ----------------------------------------------------------------------------
-- Comments for documentation
-- ----------------------------------------------------------------------------
COMMENT ON TABLE crawl_runs IS 'Tracks web crawl operations with metadata-only storage';
COMMENT ON TABLE crawl_pages IS 'Individual pages from crawls - content stored in artifacts';
COMMENT ON TABLE crawl_failures IS 'Denormalized failure log for fast querying and analysis';

COMMENT ON COLUMN crawl_pages.status IS 'Page status: discovered, fetching, unchanged, changed, ingested, failed, blocked, removed';
COMMENT ON COLUMN crawl_pages.error_category IS 'Failure taxonomy: auth, rate_limit, gating, unavailable, network, parser_fail, ssrf_blocked, content_type_blocked, size_exceeded, timeout, too_many_redirects, private_ip_blocked';
COMMENT ON COLUMN crawl_pages.content_hash IS 'SHA-256 hash of normalized content for diff detection';
COMMENT ON COLUMN crawl_pages.normalized_artifact_path IS 'Path to normalized content in artifact store (not DB)';

-- ============================================================================
-- End of Migration
-- ============================================================================
