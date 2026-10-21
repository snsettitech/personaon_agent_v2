-- ============================================================================
-- Migration: Remove staging_status column from sources table
-- Purpose: Staging/approval workflow removed - all content auto-indexes now
-- ============================================================================

-- NOTE: Run this AFTER deploying the code changes to avoid runtime errors
-- The application code has been updated to no longer reference staging_status

-- Step 1: Drop the check constraint first
ALTER TABLE sources DROP CONSTRAINT IF EXISTS sources_staging_status_check;

-- Step 2: Drop the index on staging_status
DROP INDEX IF EXISTS idx_sources_staging_status;

-- Step 3: Remove the column
ALTER TABLE sources DROP COLUMN IF EXISTS staging_status;

-- Verification: Check the column is gone
-- SELECT column_name FROM information_schema.columns 
-- WHERE table_name = 'sources' AND column_name = 'staging_status';
-- Should return no rows
