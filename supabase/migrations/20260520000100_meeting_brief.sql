-- Phase 30-L (P1.2): Pre-meeting brief storage.
-- The brief engine (adk_core.services.persona_core.brief) generates a
-- BriefContract per meeting and persists it here. The brief route fetches
-- this column; if NULL, the route triggers lazy generation.
--
-- brief_json: full BriefContract dict (person + signals + prior_meetings +
--             hooks + open_commitments + generated_at).
-- brief_generated_at: timestamp set once the brief is materialised; used to
--             support the future 15-min-pre-meeting scheduler (P1.2.1) which
--             will query for upcoming meetings still missing a brief.
--
-- This migration is additive and idempotent.

ALTER TABLE public.meetings
    ADD COLUMN IF NOT EXISTS brief_json JSONB,
    ADD COLUMN IF NOT EXISTS brief_generated_at TIMESTAMPTZ;

-- Partial index used by the scheduler to find upcoming meetings that still
-- need a brief. WHERE clause keeps the index small even for high-volume
-- accounts because it only retains rows that match both conditions.
CREATE INDEX IF NOT EXISTS idx_meetings_brief_pending
    ON public.meetings(meeting_start)
    WHERE brief_generated_at IS NULL;
