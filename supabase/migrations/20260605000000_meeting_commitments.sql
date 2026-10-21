-- 20260605000000_meeting_commitments.sql
-- Materialize commitments emitted by recap_extras_json into a queryable table.
-- content_hash enables UPSERT-based idempotency: on_conflict='meeting_id,content_hash,source'
-- so re-running recap_extras preserves user-set done/dismissed status.

CREATE TABLE IF NOT EXISTS public.meeting_commitments (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL,
  twin_id       uuid NOT NULL,
  meeting_id    uuid NOT NULL REFERENCES public.meetings(id) ON DELETE CASCADE,
  contact_id    uuid REFERENCES public.contacts(id) ON DELETE SET NULL,
  direction     text NOT NULL CHECK (direction IN ('you_owe','they_owe','unknown')),
  text          text NOT NULL,
  assignee_name text,
  due_at        timestamptz,
  content_hash  text NOT NULL,
  status        text NOT NULL DEFAULT 'open' CHECK (status IN ('open','done','dismissed')),
  source        text NOT NULL DEFAULT 'recap_extras' CHECK (source IN ('recap_extras','manual','desktop_sdk')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (meeting_id, content_hash, source)
);

CREATE INDEX IF NOT EXISTS idx_mcommit_tenant       ON public.meeting_commitments(tenant_id);
CREATE INDEX IF NOT EXISTS idx_mcommit_twin         ON public.meeting_commitments(twin_id);
CREATE INDEX IF NOT EXISTS idx_mcommit_meeting      ON public.meeting_commitments(meeting_id);
CREATE INDEX IF NOT EXISTS idx_mcommit_contact      ON public.meeting_commitments(contact_id);
CREATE INDEX IF NOT EXISTS idx_mcommit_twin_status  ON public.meeting_commitments(twin_id, status);
CREATE INDEX IF NOT EXISTS idx_mcommit_contact_dir  ON public.meeting_commitments(contact_id, direction, status);

ALTER TABLE public.meeting_commitments ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS mcommit_owner_read   ON public.meeting_commitments;
CREATE POLICY mcommit_owner_read
  ON public.meeting_commitments FOR SELECT
  USING ((SELECT auth.uid()) = tenant_id);

DROP POLICY IF EXISTS mcommit_owner_update ON public.meeting_commitments;
CREATE POLICY mcommit_owner_update
  ON public.meeting_commitments FOR UPDATE
  USING ((SELECT auth.uid()) = tenant_id);

DROP POLICY IF EXISTS mcommit_service_all  ON public.meeting_commitments;
CREATE POLICY mcommit_service_all
  ON public.meeting_commitments FOR ALL
  USING (auth.role() = 'service_role');
