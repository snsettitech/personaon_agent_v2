-- Phase 11: Owner Memory + Clarification Threads
-- Adds structured Owner Memory storage and public clarification queue

-- 0. Extend memory_events event_type constraint (for audit trail)
ALTER TABLE memory_events
    DROP CONSTRAINT IF EXISTS memory_events_event_type_check;

ALTER TABLE memory_events
    ADD CONSTRAINT memory_events_event_type_check
    CHECK (event_type IN (
        'auto_extract',
        'content_extract',
        'manual_edit',
        'confirm',
        'delete',
        'owner_memory_write',
        'owner_memory_supersede',
        'owner_memory_retract',
        'owner_memory_pending'
    ));

-- 1. Owner Beliefs table (structured, auditable)
CREATE TABLE IF NOT EXISTS owner_beliefs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  topic_normalized TEXT NOT NULL,
  memory_type TEXT NOT NULL CHECK (memory_type IN ('belief', 'preference', 'stance', 'lens', 'tone_rule')),
  value TEXT NOT NULL,
  stance TEXT, -- positive | negative | neutral | mixed | unknown
  intensity SMALLINT, -- 1-10 (optional)
  confidence FLOAT DEFAULT 0.5,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded', 'retracted')),
  embedding JSONB, -- Optional embedding vector (JSON array)
  provenance JSONB DEFAULT '{}'::jsonb, -- {conversation_id, message_id, owner_id, source}
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  superseded_by UUID REFERENCES owner_beliefs(id)
);

CREATE INDEX IF NOT EXISTS idx_owner_beliefs_twin_status ON owner_beliefs(twin_id, status);
CREATE INDEX IF NOT EXISTS idx_owner_beliefs_twin_topic ON owner_beliefs(twin_id, topic_normalized);
CREATE INDEX IF NOT EXISTS idx_owner_beliefs_twin_type ON owner_beliefs(twin_id, memory_type);
CREATE INDEX IF NOT EXISTS idx_owner_beliefs_created ON owner_beliefs(twin_id, created_at DESC);

-- 2. Clarification Threads table (pending owner confirmations)
CREATE TABLE IF NOT EXISTS clarification_threads (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
  source_message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
  mode TEXT NOT NULL DEFAULT 'owner' CHECK (mode IN ('owner', 'public')),
  status TEXT NOT NULL DEFAULT 'pending_owner' CHECK (status IN ('pending_owner', 'answered', 'expired')),
  original_query TEXT,
  question TEXT NOT NULL,
  options JSONB DEFAULT '[]'::jsonb,
  memory_write_proposal JSONB DEFAULT '{}'::jsonb,
  owner_memory_id UUID REFERENCES owner_beliefs(id),
  requested_by TEXT, -- 'owner' | 'public'
  created_by UUID, -- owner id if available
  answered_by UUID,
  answer_text TEXT,
  answered_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_clarification_threads_twin_status ON clarification_threads(twin_id, status);
CREATE INDEX IF NOT EXISTS idx_clarification_threads_twin_created ON clarification_threads(twin_id, created_at DESC);

-- 3. RLS policies (tenant isolation)
ALTER TABLE owner_beliefs ENABLE ROW LEVEL SECURITY;
ALTER TABLE clarification_threads ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant Isolation: View Owner Beliefs" ON owner_beliefs;
CREATE POLICY "Tenant Isolation: View Owner Beliefs" ON owner_beliefs
FOR SELECT USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = owner_beliefs.twin_id
    AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

DROP POLICY IF EXISTS "Tenant Isolation: Modify Owner Beliefs" ON owner_beliefs;
CREATE POLICY "Tenant Isolation: Modify Owner Beliefs" ON owner_beliefs
FOR ALL USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = owner_beliefs.twin_id
    AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

DROP POLICY IF EXISTS "Tenant Isolation: View Clarifications" ON clarification_threads;
CREATE POLICY "Tenant Isolation: View Clarifications" ON clarification_threads
FOR SELECT USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = clarification_threads.twin_id
    AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

DROP POLICY IF EXISTS "Tenant Isolation: Modify Clarifications" ON clarification_threads;
CREATE POLICY "Tenant Isolation: Modify Clarifications" ON clarification_threads
FOR ALL USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = clarification_threads.twin_id
    AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);
