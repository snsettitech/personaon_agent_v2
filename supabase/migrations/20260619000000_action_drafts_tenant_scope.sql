-- 20260619000000_action_drafts_tenant_scope.sql
-- Owner-scope the action_drafts table for the Home v1 "Respond" write-tool.
--
-- action_drafts predates the supabase/migrations history (it was created only in
-- legacy backend/database/migrations/migration_phase8_actions_engine.sql with RLS
-- USING(true) and no tenant_id). That legacy SQL reached prod but NOT staging, so
-- this migration must both CREATE the table where absent and UPGRADE it where
-- present. Idempotent across both (verified live 2026-06-20):
--   * staging (staging): action_drafts MISSING (action_triggers too)
--     -> CREATE it, with FK-free trigger_id/event_id (no action_triggers to FK).
--   * prod (prod): action_drafts EXISTS (phase8) without tenant_id,
--     with an open `drafts_all_access` policy and a stale users-join
--     `drafts_tenant_policy` -> ADD tenant_id, backfill, drop BOTH legacy policies,
--     install owner + service-role RLS.
-- Provenance is carried in context->>'source' ('automation' | 'chat'); there is
-- no dedicated source column. No functions are created, so the DROP-before-CREATE
-- migration lint does not apply.

-- 1. Create where absent (no-op on prod, which keeps its existing columns/FKs).
--    trigger_id/event_id are FK-free: action_triggers does not exist on every
--    environment, and chat-initiated drafts leave them NULL.
CREATE TABLE IF NOT EXISTS public.action_drafts (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL,
  twin_id         uuid NOT NULL REFERENCES public.twins(id) ON DELETE CASCADE,
  trigger_id      uuid,
  event_id        uuid,
  status          varchar(20) NOT NULL DEFAULT 'pending',
  proposed_action jsonb NOT NULL,
  context         jsonb NOT NULL DEFAULT '{}',
  approval_note   text,
  approved_by     uuid,
  expires_at      timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT draft_status_check CHECK (status IN
    ('pending', 'approved', 'rejected', 'expired', 'executed', 'responded'))
);

-- 2. Upgrade an existing (prod / phase8) table in place; no-ops on a fresh table.
ALTER TABLE public.action_drafts ADD COLUMN IF NOT EXISTS tenant_id uuid;

-- Backfill tenant_id from the owning twin. twin_id is NOT NULL with an
-- ON DELETE CASCADE FK, so there are no orphan rows; if a twin ever had a NULL
-- tenant_id the SET NOT NULL below fails loudly rather than corrupting data.
UPDATE public.action_drafts d
SET    tenant_id = t.tenant_id
FROM   public.twins t
WHERE  d.twin_id = t.id
  AND  d.tenant_id IS NULL;

ALTER TABLE public.action_drafts ALTER COLUMN tenant_id SET NOT NULL;

-- 3. Indexes (idx_adraft_* — distinct abbrev from the legacy idx_drafts_*).
CREATE INDEX IF NOT EXISTS idx_adraft_tenant         ON public.action_drafts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_adraft_tenant_pending ON public.action_drafts(tenant_id, status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_adraft_twin_status    ON public.action_drafts(twin_id, status);

-- 4. RLS: owners read/update their own rows; the service role does everything
--    (the backend's only write path). Drop the legacy open policy AND the stale
--    multi-tenant (twins JOIN users) policy that predate the single-tenant model.
ALTER TABLE public.action_drafts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS drafts_all_access    ON public.action_drafts;
DROP POLICY IF EXISTS drafts_tenant_policy ON public.action_drafts;

DROP POLICY IF EXISTS adraft_owner_read ON public.action_drafts;
CREATE POLICY adraft_owner_read ON public.action_drafts FOR SELECT
  USING ((SELECT auth.uid()) = tenant_id);

DROP POLICY IF EXISTS adraft_owner_update ON public.action_drafts;
CREATE POLICY adraft_owner_update ON public.action_drafts FOR UPDATE
  USING ((SELECT auth.uid()) = tenant_id);

DROP POLICY IF EXISTS adraft_service_all ON public.action_drafts;
CREATE POLICY adraft_service_all ON public.action_drafts FOR ALL
  USING (auth.role() = 'service_role');
