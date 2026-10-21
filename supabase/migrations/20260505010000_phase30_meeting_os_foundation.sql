-- Phase 30.0: Meeting OS schema foundation.
-- Extends the existing Phase 25 meetings table. Do not recreate meetings.

-- Meetings: calendar sync, participation mode, capture method, privacy, and
-- coarse cost counters for later guardrails.
ALTER TABLE public.meetings
    ADD COLUMN IF NOT EXISTS mode TEXT,
    ADD COLUMN IF NOT EXISTS capture_method TEXT,
    ADD COLUMN IF NOT EXISTS provider TEXT,
    ADD COLUMN IF NOT EXISTS provider_event_id TEXT,
    ADD COLUMN IF NOT EXISTS provider_event_instance_id TEXT,
    ADD COLUMN IF NOT EXISTS provider_calendar_id TEXT,
    ADD COLUMN IF NOT EXISTS calendar_connector_id UUID,
    ADD COLUMN IF NOT EXISTS organizer_email TEXT,
    ADD COLUMN IF NOT EXISTS attendees_json JSONB,
    ADD COLUMN IF NOT EXISTS privacy_level TEXT,
    ADD COLUMN IF NOT EXISTS share_with_persona BOOLEAN,
    ADD COLUMN IF NOT EXISTS indexed_into_persona BOOLEAN,
    ADD COLUMN IF NOT EXISTS persona_indexed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS capture_seconds INTEGER,
    ADD COLUMN IF NOT EXISTS recall_billable_seconds INTEGER,
    ADD COLUMN IF NOT EXISTS model_input_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS model_output_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS tts_characters INTEGER,
    ADD COLUMN IF NOT EXISTS estimated_cost_cents NUMERIC(12,4),
    ADD COLUMN IF NOT EXISTS cost_guardrail_status TEXT,
    ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS sync_etag TEXT;

UPDATE public.meetings
SET
    mode = COALESCE(mode, 'off'),
    capture_method = COALESCE(capture_method, 'none'),
    attendees_json = COALESCE(attendees_json, '[]'::jsonb),
    privacy_level = COALESCE(privacy_level, 'private'),
    share_with_persona = COALESCE(share_with_persona, false),
    indexed_into_persona = COALESCE(indexed_into_persona, false),
    capture_seconds = COALESCE(capture_seconds, 0),
    recall_billable_seconds = COALESCE(recall_billable_seconds, 0),
    model_input_tokens = COALESCE(model_input_tokens, 0),
    model_output_tokens = COALESCE(model_output_tokens, 0),
    tts_characters = COALESCE(tts_characters, 0),
    estimated_cost_cents = COALESCE(estimated_cost_cents, 0),
    cost_guardrail_status = COALESCE(cost_guardrail_status, 'ok');

ALTER TABLE public.meetings
    ALTER COLUMN mode SET DEFAULT 'off',
    ALTER COLUMN mode SET NOT NULL,
    ALTER COLUMN capture_method SET DEFAULT 'none',
    ALTER COLUMN capture_method SET NOT NULL,
    ALTER COLUMN attendees_json SET DEFAULT '[]'::jsonb,
    ALTER COLUMN attendees_json SET NOT NULL,
    ALTER COLUMN privacy_level SET DEFAULT 'private',
    ALTER COLUMN privacy_level SET NOT NULL,
    ALTER COLUMN share_with_persona SET DEFAULT false,
    ALTER COLUMN share_with_persona SET NOT NULL,
    ALTER COLUMN indexed_into_persona SET DEFAULT false,
    ALTER COLUMN indexed_into_persona SET NOT NULL,
    ALTER COLUMN capture_seconds SET DEFAULT 0,
    ALTER COLUMN capture_seconds SET NOT NULL,
    ALTER COLUMN recall_billable_seconds SET DEFAULT 0,
    ALTER COLUMN recall_billable_seconds SET NOT NULL,
    ALTER COLUMN model_input_tokens SET DEFAULT 0,
    ALTER COLUMN model_input_tokens SET NOT NULL,
    ALTER COLUMN model_output_tokens SET DEFAULT 0,
    ALTER COLUMN model_output_tokens SET NOT NULL,
    ALTER COLUMN tts_characters SET DEFAULT 0,
    ALTER COLUMN tts_characters SET NOT NULL,
    ALTER COLUMN estimated_cost_cents SET DEFAULT 0,
    ALTER COLUMN estimated_cost_cents SET NOT NULL,
    ALTER COLUMN cost_guardrail_status SET DEFAULT 'ok',
    ALTER COLUMN cost_guardrail_status SET NOT NULL;

ALTER TABLE public.meetings
    DROP CONSTRAINT IF EXISTS meeting_os_meetings_mode_check;
ALTER TABLE public.meetings
    ADD CONSTRAINT meeting_os_meetings_mode_check
    CHECK (mode IN ('off', 'note_taker', 'augmented', 'delegated'));

ALTER TABLE public.meetings
    DROP CONSTRAINT IF EXISTS meeting_os_meetings_capture_method_check;
ALTER TABLE public.meetings
    ADD CONSTRAINT meeting_os_meetings_capture_method_check
    CHECK (capture_method IN ('none', 'google_meet_artifact', 'google_meet_media_api', 'recall_bot'));

ALTER TABLE public.meetings
    DROP CONSTRAINT IF EXISTS meeting_os_meetings_privacy_level_check;
ALTER TABLE public.meetings
    ADD CONSTRAINT meeting_os_meetings_privacy_level_check
    CHECK (privacy_level IN ('public', 'team', 'private'));

ALTER TABLE public.meetings
    DROP CONSTRAINT IF EXISTS meeting_os_meetings_attendees_json_check;
ALTER TABLE public.meetings
    ADD CONSTRAINT meeting_os_meetings_attendees_json_check
    CHECK (jsonb_typeof(attendees_json) = 'array');

ALTER TABLE public.meetings
    DROP CONSTRAINT IF EXISTS meeting_os_meetings_cost_nonnegative_check;
ALTER TABLE public.meetings
    ADD CONSTRAINT meeting_os_meetings_cost_nonnegative_check
    CHECK (
        capture_seconds >= 0
        AND recall_billable_seconds >= 0
        AND model_input_tokens >= 0
        AND model_output_tokens >= 0
        AND tts_characters >= 0
        AND estimated_cost_cents >= 0
    );

ALTER TABLE public.meetings
    DROP CONSTRAINT IF EXISTS meeting_os_meetings_cost_guardrail_status_check;
ALTER TABLE public.meetings
    ADD CONSTRAINT meeting_os_meetings_cost_guardrail_status_check
    CHECK (cost_guardrail_status IN ('ok', 'approaching_limit', 'limited', 'blocked'));

CREATE INDEX IF NOT EXISTS idx_meetings_twin_start_desc
    ON public.meetings(twin_id, meeting_start DESC);

CREATE INDEX IF NOT EXISTS idx_meetings_tenant_start_desc
    ON public.meetings(tenant_id, meeting_start DESC);

DROP INDEX IF EXISTS public.idx_meetings_provider_event;

CREATE UNIQUE INDEX IF NOT EXISTS idx_meetings_provider_event_unique
    ON public.meetings(
        twin_id,
        provider,
        COALESCE(provider_calendar_id, ''),
        provider_event_id,
        COALESCE(provider_event_instance_id, '')
    )
    WHERE provider IS NOT NULL AND provider_event_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_meetings_active_modes_start
    ON public.meetings(twin_id, meeting_start DESC)
    WHERE mode != 'off';

CREATE INDEX IF NOT EXISTS idx_meetings_persona_index_pending
    ON public.meetings(twin_id, meeting_start DESC)
    WHERE share_with_persona = true AND indexed_into_persona = false;

DROP POLICY IF EXISTS meetings_tenant_policy ON public.meetings;
CREATE POLICY meetings_tenant_policy ON public.meetings
    FOR ALL
    USING (
        tenant_id = (SELECT tenant_id FROM public.users WHERE id = auth.uid())
    )
    WITH CHECK (
        tenant_id = (SELECT tenant_id FROM public.users WHERE id = auth.uid())
    );

DROP POLICY IF EXISTS meeting_participants_tenant_policy ON public.meeting_participants;
CREATE POLICY meeting_participants_tenant_policy ON public.meeting_participants
    FOR ALL
    USING (
        EXISTS (
            SELECT 1
            FROM public.meetings m
            WHERE m.id = meeting_participants.meeting_id
                AND m.tenant_id = (SELECT tenant_id FROM public.users WHERE id = auth.uid())
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM public.meetings m
            WHERE m.id = meeting_participants.meeting_id
                AND m.tenant_id = (SELECT tenant_id FROM public.users WHERE id = auth.uid())
        )
    );

CREATE OR REPLACE FUNCTION public.validate_meeting_os_twin_scope()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.twins t
        WHERE t.id = NEW.twin_id
            AND t.tenant_id = NEW.tenant_id
    ) THEN
        RAISE EXCEPTION 'meeting OS row twin_id must match tenant_id';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TABLE IF NOT EXISTS public.contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    twin_id UUID NOT NULL REFERENCES public.twins(id) ON DELETE CASCADE,
    email TEXT,
    display_name TEXT,
    company TEXT,
    title TEXT,
    tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    notes TEXT,
    source TEXT NOT NULL DEFAULT 'meeting',
    privacy_level TEXT NOT NULL DEFAULT 'private',
    share_with_persona BOOLEAN NOT NULL DEFAULT false,
    first_seen_at TIMESTAMPTZ,
    last_meeting_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT contacts_source_check
        CHECK (source IN ('meeting', 'manual', 'widget_lead', 'import')),
    CONSTRAINT contacts_privacy_level_check
        CHECK (privacy_level IN ('public', 'team', 'private'))
);

CREATE INDEX IF NOT EXISTS idx_contacts_tenant_twin
    ON public.contacts(tenant_id, twin_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_twin_email_lower
    ON public.contacts(twin_id, lower(email))
    WHERE email IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_contacts_twin_last_meeting
    ON public.contacts(twin_id, last_meeting_at DESC)
    WHERE last_meeting_at IS NOT NULL;

DROP TRIGGER IF EXISTS validate_contacts_twin_scope ON public.contacts;
CREATE TRIGGER validate_contacts_twin_scope
    BEFORE INSERT OR UPDATE OF tenant_id, twin_id
    ON public.contacts
    FOR EACH ROW
    EXECUTE FUNCTION public.validate_meeting_os_twin_scope();

ALTER TABLE public.contacts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS contacts_owner_all ON public.contacts;
CREATE POLICY contacts_owner_all ON public.contacts
    FOR ALL
    USING (
        tenant_id = (SELECT tenant_id FROM public.users WHERE id = auth.uid())
    )
    WITH CHECK (
        tenant_id = (SELECT tenant_id FROM public.users WHERE id = auth.uid())
    );

DROP POLICY IF EXISTS contacts_service_all ON public.contacts;
CREATE POLICY contacts_service_all ON public.contacts
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

CREATE TABLE IF NOT EXISTS public.meeting_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    twin_id UUID NOT NULL REFERENCES public.twins(id) ON DELETE CASCADE,
    meeting_id UUID REFERENCES public.meetings(id) ON DELETE CASCADE,
    contact_id UUID REFERENCES public.contacts(id) ON DELETE SET NULL,
    assignee_email TEXT,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    source TEXT NOT NULL DEFAULT 'summary',
    approval_status TEXT NOT NULL DEFAULT 'not_required',
    due_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT meeting_tasks_status_check
        CHECK (status IN ('pending', 'completed', 'dismissed')),
    CONSTRAINT meeting_tasks_source_check
        CHECK (source IN ('summary', 'manual', 'delegated_review')),
    CONSTRAINT meeting_tasks_approval_status_check
        CHECK (approval_status IN ('not_required', 'needs_approval', 'approved', 'rejected'))
);

CREATE OR REPLACE FUNCTION public.validate_meeting_task_scope()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.meeting_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM public.meetings m
        WHERE m.id = NEW.meeting_id
            AND m.tenant_id = NEW.tenant_id
            AND m.twin_id = NEW.twin_id
    ) THEN
        RAISE EXCEPTION 'meeting_tasks meeting_id must match tenant_id and twin_id';
    END IF;

    IF NEW.contact_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM public.contacts c
        WHERE c.id = NEW.contact_id
            AND c.tenant_id = NEW.tenant_id
            AND c.twin_id = NEW.twin_id
    ) THEN
        RAISE EXCEPTION 'meeting_tasks contact_id must match tenant_id and twin_id';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS validate_meeting_tasks_scope ON public.meeting_tasks;
CREATE TRIGGER validate_meeting_tasks_scope
    BEFORE INSERT OR UPDATE OF tenant_id, twin_id, meeting_id, contact_id
    ON public.meeting_tasks
    FOR EACH ROW
    EXECUTE FUNCTION public.validate_meeting_task_scope();

DROP TRIGGER IF EXISTS validate_meeting_tasks_twin_scope ON public.meeting_tasks;
CREATE TRIGGER validate_meeting_tasks_twin_scope
    BEFORE INSERT OR UPDATE OF tenant_id, twin_id
    ON public.meeting_tasks
    FOR EACH ROW
    EXECUTE FUNCTION public.validate_meeting_os_twin_scope();

CREATE INDEX IF NOT EXISTS idx_meeting_tasks_tenant_status_due
    ON public.meeting_tasks(tenant_id, status, due_at);

CREATE INDEX IF NOT EXISTS idx_meeting_tasks_twin_created
    ON public.meeting_tasks(twin_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_meeting_tasks_meeting_id
    ON public.meeting_tasks(meeting_id);

CREATE INDEX IF NOT EXISTS idx_meeting_tasks_contact_id
    ON public.meeting_tasks(contact_id)
    WHERE contact_id IS NOT NULL;

ALTER TABLE public.meeting_tasks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS meeting_tasks_owner_all ON public.meeting_tasks;
CREATE POLICY meeting_tasks_owner_all ON public.meeting_tasks
    FOR ALL
    USING (
        tenant_id = (SELECT tenant_id FROM public.users WHERE id = auth.uid())
    )
    WITH CHECK (
        tenant_id = (SELECT tenant_id FROM public.users WHERE id = auth.uid())
    );

DROP POLICY IF EXISTS meeting_tasks_service_all ON public.meeting_tasks;
CREATE POLICY meeting_tasks_service_all ON public.meeting_tasks
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

CREATE TABLE IF NOT EXISTS public.meeting_costs_daily (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    twin_id UUID NOT NULL REFERENCES public.twins(id) ON DELETE CASCADE,
    usage_date DATE NOT NULL,
    mode TEXT NOT NULL DEFAULT 'note_taker',
    capture_method TEXT NOT NULL DEFAULT 'none',
    meetings_count INTEGER NOT NULL DEFAULT 0,
    capture_seconds INTEGER NOT NULL DEFAULT 0,
    recall_billable_seconds INTEGER NOT NULL DEFAULT 0,
    model_input_tokens INTEGER NOT NULL DEFAULT 0,
    model_output_tokens INTEGER NOT NULL DEFAULT 0,
    tts_characters INTEGER NOT NULL DEFAULT 0,
    estimated_cost_cents NUMERIC(12,4) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT meeting_costs_daily_mode_check
        CHECK (mode IN ('off', 'note_taker', 'augmented', 'delegated')),
    CONSTRAINT meeting_costs_daily_capture_method_check
        CHECK (capture_method IN ('none', 'google_meet_artifact', 'google_meet_media_api', 'recall_bot')),
    CONSTRAINT meeting_costs_daily_nonnegative_check
        CHECK (
            meetings_count >= 0
            AND capture_seconds >= 0
            AND recall_billable_seconds >= 0
            AND model_input_tokens >= 0
            AND model_output_tokens >= 0
            AND tts_characters >= 0
            AND estimated_cost_cents >= 0
        ),
    CONSTRAINT meeting_costs_daily_unique
        UNIQUE (twin_id, usage_date, mode, capture_method)
);

CREATE INDEX IF NOT EXISTS idx_meeting_costs_daily_tenant_date
    ON public.meeting_costs_daily(tenant_id, usage_date DESC);

CREATE INDEX IF NOT EXISTS idx_meeting_costs_daily_twin_date
    ON public.meeting_costs_daily(twin_id, usage_date DESC);

DROP TRIGGER IF EXISTS validate_meeting_costs_daily_twin_scope ON public.meeting_costs_daily;
CREATE TRIGGER validate_meeting_costs_daily_twin_scope
    BEFORE INSERT OR UPDATE OF tenant_id, twin_id
    ON public.meeting_costs_daily
    FOR EACH ROW
    EXECUTE FUNCTION public.validate_meeting_os_twin_scope();

ALTER TABLE public.meeting_costs_daily ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS meeting_costs_daily_owner_all ON public.meeting_costs_daily;
CREATE POLICY meeting_costs_daily_owner_all ON public.meeting_costs_daily
    FOR ALL
    USING (
        tenant_id = (SELECT tenant_id FROM public.users WHERE id = auth.uid())
    )
    WITH CHECK (
        tenant_id = (SELECT tenant_id FROM public.users WHERE id = auth.uid())
    );

DROP POLICY IF EXISTS meeting_costs_daily_service_all ON public.meeting_costs_daily;
CREATE POLICY meeting_costs_daily_service_all ON public.meeting_costs_daily
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
