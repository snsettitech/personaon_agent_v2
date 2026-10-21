-- Migration: Add Tenant API Keys and Update Audit Logs
-- Description: Adds tenant_id scoping to audit logs and creates tenant_api_keys table

-- 1. Add tenant_id to audit_logs
ALTER TABLE audit_logs 
ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id);

CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_id ON audit_logs(tenant_id);

-- 2. Create tenant_api_keys table (replacing twin_api_keys concept)
CREATE TABLE IF NOT EXISTS tenant_api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    key_hash TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    name TEXT NOT NULL,
    allowed_domains TEXT[] DEFAULT '{}',
    allowed_twin_ids UUID[] DEFAULT '{}', -- Optional restriction to specific twins
    scopes TEXT[] DEFAULT '{}',           -- Optional scopes (read, write, etc.)
    is_active BOOLEAN DEFAULT TRUE,
    created_by UUID REFERENCES auth.users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tenant_api_keys_tenant_id ON tenant_api_keys(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_api_keys_key_hash ON tenant_api_keys(key_hash);

-- 3. Update governance_policies to have tenant_id
ALTER TABLE governance_policies
ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id);

CREATE INDEX IF NOT EXISTS idx_governance_policies_tenant_id ON governance_policies(tenant_id);

-- 4. Enable RLS on new table
ALTER TABLE tenant_api_keys ENABLE ROW LEVEL SECURITY;

-- Policy: Tenants can view their own keys
CREATE POLICY "Tenants can view own api keys" ON tenant_api_keys
    FOR SELECT USING (auth.uid() IN (
        SELECT id FROM users WHERE tenant_id = tenant_api_keys.tenant_id
    ));

-- Policy: Admins/Owners can manage keys
CREATE POLICY "Admins can manage api keys" ON tenant_api_keys
    FOR ALL USING (auth.uid() IN (
        SELECT id FROM users WHERE tenant_id = tenant_api_keys.tenant_id AND role IN ('owner', 'admin')
    ));
