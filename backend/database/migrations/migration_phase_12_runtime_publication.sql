-- ============================================================================
-- Deep Research: Phase 12 - Runtime Publication + Deployment Readiness
-- ============================================================================
-- Adds runtime publication layer for operational integration and deployment.
-- All changes are additive (no mutation to Phase 8/9/10/11 data).
--
-- Created: 2026-02-24
-- Phase: 12
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Runtime Publication Table
-- Denormalized view of claims ready for runtime consumption
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research_claim_runtime_publication (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id UUID NOT NULL REFERENCES research_claims(id) ON DELETE CASCADE,
    research_run_id UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    -- Publication state
    publishable BOOLEAN DEFAULT FALSE,
    published BOOLEAN DEFAULT FALSE,
    suppressed BOOLEAN DEFAULT FALSE,
    suppression_reason VARCHAR(50),
    
    -- Runtime fields (denormalized for query performance)
    runtime_claim_text TEXT NOT NULL,
    runtime_status VARCHAR(50) NOT NULL DEFAULT 'unpublished',
    runtime_confidence FLOAT DEFAULT 0.0,
    runtime_issue_flags JSONB DEFAULT '[]'::jsonb,
    runtime_citations JSONB DEFAULT '[]'::jsonb,
    
    -- Provenance (for debugging and audit)
    source_canonical_id UUID REFERENCES research_claim_canonical(id),
    source_finalization_id UUID REFERENCES research_claim_finalizations(id),
    
    -- Publication metadata
    published_at TIMESTAMPTZ,
    published_version INTEGER DEFAULT 1,
    
    -- Content hash for detecting changes
    content_hash VARCHAR(64),
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_runtime_status CHECK (
        runtime_status IN ('accepted', 'rejected', 'needs_review', 'unpublished')
    ),
    CONSTRAINT valid_suppression_reason CHECK (
        suppression_reason IN (
            'unresolved_status', 'rejected_claim', 'open_consistency_issue', 
            'low_confidence', 'manual_hold', 'rule_violation', NULL
        )
    ),
    CONSTRAINT valid_runtime_confidence CHECK (
        runtime_confidence >= 0.0 AND runtime_confidence <= 1.0
    )
);

-- Unique index: one publication record per claim
CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_publication_claim_unique 
ON research_claim_runtime_publication(claim_id);

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_runtime_publication_run 
ON research_claim_runtime_publication(research_run_id);

CREATE INDEX IF NOT EXISTS idx_runtime_publication_twin 
ON research_claim_runtime_publication(twin_id);

CREATE INDEX IF NOT EXISTS idx_runtime_publication_published 
ON research_claim_runtime_publication(published, published_at DESC) 
WHERE published = TRUE;

CREATE INDEX IF NOT EXISTS idx_runtime_publication_publishable 
ON research_claim_runtime_publication(publishable) 
WHERE publishable = TRUE AND published = FALSE;

CREATE INDEX IF NOT EXISTS idx_runtime_publication_suppressed 
ON research_claim_runtime_publication(suppressed, suppression_reason) 
WHERE suppressed = TRUE;

CREATE INDEX IF NOT EXISTS idx_runtime_publication_status 
ON research_claim_runtime_publication(runtime_status);

CREATE INDEX IF NOT EXISTS idx_runtime_publication_content_hash 
ON research_claim_runtime_publication(content_hash) 
WHERE content_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_runtime_publication_issue_flags 
ON research_claim_runtime_publication USING GIN(runtime_issue_flags);

-- ----------------------------------------------------------------------------
-- Publication Run Tracking
-- Tracks publication progress and backfill operations
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research_claim_publication_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    research_run_id UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    status VARCHAR(50) DEFAULT 'pending',
    total_claims INTEGER DEFAULT 0,
    published_count INTEGER DEFAULT 0,
    suppressed_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    
    -- Backfill mode support
    backfill_mode BOOLEAN DEFAULT FALSE,
    backfill_batch INTEGER,
    backfill_resume_token TEXT,
    
    -- Error tracking
    error_message TEXT,
    
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT valid_publication_run_status CHECK (
        status IN ('pending', 'running', 'completed', 'failed', 'partial', 'cancelled')
    )
);

-- Unique constraint: one publication run per research run
CREATE UNIQUE INDEX IF NOT EXISTS idx_publication_runs_research_unique 
ON research_claim_publication_runs(research_run_id);

CREATE INDEX IF NOT EXISTS idx_publication_runs_status 
ON research_claim_publication_runs(status);

CREATE INDEX IF NOT EXISTS idx_publication_runs_backfill 
ON research_claim_publication_runs(backfill_mode) 
WHERE backfill_mode = TRUE;

-- ----------------------------------------------------------------------------
-- Publication Configuration (Per-Twin Settings)
-- Allows customization of publication rules per twin
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research_claim_publication_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    
    -- Publication rules
    suppress_unresolved_default BOOLEAN DEFAULT TRUE,
    suppress_rejected_default BOOLEAN DEFAULT TRUE,
    min_confidence_threshold FLOAT DEFAULT 0.0,
    suppress_open_high_severity BOOLEAN DEFAULT TRUE,
    suppress_open_medium_severity BOOLEAN DEFAULT FALSE,
    
    -- Feature toggles
    auto_publish BOOLEAN DEFAULT FALSE,
    require_human_review BOOLEAN DEFAULT TRUE,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT valid_confidence_threshold CHECK (
        min_confidence_threshold >= 0.0 AND min_confidence_threshold <= 1.0
    )
);

-- Unique index: one config per twin
CREATE UNIQUE INDEX IF NOT EXISTS idx_publication_config_twin_unique 
ON research_claim_publication_config(twin_id);

-- ----------------------------------------------------------------------------
-- Runtime Publication Audit Trail
-- Records publication actions for observability
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research_claim_publication_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    publication_id UUID REFERENCES research_claim_runtime_publication(id) ON DELETE SET NULL,
    claim_id UUID REFERENCES research_claims(id) ON DELETE SET NULL,
    research_run_id UUID REFERENCES research_runs(id) ON DELETE SET NULL,
    twin_id UUID REFERENCES twins(id) ON DELETE SET NULL,
    
    action VARCHAR(50) NOT NULL,
    previous_state JSONB,
    new_state JSONB,
    
    actor_id UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_type VARCHAR(20) DEFAULT 'system',
    
    reason VARCHAR(200),
    correlation_id VARCHAR(64),
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT valid_publication_action CHECK (
        action IN ('published', 'suppressed', 'updated', 'unpublished', 'republished', 'batch_publish', 'backfill')
    )
);

-- Indexes for audit trail
CREATE INDEX IF NOT EXISTS idx_publication_audit_claim 
ON research_claim_publication_audit(claim_id);

CREATE INDEX IF NOT EXISTS idx_publication_audit_run 
ON research_claim_publication_audit(research_run_id);

CREATE INDEX IF NOT EXISTS idx_publication_audit_correlation 
ON research_claim_publication_audit(correlation_id) 
WHERE correlation_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_publication_audit_created 
ON research_claim_publication_audit(created_at DESC);

-- ----------------------------------------------------------------------------
-- Triggers for updated_at
-- ----------------------------------------------------------------------------

-- Trigger function (reuses phase 11 if exists, otherwise create)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_phase12_updated_at') THEN
        CREATE FUNCTION update_phase12_updated_at()
        RETURNS TRIGGER AS $func$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $func$ LANGUAGE plpgsql;
    END IF;
END $$;

-- Triggers
DROP TRIGGER IF EXISTS trigger_runtime_publication_updated_at ON research_claim_runtime_publication;
CREATE TRIGGER trigger_runtime_publication_updated_at
    BEFORE UPDATE ON research_claim_runtime_publication
    FOR EACH ROW
    EXECUTE FUNCTION update_phase12_updated_at();

DROP TRIGGER IF EXISTS trigger_publication_runs_updated_at ON research_claim_publication_runs;
CREATE TRIGGER trigger_publication_runs_updated_at
    BEFORE UPDATE ON research_claim_publication_runs
    FOR EACH ROW
    EXECUTE FUNCTION update_phase12_updated_at();

DROP TRIGGER IF EXISTS trigger_publication_config_updated_at ON research_claim_publication_config;
CREATE TRIGGER trigger_publication_config_updated_at
    BEFORE UPDATE ON research_claim_publication_config
    FOR EACH ROW
    EXECUTE FUNCTION update_phase12_updated_at();

-- ----------------------------------------------------------------------------
-- Views for Common Queries
-- ----------------------------------------------------------------------------

-- View: Published claims ready for runtime consumption
CREATE OR REPLACE VIEW v_runtime_claims_published AS
SELECT 
    rp.*,
    c.claim_text as original_claim_text,
    c.claim_type,
    to_jsonb(c)->>'source_chunk_id' as source_chunk_id,
    cc.canonical_status,
    cc.source_of_truth
FROM research_claim_runtime_publication rp
JOIN research_claims c ON rp.claim_id = c.id
LEFT JOIN research_claim_canonical cc ON rp.claim_id = cc.claim_id 
    AND cc.superseded_at IS NULL
WHERE rp.published = TRUE
ORDER BY rp.published_at DESC;

-- View: Claims needing review (not yet publishable)
CREATE OR REPLACE VIEW v_runtime_claims_needing_review AS
SELECT 
    rp.*,
    c.claim_text as original_claim_text,
    cc.locked,
    cc.locked_by,
    cc.locked_at
FROM research_claim_runtime_publication rp
JOIN research_claims c ON rp.claim_id = c.id
LEFT JOIN research_claim_canonical cc ON rp.claim_id = cc.claim_id 
    AND cc.superseded_at IS NULL
WHERE rp.publishable = FALSE 
   OR rp.runtime_status IN ('needs_review', 'unpublished');

-- View: Suppression summary for observability
CREATE OR REPLACE VIEW v_runtime_suppression_summary AS
SELECT 
    twin_id,
    suppression_reason,
    COUNT(*) as count,
    MIN(created_at) as oldest,
    MAX(created_at) as newest
FROM research_claim_runtime_publication
WHERE suppressed = TRUE
GROUP BY twin_id, suppression_reason;

-- ----------------------------------------------------------------------------
-- Comments
-- ----------------------------------------------------------------------------

COMMENT ON TABLE research_claim_runtime_publication IS 
'Phase 12: Runtime publication layer - denormalized claims ready for operational consumption. One row per claim.';

COMMENT ON COLUMN research_claim_runtime_publication.runtime_issue_flags IS 
'JSON array of issue flags: has_open_issues, high_severity_conflict, confidence_below_threshold, etc.';

COMMENT ON COLUMN research_claim_runtime_publication.content_hash IS 
'Hash of claim content for detecting changes and managing updates';

COMMENT ON TABLE research_claim_publication_runs IS 
'Phase 12: Tracks publication runs including backfill operations';

COMMENT ON TABLE research_claim_publication_config IS 
'Phase 12: Per-twin configuration for publication rules and behaviors';

COMMENT ON TABLE research_claim_publication_audit IS 
'Phase 12: Audit trail for all publication actions';

-- ----------------------------------------------------------------------------
-- Rollback Instructions (for reference)
-- ----------------------------------------------------------------------------
/*
To rollback this migration:

DROP VIEW IF EXISTS v_runtime_claims_published;
DROP VIEW IF EXISTS v_runtime_claims_needing_review;
DROP VIEW IF EXISTS v_runtime_suppression_summary;

DROP TRIGGER IF EXISTS trigger_runtime_publication_updated_at ON research_claim_runtime_publication;
DROP TRIGGER IF EXISTS trigger_publication_runs_updated_at ON research_claim_publication_runs;
DROP TRIGGER IF EXISTS trigger_publication_config_updated_at ON research_claim_publication_config;
DROP FUNCTION IF EXISTS update_phase12_updated_at();

DROP TABLE IF EXISTS research_claim_publication_audit;
DROP TABLE IF EXISTS research_claim_publication_config;
DROP TABLE IF EXISTS research_claim_publication_runs;
DROP TABLE IF EXISTS research_claim_runtime_publication;

Note: This is additive only - Phase 8/9/10/11 data remains intact.
*/
