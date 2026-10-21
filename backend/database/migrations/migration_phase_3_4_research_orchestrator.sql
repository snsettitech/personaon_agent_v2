-- ============================================================================
-- Deep Research: Phase 3.4 - Research Orchestrator (State Machine + Checkpointing)
-- ============================================================================
-- Adds state machine support and checkpoint persistence for research runs.
-- All changes are additive (nullable columns) to maintain backward compatibility.
--
-- Created: 2026-02-23
-- Phase: 3.4
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Add crawl_id reference to research_runs
-- ----------------------------------------------------------------------------
ALTER TABLE research_runs
ADD COLUMN IF NOT EXISTS crawl_id UUID REFERENCES crawl_runs(id) ON DELETE SET NULL;

-- Index for crawl lookup
CREATE INDEX IF NOT EXISTS idx_research_runs_crawl_id ON research_runs(crawl_id);

-- ----------------------------------------------------------------------------
-- Add onboarding session link (optional)
-- ----------------------------------------------------------------------------
ALTER TABLE research_runs
ADD COLUMN IF NOT EXISTS onboarding_session_id UUID;

CREATE INDEX IF NOT EXISTS idx_research_runs_onboarding_session 
ON research_runs(onboarding_session_id) 
WHERE onboarding_session_id IS NOT NULL;

-- ----------------------------------------------------------------------------
-- Add timing columns for better lifecycle tracking
-- ----------------------------------------------------------------------------
-- started_at: when the run actually begins (queued -> crawling transition)
ALTER TABLE research_runs
ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;

-- ----------------------------------------------------------------------------
-- Add composite index for common queries
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_research_runs_twin_status_created 
ON research_runs(twin_id, status, created_at DESC);

-- ----------------------------------------------------------------------------
-- Comment documentation
-- ----------------------------------------------------------------------------
COMMENT ON COLUMN research_runs.status IS 
'State machine status: planning -> queued -> crawling -> awaiting_confirmation -> ready_for_ingestion -> completed/failed';

COMMENT ON COLUMN research_runs.checkpoint_data IS 
'JSON checkpoint for resume capability: {phase, last_transition_at, crawl_id, confirmation: {...}, claimed_identity, seed_urls_count, timeout_at, warnings}';

COMMENT ON COLUMN research_runs.crawl_id IS 
'Reference to the associated crawl run (if any)';

COMMENT ON COLUMN research_runs.onboarding_session_id IS 
'Optional link to onboarding session that triggered this research run';

COMMENT ON COLUMN research_runs.started_at IS 
'Timestamp when run transitions from planning/queued to crawling';
