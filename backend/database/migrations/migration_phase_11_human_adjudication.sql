-- ============================================================================
-- Deep Research: Phase 11 - Human Adjudication + Canonical Claim Review
-- ============================================================================
-- Adds human review workflow and canonical claim store for owner/admin review.
-- All changes are additive (no mutation to Phase 8/9/10 data).
--
-- Created: 2026-02-24
-- Phase: 11
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Claim Adjudications Table (Audit Trail)
-- Records every human action on claims
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research_claim_adjudications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id UUID NOT NULL REFERENCES research_claims(id) ON DELETE CASCADE,
    research_run_id UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    -- Action details
    action VARCHAR(50) NOT NULL,
    previous_status VARCHAR(50),
    new_status VARCHAR(50),
    
    -- Actor information
    actor_id UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_type VARCHAR(20) DEFAULT 'user',
    
    -- Reason and notes
    reason_code VARCHAR(50),
    notes TEXT,
    
    -- Idempotency support
    idempotency_key VARCHAR(64),
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_adjudication_action CHECK (
        action IN ('approve', 'reject', 'mark_needs_review', 'mark_unresolved', 
                   'lock', 'unlock', 'override_status', 'override_canonical')
    ),
    CONSTRAINT valid_actor_type CHECK (actor_type IN ('user', 'system', 'admin'))
);

-- Indexes for adjudications
CREATE INDEX IF NOT EXISTS idx_claim_adjudications_claim 
ON research_claim_adjudications(claim_id);

CREATE INDEX IF NOT EXISTS idx_claim_adjudications_run 
ON research_claim_adjudications(research_run_id);

CREATE INDEX IF NOT EXISTS idx_claim_adjudications_twin 
ON research_claim_adjudications(twin_id);

CREATE INDEX IF NOT EXISTS idx_claim_adjudications_actor 
ON research_claim_adjudications(actor_id);

CREATE INDEX IF NOT EXISTS idx_claim_adjudications_idempotency 
ON research_claim_adjudications(idempotency_key) 
WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_claim_adjudications_created 
ON research_claim_adjudications(created_at DESC);

-- ----------------------------------------------------------------------------
-- Canonical Claims Table (Current Truth Store)
-- Represents the reviewed, canonical state of each claim
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research_claim_canonical (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id UUID NOT NULL REFERENCES research_claims(id) ON DELETE CASCADE,
    research_run_id UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    -- Canonical state (the current reviewed truth)
    canonical_status VARCHAR(50) NOT NULL DEFAULT 'unresolved',
    canonical_text TEXT,  -- Optional normalized text
    
    -- Provenance tracking
    source_of_truth VARCHAR(50) NOT NULL DEFAULT 'system_rule',
    
    -- Locking mechanism
    locked BOOLEAN DEFAULT FALSE,
    locked_by UUID REFERENCES users(id) ON DELETE SET NULL,
    locked_at TIMESTAMPTZ,
    lock_reason TEXT,
    
    -- Confidence in this canonical version
    adjudication_confidence FLOAT DEFAULT 0.0,
    
    -- Simple versioning
    version INTEGER DEFAULT 1,
    superseded_by UUID REFERENCES research_claim_canonical(id),
    effective_at TIMESTAMPTZ DEFAULT NOW(),
    superseded_at TIMESTAMPTZ,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_canonical_status CHECK (
        canonical_status IN ('accepted', 'rejected', 'needs_review', 'unresolved', 'superseded')
    ),
    CONSTRAINT valid_source_of_truth CHECK (
        source_of_truth IN ('system_rule', 'human_review', 'override', 'consensus')
    ),
    CONSTRAINT valid_adjudication_confidence CHECK (
        adjudication_confidence >= 0.0 AND adjudication_confidence <= 1.0
    )
);

-- Unique index: only one current (non-superseded) canonical per claim
CREATE UNIQUE INDEX IF NOT EXISTS idx_claim_canonical_current_unique 
ON research_claim_canonical(claim_id) 
WHERE superseded_at IS NULL;

-- Additional indexes
CREATE INDEX IF NOT EXISTS idx_claim_canonical_run 
ON research_claim_canonical(research_run_id);

CREATE INDEX IF NOT EXISTS idx_claim_canonical_twin 
ON research_claim_canonical(twin_id);

CREATE INDEX IF NOT EXISTS idx_claim_canonical_status 
ON research_claim_canonical(canonical_status);

CREATE INDEX IF NOT EXISTS idx_claim_canonical_locked 
ON research_claim_canonical(locked) 
WHERE locked = TRUE;

CREATE INDEX IF NOT EXISTS idx_claim_canonical_source 
ON research_claim_canonical(source_of_truth);

CREATE INDEX IF NOT EXISTS idx_claim_canonical_superseded 
ON research_claim_canonical(superseded_by) 
WHERE superseded_by IS NOT NULL;

-- ----------------------------------------------------------------------------
-- Consistency Issue Actions Table (Audit Trail)
-- Records actions taken on consistency issues
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research_claim_issue_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    issue_id UUID NOT NULL REFERENCES research_claim_consistency_issues(id) ON DELETE CASCADE,
    research_run_id UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    action VARCHAR(50) NOT NULL,
    previous_status VARCHAR(20),
    new_status VARCHAR(20),
    
    actor_id UUID REFERENCES users(id) ON DELETE SET NULL,
    reason_code VARCHAR(50),
    notes TEXT,
    
    idempotency_key VARCHAR(64),
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT valid_issue_action CHECK (
        action IN ('confirm_conflict', 'dismiss', 'merge_duplicate', 'split_context', 'defer')
    )
);

-- Indexes for issue actions
CREATE INDEX IF NOT EXISTS idx_issue_actions_issue 
ON research_claim_issue_actions(issue_id);

CREATE INDEX IF NOT EXISTS idx_issue_actions_run 
ON research_claim_issue_actions(research_run_id);

CREATE INDEX IF NOT EXISTS idx_issue_actions_actor 
ON research_claim_issue_actions(actor_id);

CREATE INDEX IF NOT EXISTS idx_issue_actions_idempotency 
ON research_claim_issue_actions(idempotency_key) 
WHERE idempotency_key IS NOT NULL;

-- ----------------------------------------------------------------------------
-- Adjudication Run Tracking
-- Tracks adjudication progress per research run
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research_claim_adjudication_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    research_run_id UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    status VARCHAR(50) DEFAULT 'pending',
    total_claims INTEGER DEFAULT 0,
    adjudicated_count INTEGER DEFAULT 0,
    locked_count INTEGER DEFAULT 0,
    
    error_message TEXT,
    
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT valid_adjudication_run_status CHECK (
        status IN ('pending', 'running', 'completed', 'failed', 'partial')
    )
);

-- Unique constraint: one adjudication run per research run
CREATE UNIQUE INDEX IF NOT EXISTS idx_adjudication_runs_research_unique 
ON research_claim_adjudication_runs(research_run_id);

CREATE INDEX IF NOT EXISTS idx_adjudication_runs_status 
ON research_claim_adjudication_runs(status);

-- ----------------------------------------------------------------------------
-- Triggers for updated_at
-- ----------------------------------------------------------------------------

-- Trigger function
CREATE OR REPLACE FUNCTION update_phase11_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers
DROP TRIGGER IF EXISTS trigger_claim_canonical_updated_at ON research_claim_canonical;
CREATE TRIGGER trigger_claim_canonical_updated_at
    BEFORE UPDATE ON research_claim_canonical
    FOR EACH ROW
    EXECUTE FUNCTION update_phase11_updated_at();

DROP TRIGGER IF EXISTS trigger_adjudication_runs_updated_at ON research_claim_adjudication_runs;
CREATE TRIGGER trigger_adjudication_runs_updated_at
    BEFORE UPDATE ON research_claim_adjudication_runs
    FOR EACH ROW
    EXECUTE FUNCTION update_phase11_updated_at();

-- ----------------------------------------------------------------------------
-- Comments
-- ----------------------------------------------------------------------------

COMMENT ON TABLE research_claim_adjudications IS 
'Phase 11: Audit trail of all human adjudication actions on claims';

COMMENT ON TABLE research_claim_canonical IS 
'Phase 11: Canonical claim store - the current reviewed truth for each claim. Supports versioning via superseded_by.';

COMMENT ON COLUMN research_claim_canonical.canonical_status IS 
'The reviewed status: accepted, rejected, needs_review, unresolved, superseded';

COMMENT ON COLUMN research_claim_canonical.source_of_truth IS 
'How this canonical state was determined: system_rule, human_review, override, consensus';

COMMENT ON TABLE research_claim_issue_actions IS 
'Phase 11: Audit trail of actions taken on consistency issues';

COMMENT ON TABLE research_claim_adjudication_runs IS 
'Phase 11: Tracks human adjudication progress per research run';

-- ----------------------------------------------------------------------------
-- Rollback Instructions (for reference)
-- ----------------------------------------------------------------------------
/*
To rollback this migration:

DROP TRIGGER IF EXISTS trigger_claim_canonical_updated_at ON research_claim_canonical;
DROP TRIGGER IF EXISTS trigger_adjudication_runs_updated_at ON research_claim_adjudication_runs;
DROP FUNCTION IF EXISTS update_phase11_updated_at();

DROP TABLE IF EXISTS research_claim_adjudication_runs;
DROP TABLE IF EXISTS research_claim_issue_actions;
DROP TABLE IF EXISTS research_claim_canonical;
DROP TABLE IF EXISTS research_claim_adjudications;

Note: This is additive only - Phase 8/9/10 data remains intact.
*/
