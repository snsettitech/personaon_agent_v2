-- Phase 3-B: enrich widget_leads with visitor tracking + lead state machine.
-- All ADD COLUMN IF NOT EXISTS — safe to run on existing production table.

ALTER TABLE public.widget_leads
    ADD COLUMN IF NOT EXISTS visitor_id    TEXT,
    ADD COLUMN IF NOT EXISTS utm_source    TEXT,
    ADD COLUMN IF NOT EXISTS utm_medium    TEXT,
    ADD COLUMN IF NOT EXISTS utm_campaign  TEXT,
    ADD COLUMN IF NOT EXISTS utm_content   TEXT,
    ADD COLUMN IF NOT EXISTS offer_state   TEXT NOT NULL DEFAULT 'not_yet_offered',
    ADD COLUMN IF NOT EXISTS turn_count    INTEGER NOT NULL DEFAULT 0;

-- Index for visitor_id lookups (returning visitor detection)
CREATE INDEX IF NOT EXISTS widget_leads_visitor_id_twin_idx
    ON public.widget_leads(visitor_id, twin_id)
    WHERE visitor_id IS NOT NULL;

-- offer_state values: 'not_yet_offered' | 'already_offered' | 'email_captured'
-- Enforced by application logic, not a DB constraint (allows future states).
