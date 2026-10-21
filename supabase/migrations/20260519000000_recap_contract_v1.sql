-- Phase 30-F: Recap contract typed columns.
-- Adds 10 RecapContract payload columns + 2 metadata columns (recap_version,
-- recap_corrected_at) to public.meetings. The recap engine (Task P1.4.A) will
-- populate these going forward; today's engine writes only summary/summary_json/
-- action_items (untouched here for backward compat).
-- RLS coverage inherits from Phase 30 meetings_tenant_policy (FOR ALL).

ALTER TABLE public.meetings
    ADD COLUMN IF NOT EXISTS recap TEXT,
    ADD COLUMN IF NOT EXISTS intent_vs_outcome JSONB,
    ADD COLUMN IF NOT EXISTS action_items JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS commitments JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS decisions JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS topics JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS unanswered_questions JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS people_observed JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS my_positions JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS style_sample TEXT,
    ADD COLUMN IF NOT EXISTS recap_version INT DEFAULT 1,
    ADD COLUMN IF NOT EXISTS recap_corrected_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_meetings_recap_corrected
    ON public.meetings(recap_corrected_at)
    WHERE recap_corrected_at IS NOT NULL;
