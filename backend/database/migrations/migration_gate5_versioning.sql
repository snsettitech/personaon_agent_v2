-- Gate 5: Approval Versioning
-- Creates profile_versions table for immutable cognitive profile snapshots

-- Profile Versions table
CREATE TABLE IF NOT EXISTS profile_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    snapshot_json JSONB NOT NULL,
    diff_json JSONB,
    node_count INTEGER NOT NULL DEFAULT 0,
    edge_count INTEGER NOT NULL DEFAULT 0,
    approved_by UUID,
    approved_at TIMESTAMPTZ DEFAULT NOW(),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(twin_id, version)
);

-- RLS Policy
ALTER TABLE profile_versions ENABLE ROW LEVEL SECURITY;

-- Policy for viewing own versions
CREATE POLICY "Users can view own approvals" ON profile_versions
    FOR SELECT USING (
        twin_id IN (SELECT id FROM twins WHERE tenant_id = auth.uid())
    );

-- Policy for creating versions (owner only)
CREATE POLICY "Users can create own versions" ON profile_versions
    FOR INSERT WITH CHECK (
        twin_id IN (SELECT id FROM twins WHERE tenant_id = auth.uid())
    );

-- System RPC to bypass RLS for backend operations
CREATE OR REPLACE FUNCTION get_profile_versions_system(t_id UUID, limit_val INTEGER DEFAULT 10)
RETURNS SETOF profile_versions
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT * FROM profile_versions 
    WHERE twin_id = t_id 
    ORDER BY version DESC 
    LIMIT limit_val;
$$;

-- System RPC to get latest version number
CREATE OR REPLACE FUNCTION get_latest_version_system(t_id UUID)
RETURNS INTEGER
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT COALESCE(MAX(version), 0) FROM profile_versions WHERE twin_id = t_id;
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
SET search_path = public
AS $$
DECLARE
    new_id UUID;
BEGIN
    INSERT INTO profile_versions (twin_id, version, snapshot_json, diff_json, node_count, edge_count, approved_by, notes)
    VALUES (t_id, ver, snapshot, diff, n_count, e_count, approver, approval_notes)
    RETURNING id INTO new_id;
    RETURN new_id;
END;
$$;

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_profile_versions_twin_id ON profile_versions(twin_id);
CREATE INDEX IF NOT EXISTS idx_profile_versions_version ON profile_versions(twin_id, version DESC);

-- Delete policy (owner can delete their own versions)
CREATE POLICY "Users can delete own versions" ON profile_versions
    FOR DELETE USING (
        twin_id IN (SELECT id FROM twins WHERE tenant_id = auth.uid())
    );

-- System RPC to delete a version (bypasses RLS for admin)
CREATE OR REPLACE FUNCTION delete_profile_version_system(t_id UUID, ver INTEGER)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    DELETE FROM profile_versions WHERE twin_id = t_id AND version = ver;
    RETURN FOUND;
END;
$$;

-- System RPC to delete ALL versions for a twin (reset)
CREATE OR REPLACE FUNCTION delete_all_versions_system(t_id UUID)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM profile_versions WHERE twin_id = t_id;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$;
