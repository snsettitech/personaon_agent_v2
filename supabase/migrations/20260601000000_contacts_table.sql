-- Phase F.1: contacts table + linkage to meeting_participants + widget_leads.
-- Cross-meeting identity for the workspace v2 People surface (US-O-10).

CREATE TABLE IF NOT EXISTS public.contacts (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL,
  twin_id         uuid NOT NULL REFERENCES public.twins(id) ON DELETE CASCADE,
  name            text NOT NULL,
  email           text,
  linkedin_url    text,
  avatar_url      text,
  first_seen_at   timestamptz NOT NULL DEFAULT now(),
  last_seen_at    timestamptz NOT NULL DEFAULT now(),
  meeting_count   integer NOT NULL DEFAULT 0,
  notes           text,
  allow_mention   boolean NOT NULL DEFAULT true,
  tags            text[] DEFAULT '{}'::text[],
  metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Reconcile when an earlier migration (phase30 20260505) already created a
-- DIFFERENT `contacts` table (display_name-based), which makes the CREATE TABLE
-- IF NOT EXISTS above a no-op. These idempotent ALTERs guarantee the canonical
-- columns the backend + search RPC + pg_trgm index require exist regardless of
-- which definition won. `name` is added nullable (the app always provides it);
-- backfill from a pre-existing display_name for safety.
ALTER TABLE public.contacts ADD COLUMN IF NOT EXISTS name          text;
ALTER TABLE public.contacts ADD COLUMN IF NOT EXISTS linkedin_url  text;
ALTER TABLE public.contacts ADD COLUMN IF NOT EXISTS avatar_url    text;
ALTER TABLE public.contacts ADD COLUMN IF NOT EXISTS last_seen_at  timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.contacts ADD COLUMN IF NOT EXISTS meeting_count integer NOT NULL DEFAULT 0;
ALTER TABLE public.contacts ADD COLUMN IF NOT EXISTS allow_mention boolean NOT NULL DEFAULT true;
ALTER TABLE public.contacts ADD COLUMN IF NOT EXISTS metadata      jsonb NOT NULL DEFAULT '{}'::jsonb;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='contacts' AND column_name='display_name') THEN
    UPDATE public.contacts SET name = display_name WHERE name IS NULL AND display_name IS NOT NULL;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_contacts_twin ON public.contacts(twin_id);
CREATE INDEX IF NOT EXISTS idx_contacts_tenant ON public.contacts(tenant_id);
-- Partial unique on lower(email) per twin: only enforced when email IS NOT NULL.
CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_twin_email
  ON public.contacts(twin_id, lower(email))
  WHERE email IS NOT NULL;

ALTER TABLE public.contacts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS contacts_owner_read ON public.contacts;
CREATE POLICY contacts_owner_read
  ON public.contacts FOR SELECT
  USING ((SELECT auth.uid()) = tenant_id);

DROP POLICY IF EXISTS contacts_service_all ON public.contacts;
CREATE POLICY contacts_service_all
  ON public.contacts FOR ALL
  USING (auth.role() = 'service_role');

-- Linkage: meeting_participants.contact_id — populated by the identity-linking worker.
ALTER TABLE public.meeting_participants
  ADD COLUMN IF NOT EXISTS contact_id uuid REFERENCES public.contacts(id) ON DELETE SET NULL;

-- Linkage: widget_leads.contact_id — populated when email is captured.
ALTER TABLE public.widget_leads
  ADD COLUMN IF NOT EXISTS contact_id uuid REFERENCES public.contacts(id) ON DELETE SET NULL;
