-- Production runtime governance for Twin workflow routing + auditability
-- Adds:
-- 1) conversation_routing_decisions
-- 2) conversation_response_audits
-- 3) owner_review_queue
-- 4) learning_inputs

CREATE TABLE IF NOT EXISTS conversation_routing_decisions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
  message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
  interaction_context TEXT,
  router_mode TEXT,
  intent TEXT NOT NULL,
  confidence NUMERIC(6,4) NOT NULL DEFAULT 0.0,
  required_inputs_missing JSONB NOT NULL DEFAULT '[]'::jsonb,
  chosen_workflow TEXT NOT NULL,
  output_schema TEXT NOT NULL,
  action TEXT NOT NULL DEFAULT 'answer'
    CHECK (action IN ('answer', 'clarify', 'refuse', 'escalate')),
  clarifying_questions JSONB NOT NULL DEFAULT '[]'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversation_response_audits (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
  assistant_message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
  routing_decision_id UUID REFERENCES conversation_routing_decisions(id) ON DELETE SET NULL,
  spec_version TEXT,
  prompt_variant TEXT,
  intent_label TEXT,
  workflow_intent TEXT,
  response_action TEXT NOT NULL DEFAULT 'answer'
    CHECK (response_action IN ('answer', 'clarify', 'refuse', 'escalate')),
  confidence_score NUMERIC(6,4),
  citations JSONB NOT NULL DEFAULT '[]'::jsonb,
  sources_used JSONB NOT NULL DEFAULT '[]'::jsonb,
  refusal_reason TEXT,
  escalation_reason TEXT,
  retrieval_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  artifacts_used JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS owner_review_queue (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
  message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
  routing_decision_id UUID REFERENCES conversation_routing_decisions(id) ON DELETE SET NULL,
  reason TEXT NOT NULL,
  priority TEXT NOT NULL DEFAULT 'medium'
    CHECK (priority IN ('low', 'medium', 'high')),
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'resolved', 'dismissed')),
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at TIMESTAMPTZ,
  resolved_by UUID REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS learning_inputs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  created_by UUID REFERENCES users(id) ON DELETE SET NULL,
  base_persona_spec_version TEXT,
  input_type TEXT NOT NULL CHECK (
    input_type IN (
      'add_faq_answer',
      'add_adjust_rubric_rule',
      'add_workflow_step_template',
      'add_guardrail_refusal_rule',
      'add_style_preference'
    )
  ),
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'applied', 'rejected')),
  applied_persona_spec_version TEXT,
  review_note TEXT,
  source_conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
  source_message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  applied_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_crd_twin_created
  ON conversation_routing_decisions(twin_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_crd_action_conf
  ON conversation_routing_decisions(action, confidence, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cra_twin_created
  ON conversation_response_audits(twin_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_review_queue_twin_status
  ON owner_review_queue(twin_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_learning_inputs_twin_status
  ON learning_inputs(twin_id, status, created_at DESC);

ALTER TABLE conversation_routing_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_response_audits ENABLE ROW LEVEL SECURITY;
ALTER TABLE owner_review_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE learning_inputs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant Isolation: View Routing Decisions" ON conversation_routing_decisions;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Routing Decisions" ON conversation_routing_decisions;
DROP POLICY IF EXISTS "Tenant Isolation: View Response Audits" ON conversation_response_audits;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Response Audits" ON conversation_response_audits;
DROP POLICY IF EXISTS "Tenant Isolation: View Owner Review Queue" ON owner_review_queue;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Owner Review Queue" ON owner_review_queue;
DROP POLICY IF EXISTS "Tenant Isolation: View Learning Inputs" ON learning_inputs;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Learning Inputs" ON learning_inputs;

CREATE POLICY "Tenant Isolation: View Routing Decisions" ON conversation_routing_decisions
FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = conversation_routing_decisions.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Routing Decisions" ON conversation_routing_decisions
FOR ALL
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = conversation_routing_decisions.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = conversation_routing_decisions.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: View Response Audits" ON conversation_response_audits
FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = conversation_response_audits.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Response Audits" ON conversation_response_audits
FOR ALL
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = conversation_response_audits.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = conversation_response_audits.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: View Owner Review Queue" ON owner_review_queue
FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = owner_review_queue.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Owner Review Queue" ON owner_review_queue
FOR ALL
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = owner_review_queue.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = owner_review_queue.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: View Learning Inputs" ON learning_inputs
FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = learning_inputs.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Learning Inputs" ON learning_inputs
FOR ALL
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = learning_inputs.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = learning_inputs.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);
