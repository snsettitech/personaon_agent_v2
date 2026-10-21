-- Admin Control Center: append-only audit log.
--
-- One row per mutating admin action (plan/flag change, role change, suspend,
-- delete, takedown, …). Written best-effort by modules/admin_audit.py.
-- Reads go through the service-role client (bypasses RLS); the owner-select
-- policy is a safety net for any authenticated read of one's own actions.

CREATE TABLE IF NOT EXISTS public.admin_audit_log (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID        NOT NULL,
    actor_id     UUID,
    actor_email  TEXT,
    action       TEXT        NOT NULL,
    target_type  TEXT,
    target_id    TEXT,
    target_email TEXT,
    before       JSONB,
    after        JSONB,
    details      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_aaud_created ON public.admin_audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_aaud_actor   ON public.admin_audit_log(actor_id);
CREATE INDEX IF NOT EXISTS idx_aaud_action  ON public.admin_audit_log(action);
CREATE INDEX IF NOT EXISTS idx_aaud_target  ON public.admin_audit_log(target_type, target_id);

ALTER TABLE public.admin_audit_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "admin_audit_owner_select" ON public.admin_audit_log;
CREATE POLICY "admin_audit_owner_select" ON public.admin_audit_log
    FOR SELECT USING ((SELECT auth.uid()) = tenant_id);

DROP POLICY IF EXISTS "admin_audit_service_all" ON public.admin_audit_log;
CREATE POLICY "admin_audit_service_all" ON public.admin_audit_log
    FOR ALL USING (auth.role() = 'service_role');
