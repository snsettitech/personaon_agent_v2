-- 20260205_phase4_memory_tiers.sql
-- Refines owner_beliefs to support Phase 4 Dialogue System Architecture

-- 1. Add temporal columns to owner_beliefs (Path C + Phase 4)
ALTER TABLE owner_beliefs
ADD COLUMN IF NOT EXISTS effective_from TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
ADD COLUMN IF NOT EXISTS effective_to TIMESTAMP WITH TIME ZONE;

-- 2. Update status constraint to include 'proposed', 'verified', 'deprecated'
-- Note: PostgreSQL doesn't support easy 'ALTER CONSTRAINT', so we drop and recreate.
ALTER TABLE owner_beliefs
DROP CONSTRAINT IF EXISTS owner_beliefs_status_check;

ALTER TABLE owner_beliefs
ADD CONSTRAINT owner_beliefs_status_check
CHECK (status IN ('active', 'superseded', 'retracted', 'proposed', 'verified', 'deprecated'));

-- 3. Add commentary for documentation
COMMENT ON COLUMN owner_beliefs.status IS 'Memory lifecycle status: proposed (from auto-extract), verified (owner confirmed), deprecated (old/incorrect)';
COMMENT ON COLUMN owner_beliefs.provenance IS 'Metadata: {source_type: "doc"|"interview"|"revision", source_id: UUID, timestamp: ISO8601}';
