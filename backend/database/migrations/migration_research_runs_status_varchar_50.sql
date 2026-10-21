-- Migration: Expand research_runs.status length for orchestrator states
-- Purpose: Allow statuses like 'awaiting_confirmation' (21 chars) without truncation failures.

ALTER TABLE research_runs
ALTER COLUMN status TYPE VARCHAR(50);

