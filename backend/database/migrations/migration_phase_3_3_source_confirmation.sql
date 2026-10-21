-- ============================================================================
-- Deep Research: Phase 3.3 - Source Confirmation System
-- ============================================================================
-- Adds research_run_id column to source_confirmations for confirmation workflow.
-- All changes are additive to maintain backward compatibility.
--
-- Created: 2026-02-24
-- Phase: 3.3
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Add research_run_id to source_confirmations table
-- ----------------------------------------------------------------------------
ALTER TABLE source_confirmations 
ADD COLUMN IF NOT EXISTS research_run_id UUID REFERENCES research_runs(id) ON DELETE CASCADE;

-- Add index for research_run_id lookups
CREATE INDEX IF NOT EXISTS idx_source_confirmations_research_run_id 
    ON source_confirmations(research_run_id);

-- Add composite index for common query patterns
CREATE INDEX IF NOT EXISTS idx_source_confirmations_research_status 
    ON source_confirmations(research_run_id, confirmation_status);

-- ----------------------------------------------------------------------------
-- Add additional columns for confirmation details (if not already present)
-- ----------------------------------------------------------------------------

-- Content quality for display
ALTER TABLE source_confirmations 
ADD COLUMN IF NOT EXISTS content_quality VARCHAR(20);

-- URL fields for display
ALTER TABLE source_confirmations 
ADD COLUMN IF NOT EXISTS url TEXT;

ALTER TABLE source_confirmations 
ADD COLUMN IF NOT EXISTS canonical_url TEXT;

-- Title and snippet for UI display
ALTER TABLE source_confirmations 
ADD COLUMN IF NOT EXISTS title TEXT;

ALTER TABLE source_confirmations 
ADD COLUMN IF NOT EXISTS snippet TEXT;

-- Submitted root URL for lineage tracking
ALTER TABLE source_confirmations 
ADD COLUMN IF NOT EXISTS submitted_root_url TEXT;

-- Match details (JSONB for flexible identity match info)
ALTER TABLE source_confirmations 
ADD COLUMN IF NOT EXISTS match_details JSONB;

-- ----------------------------------------------------------------------------
-- Comments documenting column purposes
-- ----------------------------------------------------------------------------
COMMENT ON COLUMN source_confirmations.research_run_id IS 
    'Links confirmation to research run for workflow scoping (Phase 3.3)';
COMMENT ON COLUMN source_confirmations.content_quality IS 
    'Content quality from Firecrawl (full/partial/blocked/manual_needed)';
COMMENT ON COLUMN source_confirmations.url IS 
    'Original URL for display';
COMMENT ON COLUMN source_confirmations.canonical_url IS 
    'Canonical URL for deduplication';
COMMENT ON COLUMN source_confirmations.title IS 
    'Page title for UI display';
COMMENT ON COLUMN source_confirmations.snippet IS 
    'Page snippet/description for UI display';
COMMENT ON COLUMN source_confirmations.submitted_root_url IS 
    'Original submitted URL for lineage';
COMMENT ON COLUMN source_confirmations.match_details IS 
    'JSON with identity match details (signals, reasons)';

-- ----------------------------------------------------------------------------
-- Update RLS policies to include research_run_id-based access
-- ----------------------------------------------------------------------------
-- Note: Existing policies from Phase 3.0 still apply for twin-based access
