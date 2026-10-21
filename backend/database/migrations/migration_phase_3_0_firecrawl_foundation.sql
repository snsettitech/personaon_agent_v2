-- ============================================================================
-- Deep Research: Phase 3.0 - Firecrawl Integration Foundation
-- ============================================================================
-- Creates tables for Deep Research orchestration and source confirmation.
-- All changes are additive (nullable columns) to maintain backward compatibility.
--
-- Created: 2026-02-23
-- Phase: 3.0
-- ============================================================================

-- ----------------------------------------------------------------------------
-- research_runs: Tracks Deep Research runs with checkpoint/resume support
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    -- Run configuration
    input_question TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    
    -- Progress tracking
    current_phase VARCHAR(50),
    subquestions_total INT DEFAULT 0,
    subquestions_completed INT DEFAULT 0,
    sources_confirmed INT DEFAULT 0,
    sources_rejected INT DEFAULT 0,
    
    -- Checkpoint for resume capability
    checkpoint_data JSONB DEFAULT '{}',
    
    -- Artifact references (not content)
    manifest_artifact_path TEXT,
    
    -- Timing
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for research_runs
CREATE INDEX IF NOT EXISTS idx_research_runs_twin_id ON research_runs(twin_id);
CREATE INDEX IF NOT EXISTS idx_research_runs_status ON research_runs(status);
CREATE INDEX IF NOT EXISTS idx_research_runs_twin_status ON research_runs(twin_id, status);

-- ----------------------------------------------------------------------------
-- research_subquestions: Individual subquestions within a research run
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research_subquestions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    research_run_id UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    
    -- Question details
    question_text TEXT NOT NULL,
    priority INT DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    
    -- Classification
    claim_class VARCHAR(50),
    web_verify_eligible BOOLEAN DEFAULT false,
    
    -- Progress
    sources_found INT DEFAULT 0,
    sources_processed INT DEFAULT 0,
    
    -- Timing
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for research_subquestions
CREATE INDEX IF NOT EXISTS idx_research_subquestions_run_id ON research_subquestions(research_run_id);
CREATE INDEX IF NOT EXISTS idx_research_subquestions_status ON research_subquestions(status);

-- ----------------------------------------------------------------------------
-- source_confirmations: Manual user confirmations for identity-aligned sources
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source_confirmations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    crawl_page_id UUID NOT NULL REFERENCES crawl_pages(id) ON DELETE CASCADE,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    -- Confirmation status
    confirmation_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    confirmed_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    confirmed_at TIMESTAMPTZ,
    
    -- Identity alignment scores (0-100 scale)
    identity_confidence_score INT,
    
    -- Rejection reason if not confirmed
    rejection_reason TEXT,
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for source_confirmations
CREATE INDEX IF NOT EXISTS idx_source_confirmations_page_id ON source_confirmations(crawl_page_id);
CREATE INDEX IF NOT EXISTS idx_source_confirmations_twin_id ON source_confirmations(twin_id);
CREATE INDEX IF NOT EXISTS idx_source_confirmations_status ON source_confirmations(confirmation_status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_source_confirmations_unique 
    ON source_confirmations(crawl_page_id, twin_id);

-- ----------------------------------------------------------------------------
-- Additive columns to existing crawl_pages table (Phase 3.0)
-- ----------------------------------------------------------------------------
-- Note: All columns are nullable to maintain backward compatibility

-- Identity confidence score for source confirmation (0-100)
ALTER TABLE crawl_pages 
ADD COLUMN IF NOT EXISTS identity_confidence_score INT;

-- Confirmation status for source confirmation workflow
ALTER TABLE crawl_pages 
ADD COLUMN IF NOT EXISTS confirmation_status VARCHAR(20);

-- Submitted root URL for lineage tracking (maps crawled page to original submission)
ALTER TABLE crawl_pages 
ADD COLUMN IF NOT EXISTS submitted_root_url TEXT;

-- ----------------------------------------------------------------------------
-- Additive columns to existing crawl_runs table (Phase 3.0)
-- ----------------------------------------------------------------------------

-- Onboarding session association for deep research onboarding integration
ALTER TABLE crawl_runs 
ADD COLUMN IF NOT EXISTS onboarding_session_id UUID;

-- ----------------------------------------------------------------------------
-- Comments documenting column purposes
-- ----------------------------------------------------------------------------
COMMENT ON COLUMN crawl_pages.identity_confidence_score IS 
    'Identity alignment score (0-100) computed by IdentityConfidenceScorer (Phase 3.3)';
COMMENT ON COLUMN crawl_pages.confirmation_status IS 
    'Source confirmation status: pending|confirmed|rejected (Phase 3.2)';
COMMENT ON COLUMN crawl_pages.submitted_root_url IS 
    'Original submitted URL for source-to-submission lineage tracking (Phase 3.2)';
COMMENT ON COLUMN crawl_runs.onboarding_session_id IS 
    'Association with onboarding session for unified source management (Phase 3.2)';

-- ----------------------------------------------------------------------------
-- RLS policies for new tables (follow existing pattern)
-- ----------------------------------------------------------------------------
-- Note: These policies assume the RLS is enabled on twins table
-- and follow the same tenant isolation pattern

-- Enable RLS on new tables
ALTER TABLE research_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE research_subquestions ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_confirmations ENABLE ROW LEVEL SECURITY;

-- Policy: Tenant isolation via twins.tenant_id (matches existing project pattern)
CREATE POLICY research_runs_tenant_isolation ON research_runs
    FOR ALL
    USING (
        twin_id IN (
            SELECT id FROM twins
            WHERE tenant_id = ((auth.jwt() ->> 'tenant_id')::uuid)
        )
    );

-- Policy: Users can only see subquestions for their research runs
CREATE POLICY research_subquestions_tenant_isolation ON research_subquestions
    FOR ALL
    USING (
        research_run_id IN (
            SELECT rr.id FROM research_runs rr
            JOIN twins t ON rr.twin_id = t.id
            WHERE t.tenant_id = ((auth.jwt() ->> 'tenant_id')::uuid)
        )
    );

-- Policy: Tenant isolation via twins.tenant_id (matches existing project pattern)
CREATE POLICY source_confirmations_tenant_isolation ON source_confirmations
    FOR ALL
    USING (
        twin_id IN (
            SELECT id FROM twins
            WHERE tenant_id = ((auth.jwt() ->> 'tenant_id')::uuid)
        )
    );

-- ----------------------------------------------------------------------------
-- Trigger function for updated_at timestamps
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply triggers to new tables
DROP TRIGGER IF EXISTS update_research_runs_updated_at ON research_runs;
CREATE TRIGGER update_research_runs_updated_at
    BEFORE UPDATE ON research_runs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_research_subquestions_updated_at ON research_subquestions;
CREATE TRIGGER update_research_subquestions_updated_at
    BEFORE UPDATE ON research_subquestions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_source_confirmations_updated_at ON source_confirmations;
CREATE TRIGGER update_source_confirmations_updated_at
    BEFORE UPDATE ON source_confirmations
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
