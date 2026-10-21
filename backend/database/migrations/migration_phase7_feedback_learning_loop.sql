-- Phase 7 Feedback Learning Loop
-- Captures user feedback as training events and stores auditable feedback-learning runs.

CREATE TABLE IF NOT EXISTS persona_training_events (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
  message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
  trace_id TEXT,
  source TEXT NOT NULL CHECK (source IN ('langfuse_feedback', 'persona_audit', 'manual_import')),
  event_type TEXT NOT NULL CHECK (event_type IN ('thumb_up', 'thumb_down', 'rewrite', 'policy_violation', 'manual_label')),
  score NUMERIC(6,4),
  reason TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  processed BOOLEAN NOT NULL DEFAULT FALSE,
  processed_at TIMESTAMPTZ,
  created_by UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS persona_feedback_learning_runs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
  events_scanned INTEGER NOT NULL DEFAULT 0 CHECK (events_scanned >= 0),
  modules_updated INTEGER NOT NULL DEFAULT 0 CHECK (modules_updated >= 0),
  avg_confidence_delta NUMERIC(8,6),
  publish_candidate_version TEXT,
  publish_decision TEXT NOT NULL DEFAULT 'held'
    CHECK (publish_decision IN ('published', 'held', 'no_candidate')),
  gate_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by UUID REFERENCES users(id) ON DELETE SET NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_persona_training_events_twin_processed_created
  ON persona_training_events(twin_id, processed, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_persona_training_events_trace
  ON persona_training_events(trace_id);
CREATE INDEX IF NOT EXISTS idx_persona_feedback_learning_runs_twin_created
  ON persona_feedback_learning_runs(twin_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_persona_feedback_learning_runs_status
  ON persona_feedback_learning_runs(status, created_at DESC);

ALTER TABLE persona_training_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE persona_feedback_learning_runs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant Isolation: View Persona Training Events" ON persona_training_events;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Persona Training Events" ON persona_training_events;
DROP POLICY IF EXISTS "Tenant Isolation: View Persona Feedback Learning Runs" ON persona_feedback_learning_runs;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Persona Feedback Learning Runs" ON persona_feedback_learning_runs;

CREATE POLICY "Tenant Isolation: View Persona Training Events" ON persona_training_events
FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_training_events.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Persona Training Events" ON persona_training_events
FOR ALL
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_training_events.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_training_events.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: View Persona Feedback Learning Runs" ON persona_feedback_learning_runs
FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_feedback_learning_runs.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Persona Feedback Learning Runs" ON persona_feedback_learning_runs
FOR ALL
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_feedback_learning_runs.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_feedback_learning_runs.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);
