-- Admin Control Center: ops alert ingestion (GCP Cloud Monitoring -> admin ops page).
--
-- Platform-level infra table, intentionally NOT tenant-scoped: no single tenant
-- "owns" a GCP uptime-check failure or a billing-budget threshold breach --
-- these are operational signals about the whole platform. Follows the same
-- convention as public.public_rate_limits (20260530120000_public_rate_limits.sql):
-- no tenant_id column, RLS enabled with a service-role-only policy, admin reads
-- go through the service-role client (see routers/admin/_common.py::_supabase).
--
-- Rows are inserted by the webhook handler (backend/routers/admin/ops.py::
-- receive_ops_alert_webhook) authenticated via a shared secret, not by an
-- authenticated tenant -- there is no user session to scope this to.

CREATE TABLE IF NOT EXISTS public.ops_alerts (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    source       TEXT        NOT NULL,
    severity     TEXT        NOT NULL DEFAULT 'unknown',
    title        TEXT        NOT NULL,
    detail       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at  TIMESTAMPTZ
);

-- Source is constrained to the known alert origins wired up so far. Extend this
-- list (DROP-then-ADD, keep the full prior list) as new alert sources are added --
-- same convention as graph_outbox_operation_check
-- (20260701000000_graph_outbox_ops_lead_captured.sql).
ALTER TABLE public.ops_alerts DROP CONSTRAINT IF EXISTS ops_alerts_source_check;
ALTER TABLE public.ops_alerts ADD CONSTRAINT ops_alerts_source_check
    CHECK (source IN ('gcp_uptime', 'gcp_billing'));

CREATE INDEX IF NOT EXISTS idx_opsal_created  ON public.ops_alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_opsal_source   ON public.ops_alerts(source);
CREATE INDEX IF NOT EXISTS idx_opsal_unresolved ON public.ops_alerts(resolved_at) WHERE resolved_at IS NULL;

ALTER TABLE public.ops_alerts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS ops_alerts_service ON public.ops_alerts;
CREATE POLICY ops_alerts_service ON public.ops_alerts
    FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
