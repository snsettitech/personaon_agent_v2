-- Add contacted_at column to widget_leads for tracking when a lead was marked
-- contacted in the dashboard (selected by widget.py Mark Contacted endpoint).
-- Populated by PATCH /widget/leads/{lead_id} (contacted_at field).
-- ADD COLUMN IF NOT EXISTS — safe to re-run on existing tables.
ALTER TABLE public.widget_leads
    ADD COLUMN IF NOT EXISTS contacted_at TIMESTAMPTZ;
