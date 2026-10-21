-- Phase 3.5 Gate 3: Graph Persistence
-- Tables for Cognitive Graph (Nodes and Edges)

-- 1. Nodes Table
CREATE TABLE IF NOT EXISTS nodes (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  type TEXT NOT NULL, -- 'Person', 'Company', 'Concept', 'Cluster'
  description TEXT,
  properties JSONB DEFAULT '{}'::jsonb,
  status TEXT DEFAULT 'active' CHECK (status IN ('active', 'archived', 'rejected')),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  -- Ensure unique entities within a twin
  UNIQUE (twin_id, name, type)
);

-- 2. Edges Table
CREATE TABLE IF NOT EXISTS edges (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  from_node_id UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  to_node_id UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  type TEXT NOT NULL, -- 'FOUNDED', 'INVESTED_IN', 'RELATED_TO'
  description TEXT,
  weight FLOAT DEFAULT 1.0,
  properties JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (twin_id, from_node_id, to_node_id, type)
);

-- 3. RLS Policies
ALTER TABLE nodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE edges ENABLE ROW LEVEL SECURITY;

-- Nodes Policies
CREATE POLICY "Tenant Isolation: View Nodes" ON nodes
FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM twins 
        WHERE twins.id = nodes.twin_id 
        AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    )
);

CREATE POLICY "Tenant Isolation: Modify Nodes" ON nodes
FOR ALL USING (
    EXISTS (
        SELECT 1 FROM twins 
        WHERE twins.id = nodes.twin_id 
        AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    )
);

-- Edges Policies
CREATE POLICY "Tenant Isolation: View Edges" ON edges
FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM twins 
        WHERE twins.id = edges.twin_id 
        AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    )
);

CREATE POLICY "Tenant Isolation: Modify Edges" ON edges
FOR ALL USING (
    EXISTS (
        SELECT 1 FROM twins 
        WHERE twins.id = edges.twin_id 
        AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    )
);

-- 4. Indexes for Performance
CREATE INDEX IF NOT EXISTS idx_nodes_twin_type ON nodes(twin_id, type);
CREATE INDEX IF NOT EXISTS idx_edges_twin_from ON edges(twin_id, from_node_id);
CREATE INDEX IF NOT EXISTS idx_edges_twin_to ON edges(twin_id, to_node_id);
