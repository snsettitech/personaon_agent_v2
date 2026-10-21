-- Interaction Context + Training Sessions
-- Introduces explicit owner training windows and immutable context metadata.

CREATE TABLE IF NOT EXISTS training_sessions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'stopped', 'expired')),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ended_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_training_sessions_twin_owner_status
  ON training_sessions(twin_id, owner_id, status);
CREATE INDEX IF NOT EXISTS idx_training_sessions_started_at
  ON training_sessions(started_at DESC);

ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS interaction_context TEXT
    CHECK (interaction_context IN ('owner_training', 'owner_chat', 'public_share', 'public_widget'));
ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS origin_endpoint TEXT;
ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS share_link_id TEXT;
ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS training_session_id UUID REFERENCES training_sessions(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_conversations_interaction_context
  ON conversations(interaction_context);
CREATE INDEX IF NOT EXISTS idx_conversations_training_session
  ON conversations(training_session_id);

ALTER TABLE messages
  ADD COLUMN IF NOT EXISTS interaction_context TEXT
    CHECK (interaction_context IN ('owner_training', 'owner_chat', 'public_share', 'public_widget'));

CREATE INDEX IF NOT EXISTS idx_messages_interaction_context
  ON messages(interaction_context);

ALTER TABLE training_sessions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant Isolation: View Training Sessions" ON training_sessions;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Training Sessions" ON training_sessions;

CREATE POLICY "Tenant Isolation: View Training Sessions" ON training_sessions
FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = training_sessions.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Training Sessions" ON training_sessions
FOR ALL
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = training_sessions.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = training_sessions.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);
