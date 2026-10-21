-- ============================================================================
-- Migration: Phased Backend Scope Hardening (v2)
-- Description: 
-- 1. Corrects audit_logs (tenant_id mandatory, twin_id nullable)
-- 2. Scopes escalations (tenant_id/twin_id mandatory with backfill)
-- 3. Adds production-safe indexes for tenant filtering
-- ============================================================================

-- ============================================================================
-- PHASE 1: Schema Setup & Constraint Relaxation
-- ============================================================================

-- relax audit_logs twin_id (legacy P0 made this NOT NULL)
ALTER TABLE audit_logs ALTER COLUMN twin_id DROP NOT NULL;

-- ensure audit_logs has tenant_id (NULLABLE initially)
DO $$ 
BEGIN 
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='audit_logs' AND column_name='tenant_id') THEN
        ALTER TABLE audit_logs ADD COLUMN tenant_id UUID REFERENCES tenants(id);
    END IF;
END $$;

-- prepare escalations for scoping (NULLABLE initially)
DO $$ 
BEGIN 
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='escalations' AND column_name='tenant_id') THEN
        ALTER TABLE escalations ADD COLUMN tenant_id UUID REFERENCES tenants(id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='escalations' AND column_name='twin_id') THEN
        ALTER TABLE escalations ADD COLUMN twin_id UUID REFERENCES twins(id);
    END IF;
END $$;


-- ============================================================================
-- PHASE 2: Backfill (Safe Data Migration)
-- ============================================================================

-- A) Backfill audit_logs.tenant_id from twins where twin_id exists
UPDATE audit_logs a
SET tenant_id = t.tenant_id
FROM twins t
WHERE a.twin_id = t.id
AND a.tenant_id IS NULL;

-- B) Backfill escalations.twin_id and tenant_id from messages -> conversations
-- Path: escalations.message_id -> messages.conversation_id -> conversations.twin_id -> twins.tenant_id
UPDATE escalations e
SET 
  twin_id = c.twin_id,
  tenant_id = t.tenant_id
FROM messages m
JOIN conversations c ON m.conversation_id = c.id
JOIN twins t ON c.twin_id = t.id
WHERE e.message_id = m.id
AND (e.twin_id IS NULL OR e.tenant_id IS NULL);


-- ============================================================================
-- PHASE 3: Validation & Constraint Enforcement
-- ============================================================================

-- VALIDATION 1: Check for orphan audit_logs
-- SELECT COUNT(*) as orphan_audit_logs FROM audit_logs WHERE tenant_id IS NULL;

-- VALIDATION 2: Check for orphan escalations
-- SELECT COUNT(*) as orphan_escalations FROM escalations WHERE tenant_id IS NULL OR twin_id IS NULL;

-- ENFORCEMENT (Only run if validations above return 0)
-- If orphans exist, do NOT run these. Manually investigate.
DO $$ 
BEGIN 
    -- Only enforce if no orphans exist
    IF (SELECT COUNT(*) FROM audit_logs WHERE tenant_id IS NULL) = 0 THEN
        ALTER TABLE audit_logs ALTER COLUMN tenant_id SET NOT NULL;
    END IF;

    IF (SELECT COUNT(*) FROM escalations WHERE tenant_id IS NULL) = 0 THEN
        ALTER TABLE escalations ALTER COLUMN tenant_id SET NOT NULL;
    END IF;

    IF (SELECT COUNT(*) FROM escalations WHERE twin_id IS NULL) = 0 THEN
        ALTER TABLE escalations ALTER COLUMN twin_id SET NOT NULL;
    END IF;
END $$;


-- ============================================================================
-- PHASE 4: Optimization (Indexes)
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_id ON audit_logs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_twin_created ON audit_logs(tenant_id, twin_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_escalations_tenant_id ON escalations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_escalations_tenant_twin_created ON escalations(tenant_id, twin_id, created_at DESC);


-- ============================================================================
-- ROLLBACK SQL (For emergency use)
-- ============================================================================
/*
-- 1. Remove constraints
ALTER TABLE audit_logs ALTER COLUMN tenant_id DROP NOT NULL;
ALTER TABLE audit_logs ALTER COLUMN twin_id SET NOT NULL; -- Warning: May fail if NULLs were introduced
ALTER TABLE escalations ALTER COLUMN tenant_id DROP NOT NULL;
ALTER TABLE escalations ALTER COLUMN twin_id DROP NOT NULL;

-- 2. Drop columns (Careful: data loss)
-- ALTER TABLE audit_logs DROP COLUMN tenant_id;
-- ALTER TABLE escalations DROP COLUMN tenant_id;
-- ALTER TABLE escalations DROP COLUMN twin_id;

-- 3. Drop indexes
DROP INDEX IF EXISTS idx_audit_logs_tenant_twin_created;
DROP INDEX IF EXISTS idx_escalations_tenant_twin_created;
*/
