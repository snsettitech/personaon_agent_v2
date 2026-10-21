-- ============================================================================
-- Twins Lifecycle Alignment (single-profile hardening)
-- ============================================================================
-- Ensures twins lifecycle columns exist and are compatible across environments:
-- - status
-- - creation_mode
-- - is_active
-- - updated_at
--
-- Also aligns CHECK constraints so name-first/profile flows do not fail on
-- legacy schemas.
-- ============================================================================

-- 1) Ensure lifecycle columns exist
ALTER TABLE twins ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE twins ADD COLUMN IF NOT EXISTS is_active BOOLEAN;
ALTER TABLE twins ADD COLUMN IF NOT EXISTS creation_mode TEXT;
ALTER TABLE twins ADD COLUMN IF NOT EXISTS status TEXT;

-- 2) Backfill updated_at
UPDATE twins
SET updated_at = COALESCE(updated_at, created_at, NOW())
WHERE updated_at IS NULL;

-- 3) Backfill creation_mode from settings/state heuristics
UPDATE twins
SET creation_mode = COALESCE(
    NULLIF(creation_mode, ''),
    NULLIF(settings->>'creation_mode', ''),
    CASE
        WHEN COALESCE(settings->>'name_first_state', '') <> '' THEN 'name_first'
        WHEN COALESCE(settings->>'link_first_state', '') <> '' THEN 'link_first'
        WHEN COALESCE(settings->>'build_mode', '') = 'with_links' THEN 'link_first'
        ELSE 'manual'
    END
)
WHERE creation_mode IS NULL OR creation_mode = '';

ALTER TABLE twins ALTER COLUMN creation_mode SET DEFAULT 'manual';
ALTER TABLE twins DROP CONSTRAINT IF EXISTS twins_creation_mode_check;
ALTER TABLE twins
ADD CONSTRAINT twins_creation_mode_check
CHECK (creation_mode IN ('manual', 'link_first', 'name_first'));

-- 4) Backfill status
UPDATE twins
SET status = COALESCE(
    NULLIF(status, ''),
    NULLIF(settings->>'link_first_state', ''),
    CASE
        WHEN COALESCE(is_active, FALSE) = TRUE THEN 'active'
        ELSE 'draft'
    END
)
WHERE status IS NULL OR status = '';

ALTER TABLE twins ALTER COLUMN status SET DEFAULT 'draft';
ALTER TABLE twins DROP CONSTRAINT IF EXISTS twins_status_check;
ALTER TABLE twins
ADD CONSTRAINT twins_status_check
CHECK (
    status IN (
        'draft',
        'building',
        'ingesting',
        'claims_ready',
        'clarification_pending',
        'persona_built',
        'active',
        'live',
        'needs_attention',
        'failed',
        'archived'
    )
);

-- 5) Backfill is_active using status as source of truth
UPDATE twins
SET is_active = CASE
    WHEN status IN ('active', 'live', 'persona_built') THEN TRUE
    ELSE FALSE
END
WHERE is_active IS NULL;

ALTER TABLE twins ALTER COLUMN is_active SET DEFAULT TRUE;
ALTER TABLE twins ALTER COLUMN is_active SET NOT NULL;

-- 6) Helpful index: one non-deleted profile per owner within tenant
CREATE UNIQUE INDEX IF NOT EXISTS idx_twins_tenant_owner_user_single_profile
ON twins (tenant_id, (settings->>'owner_user_id'))
WHERE (settings->>'owner_user_id') IS NOT NULL
  AND (settings->>'deleted_at') IS NULL;

-- 7) Useful lifecycle index
CREATE INDEX IF NOT EXISTS idx_twins_tenant_status_created
ON twins (tenant_id, status, created_at DESC);

