-- Lifecycle education and activity emails.
-- Safe to run on existing databases.

-- Meeting notification guard now claims rows before sending, so "sending" is
-- a valid transient state. The non-partial unique index lets PostgREST upsert
-- infer the weekly digest conflict target while still allowing multiple NULL
-- week_of rows for meeting-specific notifications.
ALTER TABLE public.meeting_notifications
    DROP CONSTRAINT IF EXISTS meeting_notifications_status_check;

ALTER TABLE public.meeting_notifications
    ADD CONSTRAINT meeting_notifications_status_check
    CHECK (status IN ('sending', 'sent', 'skipped', 'failed'));

CREATE UNIQUE INDEX IF NOT EXISTS meeting_notifications_weekly_digest_conflict_idx
    ON public.meeting_notifications (twin_id, notification_type, week_of);

-- User-level email category preferences. Meeting notification settings remain
-- on twins.settings; this table covers lifecycle education/activity emails.
CREATE TABLE IF NOT EXISTS public.notification_preferences (
    user_id UUID PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    product_education_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    daily_activity_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    weekly_report_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    hot_lead_alerts_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    unsubscribe_token_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS notification_preferences_tenant_idx
    ON public.notification_preferences (tenant_id);

ALTER TABLE public.notification_preferences ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "notification_preferences_owner_all" ON public.notification_preferences;
CREATE POLICY "notification_preferences_owner_all" ON public.notification_preferences
    FOR ALL USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS "notification_preferences_service_all" ON public.notification_preferences;
CREATE POLICY "notification_preferences_service_all" ON public.notification_preferences
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

CREATE TABLE IF NOT EXISTS public.lifecycle_email_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    email_type TEXT NOT NULL,
    category TEXT NOT NULL CHECK (
        category IN ('product_education', 'daily_activity', 'weekly_report', 'hot_lead_alert')
    ),
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    period_key TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'sending'
        CHECK (status IN ('sending', 'sent', 'skipped', 'failed')),
    payload JSONB NOT NULL DEFAULT '{}',
    resend_message_id TEXT,
    error_message TEXT,
    skip_reason TEXT,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (email_type, scope_type, scope_id, period_key),
    UNIQUE (idempotency_key)
);

CREATE INDEX IF NOT EXISTS lifecycle_email_events_user_created_idx
    ON public.lifecycle_email_events (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS lifecycle_email_events_tenant_status_idx
    ON public.lifecycle_email_events (tenant_id, status, created_at DESC);

ALTER TABLE public.lifecycle_email_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "lifecycle_email_events_owner_select" ON public.lifecycle_email_events;
CREATE POLICY "lifecycle_email_events_owner_select" ON public.lifecycle_email_events
    FOR SELECT USING (user_id = auth.uid());

DROP POLICY IF EXISTS "lifecycle_email_events_service_all" ON public.lifecycle_email_events;
CREATE POLICY "lifecycle_email_events_service_all" ON public.lifecycle_email_events
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

CREATE TABLE IF NOT EXISTS public.email_suppressions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES public.users(id) ON DELETE SET NULL,
    email TEXT NOT NULL,
    reason TEXT NOT NULL,
    provider_event_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (email, reason)
);

CREATE INDEX IF NOT EXISTS email_suppressions_user_idx
    ON public.email_suppressions (user_id);

ALTER TABLE public.email_suppressions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "email_suppressions_owner_select" ON public.email_suppressions;
CREATE POLICY "email_suppressions_owner_select" ON public.email_suppressions
    FOR SELECT USING (user_id = auth.uid());

DROP POLICY IF EXISTS "email_suppressions_service_all" ON public.email_suppressions;
CREATE POLICY "email_suppressions_service_all" ON public.email_suppressions
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

CREATE TABLE IF NOT EXISTS public.resend_webhook_events (
    svix_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    resend_message_id TEXT,
    payload JSONB NOT NULL DEFAULT '{}',
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.resend_webhook_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "resend_webhook_events_service_all" ON public.resend_webhook_events;
CREATE POLICY "resend_webhook_events_service_all" ON public.resend_webhook_events
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- Extend graph_outbox_operation_check for lifecycle email delivery jobs.
ALTER TABLE public.graph_outbox DROP CONSTRAINT IF EXISTS graph_outbox_operation_check;

ALTER TABLE public.graph_outbox ADD CONSTRAINT graph_outbox_operation_check
CHECK (operation = ANY (ARRAY[
    'create_episode',
    'create_claims',
    'update_claim_status',
    'create_relationship',
    'delete_twin_graph',
    'extract_claims',
    'evaluate_contradictions',
    'refresh_snapshot',
    'persona_research',
    'firecrawl_extract',
    'enrich_from_web',
    'schedule_meeting_bot',
    'process_meeting_transcript',
    'generate_meeting_summary',
    'warm_meeting_cache',
    'index_meeting_transcript',
    'generate_meeting_briefing',
    'generate_meeting_followup',
    'generate_weekly_digest',
    'enrich_twin_responses',
    'prep_meeting_context',
    'stripe_meter_event',
    'send_lifecycle_email'
]::text[]));
