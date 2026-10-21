-- ============================================================================
-- Deep Research: Phase 10 - Claims Finalization + Consistency Review
-- ============================================================================
-- Adds final claim adjudication and cross-claim consistency checking.
-- Combines Phase 8 local verification + Phase 9 web verification.
-- All changes are additive (no mutation to Phase 8/9 data).
--
-- Created: 2026-02-24
-- Phase: 10
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Final Claim Decisions Table
-- Stores final adjudication combining Phase 8 + Phase 9 results
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research_claim_finalizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id UUID NOT NULL REFERENCES research_claims(id) ON DELETE CASCADE,
    research_run_id UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    -- Final decision (additive, separate from Phase 8/9)
    final_status VARCHAR(50) NOT NULL DEFAULT 'unresolved',
    final_confidence FLOAT NOT NULL DEFAULT 0.0,
    final_reason_codes JSONB DEFAULT '[]'::jsonb,
    
    -- Resolution metadata
    resolution_source VARCHAR(50) NOT NULL DEFAULT 'system_rule',
    finalized_by UUID REFERENCES users(id) ON DELETE SET NULL,
    finalized_at TIMESTAMPTZ,
    
    -- Inputs that determined the decision (for audit)
    local_verification_status VARCHAR(50),
    local_confidence FLOAT,
    web_verification_status VARCHAR(50),
    web_confidence FLOAT,
    
    -- Notes
    notes TEXT,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_final_status CHECK (
        final_status IN ('accepted', 'rejected', 'needs_review', 'unresolved', 'overridden')
    ),
    CONSTRAINT valid_final_confidence CHECK (
        final_confidence >= 0.0 AND final_confidence <= 1.0
    ),
    CONSTRAINT valid_resolution_source CHECK (
        resolution_source IN ('system_rule', 'manual_override', 'consistency_review')
    )
);

-- Unique constraint: one finalization per claim
CREATE UNIQUE INDEX IF NOT EXISTS idx_claim_finalizations_claim_unique 
ON research_claim_finalizations(claim_id);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_claim_finalizations_run 
ON research_claim_finalizations(research_run_id);

CREATE INDEX IF NOT EXISTS idx_claim_finalizations_twin 
ON research_claim_finalizations(twin_id);

CREATE INDEX IF NOT EXISTS idx_claim_finalizations_status 
ON research_claim_finalizations(final_status);

CREATE INDEX IF NOT EXISTS idx_claim_finalizations_run_status 
ON research_claim_finalizations(research_run_id, final_status);

-- ----------------------------------------------------------------------------
-- Consistency Issues Table
-- Tracks contradictions, duplicates, and conflicts across claims
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research_claim_consistency_issues (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    research_run_id UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    issue_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'medium',
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    
    -- Claim IDs involved (JSONB array for flexibility)
    claim_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    
    -- Issue description
    title TEXT NOT NULL,
    description TEXT,
    
    -- Detection metadata
    detection_rule VARCHAR(100),
    confidence FLOAT DEFAULT 0.0,
    
    -- Resolution
    resolved_by UUID REFERENCES users(id) ON DELETE SET NULL,
    resolved_at TIMESTAMPTZ,
    resolution_notes TEXT,
    resolution_action VARCHAR(50),
    
    -- Deduplication hash
    issue_hash VARCHAR(64),
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_issue_type CHECK (
        issue_type IN ('contradiction', 'duplicate', 'confidence_mismatch', 'status_conflict')
    ),
    CONSTRAINT valid_severity CHECK (severity IN ('low', 'medium', 'high')),
    CONSTRAINT valid_status CHECK (status IN ('open', 'resolved', 'dismissed')),
    CONSTRAINT valid_resolution_action CHECK (
        resolution_action IN (NULL, 'dismissed', 'claims_updated', 'manual_override')
    )
);

-- Indexes for consistency issues
CREATE INDEX IF NOT EXISTS idx_consistency_issues_run 
ON research_claim_consistency_issues(research_run_id);

CREATE INDEX IF NOT EXISTS idx_consistency_issues_twin 
ON research_claim_consistency_issues(twin_id);

CREATE INDEX IF NOT EXISTS idx_consistency_issues_status 
ON research_claim_consistency_issues(status);

CREATE INDEX IF NOT EXISTS idx_consistency_issues_type 
ON research_claim_consistency_issues(issue_type);

CREATE INDEX IF NOT EXISTS idx_consistency_issues_hash 
ON research_claim_consistency_issues(issue_hash);

-- ----------------------------------------------------------------------------
-- Finalization Run Tracking
-- Tracks finalization progress per research run
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research_claim_finalization_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    research_run_id UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    total_claims INTEGER NOT NULL DEFAULT 0,
    finalized_count INTEGER NOT NULL DEFAULT 0,
    issues_found INTEGER NOT NULL DEFAULT 0,
    
    error_message TEXT,
    
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_finalization_run_status CHECK (
        status IN ('pending', 'running', 'completed', 'failed', 'partial')
    )
);

-- Unique constraint: one finalization run per research run
CREATE UNIQUE INDEX IF NOT EXISTS idx_finalization_runs_research_unique 
ON research_claim_finalization_runs(research_run_id);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_finalization_runs_status 
ON research_claim_finalization_runs(status);

-- ----------------------------------------------------------------------------
-- Triggers for updated_at
-- ----------------------------------------------------------------------------

-- Trigger function
CREATE OR REPLACE FUNCTION update_phase10_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers
DROP TRIGGER IF EXISTS trigger_claim_finalizations_updated_at ON research_claim_finalizations;
CREATE TRIGGER trigger_claim_finalizations_updated_at
    BEFORE UPDATE ON research_claim_finalizations
    FOR EACH ROW
    EXECUTE FUNCTION update_phase10_updated_at();

DROP TRIGGER IF EXISTS trigger_consistency_issues_updated_at ON research_claim_consistency_issues;
CREATE TRIGGER trigger_consistency_issues_updated_at
    BEFORE UPDATE ON research_claim_consistency_issues
    FOR EACH ROW
    EXECUTE FUNCTION update_phase10_updated_at();

DROP TRIGGER IF EXISTS trigger_finalization_runs_updated_at ON research_claim_finalization_runs;
CREATE TRIGGER trigger_finalization_runs_updated_at
    BEFORE UPDATE ON research_claim_finalization_runs
    FOR EACH ROW
    EXECUTE FUNCTION update_phase10_updated_at();

-- ----------------------------------------------------------------------------
-- Comments
-- ----------------------------------------------------------------------------

COMMENT ON TABLE research_claim_finalizations IS 
'Phase 10: Final claim decisions combining Phase 8 local + Phase 9 web verification';

COMMENT ON COLUMN research_claim_finalizations.final_status IS 
'Final status: accepted, rejected, needs_review, unresolved, overridden';

COMMENT ON COLUMN research_claim_finalizations.resolution_source IS 
'How the decision was made: system_rule, manual_override, consistency_review';

COMMENT ON TABLE research_claim_consistency_issues IS 
'Phase 10: Cross-claim consistency issues (contradictions, duplicates, conflicts)';

COMMENT ON TABLE research_claim_finalization_runs IS 
'Phase 10: Tracks claim finalization progress per research run';

-- ----------------------------------------------------------------------------
-- Rollback Instructions (for reference)
-- ----------------------------------------------------------------------------
/*
To rollback this migration:

DROP TRIGGER IF EXISTS trigger_claim_finalizations_updated_at ON research_claim_finalizations;
DROP TRIGGER IF EXISTS trigger_consistency_issues_updated_at ON research_claim_consistency_issues;
DROP TRIGGER IF EXISTS trigger_finalization_runs_updated_at ON research_claim_finalization_runs;
DROP FUNCTION IF EXISTS update_phase10_updated_at();

DROP TABLE IF EXISTS research_claim_finalization_runs;
DROP TABLE IF EXISTS research_claim_consistency_issues;
DROP TABLE IF EXISTS research_claim_finalizations;

Note: This is additive only - Phase 8 and 9 data remains intact.
*/
