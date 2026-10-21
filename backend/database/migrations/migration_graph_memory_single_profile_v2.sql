-- ============================================================================
-- Migration: Graph Memory Single-Profile Scope (V2 - TYPE FIX)
-- 
-- Fixes: UUID = text comparison error in backfill queries
-- ============================================================================

-- =============================================================================
-- 1.1 Add scope_id columns (nullable first)
-- =============================================================================

-- graph_outbox
ALTER TABLE graph_outbox 
ADD COLUMN IF NOT EXISTS scope_id TEXT,
ADD COLUMN IF NOT EXISTS creator_id TEXT;

-- graph_extraction_cache
ALTER TABLE graph_extraction_cache 
ADD COLUMN IF NOT EXISTS scope_id TEXT;

-- graph_context_snapshots
ALTER TABLE graph_context_snapshots 
ADD COLUMN IF NOT EXISTS scope_id TEXT;

-- graph_claims
ALTER TABLE graph_claims 
ADD COLUMN IF NOT EXISTS scope_id TEXT;

-- graph_contradiction_queue
ALTER TABLE graph_contradiction_queue 
ADD COLUMN IF NOT EXISTS scope_id TEXT;

-- =============================================================================
-- 1.2 Create indexes for scope_id queries
-- =============================================================================

-- graph_outbox indexes
CREATE INDEX IF NOT EXISTS idx_graph_outbox_scope_status 
ON graph_outbox(tenant_id, scope_id, status);

CREATE INDEX IF NOT EXISTS idx_graph_outbox_scope_idempotency 
ON graph_outbox(tenant_id, scope_id, idempotency_key);

-- graph_extraction_cache indexes
CREATE INDEX IF NOT EXISTS idx_graph_extraction_cache_scope 
ON graph_extraction_cache(tenant_id, scope_id);

-- graph_context_snapshots indexes
CREATE INDEX IF NOT EXISTS idx_graph_context_snapshots_scope 
ON graph_context_snapshots(tenant_id, scope_id);

-- graph_claims indexes
CREATE INDEX IF NOT EXISTS idx_graph_claims_scope 
ON graph_claims(tenant_id, scope_id);

-- graph_contradiction_queue indexes
CREATE INDEX IF NOT EXISTS idx_graph_contradiction_queue_scope 
ON graph_contradiction_queue(tenant_id, scope_id);

-- =============================================================================
-- 1.3 Backfill scope_id from twins.creator_id
-- FIX: Use direct UUID comparison (both columns are UUID)
-- =============================================================================

-- Backfill graph_outbox
UPDATE graph_outbox g
SET 
    scope_id = g.tenant_id::text || '__' || COALESCE(t.creator_id, 'tenant_' || t.tenant_id::text),
    creator_id = COALESCE(t.creator_id, 'tenant_' || t.tenant_id::text)
FROM twins t 
WHERE g.twin_id = t.id
AND g.scope_id IS NULL;

-- Fallback for orphaned rows where twin_id no longer exists in twins
UPDATE graph_outbox g
SET
    scope_id = g.tenant_id::text || '__tenant_' || g.tenant_id::text,
    creator_id = COALESCE(g.creator_id, 'tenant_' || g.tenant_id::text)
WHERE g.scope_id IS NULL
AND NOT EXISTS (
    SELECT 1 FROM twins t WHERE t.id = g.twin_id
);

-- Backfill graph_extraction_cache
UPDATE graph_extraction_cache g
SET scope_id = g.tenant_id::text || '__' || COALESCE(t.creator_id, 'tenant_' || t.tenant_id::text)
FROM twins t 
WHERE g.twin_id = t.id
AND g.scope_id IS NULL;

-- Fallback for orphaned rows where twin_id no longer exists in twins
UPDATE graph_extraction_cache g
SET scope_id = g.tenant_id::text || '__tenant_' || g.tenant_id::text
WHERE g.scope_id IS NULL
AND NOT EXISTS (
    SELECT 1 FROM twins t WHERE t.id = g.twin_id
);

-- Backfill graph_context_snapshots
UPDATE graph_context_snapshots g
SET scope_id = g.tenant_id::text || '__' || COALESCE(t.creator_id, 'tenant_' || t.tenant_id::text)
FROM twins t 
WHERE g.twin_id = t.id
AND g.scope_id IS NULL;

-- Fallback for orphaned rows where twin_id no longer exists in twins
UPDATE graph_context_snapshots g
SET scope_id = g.tenant_id::text || '__tenant_' || g.tenant_id::text
WHERE g.scope_id IS NULL
AND NOT EXISTS (
    SELECT 1 FROM twins t WHERE t.id = g.twin_id
);

-- Backfill graph_claims
UPDATE graph_claims g
SET scope_id = g.tenant_id::text || '__' || COALESCE(t.creator_id, 'tenant_' || t.tenant_id::text)
FROM twins t 
WHERE g.twin_id = t.id
AND g.scope_id IS NULL;

-- Fallback for orphaned rows where twin_id no longer exists in twins
UPDATE graph_claims g
SET scope_id = g.tenant_id::text || '__tenant_' || g.tenant_id::text
WHERE g.scope_id IS NULL
AND NOT EXISTS (
    SELECT 1 FROM twins t WHERE t.id = g.twin_id
);

-- Backfill graph_contradiction_queue
UPDATE graph_contradiction_queue g
SET scope_id = g.tenant_id::text || '__' || COALESCE(t.creator_id, 'tenant_' || t.tenant_id::text)
FROM twins t 
WHERE g.twin_id = t.id
AND g.scope_id IS NULL;

-- Fallback for orphaned rows where twin_id no longer exists in twins
UPDATE graph_contradiction_queue g
SET scope_id = g.tenant_id::text || '__tenant_' || g.tenant_id::text
WHERE g.scope_id IS NULL
AND NOT EXISTS (
    SELECT 1 FROM twins t WHERE t.id = g.twin_id
);

-- =============================================================================
-- 1.4 Add new unique constraint for scope-isolated idempotency
-- Keep old constraint for backward compatibility during rollout
-- =============================================================================

-- Drop existing unique constraint if exists (we'll recreate it properly)
ALTER TABLE graph_outbox 
DROP CONSTRAINT IF EXISTS graph_outbox_tenant_scope_idempotency_unique;

-- Add new scope-based unique constraint
ALTER TABLE graph_outbox
ADD CONSTRAINT graph_outbox_tenant_scope_idempotency_unique
UNIQUE (tenant_id, scope_id, idempotency_key);

-- =============================================================================
-- 1.5 Add comments for documentation
-- =============================================================================

COMMENT ON COLUMN graph_outbox.scope_id IS 
'Single-profile scope identifier: {tenant_id}__{creator_id}. Used for isolation in single-profile model.';

COMMENT ON COLUMN graph_outbox.creator_id IS 
'The creator ID from twins table. Cached here to avoid joins during job processing.';

COMMENT ON COLUMN graph_extraction_cache.scope_id IS 
'Single-profile scope identifier for cache isolation.';

COMMENT ON COLUMN graph_context_snapshots.scope_id IS 
'Single-profile scope identifier for snapshot isolation.';

COMMENT ON COLUMN graph_claims.scope_id IS 
'Single-profile scope identifier for claim isolation.';

COMMENT ON COLUMN graph_contradiction_queue.scope_id IS 
'Single-profile scope identifier for contradiction queue isolation.';

-- =============================================================================
-- Migration complete
-- Note: Making scope_id NOT NULL will be done in cleanup phase after
-- all code is writing scope_id consistently.
-- =============================================================================
