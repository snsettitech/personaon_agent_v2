-- Phase 5 Persona Prompt Optimization
-- Stores optimization runs and variant artifacts for prompt rendering.

CREATE TABLE IF NOT EXISTS persona_prompt_optimization_runs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  base_persona_spec_version TEXT,
  dataset_version TEXT,
  run_mode TEXT NOT NULL CHECK (run_mode IN ('heuristic', 'openai')),
  status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
  candidate_count INTEGER NOT NULL DEFAULT 0 CHECK (candidate_count >= 0),
  best_variant_id TEXT,
  best_objective_score NUMERIC(8,6),
  summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by UUID REFERENCES users(id) ON DELETE SET NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS persona_prompt_variants (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  optimization_run_id UUID REFERENCES persona_prompt_optimization_runs(id) ON DELETE SET NULL,
  variant_id TEXT NOT NULL,
  render_options JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'archived')),
  source TEXT NOT NULL DEFAULT 'optimizer',
  objective_score NUMERIC(8,6),
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by UUID REFERENCES users(id) ON DELETE SET NULL,
  activated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_persona_prompt_optimization_runs_twin_created
  ON persona_prompt_optimization_runs(twin_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_persona_prompt_optimization_runs_status
  ON persona_prompt_optimization_runs(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_persona_prompt_variants_twin_status
  ON persona_prompt_variants(twin_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_persona_prompt_variants_variant
  ON persona_prompt_variants(twin_id, variant_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_persona_prompt_variants_active
  ON persona_prompt_variants(twin_id)
  WHERE status = 'active';

ALTER TABLE persona_prompt_optimization_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE persona_prompt_variants ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant Isolation: View Persona Prompt Optimization Runs" ON persona_prompt_optimization_runs;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Persona Prompt Optimization Runs" ON persona_prompt_optimization_runs;
DROP POLICY IF EXISTS "Tenant Isolation: View Persona Prompt Variants" ON persona_prompt_variants;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Persona Prompt Variants" ON persona_prompt_variants;

CREATE POLICY "Tenant Isolation: View Persona Prompt Optimization Runs" ON persona_prompt_optimization_runs
FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_prompt_optimization_runs.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Persona Prompt Optimization Runs" ON persona_prompt_optimization_runs
FOR ALL
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_prompt_optimization_runs.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_prompt_optimization_runs.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: View Persona Prompt Variants" ON persona_prompt_variants
FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_prompt_variants.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Persona Prompt Variants" ON persona_prompt_variants
FOR ALL
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_prompt_variants.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_prompt_variants.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);
