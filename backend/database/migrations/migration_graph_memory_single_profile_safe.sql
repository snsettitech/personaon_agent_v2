-- ============================================================================
-- Migration: Graph Memory Single-Profile Scope (SAFE VERSION)
-- 
-- This version checks if tables exist before trying to alter them.
-- Run this AFTER migration_phase3_claims_contradictions.sql
-- ============================================================================

-- Helper function to check if table exists
CREATE OR REPLACE FUNCTION table_exists(p_table_name TEXT)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_name = p_table_name
    );
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- 1.1 Add scope_id columns (only if table exists)
-- =============================================================================

-- graph_outbox (should exist from Phase 1)
DO $$
BEGIN
    IF table_exists('graph_outbox') THEN
        ALTER TABLE graph_outbox 
        ADD COLUMN IF NOT EXISTS scope_id TEXT,
        ADD COLUMN IF NOT EXISTS creator_id TEXT;
        RAISE NOTICE 'Updated graph_outbox';
    ELSE
        RAISE NOTICE 'graph_outbox does not exist - skipping';
    END IF;
END $$;

-- graph_extraction_cache (should exist from Phase 1)
DO $$
BEGIN
    IF table_exists('graph_extraction_cache') THEN
        ALTER TABLE graph_extraction_cache 
        ADD COLUMN IF NOT EXISTS scope_id TEXT;
        RAISE NOTICE 'Updated graph_extraction_cache';
    ELSE
        RAISE NOTICE 'graph_extraction_cache does not exist - skipping';
    END IF;
END $$;

-- graph_context_snapshots (from Phase 3)
DO $$
BEGIN
    IF table_exists('graph_context_snapshots') THEN
        ALTER TABLE graph_context_snapshots 
        ADD COLUMN IF NOT EXISTS scope_id TEXT;
        RAISE NOTICE 'Updated graph_context_snapshots';
    ELSE
        RAISE NOTICE 'graph_context_snapshots does not exist - skipping. Run migration_phase3_claims_contradictions.sql first!';
    END IF;
END $$;

-- graph_claims (from Phase 3)
DO $$
BEGIN
    IF table_exists('graph_claims') THEN
        ALTER TABLE graph_claims 
        ADD COLUMN IF NOT EXISTS scope_id TEXT;
        RAISE NOTICE 'Updated graph_claims';
    ELSE
        RAISE NOTICE 'graph_claims does not exist - skipping. Run migration_phase3_claims_contradictions.sql first!';
    END IF;
END $$;

-- graph_contradiction_queue (from Phase 3)
DO $$
BEGIN
    IF table_exists('graph_contradiction_queue') THEN
        ALTER TABLE graph_contradiction_queue 
        ADD COLUMN IF NOT EXISTS scope_id TEXT;
        RAISE NOTICE 'Updated graph_contradiction_queue';
    ELSE
        RAISE NOTICE 'graph_contradiction_queue does not exist - skipping. Run migration_phase3_claims_contradictions.sql first!';
    END IF;
END $$;

-- =============================================================================
-- 1.2 Create indexes for scope_id queries
-- =============================================================================

DO $$
BEGIN
    IF table_exists('graph_outbox') THEN
        CREATE INDEX IF NOT EXISTS idx_graph_outbox_scope_status 
        ON graph_outbox(tenant_id, scope_id, status);
        
        CREATE INDEX IF NOT EXISTS idx_graph_outbox_scope_idempotency 
        ON graph_outbox(tenant_id, scope_id, idempotency_key);
    END IF;
END $$;

DO $$
BEGIN
    IF table_exists('graph_extraction_cache') THEN
        CREATE INDEX IF NOT EXISTS idx_graph_extraction_cache_scope 
        ON graph_extraction_cache(tenant_id, scope_id);
    END IF;
END $$;

DO $$
BEGIN
    IF table_exists('graph_context_snapshots') THEN
        CREATE INDEX IF NOT EXISTS idx_graph_context_snapshots_scope 
        ON graph_context_snapshots(tenant_id, scope_id);
    END IF;
END $$;

DO $$
BEGIN
    IF table_exists('graph_claims') THEN
        CREATE INDEX IF NOT EXISTS idx_graph_claims_scope 
        ON graph_claims(tenant_id, scope_id);
    END IF;
END $$;

DO $$
BEGIN
    IF table_exists('graph_contradiction_queue') THEN
        CREATE INDEX IF NOT EXISTS idx_graph_contradiction_queue_scope 
        ON graph_contradiction_queue(tenant_id, scope_id);
    END IF;
END $$;

-- =============================================================================
-- 1.3 Backfill scope_id from twins.creator_id (only where table exists)
-- =============================================================================

DO $$
BEGIN
    IF table_exists('graph_outbox') AND table_exists('twins') THEN
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
        RAISE NOTICE 'Backfilled graph_outbox';
    END IF;
END $$;

DO $$
BEGIN
    IF table_exists('graph_extraction_cache') AND table_exists('twins') THEN
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
        RAISE NOTICE 'Backfilled graph_extraction_cache';
    END IF;
END $$;

DO $$
BEGIN
    IF table_exists('graph_context_snapshots') AND table_exists('twins') THEN
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
        RAISE NOTICE 'Backfilled graph_context_snapshots';
    END IF;
END $$;

DO $$
BEGIN
    IF table_exists('graph_claims') AND table_exists('twins') THEN
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
        RAISE NOTICE 'Backfilled graph_claims';
    END IF;
END $$;

DO $$
BEGIN
    IF table_exists('graph_contradiction_queue') AND table_exists('twins') THEN
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
        RAISE NOTICE 'Backfilled graph_contradiction_queue';
    END IF;
END $$;

-- =============================================================================
-- 1.4 Add new unique constraint for scope-isolated idempotency (graph_outbox only)
-- =============================================================================

DO $$
BEGIN
    IF table_exists('graph_outbox') THEN
        -- Drop existing unique constraint if exists (we'll recreate it properly)
        ALTER TABLE graph_outbox 
        DROP CONSTRAINT IF EXISTS graph_outbox_tenant_scope_idempotency_unique;
        
        -- Add new scope-based unique constraint
        ALTER TABLE graph_outbox
        ADD CONSTRAINT graph_outbox_tenant_scope_idempotency_unique
        UNIQUE (tenant_id, scope_id, idempotency_key);
        
        RAISE NOTICE 'Added unique constraint to graph_outbox';
    END IF;
END $$;

-- =============================================================================
-- 1.5 Add comments for documentation
-- =============================================================================

DO $$
BEGIN
    IF table_exists('graph_outbox') THEN
        COMMENT ON COLUMN graph_outbox.scope_id IS 
        'Single-profile scope identifier: {tenant_id}__{creator_id}. Used for isolation in single-profile model.';
        
        COMMENT ON COLUMN graph_outbox.creator_id IS 
        'The creator ID from twins table. Cached here to avoid joins during job processing.';
    END IF;
END $$;

DO $$
BEGIN
    IF table_exists('graph_extraction_cache') THEN
        COMMENT ON COLUMN graph_extraction_cache.scope_id IS 
        'Single-profile scope identifier for cache isolation.';
    END IF;
END $$;

DO $$
BEGIN
    IF table_exists('graph_context_snapshots') THEN
        COMMENT ON COLUMN graph_context_snapshots.scope_id IS 
        'Single-profile scope identifier for snapshot isolation.';
    END IF;
END $$;

DO $$
BEGIN
    IF table_exists('graph_claims') THEN
        COMMENT ON COLUMN graph_claims.scope_id IS 
        'Single-profile scope identifier for claim isolation.';
    END IF;
END $$;

DO $$
BEGIN
    IF table_exists('graph_contradiction_queue') THEN
        COMMENT ON COLUMN graph_contradiction_queue.scope_id IS 
        'Single-profile scope identifier for contradiction queue isolation.';
    END IF;
END $$;

-- Drop helper function
DROP FUNCTION IF EXISTS table_exists(TEXT);

-- =============================================================================
-- Migration complete
-- Note: Making scope_id NOT NULL will be done in cleanup phase after
-- all code is writing scope_id consistently.
-- =============================================================================
