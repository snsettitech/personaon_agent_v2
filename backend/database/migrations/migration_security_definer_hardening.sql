-- Migration: SECURITY DEFINER Hardening (P0-C)
-- Purpose: Harden all SECURITY DEFINER functions to prevent object shadowing attacks
-- This migration adds SET search_path = '' and fully qualifies all table references

-- Drop function signatures that may have drifted in return type.
DROP FUNCTION IF EXISTS check_twin_tenant_access(UUID, UUID);
DROP FUNCTION IF EXISTS get_twin_system(UUID);
DROP FUNCTION IF EXISTS get_nodes_system(UUID, INT);
DROP FUNCTION IF EXISTS get_edges_system(UUID, INT);
DROP FUNCTION IF EXISTS create_node_system(UUID, TEXT, TEXT, TEXT, JSONB);
DROP FUNCTION IF EXISTS create_edge_system(UUID, UUID, UUID, TEXT, TEXT, JSONB);

-- ============================================================================
-- Phase 3.5 Gate 3 Functions (migration_phase3_5_gate3_fix_rls.sql)
-- ============================================================================

-- 1. Check Twin Access (for tenant_guard.py)
CREATE OR REPLACE FUNCTION check_twin_tenant_access(t_id UUID, req_tenant_id UUID)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
  RETURN EXISTS (
    SELECT 1 FROM public.twins 
    WHERE id = t_id 
    AND tenant_id = req_tenant_id
  );
END;
$$;

-- 2. Get Twin System (for Config and General Fetch)
CREATE OR REPLACE FUNCTION get_twin_system(t_id UUID)
RETURNS SETOF public.twins
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
  RETURN QUERY SELECT * FROM public.twins WHERE id = t_id;
END;
$$;

-- 3. Get Nodes System
CREATE OR REPLACE FUNCTION get_nodes_system(t_id UUID, limit_val INT)
RETURNS SETOF public.nodes
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
  RETURN QUERY SELECT * FROM public.nodes WHERE twin_id = t_id LIMIT limit_val;
END;
$$;

-- 4. Get Edges System
CREATE OR REPLACE FUNCTION get_edges_system(t_id UUID, limit_val INT)
RETURNS SETOF public.edges
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
  RETURN QUERY SELECT * FROM public.edges WHERE twin_id = t_id LIMIT limit_val;
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
RETURNS SETOF public.nodes
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
  RETURN QUERY INSERT INTO public.nodes (twin_id, name, type, description, properties)
  VALUES (t_id, n_name, n_type, n_desc, n_props)
  ON CONFLICT (twin_id, name, type) DO UPDATE
  SET description = EXCLUDED.description,
      properties = public.nodes.properties || EXCLUDED.properties
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
RETURNS SETOF public.edges
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
  RETURN QUERY INSERT INTO public.edges (twin_id, from_node_id, to_node_id, type, description, properties)
  VALUES (t_id, from_id, to_id, e_type, e_desc, e_props)
  RETURNING *;
END;
$$;

-- ============================================================================
-- Memory Events Functions (migration_memory_events.sql)
-- ============================================================================

-- 4. System RPC for creating events (bypasses RLS for backend use)
CREATE OR REPLACE FUNCTION create_memory_event_system(
  p_tenant_id UUID,
  p_twin_id UUID,
  p_event_type TEXT,
  p_payload JSONB,
  p_status TEXT DEFAULT 'applied',
  p_source_type TEXT DEFAULT NULL,
  p_source_id TEXT DEFAULT NULL
)
RETURNS SETOF public.memory_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
  RETURN QUERY
  INSERT INTO public.memory_events (tenant_id, twin_id, event_type, payload, status, source_type, source_id)
  VALUES (p_tenant_id, p_twin_id, p_event_type, p_payload, p_status, p_source_type, p_source_id)
  RETURNING *;
END;
$$;

-- 5. System RPC for updating event payload
CREATE OR REPLACE FUNCTION update_memory_event_system(
  p_event_id UUID,
  p_payload JSONB
)
RETURNS SETOF public.memory_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
  RETURN QUERY
  UPDATE public.memory_events
  SET payload = public.memory_events.payload || p_payload
  WHERE id = p_event_id
  RETURNING *;
END;
$$;

-- 6. System RPC for getting events by twin (for TIL feed)
CREATE OR REPLACE FUNCTION get_memory_events_system(
  p_twin_id UUID,
  p_limit INT DEFAULT 50,
  p_event_type TEXT DEFAULT NULL
)
RETURNS SETOF public.memory_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
  RETURN QUERY
  SELECT * FROM public.memory_events
  WHERE twin_id = p_twin_id
    AND (p_event_type IS NULL OR event_type = p_event_type)
  ORDER BY created_at DESC
  LIMIT p_limit;
END;
$$;

-- ============================================================================
-- Interview Sessions Functions (migration_interview_sessions.sql)
-- ============================================================================

-- System RPC: Create or get session (bypasses RLS for service operations)
CREATE OR REPLACE FUNCTION get_or_create_interview_session(
    t_id UUID,
    conv_id UUID DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    session_record public.interview_sessions%ROWTYPE;
BEGIN
    -- First, check if there's a completed session from the last 24 hours
    -- Return it so the interview can continue conversationally
    SELECT * INTO session_record
    FROM public.interview_sessions
    WHERE twin_id = t_id
      AND (conv_id IS NULL OR conversation_id = conv_id)
    ORDER BY 
        CASE WHEN stage = 'complete' THEN 0 ELSE 1 END,  -- Prefer complete sessions
        created_at DESC
    LIMIT 1;
    
    -- If found any session (complete or not), return it
    IF FOUND THEN
        RETURN to_jsonb(session_record);
    END IF;
    
    -- If no session exists at all, create a new one
    INSERT INTO public.interview_sessions (twin_id, conversation_id, stage)
    VALUES (t_id, conv_id, 'opening')
    RETURNING * INTO session_record;
    
    RETURN to_jsonb(session_record);
END;
$$;

-- System RPC: Update session state
CREATE OR REPLACE FUNCTION update_interview_session(
    session_id UUID,
    new_stage TEXT DEFAULT NULL,
    new_intent_confirmed BOOLEAN DEFAULT NULL,
    new_intent_summary TEXT DEFAULT NULL,
    new_blueprint JSONB DEFAULT NULL,
    add_template_id TEXT DEFAULT NULL,
    increment_turn BOOLEAN DEFAULT FALSE,
    new_slots_filled INTEGER DEFAULT NULL,
    new_total_slots INTEGER DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    session_record public.interview_sessions%ROWTYPE;
BEGIN
    UPDATE public.interview_sessions
    SET
        stage = COALESCE(new_stage, stage),
        intent_confirmed = COALESCE(new_intent_confirmed, intent_confirmed),
        intent_summary = COALESCE(new_intent_summary, intent_summary),
        blueprint_json = COALESCE(new_blueprint, blueprint_json),
        asked_template_ids = CASE 
            WHEN add_template_id IS NOT NULL 
            THEN array_append(asked_template_ids, add_template_id)
            ELSE asked_template_ids
        END,
        turn_count = CASE WHEN increment_turn THEN turn_count + 1 ELSE turn_count END,
        slots_filled = COALESCE(new_slots_filled, slots_filled),
        total_required_slots = COALESCE(new_total_slots, total_required_slots),
        updated_at = NOW(),
        completed_at = CASE WHEN new_stage = 'complete' THEN NOW() ELSE completed_at END
    WHERE id = session_id
    RETURNING * INTO session_record;
    
    RETURN to_jsonb(session_record);
END;
$$;

-- ============================================================================
-- Profile Versions Functions (migration_gate5_versioning.sql)
-- ============================================================================

-- System RPC to bypass RLS for backend operations
CREATE OR REPLACE FUNCTION get_profile_versions_system(t_id UUID, limit_val INTEGER DEFAULT 10)
RETURNS SETOF public.profile_versions
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT * FROM public.profile_versions 
    WHERE twin_id = t_id 
    ORDER BY version DESC 
    LIMIT limit_val;
$$;

-- System RPC to get latest version number
CREATE OR REPLACE FUNCTION get_latest_version_system(t_id UUID)
RETURNS INTEGER
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT COALESCE(MAX(version), 0) FROM public.profile_versions WHERE twin_id = t_id;
$$;

-- System RPC to insert new version (bypasses RLS)
CREATE OR REPLACE FUNCTION insert_profile_version_system(
    t_id UUID,
    ver INTEGER,
    snapshot JSONB,
    diff JSONB,
    n_count INTEGER,
    e_count INTEGER,
    approver UUID DEFAULT NULL,
    approval_notes TEXT DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    new_id UUID;
BEGIN
    INSERT INTO public.profile_versions (twin_id, version, snapshot_json, diff_json, node_count, edge_count, approved_by, notes)
    VALUES (t_id, ver, snapshot, diff, n_count, e_count, approver, approval_notes)
    RETURNING id INTO new_id;
    RETURN new_id;
END;
$$;

-- System RPC to delete a version (bypasses RLS for admin)
CREATE OR REPLACE FUNCTION delete_profile_version_system(t_id UUID, ver INTEGER)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    DELETE FROM public.profile_versions WHERE twin_id = t_id AND version = ver;
    RETURN FOUND;
END;
$$;

-- System RPC to delete ALL versions for a twin (reset)
CREATE OR REPLACE FUNCTION delete_all_versions_system(t_id UUID)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM public.profile_versions WHERE twin_id = t_id;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$;

-- ============================================================================
-- Restrict Execution Permissions
-- Note: Only restrict if backend uses service_role pattern
-- These grants are idempotent (safe to run multiple times)
-- ============================================================================

-- Phase 3.5 Gate 3 functions
REVOKE EXECUTE ON FUNCTION check_twin_tenant_access(UUID, UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION check_twin_tenant_access(UUID, UUID) TO service_role, authenticated;

REVOKE EXECUTE ON FUNCTION get_twin_system(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_twin_system(UUID) TO service_role, authenticated;

REVOKE EXECUTE ON FUNCTION get_nodes_system(UUID, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_nodes_system(UUID, INT) TO service_role, authenticated;

REVOKE EXECUTE ON FUNCTION get_edges_system(UUID, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_edges_system(UUID, INT) TO service_role, authenticated;

REVOKE EXECUTE ON FUNCTION create_node_system(UUID, TEXT, TEXT, TEXT, JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION create_node_system(UUID, TEXT, TEXT, TEXT, JSONB) TO service_role, authenticated;

REVOKE EXECUTE ON FUNCTION create_edge_system(UUID, UUID, UUID, TEXT, TEXT, JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION create_edge_system(UUID, UUID, UUID, TEXT, TEXT, JSONB) TO service_role, authenticated;

-- Memory events functions (already have grants, but ensure consistency)
REVOKE EXECUTE ON FUNCTION create_memory_event_system(UUID, UUID, TEXT, JSONB, TEXT, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION create_memory_event_system(UUID, UUID, TEXT, JSONB, TEXT, TEXT, TEXT) TO service_role, authenticated;

REVOKE EXECUTE ON FUNCTION update_memory_event_system(UUID, JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION update_memory_event_system(UUID, JSONB) TO service_role, authenticated;

REVOKE EXECUTE ON FUNCTION get_memory_events_system(UUID, INT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_memory_events_system(UUID, INT, TEXT) TO service_role, authenticated;

-- Interview sessions functions (already have grants, but ensure consistency)
REVOKE EXECUTE ON FUNCTION get_or_create_interview_session(UUID, UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_or_create_interview_session(UUID, UUID) TO service_role, authenticated;

REVOKE EXECUTE ON FUNCTION update_interview_session(UUID, TEXT, BOOLEAN, TEXT, JSONB, TEXT, BOOLEAN, INTEGER, INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION update_interview_session(UUID, TEXT, BOOLEAN, TEXT, JSONB, TEXT, BOOLEAN, INTEGER, INTEGER) TO service_role, authenticated;

-- Profile versions functions
REVOKE EXECUTE ON FUNCTION get_profile_versions_system(UUID, INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_profile_versions_system(UUID, INTEGER) TO service_role, authenticated;

REVOKE EXECUTE ON FUNCTION get_latest_version_system(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_latest_version_system(UUID) TO service_role, authenticated;

REVOKE EXECUTE ON FUNCTION insert_profile_version_system(UUID, INTEGER, JSONB, JSONB, INTEGER, INTEGER, UUID, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION insert_profile_version_system(UUID, INTEGER, JSONB, JSONB, INTEGER, INTEGER, UUID, TEXT) TO service_role, authenticated;

REVOKE EXECUTE ON FUNCTION delete_profile_version_system(UUID, INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION delete_profile_version_system(UUID, INTEGER) TO service_role, authenticated;

REVOKE EXECUTE ON FUNCTION delete_all_versions_system(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION delete_all_versions_system(UUID) TO service_role, authenticated;

