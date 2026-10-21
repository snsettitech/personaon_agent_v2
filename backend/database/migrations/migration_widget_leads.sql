-- Widget leads: captures visitor info from embedded chat widgets
-- Depends on: twin_api_keys table (from migration_phase7_omnichannel.sql)

CREATE TABLE IF NOT EXISTS widget_leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    api_key_id UUID REFERENCES twin_api_keys(id) ON DELETE SET NULL,
    visitor_name TEXT,
    visitor_email TEXT,
    conversation_id TEXT,
    source_domain TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_widget_leads_twin_id ON widget_leads(twin_id);
CREATE INDEX IF NOT EXISTS idx_widget_leads_api_key_id ON widget_leads(api_key_id);
CREATE INDEX IF NOT EXISTS idx_widget_leads_created_at ON widget_leads(twin_id, created_at DESC);

-- Add widget_config column to twin_api_keys if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'twin_api_keys' AND column_name = 'widget_config'
    ) THEN
        ALTER TABLE twin_api_keys ADD COLUMN widget_config JSONB DEFAULT '{}'::jsonb;
    END IF;
END $$;

-- Enable RLS
ALTER TABLE widget_leads ENABLE ROW LEVEL SECURITY;

-- Service role has full access (backend uses service key)
CREATE POLICY "service_role_all" ON widget_leads
    FOR ALL TO service_role USING (true) WITH CHECK (true);
