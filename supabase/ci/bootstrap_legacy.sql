-- CI-ONLY legacy prerequisites. NEVER copy this into supabase/migrations/.
--
-- Objects that exist on staging and prod but were created outside the migration chain
-- (hand-run legacy files under backend/database/migrations/). migrations.yml copies this
-- file onto the runner as supabase/migrations/20260519000150_ci_bootstrap_legacy.sql so a
-- clean DB can apply the whole chain. Committing it with that low timestamp would break
-- `supabase db push` on staging/prod. Add more objects here as they surface.
-- See docs/runbooks/migrations.md § "Legacy prerequisites".

-- From backend/database/migrations/migration_phase8_actions_engine.sql lines 41-60.
-- Needed by 20260519000200_recall_calendar_link.sql (ALTER TABLE public.tool_connectors).
CREATE TABLE IF NOT EXISTS public.tool_connectors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES public.twins(id) ON DELETE CASCADE,
    connector_type VARCHAR(50) NOT NULL,
    -- Connector types: gmail, google_calendar, slack, notion, composio
    name VARCHAR(100) NOT NULL,
    -- User-friendly name for this connector instance
    config JSONB DEFAULT '{}',
    -- Non-sensitive configuration (scopes, settings)
    credentials_encrypted TEXT,
    -- Encrypted OAuth tokens or API keys (use pgcrypto or app-level encryption)
    is_active BOOLEAN DEFAULT true,
    last_used_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    -- Unique constraint: one connector type per twin per name
    CONSTRAINT unique_connector_per_twin UNIQUE (twin_id, connector_type, name)
);

CREATE INDEX IF NOT EXISTS idx_connectors_twin_id ON public.tool_connectors(twin_id);
CREATE INDEX IF NOT EXISTS idx_connectors_type ON public.tool_connectors(connector_type);
