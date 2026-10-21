-- PR2: persist the persona's inline-inferred visitor type + intent on the lead row.
-- Powers the Home operator ("3 recruiters asked about backend") and the enriched
-- hot-lead alert. Coarse categorical strings only (not free-text dossiers); owner-
-- scoped via the existing widget_leads RLS. All ADD COLUMN IF NOT EXISTS — safe to
-- re-run on existing production tables.

ALTER TABLE public.widget_leads
    ADD COLUMN IF NOT EXISTS inferred_visitor_type TEXT,
    ADD COLUMN IF NOT EXISTS inferred_intent       TEXT;
