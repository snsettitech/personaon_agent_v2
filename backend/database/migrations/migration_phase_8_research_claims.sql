-- ============================================================================
-- Deep Research: Phase 8 - Research Claims Enrichment
-- ============================================================================
-- Adds claims extraction and verification for completed research runs.
-- All changes are additive (nullable columns) to maintain backward compatibility.
--
-- Created: 2026-02-24
-- Phase: 8
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Claim Verification Status Enum (as text for compatibility)
-- ----------------------------------------------------------------------------
-- pending: Initial state after extraction
-- supported: Verified against ingested sources
-- insufficient_evidence: No supporting evidence found
-- conflicting: Evidence contradicts the claim
-- needs_review: Requires manual human review

-- ----------------------------------------------------------------------------
-- Research Claims Table
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research_claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    research_run_id UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    -- Claim content
    claim_text TEXT NOT NULL,
    claim_type TEXT NOT NULL CHECK (claim_type IN (
        'preference', 'belief', 'heuristic', 'value', 
        'experience', 'boundary', 'uncertain'
    )),
    
    -- Verification status (Phase 8 MVP)
    verification_status TEXT NOT NULL DEFAULT 'pending' CHECK (verification_status IN (
        'pending', 'supported', 'insufficient_evidence', 'conflicting', 'needs_review'
    )),
    
    -- Confidence and authority
    confidence FLOAT NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    authority TEXT NOT NULL DEFAULT 'extracted' CHECK (authority IN (
        'extracted', 'owner_direct', 'inferred', 'uncertain'
    )),
    
    -- Source citation
    source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
    source_url TEXT,
    source_title TEXT,
    
    -- Evidence (JSONB for flexibility in MVP)
    evidence_quotes JSONB DEFAULT '[]'::jsonb,
    -- Schema: [{"quote": "text", "source_id": "uuid", "relevance": 0.9}]
    
    -- Extraction metadata
    extraction_version TEXT NOT NULL DEFAULT '1.0.0',
    extractor_model TEXT,
    
    -- Manual review metadata
    reviewed_at TIMESTAMPTZ,
    reviewed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    review_notes TEXT,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Soft delete for audit trail
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- Indexes for research_claims
CREATE INDEX IF NOT EXISTS idx_research_claims_run_id 
ON research_claims(research_run_id) 
WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_research_claims_twin_id 
ON research_claims(twin_id) 
WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_research_claims_verification_status 
ON research_claims(research_run_id, verification_status) 
WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_research_claims_type 
ON research_claims(research_run_id, claim_type) 
WHERE is_active = TRUE;

-- Composite index for common query patterns
CREATE INDEX IF NOT EXISTS idx_research_claims_run_status_type 
ON research_claims(research_run_id, verification_status, claim_type) 
WHERE is_active = TRUE;

-- ----------------------------------------------------------------------------
-- Research Claim Enrichment Summary Table
-- Tracks enrichment progress and stats per research run
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research_claim_enrichment (
    research_run_id UUID PRIMARY KEY REFERENCES research_runs(id) ON DELETE CASCADE,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    -- Enrichment status
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'enriching', 'completed', 'failed'
    )),
    
    -- Claim counts by status
    total_claims INTEGER NOT NULL DEFAULT 0,
    supported_count INTEGER NOT NULL DEFAULT 0,
    insufficient_count INTEGER NOT NULL DEFAULT 0,
    conflicting_count INTEGER NOT NULL DEFAULT 0,
    needs_review_count INTEGER NOT NULL DEFAULT 0,
    pending_count INTEGER NOT NULL DEFAULT 0,
    
    -- Error tracking
    error_message TEXT,
    
    -- Timing
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for querying enrichment status
CREATE INDEX IF NOT EXISTS idx_claim_enrichment_status 
ON research_claim_enrichment(status) 
WHERE status IN ('pending', 'enriching');

CREATE INDEX IF NOT EXISTS idx_claim_enrichment_twin 
ON research_claim_enrichment(twin_id, created_at DESC);

-- ----------------------------------------------------------------------------
-- Trigger to update updated_at timestamp
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION update_research_claims_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_research_claims_updated_at ON research_claims;
CREATE TRIGGER trigger_research_claims_updated_at
    BEFORE UPDATE ON research_claims
    FOR EACH ROW
    EXECUTE FUNCTION update_research_claims_updated_at();

CREATE OR REPLACE FUNCTION update_claim_enrichment_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_claim_enrichment_updated_at ON research_claim_enrichment;
CREATE TRIGGER trigger_claim_enrichment_updated_at
    BEFORE UPDATE ON research_claim_enrichment
    FOR EACH ROW
    EXECUTE FUNCTION update_claim_enrichment_updated_at();

-- ----------------------------------------------------------------------------
-- Comments for documentation
-- ----------------------------------------------------------------------------
COMMENT ON TABLE research_claims IS 
'Atomic claims extracted from confirmed sources in a research run. Phase 8 enrichment.';

COMMENT ON COLUMN research_claims.verification_status IS 
'pending: Initial state. supported: Verified against sources. insufficient_evidence: No support. conflicting: Contradicted. needs_review: Manual review required.';

COMMENT ON COLUMN research_claims.evidence_quotes IS 
'JSONB array of supporting/contradicting evidence quotes from sources: [{"quote": "...", "source_id": "...", "relevance": 0.9}]';

COMMENT ON TABLE research_claim_enrichment IS 
'Summary and progress tracking for claim enrichment per research run. Phase 8.';

-- ----------------------------------------------------------------------------
-- Add Phase 8 checkpoint data support to research_runs
-- ----------------------------------------------------------------------------
-- Note: checkpoint_data is JSONB, so we can add claims data there
-- This migration doesn't modify the column, just documents the contract

COMMENT ON COLUMN research_runs.checkpoint_data IS 
'Extended Phase 8: Now includes claims enrichment data: {..., claims_enrichment: {status, total_claims, supported_count, ...}}';

-- ----------------------------------------------------------------------------
-- Migration complete
-- ----------------------------------------------------------------------------
