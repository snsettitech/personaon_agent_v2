-- Agentic notification flow registry and run ledger.

CREATE TABLE IF NOT EXISTS public.notification_flows (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid,
    key text NOT NULL UNIQUE,
    name text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('transactional', 'lifecycle', 'announcement')),
    trigger_type text NOT NULL CHECK (trigger_type IN ('event', 'cron', 'manual')),
    audience_spec jsonb NOT NULL DEFAULT '{}',
    email_type text NOT NULL,
    category text NOT NULL,
    context_overrides jsonb NOT NULL DEFAULT '{}',
    schedule_cron text,
    status text NOT NULL DEFAULT 'proposed'
        CHECK (status IN ('proposed', 'approved', 'active', 'paused', 'archived')),
    guardrails jsonb NOT NULL DEFAULT '{}',
    created_by text NOT NULL,
    approved_by text,
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_nflow_status
    ON public.notification_flows (status);

ALTER TABLE public.notification_flows ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "notification_flows_service_role_only" ON public.notification_flows;
CREATE POLICY "notification_flows_service_role_only" ON public.notification_flows
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

CREATE TABLE IF NOT EXISTS public.notification_flow_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid,
    flow_id uuid NOT NULL REFERENCES public.notification_flows(id),
    flow_run_key text NOT NULL UNIQUE,
    trigger_kind text NOT NULL CHECK (trigger_kind IN ('scheduled', 'manual', 'event', 'dry_run')),
    audience_count int NOT NULL DEFAULT 0,
    enqueued int NOT NULL DEFAULT 0,
    skipped int NOT NULL DEFAULT 0,
    failed int NOT NULL DEFAULT 0,
    open_count int,
    click_count int,
    conversion_count int,
    outcome_measured_at timestamptz,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    summary jsonb NOT NULL DEFAULT '{}',
    audience_snapshot_hash text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_nfrun_flow_id
    ON public.notification_flow_runs (flow_id);

CREATE INDEX IF NOT EXISTS idx_nfrun_tenant_created
    ON public.notification_flow_runs (tenant_id, created_at DESC);

ALTER TABLE public.notification_flow_runs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "notification_flow_runs_service_role_only" ON public.notification_flow_runs;
CREATE POLICY "notification_flow_runs_service_role_only" ON public.notification_flow_runs
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
