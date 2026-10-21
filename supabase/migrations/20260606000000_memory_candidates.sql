-- 20260606000000_memory_candidates.sql
-- Memory candidates extracted from meetings for user review (approve/dismiss).
-- Approved candidates surface in Person Detail "Memory mentioning" section.

CREATE TABLE IF NOT EXISTS public.memory_candidates (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL,
  twin_id       uuid NOT NULL,
  meeting_id    uuid REFERENCES public.meetings(id) ON DELETE SET NULL,
  contact_id    uuid REFERENCES public.contacts(id) ON DELETE SET NULL,
  kind          text NOT NULL CHECK (kind IN ('fact','preference','context')),
  subject       text NOT NULL,
  predicate     text NOT NULL,
  text          text NOT NULL,
  confidence    real NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
  status        text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','approved','dismissed','superseded')),
  approved_at   timestamptz,
  dismissed_at  timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mcand_tenant       ON public.memory_candidates(tenant_id);
CREATE INDEX IF NOT EXISTS idx_mcand_twin         ON public.memory_candidates(twin_id);
CREATE INDEX IF NOT EXISTS idx_mcand_twin_status  ON public.memory_candidates(twin_id, status);
CREATE INDEX IF NOT EXISTS idx_mcand_meeting      ON public.memory_candidates(meeting_id);
CREATE INDEX IF NOT EXISTS idx_mcand_contact      ON public.memory_candidates(contact_id);

ALTER TABLE public.memory_candidates ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS mcand_owner_read ON public.memory_candidates;
CREATE POLICY mcand_owner_read ON public.memory_candidates FOR SELECT
  USING ((SELECT auth.uid()) = tenant_id);

DROP POLICY IF EXISTS mcand_owner_update ON public.memory_candidates;
CREATE POLICY mcand_owner_update ON public.memory_candidates FOR UPDATE
  USING ((SELECT auth.uid()) = tenant_id);

DROP POLICY IF EXISTS mcand_service_all ON public.memory_candidates;
CREATE POLICY mcand_service_all ON public.memory_candidates FOR ALL
  USING (auth.role() = 'service_role');


-- Audit log of approve/dismiss decisions
CREATE TABLE IF NOT EXISTS public.memory_candidate_decisions (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL,
  candidate_id  uuid NOT NULL REFERENCES public.memory_candidates(id) ON DELETE CASCADE,
  decision      text NOT NULL CHECK (decision IN ('approved','dismissed','edited')),
  notes         text,
  decided_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mdec_tenant     ON public.memory_candidate_decisions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_mdec_candidate  ON public.memory_candidate_decisions(candidate_id);

ALTER TABLE public.memory_candidate_decisions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS mdec_owner_read ON public.memory_candidate_decisions;
CREATE POLICY mdec_owner_read ON public.memory_candidate_decisions FOR SELECT
  USING ((SELECT auth.uid()) = tenant_id);

-- v2 amendment: INSERT RLS so authenticated owners can write decisions
DROP POLICY IF EXISTS mdec_owner_insert ON public.memory_candidate_decisions;
CREATE POLICY mdec_owner_insert ON public.memory_candidate_decisions FOR INSERT
  WITH CHECK ((SELECT auth.uid()) = tenant_id);

DROP POLICY IF EXISTS mdec_service_all ON public.memory_candidate_decisions;
CREATE POLICY mdec_service_all ON public.memory_candidate_decisions FOR ALL
  USING (auth.role() = 'service_role');
