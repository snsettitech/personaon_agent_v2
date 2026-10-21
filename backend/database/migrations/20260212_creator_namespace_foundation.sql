-- ============================================================================
-- Phase 1/2: advisor Creator Namespace Foundation
-- Adds creator_id for namespace-per-creator strategy.
-- ============================================================================

ALTER TABLE twins
ADD COLUMN IF NOT EXISTS creator_id TEXT;

-- Backfill creator_id from tenant_id for existing rows.
-- This keeps current tenant isolation semantics while enabling creator namespaces.
UPDATE twins
SET creator_id = 'tenant_' || tenant_id::text
WHERE creator_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_twins_creator_id
ON twins(creator_id);

-- Optional helper index used in migration tooling.
CREATE INDEX IF NOT EXISTS idx_twins_tenant_creator
ON twins(tenant_id, creator_id);
