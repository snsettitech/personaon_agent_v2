-- Phase 3.5 Gate 3 Fix: RLS Bypass for Backend (Dev Mode Support)
-- Create SECURITY DEFINER functions to allow the Backend (Anon Key) to perform system lookups
-- forcing authorization to happen in the Application Layer (FastAPI Guard) rather than DB Layer (RLS)
-- when using Mock Tokens.

-- Drop old signatures first so return-type changes don't fail on reruns.
DROP FUNCTION IF EXISTS check_twin_tenant_access(UUID, UUID);
DROP FUNCTION IF EXISTS get_twin_system(UUID);
DROP FUNCTION IF EXISTS get_nodes_system(UUID, INT);
DROP FUNCTION IF EXISTS get_edges_system(UUID, INT);
DROP FUNCTION IF EXISTS create_node_system(UUID, TEXT, TEXT, TEXT, JSONB);
DROP FUNCTION IF EXISTS create_edge_system(UUID, UUID, UUID, TEXT, TEXT, JSONB);

-- 1. Check Twin Access (for tenant_guard.py)
CREATE OR REPLACE FUNCTION check_twin_tenant_access(t_id UUID, req_tenant_id UUID)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  RETURN EXISTS (
    SELECT 1 FROM twins 
    WHERE id = t_id 
    AND tenant_id = req_tenant_id
  );
END;
$$;

-- 2. Get Twin System (for Config and General Fetch)
CREATE OR REPLACE FUNCTION get_twin_system(t_id UUID)
RETURNS SETOF twins
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  RETURN QUERY SELECT * FROM twins WHERE id = t_id;
END;
$$;

-- 3. Get Nodes System
CREATE OR REPLACE FUNCTION get_nodes_system(t_id UUID, limit_val INT)
RETURNS SETOF nodes
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  RETURN QUERY SELECT * FROM nodes WHERE twin_id = t_id LIMIT limit_val;
END;
$$;

-- 4. Get Edges System
CREATE OR REPLACE FUNCTION get_edges_system(t_id UUID, limit_val INT)
RETURNS SETOF edges
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  RETURN QUERY SELECT * FROM edges WHERE twin_id = t_id LIMIT limit_val;
END;
$$;

-- 5. Create/Update Node System (Scribe)
CREATE OR REPLACE FUNCTION create_node_system(
  t_id UUID,
  n_name TEXT,
  n_type TEXT,
  n_desc TEXT,
  n_props JSONB
)
RETURNS SETOF nodes
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  RETURN QUERY INSERT INTO nodes (twin_id, name, type, description, properties)
  VALUES (t_id, n_name, n_type, n_desc, n_props)
  ON CONFLICT (twin_id, name, type) DO UPDATE
  SET description = EXCLUDED.description,
      properties = nodes.properties || EXCLUDED.properties
  RETURNING *;
END;
$$;

-- 6. Create Edge System (Scribe)
CREATE OR REPLACE FUNCTION create_edge_system(
  t_id UUID,
  from_id UUID,
  to_id UUID,
  e_type TEXT,
  e_desc TEXT,
  e_props JSONB
)
RETURNS SETOF edges
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  RETURN QUERY INSERT INTO edges (twin_id, from_node_id, to_node_id, type, description, properties)
  VALUES (t_id, from_id, to_id, e_type, e_desc, e_props)
  RETURNING *;
END;
$$;
