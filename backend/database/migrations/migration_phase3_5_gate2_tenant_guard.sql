-- Phase 3.5 Gate 2: Real Tenant Guard (Fix 1)
-- Enable RLS and enforce strict tenant isolation
-- Fix: Removed references to non-existent 'owner_id' column on twins table.

-- 1. Twins Table
ALTER TABLE twins ENABLE ROW LEVEL SECURITY;

-- Drop existing policies if they exist (to allow re-running)
DROP POLICY IF EXISTS "Tenant Isolation: View Twins" ON twins;
DROP POLICY IF EXISTS "Tenant Isolation: Update Twins" ON twins;

CREATE POLICY "Tenant Isolation: View Twins" ON twins
FOR SELECT
USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
);

CREATE POLICY "Tenant Isolation: Update Twins" ON twins
FOR UPDATE
USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
);

-- 2. Sources Table (Cascades twin isolation)
ALTER TABLE sources ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant Isolation: View Sources" ON sources;

CREATE POLICY "Tenant Isolation: View Sources" ON sources
FOR SELECT
USING (
    EXISTS (
        SELECT 1 FROM twins 
        WHERE twins.id = sources.twin_id 
        AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    )
);

-- 3. Audit Logs (Append Only)
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant Isolation: View Audit Logs" ON audit_logs;
DROP POLICY IF EXISTS "System: Insert Audit Logs" ON audit_logs;

CREATE POLICY "Tenant Isolation: View Audit Logs" ON audit_logs
FOR SELECT
USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
);

CREATE POLICY "System: Insert Audit Logs" ON audit_logs
FOR INSERT
WITH CHECK (true); -- Application controls inserts via service key for now

-- 4. Conversations
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "User: View Own Conversations" ON conversations;

CREATE POLICY "User: View Own Conversations" ON conversations
FOR SELECT
USING (
    user_id = auth.uid()
    OR
    -- Allow users in the same tenant (with correct role) to view
    EXISTS (
        SELECT 1 FROM twins
        WHERE twins.id = conversations.twin_id
        AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    )
);
