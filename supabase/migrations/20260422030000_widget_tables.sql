-- Widget tables: twin_api_keys and widget_leads
-- Idempotent: safe to run on existing production DB.

-- ── twin_api_keys ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.twin_api_keys (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id     UUID        NOT NULL REFERENCES public.twins(id) ON DELETE CASCADE,
    group_id    UUID,
    key_hash    TEXT        NOT NULL,
    key_prefix  TEXT        NOT NULL,
    name        TEXT        NOT NULL DEFAULT 'Widget Key',
    allowed_domains TEXT[]  NOT NULL DEFAULT '{}',
    widget_config   JSONB   NOT NULL DEFAULT '{}',
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    expires_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS twin_api_keys_twin_id_idx
    ON public.twin_api_keys(twin_id);

CREATE INDEX IF NOT EXISTS twin_api_keys_prefix_active_idx
    ON public.twin_api_keys(key_prefix)
    WHERE is_active = TRUE;

ALTER TABLE public.twin_api_keys ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "twin_api_keys_owner_all" ON public.twin_api_keys;
CREATE POLICY "twin_api_keys_owner_all" ON public.twin_api_keys
    FOR ALL
    USING (
        twin_id IN (
            SELECT id FROM public.twins
            WHERE tenant_id = (
                SELECT tenant_id FROM public.users WHERE id = auth.uid()
            )
        )
    );

-- ── widget_leads ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.widget_leads (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id         UUID        NOT NULL REFERENCES public.twins(id) ON DELETE CASCADE,
    api_key_id      UUID        REFERENCES public.twin_api_keys(id) ON DELETE SET NULL,
    visitor_name    TEXT,
    visitor_email   TEXT,
    source_domain   TEXT,
    conversation_id TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS widget_leads_twin_id_created_idx
    ON public.widget_leads(twin_id, created_at DESC);

ALTER TABLE public.widget_leads ENABLE ROW LEVEL SECURITY;

-- Owners can SELECT their leads; widget backend uses service key for INSERT.
DROP POLICY IF EXISTS "widget_leads_owner_select" ON public.widget_leads;
CREATE POLICY "widget_leads_owner_select" ON public.widget_leads
    FOR SELECT
    USING (
        twin_id IN (
            SELECT id FROM public.twins
            WHERE tenant_id = (
                SELECT tenant_id FROM public.users WHERE id = auth.uid()
            )
        )
    );
