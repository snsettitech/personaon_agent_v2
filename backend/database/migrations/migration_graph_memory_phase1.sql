-- Phase 1: Graph Memory Infrastructure
-- Outbox pattern and durable extraction cache

-- 1. Graph Outbox Table
-- Reliable job queue for graph writes with idempotency
CREATE TABLE IF NOT EXISTS graph_outbox (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL,
    twin_id UUID NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN (
        'create_episode',
        'create_claims',
        'update_claim_status',
        'create_relationship',
        'delete_twin_graph',
        'extract_claims',
        'evaluate_contradictions',
        'refresh_snapshot'
    )),
    idempotency_key TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    priority INTEGER DEFAULT 0,
    attempt_count INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 5,
    correlation_id TEXT,
    error_message TEXT,
    next_attempt_after TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    
    -- Unique constraint for idempotency
    UNIQUE (tenant_id, twin_id, idempotency_key)
);

-- Indexes for outbox queries
CREATE INDEX IF NOT EXISTS idx_graph_outbox_status ON graph_outbox(status);
CREATE INDEX IF NOT EXISTS idx_graph_outbox_tenant_twin ON graph_outbox(tenant_id, twin_id);
CREATE INDEX IF NOT EXISTS idx_graph_outbox_pending ON graph_outbox(status, priority, created_at) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_graph_outbox_idempotency ON graph_outbox(tenant_id, twin_id, idempotency_key);

-- 2. Graph Extraction Cache Table
-- Durable cache for claim extraction results
CREATE TABLE IF NOT EXISTS graph_extraction_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL,
    twin_id UUID NOT NULL,
    source_ref TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    extractor_version TEXT NOT NULL DEFAULT '1',
    claims JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Unique constraint for cache key
    UNIQUE (tenant_id, twin_id, source_ref, content_hash, extractor_version)
);

-- Indexes for cache lookups
CREATE INDEX IF NOT EXISTS idx_graph_extraction_cache_lookup ON graph_extraction_cache(tenant_id, twin_id, source_ref, content_hash, extractor_version);
CREATE INDEX IF NOT EXISTS idx_graph_extraction_cache_updated ON graph_extraction_cache(updated_at);

-- 3. RLS Policies
ALTER TABLE graph_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE graph_extraction_cache ENABLE ROW LEVEL SECURITY;

-- Outbox policies
DROP POLICY IF EXISTS "Tenant Isolation: View Graph Outbox" ON graph_outbox;
CREATE POLICY "Tenant Isolation: View Graph Outbox" ON graph_outbox
FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM twins 
        WHERE twins.id = graph_outbox.twin_id 
        AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    )
);

DROP POLICY IF EXISTS "Tenant Isolation: Modify Graph Outbox" ON graph_outbox;
CREATE POLICY "Tenant Isolation: Modify Graph Outbox" ON graph_outbox
FOR ALL USING (
    EXISTS (
        SELECT 1 FROM twins 
        WHERE twins.id = graph_outbox.twin_id 
        AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    )
);

-- Cache policies
DROP POLICY IF EXISTS "Tenant Isolation: View Graph Cache" ON graph_extraction_cache;
CREATE POLICY "Tenant Isolation: View Graph Cache" ON graph_extraction_cache
FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM twins 
        WHERE twins.id = graph_extraction_cache.twin_id 
        AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    )
);

DROP POLICY IF EXISTS "Tenant Isolation: Modify Graph Cache" ON graph_extraction_cache;
CREATE POLICY "Tenant Isolation: Modify Graph Cache" ON graph_extraction_cache
FOR ALL USING (
    EXISTS (
        SELECT 1 FROM twins 
        WHERE twins.id = graph_extraction_cache.twin_id 
        AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    )
);

-- 4. System RPC Functions

-- Atomic job claiming
CREATE OR REPLACE FUNCTION claim_graph_outbox_job(
    p_job_id UUID,
    p_worker_id TEXT,
    p_now TIMESTAMPTZ
)
RETURNS TABLE (
    id UUID,
    tenant_id UUID,
    twin_id UUID,
    operation TEXT,
    payload JSONB,
    attempt_count INTEGER
) AS $$
BEGIN
    RETURN QUERY
    UPDATE graph_outbox
    SET 
        status = 'processing',
        updated_at = p_now,
        attempt_count = attempt_count + 1
    WHERE 
        id = p_job_id
        AND status = 'pending'
        AND (next_attempt_after IS NULL OR next_attempt_after <= p_now)
    RETURNING 
        graph_outbox.id,
        graph_outbox.tenant_id,
        graph_outbox.twin_id,
        graph_outbox.operation,
        graph_outbox.payload,
        graph_outbox.attempt_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Get outbox depth for monitoring
CREATE OR REPLACE FUNCTION get_graph_outbox_depth(
    p_tenant_id UUID DEFAULT NULL
)
RETURNS TABLE (status TEXT, count BIGINT) AS $$
BEGIN
    IF p_tenant_id IS NOT NULL THEN
        RETURN QUERY
        SELECT 
            g.status,
            COUNT(*)::BIGINT
        FROM graph_outbox g
        JOIN twins t ON t.id = g.twin_id
        WHERE t.tenant_id = p_tenant_id
        GROUP BY g.status;
    ELSE
        RETURN QUERY
        SELECT 
            status,
            COUNT(*)::BIGINT
        FROM graph_outbox
        GROUP BY status;
    END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Cleanup old completed jobs (call periodically)
CREATE OR REPLACE FUNCTION cleanup_graph_outbox(
    p_completed_before TIMESTAMPTZ
)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM graph_outbox
    WHERE status IN ('completed', 'failed')
    AND updated_at < p_completed_before;
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
