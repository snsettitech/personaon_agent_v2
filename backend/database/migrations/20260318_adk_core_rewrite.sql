-- ============================================================================
-- Fresh-Start ADK Core Rewrite
-- ============================================================================
-- Authoritative storage for:
-- - Research runs and artifacts
-- - Persona artifacts and quote packs
-- - Conversations, messages, and ADK session state
-- ============================================================================

CREATE TABLE IF NOT EXISTS adk_research_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID,
    twin_id UUID,
    subject_name TEXT NOT NULL,
    hints JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'queued',
    idempotency_key TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_adk_research_runs_tenant ON adk_research_runs (tenant_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_adk_research_runs_idempotency
ON adk_research_runs (tenant_id, idempotency_key)
WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS adk_research_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL UNIQUE REFERENCES adk_research_runs(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    twin_id UUID,
    artifact_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS adk_persona_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    artifact_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_adk_persona_artifacts_twin ON adk_persona_artifacts (tenant_id, twin_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_adk_persona_artifacts_active
ON adk_persona_artifacts (twin_id)
WHERE status = 'active';

CREATE TABLE IF NOT EXISTS adk_persona_quotes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    persona_artifact_id UUID NOT NULL REFERENCES adk_persona_artifacts(id) ON DELETE CASCADE,
    quote_text TEXT NOT NULL,
    source_id TEXT,
    context TEXT,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_adk_persona_quotes_twin ON adk_persona_quotes (tenant_id, twin_id, confidence DESC);

CREATE TABLE IF NOT EXISTS adk_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    user_id TEXT,
    surface TEXT NOT NULL,
    share_token TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_adk_conversations_twin ON adk_conversations (twin_id, created_at DESC);

CREATE TABLE IF NOT EXISTS adk_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES adk_conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_adk_messages_conversation ON adk_messages (conversation_id, created_at ASC);

CREATE TABLE IF NOT EXISTS adk_sessions (
    id UUID PRIMARY KEY,
    app_name TEXT NOT NULL,
    user_id TEXT NOT NULL,
    tenant_id UUID,
    twin_id UUID,
    session_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_adk_sessions_app_user ON adk_sessions (app_name, user_id, id);

ALTER TABLE IF EXISTS adk_research_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS adk_research_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS adk_persona_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS adk_persona_quotes ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS adk_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS adk_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS adk_sessions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant Isolation: View ADK Research Runs" ON adk_research_runs;
DROP POLICY IF EXISTS "Tenant Isolation: Modify ADK Research Runs" ON adk_research_runs;
DROP POLICY IF EXISTS "Tenant Isolation: View ADK Research Artifacts" ON adk_research_artifacts;
DROP POLICY IF EXISTS "Tenant Isolation: Modify ADK Research Artifacts" ON adk_research_artifacts;
DROP POLICY IF EXISTS "Tenant Isolation: View ADK Persona Artifacts" ON adk_persona_artifacts;
DROP POLICY IF EXISTS "Tenant Isolation: Modify ADK Persona Artifacts" ON adk_persona_artifacts;
DROP POLICY IF EXISTS "Tenant Isolation: View ADK Persona Quotes" ON adk_persona_quotes;
DROP POLICY IF EXISTS "Tenant Isolation: Modify ADK Persona Quotes" ON adk_persona_quotes;
DROP POLICY IF EXISTS "Tenant Isolation: View ADK Conversations" ON adk_conversations;
DROP POLICY IF EXISTS "Tenant Isolation: Modify ADK Conversations" ON adk_conversations;
DROP POLICY IF EXISTS "Tenant Isolation: View ADK Messages" ON adk_messages;
DROP POLICY IF EXISTS "Tenant Isolation: Modify ADK Messages" ON adk_messages;
DROP POLICY IF EXISTS "Tenant Isolation: View ADK Sessions" ON adk_sessions;
DROP POLICY IF EXISTS "Tenant Isolation: Modify ADK Sessions" ON adk_sessions;

CREATE POLICY "Tenant Isolation: View ADK Research Runs" ON adk_research_runs
FOR SELECT USING (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid);

CREATE POLICY "Tenant Isolation: Modify ADK Research Runs" ON adk_research_runs
FOR ALL
USING (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid)
WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid);

CREATE POLICY "Tenant Isolation: View ADK Research Artifacts" ON adk_research_artifacts
FOR SELECT USING (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid);

CREATE POLICY "Tenant Isolation: Modify ADK Research Artifacts" ON adk_research_artifacts
FOR ALL
USING (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid)
WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid);

CREATE POLICY "Tenant Isolation: View ADK Persona Artifacts" ON adk_persona_artifacts
FOR SELECT USING (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid);

CREATE POLICY "Tenant Isolation: Modify ADK Persona Artifacts" ON adk_persona_artifacts
FOR ALL
USING (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid)
WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid);

CREATE POLICY "Tenant Isolation: View ADK Persona Quotes" ON adk_persona_quotes
FOR SELECT USING (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid);

CREATE POLICY "Tenant Isolation: Modify ADK Persona Quotes" ON adk_persona_quotes
FOR ALL
USING (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid)
WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid);

CREATE POLICY "Tenant Isolation: View ADK Conversations" ON adk_conversations
FOR SELECT USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    OR tenant_id IS NULL
);

CREATE POLICY "Tenant Isolation: Modify ADK Conversations" ON adk_conversations
FOR ALL
USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    OR tenant_id IS NULL
)
WITH CHECK (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    OR tenant_id IS NULL
);

CREATE POLICY "Tenant Isolation: View ADK Messages" ON adk_messages
FOR SELECT USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    OR tenant_id IS NULL
);

CREATE POLICY "Tenant Isolation: Modify ADK Messages" ON adk_messages
FOR ALL
USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    OR tenant_id IS NULL
)
WITH CHECK (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    OR tenant_id IS NULL
);

CREATE POLICY "Tenant Isolation: View ADK Sessions" ON adk_sessions
FOR SELECT USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    OR tenant_id IS NULL
);

CREATE POLICY "Tenant Isolation: Modify ADK Sessions" ON adk_sessions
FOR ALL
USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    OR tenant_id IS NULL
)
WITH CHECK (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    OR tenant_id IS NULL
);
