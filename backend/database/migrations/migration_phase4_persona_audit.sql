-- Phase 4 Persona Audit
-- Stores deterministic/judge/rewrite results for persona enforcement.

CREATE TABLE IF NOT EXISTS persona_judge_results (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
  interaction_context TEXT
    CHECK (interaction_context IN ('owner_training', 'owner_chat', 'public_share', 'public_widget')),
  intent_label TEXT NOT NULL,
  module_ids TEXT[] NOT NULL DEFAULT '{}'::text[],
  persona_spec_version TEXT,
  deterministic_gate_passed BOOLEAN NOT NULL DEFAULT TRUE,
  structure_policy_score NUMERIC(5,4) NOT NULL DEFAULT 1.0000,
  voice_score NUMERIC(5,4) NOT NULL DEFAULT 1.0000,
  draft_persona_score NUMERIC(5,4) NOT NULL DEFAULT 1.0000,
  final_persona_score NUMERIC(5,4) NOT NULL DEFAULT 1.0000,
  rewrite_applied BOOLEAN NOT NULL DEFAULT FALSE,
  structure_policy_passed BOOLEAN NOT NULL DEFAULT TRUE,
  voice_passed BOOLEAN NOT NULL DEFAULT TRUE,
  violated_clause_ids TEXT[] NOT NULL DEFAULT '{}'::text[],
  rewrite_reason_categories TEXT[] NOT NULL DEFAULT '{}'::text[],
  rewrite_directives TEXT[] NOT NULL DEFAULT '{}'::text[],
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_persona_judge_results_twin_created
  ON persona_judge_results(twin_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_persona_judge_results_twin_intent
  ON persona_judge_results(twin_id, intent_label, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_persona_judge_results_conversation
  ON persona_judge_results(conversation_id);

ALTER TABLE persona_judge_results ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant Isolation: View Persona Judge Results" ON persona_judge_results;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Persona Judge Results" ON persona_judge_results;

CREATE POLICY "Tenant Isolation: View Persona Judge Results" ON persona_judge_results
FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_judge_results.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Persona Judge Results" ON persona_judge_results
FOR ALL
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_judge_results.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_judge_results.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

