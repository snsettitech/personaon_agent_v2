-- Phase 2 Decision Capture
-- Stores SJT, pairwise preferences, and introspection traces from owner training sessions.

CREATE TABLE IF NOT EXISTS persona_decision_traces (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  training_session_id UUID NOT NULL REFERENCES training_sessions(id) ON DELETE CASCADE,
  scenario_id TEXT,
  intent_label TEXT,
  prompt TEXT NOT NULL,
  options JSONB NOT NULL DEFAULT '[]'::jsonb,
  selected_option TEXT NOT NULL,
  rationale TEXT,
  thresholds JSONB NOT NULL DEFAULT '{}'::jsonb,
  clause_ids TEXT[] NOT NULL DEFAULT '{}'::text[],
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS persona_preferences (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  training_session_id UUID NOT NULL REFERENCES training_sessions(id) ON DELETE CASCADE,
  intent_label TEXT,
  prompt TEXT NOT NULL,
  candidate_a JSONB NOT NULL,
  candidate_b JSONB NOT NULL,
  preferred TEXT NOT NULL CHECK (preferred IN ('a', 'b', 'tie')),
  rationale TEXT,
  clause_ids TEXT[] NOT NULL DEFAULT '{}'::text[],
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS persona_introspection (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  training_session_id UUID NOT NULL REFERENCES training_sessions(id) ON DELETE CASCADE,
  intent_label TEXT,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  thresholds JSONB NOT NULL DEFAULT '{}'::jsonb,
  clause_ids TEXT[] NOT NULL DEFAULT '{}'::text[],
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS persona_modules (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  training_session_id UUID REFERENCES training_sessions(id) ON DELETE SET NULL,
  source_event_type TEXT NOT NULL CHECK (source_event_type IN ('sjt', 'pairwise', 'introspection')),
  source_event_id UUID NOT NULL,
  module_id TEXT NOT NULL,
  intent_label TEXT,
  module_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'archived')),
  confidence NUMERIC(5,4) DEFAULT 0.7000,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_persona_decision_traces_twin_created
  ON persona_decision_traces(twin_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_persona_preferences_twin_created
  ON persona_preferences(twin_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_persona_introspection_twin_created
  ON persona_introspection(twin_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_persona_modules_twin_status
  ON persona_modules(twin_id, status);
CREATE INDEX IF NOT EXISTS idx_persona_modules_source
  ON persona_modules(source_event_type, source_event_id);

ALTER TABLE persona_decision_traces ENABLE ROW LEVEL SECURITY;
ALTER TABLE persona_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE persona_introspection ENABLE ROW LEVEL SECURITY;
ALTER TABLE persona_modules ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant Isolation: View Persona Decision Traces" ON persona_decision_traces;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Persona Decision Traces" ON persona_decision_traces;
DROP POLICY IF EXISTS "Tenant Isolation: View Persona Preferences" ON persona_preferences;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Persona Preferences" ON persona_preferences;
DROP POLICY IF EXISTS "Tenant Isolation: View Persona Introspection" ON persona_introspection;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Persona Introspection" ON persona_introspection;
DROP POLICY IF EXISTS "Tenant Isolation: View Persona Modules" ON persona_modules;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Persona Modules" ON persona_modules;

CREATE POLICY "Tenant Isolation: View Persona Decision Traces" ON persona_decision_traces
FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_decision_traces.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Persona Decision Traces" ON persona_decision_traces
FOR ALL
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_decision_traces.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_decision_traces.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: View Persona Preferences" ON persona_preferences
FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_preferences.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Persona Preferences" ON persona_preferences
FOR ALL
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_preferences.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_preferences.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: View Persona Introspection" ON persona_introspection
FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_introspection.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Persona Introspection" ON persona_introspection
FOR ALL
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_introspection.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_introspection.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: View Persona Modules" ON persona_modules
FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_modules.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Persona Modules" ON persona_modules
FOR ALL
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_modules.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_modules.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);
