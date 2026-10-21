-- Persona Specs V1
-- Versioned persona artifact storage for user-trained twin behavior.

CREATE TABLE IF NOT EXISTS persona_specs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  version TEXT NOT NULL CHECK (version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'archived')),
  spec JSONB NOT NULL,
  source TEXT NOT NULL DEFAULT 'manual',
  notes TEXT,
  created_by UUID REFERENCES users(id) ON DELETE SET NULL,
  published_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (twin_id, version)
);

CREATE INDEX IF NOT EXISTS idx_persona_specs_twin_status
  ON persona_specs(twin_id, status);
CREATE INDEX IF NOT EXISTS idx_persona_specs_created_at
  ON persona_specs(created_at DESC);

ALTER TABLE persona_specs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant Isolation: View Persona Specs" ON persona_specs;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Persona Specs" ON persona_specs;

CREATE POLICY "Tenant Isolation: View Persona Specs" ON persona_specs
FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_specs.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Persona Specs" ON persona_specs
FOR ALL
USING (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_specs.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1 FROM twins
    WHERE twins.id = persona_specs.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);
