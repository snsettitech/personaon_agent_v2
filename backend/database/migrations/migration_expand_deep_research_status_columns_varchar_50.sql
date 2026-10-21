-- Migration: Expand Deep Research status columns to avoid varchar(20) overflows
-- Purpose: Allow orchestrator/crawl statuses like 'awaiting_confirmation'
-- and 'completed_with_warnings' without write failures.

ALTER TABLE research_runs
ALTER COLUMN status TYPE VARCHAR(50);

ALTER TABLE crawl_runs
ALTER COLUMN status TYPE VARCHAR(50);

