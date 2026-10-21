-- ============================================================================
-- Phase 1: Add twin_id to name_deep_research_runs for Profile Completeness V1
-- ============================================================================
-- This enables the name-only flow to return a twin_id that can be used
-- as the profile identifier in the UI.
--
-- Created: 2026-02-25
-- ============================================================================

-- Add twin_id column to name_deep_research_runs
ALTER TABLE name_deep_research_runs
ADD COLUMN IF NOT EXISTS twin_id UUID NULL;

-- Create index for fast lookups
CREATE INDEX IF NOT EXISTS idx_name_research_runs_twin_id
ON name_deep_research_runs(twin_id);

-- Add comment explaining the column
COMMENT ON COLUMN name_deep_research_runs.twin_id IS
'Twin ID created for this name-only research run. Used for profile sharing and public access.';

-- ----------------------------------------------------------------------------
-- Rollback (manual)
-- ----------------------------------------------------------------------------
-- ALTER TABLE name_deep_research_runs DROP COLUMN IF EXISTS twin_id;
