-- Phase 3 Migration: Claims, Contradictions, and Snapshots
-- Creates tables for claim extraction, contradiction review queue, and materialized snapshots

-- =============================================================================
-- Table: graph_contradiction_queue
-- Stores contradictions detected between claims for human review
-- =============================================================================

CREATE TABLE IF NOT EXISTS graph_contradiction_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    twin_id UUID NOT NULL,
    group_id TEXT NOT NULL,
    
    -- Contradiction identification
    contradiction_id TEXT NOT NULL,
    new_claim_id TEXT NOT NULL,
    new_claim_text TEXT NOT NULL,
    existing_claim_id TEXT NOT NULL,
    existing_claim_text TEXT NOT NULL,
    
    -- Evaluation results
    severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
    explanation TEXT NOT NULL,
    confidence FLOAT NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    
    -- Review workflow
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'reviewing', 'resolved', 'dismissed')),
    resolution TEXT CHECK (resolution IN ('new_claim_kept', 'existing_claim_kept', 'both_kept', 'merged')),
    reviewed_by UUID REFERENCES auth.users(id),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    review_notes TEXT,
    
    -- Metadata
    detected_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    correlation_id TEXT,
    
    -- Constraints
    UNIQUE(tenant_id, twin_id, contradiction_id),
    
    -- Indexes
    CONSTRAINT fk_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT fk_twin FOREIGN KEY (twin_id) REFERENCES twins(id) ON DELETE CASCADE
);

-- Indexes for contradiction queue
CREATE INDEX IF NOT EXISTS idx_contradiction_queue_tenant ON graph_contradiction_queue(tenant_id);
CREATE INDEX IF NOT EXISTS idx_contradiction_queue_twin ON graph_contradiction_queue(twin_id);
CREATE INDEX IF NOT EXISTS idx_contradiction_queue_status ON graph_contradiction_queue(status);
CREATE INDEX IF NOT EXISTS idx_contradiction_queue_severity ON graph_contradiction_queue(severity);
CREATE INDEX IF NOT EXISTS idx_contradiction_queue_group ON graph_contradiction_queue(group_id);
CREATE INDEX IF NOT EXISTS idx_contradiction_queue_detected ON graph_contradiction_queue(detected_at);

-- RLS for contradiction queue
ALTER TABLE graph_contradiction_queue ENABLE ROW LEVEL SECURITY;

CREATE POLICY "tenant_isolation_contradiction_queue" ON graph_contradiction_queue
    USING (tenant_id = auth.jwt()->>'tenant_id');

-- =============================================================================
-- Table: graph_context_snapshots
-- Materialized snapshots of graph context for fast chat reads
-- =============================================================================

CREATE TABLE IF NOT EXISTS graph_context_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    group_id TEXT NOT NULL,
    
    -- Snapshot data
    snapshot_data JSONB NOT NULL,
    episode_count INTEGER NOT NULL DEFAULT 0,
    claim_count INTEGER NOT NULL DEFAULT 0,
    
    -- Versioning and TTL
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- Metadata
    refreshed_by UUID REFERENCES auth.users(id),
    correlation_id TEXT,
    
    -- Constraints
    UNIQUE(twin_id, group_id),
    
    -- Foreign keys
    CONSTRAINT fk_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT fk_twin FOREIGN KEY (twin_id) REFERENCES twins(id) ON DELETE CASCADE
);

-- Indexes for snapshots
CREATE INDEX IF NOT EXISTS idx_snapshots_tenant ON graph_context_snapshots(tenant_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_twin ON graph_context_snapshots(twin_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_expires ON graph_context_snapshots(expires_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_group ON graph_context_snapshots(group_id);

-- RLS for snapshots
ALTER TABLE graph_context_snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY "tenant_isolation_snapshots" ON graph_context_snapshots
    USING (tenant_id = auth.jwt()->>'tenant_id');

-- =============================================================================
-- Table: graph_claims (for extracted claims metadata)
-- Tracks claims extracted from various sources
-- =============================================================================

CREATE TABLE IF NOT EXISTS graph_claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    twin_id UUID NOT NULL,
    group_id TEXT NOT NULL,
    
    -- Claim identification
    claim_id TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    claim_type TEXT NOT NULL CHECK (claim_type IN ('fact', 'opinion', 'preference', 'belief')),
    
    -- Confidence and verification
    confidence FLOAT NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    content_hash TEXT NOT NULL,
    
    -- Source tracking
    source_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    extracted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- Graph reference (populated when stored in Neo4j)
    graph_entity_id TEXT,
    graph_entity_type TEXT,
    
    -- Metadata
    correlation_id TEXT,
    
    -- Constraints
    UNIQUE(tenant_id, twin_id, claim_id),
    
    -- Foreign keys
    CONSTRAINT fk_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT fk_twin FOREIGN KEY (twin_id) REFERENCES twins(id) ON DELETE CASCADE
);

-- Indexes for claims
CREATE INDEX IF NOT EXISTS idx_claims_tenant ON graph_claims(tenant_id);
CREATE INDEX IF NOT EXISTS idx_claims_twin ON graph_claims(twin_id);
CREATE INDEX IF NOT EXISTS idx_claims_type ON graph_claims(claim_type);
CREATE INDEX IF NOT EXISTS idx_claims_source ON graph_claims(source_type, source_ref);
CREATE INDEX IF NOT EXISTS idx_claims_group ON graph_claims(group_id);

-- RLS for claims
ALTER TABLE graph_claims ENABLE ROW LEVEL SECURITY;

CREATE POLICY "tenant_isolation_claims" ON graph_claims
    USING (tenant_id = auth.jwt()->>'tenant_id');

-- =============================================================================
-- Comments for documentation
-- =============================================================================

COMMENT ON TABLE graph_contradiction_queue IS 
'Review queue for contradictions detected between claims. Human reviewers resolve these.';

COMMENT ON TABLE graph_context_snapshots IS 
'Materialized snapshots of graph context for fast chat reads. Refreshed by background worker.';

COMMENT ON TABLE graph_claims IS 
'Tracking table for claims extracted from text. References actual claims stored in Neo4j.';

-- =============================================================================
-- Done
-- =============================================================================
