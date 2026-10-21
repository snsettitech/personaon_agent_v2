-- Allows owners to mark leads as contacted
ALTER TABLE public.widget_leads
  ADD COLUMN IF NOT EXISTS contacted_at TIMESTAMPTZ;
