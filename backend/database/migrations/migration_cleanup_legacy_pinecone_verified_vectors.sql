-- Migration: Cleanup Legacy Pinecone Verified Vectors
-- Purpose: Remove dual storage approach - verified QnA now uses Postgres-only storage
-- 
-- NOTE: This migration script documents the cleanup process for legacy Pinecone vectors.
-- The actual Pinecone cleanup must be done via a Python script since Pinecone operations
-- cannot be done via SQL.
--
-- Run the Python script: backend/scripts/cleanup_legacy_pinecone_verified.py
-- This script will:
-- 1. Query all verified vectors from Pinecone (filter: is_verified=true)
-- 2. Delete them from Pinecone
-- 3. Optionally log which vectors were deleted for audit purposes
--
-- This migration is idempotent - safe to run multiple times.
--
-- After running the Python cleanup script, this migration is considered complete.
-- No SQL operations are needed since the Postgres verified_qna table already
-- contains all the data we need.

-- Migration status tracking (optional - for documentation)
DO $$
BEGIN
    -- This is a placeholder migration to document the cleanup process
    -- The actual cleanup is done via Python script
    RAISE NOTICE 'Legacy Pinecone verified vectors cleanup documented. Run Python script to execute cleanup.';
END $$;

