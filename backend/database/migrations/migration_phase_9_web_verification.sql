-- Migration: Phase 9 Web Verification Enrichment
-- Adds web verification for Phase 8 claims (external verification against public web sources)
-- Phase 9 is additive - Phase 8 local verification remains unchanged

-- =============================================================================
-- Web Verification Status Table (per claim)
-- =============================================================================
CREATE TABLE IF NOT EXISTS research_claim_web_verifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id UUID NOT NULL REFERENCES research_claims(id) ON DELETE CASCADE,
    research_run_id UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    -- Web verification fields (separate from Phase 8 local verification)
    web_verification_status VARCHAR(50) DEFAULT 'pending',
    web_verification_confidence FLOAT DEFAULT 0.0,
    web_verification_notes TEXT,
    
    -- Evidence summary
    sources_searched INTEGER DEFAULT 0,
    sources_found INTEGER DEFAULT 0,
    supporting_evidence_count INTEGER DEFAULT 0,
    conflicting_evidence_count INTEGER DEFAULT 0,
    
    -- Search metadata
    search_query TEXT,
    search_provider VARCHAR(50),
    
    -- Timestamps
    web_verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_web_verification_status CHECK (
        web_verification_status IN (
            'pending', 'supported', 'conflicting', 'insufficient_evidence', 
            'needs_review', 'blocked', 'error', 'skipped'
        )
    ),
    CONSTRAINT valid_web_confidence CHECK (
        web_verification_confidence >= 0.0 AND web_verification_confidence <= 1.0
    )
);

-- Unique constraint: one web verification per claim
CREATE UNIQUE INDEX IF NOT EXISTS idx_web_verifications_claim_unique 
ON research_claim_web_verifications(claim_id);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_web_verifications_run 
ON research_claim_web_verifications(research_run_id);

CREATE INDEX IF NOT EXISTS idx_web_verifications_twin 
ON research_claim_web_verifications(twin_id);

CREATE INDEX IF NOT EXISTS idx_web_verifications_status 
ON research_claim_web_verifications(web_verification_status);

CREATE INDEX IF NOT EXISTS idx_web_verifications_run_status 
ON research_claim_web_verifications(research_run_id, web_verification_status);

-- =============================================================================
-- Web Evidence Items Table (supporting or conflicting evidence)
-- =============================================================================
CREATE TABLE IF NOT EXISTS research_claim_web_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    verification_id UUID NOT NULL REFERENCES research_claim_web_verifications(id) ON DELETE CASCADE,
    claim_id UUID NOT NULL REFERENCES research_claims(id) ON DELETE CASCADE,
    
    -- Evidence details
    source_url TEXT NOT NULL,
    source_title TEXT,
    source_snippet TEXT,
    extracted_quote TEXT,
    relevance_score FLOAT,
    evidence_type VARCHAR(20), -- 'supporting' | 'conflicting' | 'neutral'
    
    -- Quality metrics (from Firecrawl quality assessment)
    content_quality VARCHAR(20), -- 'full' | 'partial' | 'blocked'
    domain_tier INTEGER, -- 1, 2, 3 for source quality
    
    -- Deduplication hash
    url_hash VARCHAR(64),
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_evidence_type CHECK (
        evidence_type IN ('supporting', 'conflicting', 'neutral')
    ),
    CONSTRAINT valid_content_quality CHECK (
        content_quality IN ('full', 'partial', 'blocked', NULL)
    ),
    CONSTRAINT valid_domain_tier CHECK (
        domain_tier IN (1, 2, 3, NULL)
    )
);

-- Indexes for evidence queries
CREATE INDEX IF NOT EXISTS idx_web_evidence_verification 
ON research_claim_web_evidence(verification_id);

CREATE INDEX IF NOT EXISTS idx_web_evidence_claim 
ON research_claim_web_evidence(claim_id);

CREATE INDEX IF NOT EXISTS idx_web_evidence_type 
ON research_claim_web_evidence(evidence_type);

CREATE INDEX IF NOT EXISTS idx_web_evidence_url_hash 
ON research_claim_web_evidence(verification_id, url_hash);

-- =============================================================================
-- Web Verification Run Tracking (per research run)
-- =============================================================================
CREATE TABLE IF NOT EXISTS research_web_verification_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    research_run_id UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    status VARCHAR(50) DEFAULT 'pending',
    total_claims INTEGER DEFAULT 0,
    verified_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    
    error_message TEXT,
    
    -- Timestamps
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_web_verification_run_status CHECK (
        status IN ('pending', 'running', 'completed', 'failed', 'partial')
    )
);

-- Unique constraint: one verification run per research run
CREATE UNIQUE INDEX IF NOT EXISTS idx_web_verification_runs_research_unique 
ON research_web_verification_runs(research_run_id);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_web_verification_runs_twin 
ON research_web_verification_runs(twin_id);

CREATE INDEX IF NOT EXISTS idx_web_verification_runs_status 
ON research_web_verification_runs(status);

-- =============================================================================
-- Update Triggers
-- =============================================================================

-- Trigger function for updating updated_at
CREATE OR REPLACE FUNCTION update_web_verifications_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for web_verifications
DROP TRIGGER IF EXISTS trigger_web_verifications_updated_at ON research_claim_web_verifications;
CREATE TRIGGER trigger_web_verifications_updated_at
    BEFORE UPDATE ON research_claim_web_verifications
    FOR EACH ROW
    EXECUTE FUNCTION update_web_verifications_updated_at();

-- Trigger for web_evidence (no updated_at needed - immutable)

-- Trigger for web_verification_runs
DROP TRIGGER IF EXISTS trigger_web_verification_runs_updated_at ON research_web_verification_runs;
CREATE TRIGGER trigger_web_verification_runs_updated_at
    BEFORE UPDATE ON research_web_verification_runs
    FOR EACH ROW
    EXECUTE FUNCTION update_web_verifications_updated_at();

-- =============================================================================
-- Comments
-- =============================================================================

COMMENT ON TABLE research_claim_web_verifications IS 
'Phase 9: Web verification results for claims. Separate from Phase 8 local verification.';

COMMENT ON COLUMN research_claim_web_verifications.web_verification_status IS 
'Status: pending, supported, conflicting, insufficient_evidence, needs_review, blocked, error, skipped';

COMMENT ON COLUMN research_claim_web_verifications.web_verification_confidence IS 
'Confidence score 0.0-1.0 for web verification result';

COMMENT ON TABLE research_claim_web_evidence IS 
'Individual web evidence items (URLs, snippets, quotes) supporting or conflicting with claims';

COMMENT ON TABLE research_web_verification_runs IS 
'Tracks web verification progress per research run (Phase 9)';

-- =============================================================================
-- Rollback Instructions (for reference)
-- =============================================================================
/*
To rollback this migration:

DROP TRIGGER IF EXISTS trigger_web_verifications_updated_at ON research_claim_web_verifications;
DROP TRIGGER IF EXISTS trigger_web_verification_runs_updated_at ON research_web_verification_runs;
DROP FUNCTION IF EXISTS update_web_verifications_updated_at();

DROP TABLE IF EXISTS research_claim_web_evidence;
DROP TABLE IF EXISTS research_claim_web_verifications;
DROP TABLE IF EXISTS research_web_verification_runs;

Note: This is additive only - no data migration needed from Phase 8.
Phase 8 local verification continues to work independently.
*/
