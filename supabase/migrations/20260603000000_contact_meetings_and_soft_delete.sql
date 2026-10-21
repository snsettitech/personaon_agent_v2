-- Phase F follow-up: persistent contact↔meeting association + soft-delete on contacts.

-- 1. Soft-delete column on contacts so user-removed contacts are not resurrected
--    by the recap-extractor on the next worker run.
ALTER TABLE public.contacts
  ADD COLUMN IF NOT EXISTS deleted_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_contacts_deleted
  ON public.contacts(deleted_at)
  WHERE deleted_at IS NOT NULL;

-- 2. Persistent contact↔meeting join. Lets us show "meetings with this person"
--    cleanly. Populated at link time (both email + recap paths).
CREATE TABLE IF NOT EXISTS public.contact_meetings (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id  uuid NOT NULL,
  twin_id    uuid NOT NULL REFERENCES public.twins(id) ON DELETE CASCADE,
  contact_id uuid NOT NULL REFERENCES public.contacts(id) ON DELETE CASCADE,
  meeting_id uuid NOT NULL,            -- not FK: meetings can be soft-deleted
  source     text NOT NULL DEFAULT 'recap' CHECK (source IN ('participant','recap')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (contact_id, meeting_id)      -- one row per (contact, meeting)
);

CREATE INDEX IF NOT EXISTS idx_cm_contact   ON public.contact_meetings(contact_id);
CREATE INDEX IF NOT EXISTS idx_cm_meeting   ON public.contact_meetings(meeting_id);
CREATE INDEX IF NOT EXISTS idx_cm_tenant    ON public.contact_meetings(tenant_id);

ALTER TABLE public.contact_meetings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS cm_owner_read   ON public.contact_meetings;
CREATE POLICY cm_owner_read
  ON public.contact_meetings FOR SELECT
  USING ((SELECT auth.uid()) = tenant_id);

DROP POLICY IF EXISTS cm_service_all  ON public.contact_meetings;
CREATE POLICY cm_service_all
  ON public.contact_meetings FOR ALL
  USING (auth.role() = 'service_role');
