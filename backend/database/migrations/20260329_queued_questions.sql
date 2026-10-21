-- Phase 19: Three-Bucket Agent Behavior — queued_questions table
-- Stores visitor questions the agent couldn't answer (Bucket 3 topic gaps)
-- for the twin owner to review and answer later.

CREATE TABLE IF NOT EXISTS queued_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    tenant_id UUID,
    question TEXT NOT NULL,
    topic TEXT NOT NULL,
    conversation_id UUID REFERENCES adk_conversations(id) ON DELETE SET NULL,
    visitor_user_id TEXT,
    ask_count INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'answered', 'dismissed')),
    owner_answer TEXT,
    answered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_queued_questions_twin_status
ON queued_questions (twin_id, status, ask_count DESC);

ALTER TABLE queued_questions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Tenant Isolation: View Queued Questions" ON queued_questions
FOR SELECT USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    OR tenant_id IS NULL
);

CREATE POLICY "Tenant Isolation: Modify Queued Questions" ON queued_questions
FOR ALL
USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    OR tenant_id IS NULL
)
WITH CHECK (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    OR tenant_id IS NULL
);

-- Service role bypass for backend inserts (queue_question tool runs as service role)
CREATE POLICY "Service Role Bypass" ON queued_questions
FOR ALL
USING (auth.role() = 'service_role')
WITH CHECK (auth.role() = 'service_role');
