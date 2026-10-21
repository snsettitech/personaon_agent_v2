-- Event bus and learning store for the self-improving notification agent.

CREATE TABLE IF NOT EXISTS public.notification_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    event_type text NOT NULL,
    actor_id text,
    subject_id text NOT NULL,
    context_json jsonb NOT NULL DEFAULT '{}',
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'processed', 'failed')),
    error_message text,
    processed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notification_events_status_created
    ON public.notification_events (status, created_at);

CREATE INDEX IF NOT EXISTS idx_notification_events_type_created
    ON public.notification_events (event_type, created_at DESC);

ALTER TABLE public.notification_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "notification_events_service_role_all" ON public.notification_events;
CREATE POLICY "notification_events_service_role_all" ON public.notification_events
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

DROP POLICY IF EXISTS "notification_events_tenant_select" ON public.notification_events;
CREATE POLICY "notification_events_tenant_select" ON public.notification_events
    FOR SELECT USING ((SELECT auth.uid()) = tenant_id);

CREATE TABLE IF NOT EXISTS public.agent_memory (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid,
    agent_slug text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('learning', 'outcome', 'reflection')),
    content text NOT NULL,
    embedding vector(768),
    meta jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_memory_slug_kind_created
    ON public.agent_memory (agent_slug, kind, created_at DESC);

ALTER TABLE public.agent_memory ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "agent_memory_service_role_all" ON public.agent_memory;
CREATE POLICY "agent_memory_service_role_all" ON public.agent_memory
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
