-- Phase 9: Verification & Governance Migration
-- This migration creates tables for audit logging, governance policies, and twin verification

-- 1. Audit Logs Table
-- Immutable storage for critical system actions
CREATE TABLE IF NOT EXISTS audit_logs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  actor_id UUID REFERENCES users(id) ON DELETE SET NULL,
  event_type TEXT NOT NULL, -- e.g., 'AUTHENTICATION', 'CONFIGURATION_CHANGE', 'KNOWLEDGE_UPDATE', 'VERIFIED_QNA', 'ACTION_EXECUTION'
  action TEXT NOT NULL,     -- e.g., 'API_KEY_CREATED', 'SOURCE_DELETED', 'ANSWER_PUBLISHED'
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_twin ON audit_logs(twin_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_event ON audit_logs(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at);

-- 2. Governance Policies Table
-- Define safety rules and restrictions for twins
CREATE TABLE IF NOT EXISTS governance_policies (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  policy_type TEXT NOT NULL CHECK (policy_type IN ('refusal_rule', 'guardrail', 'tool_restriction')),
  name TEXT NOT NULL,
  content TEXT NOT NULL, -- The rule description or regex pattern
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (twin_id, name)
);

CREATE INDEX IF NOT EXISTS idx_governance_policies_twin ON governance_policies(twin_id);

-- 3. Twin Verification Table
-- Track formal verification status for AI personas
CREATE TABLE IF NOT EXISTS twin_verification (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'verified', 'rejected')),
  verification_method TEXT NOT NULL, -- e.g., 'ID_UPLOAD', 'DOMAIN_VERIFICATION', 'MANUAL_REVIEW'
  metadata JSONB DEFAULT '{}'::jsonb,
  requested_at TIMESTAMPTZ DEFAULT NOW(),
  verified_at TIMESTAMPTZ,
  verified_by UUID REFERENCES users(id),
  UNIQUE (twin_id)
);

CREATE INDEX IF NOT EXISTS idx_twin_verification_twin ON twin_verification(twin_id);
CREATE INDEX IF NOT EXISTS idx_twin_verification_status ON twin_verification(status);

-- 4. Ingestion Logs Extension (Phase 6 Enhancement)
-- Adding deep scrub tracking to ingestion logs
ALTER TABLE sources ADD COLUMN IF NOT EXISTS last_deep_scrub_at TIMESTAMPTZ;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS is_verified_content BOOLEAN NOT NULL DEFAULT false;

-- 5. Twins Table Enhancement
-- Add status shorthand for twins
ALTER TABLE twins ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE twins ADD COLUMN IF NOT EXISTS verification_status TEXT DEFAULT 'unverified' CHECK (verification_status IN ('unverified', 'pending', 'verified', 'rejected'));

-- Create triggers for updated_at where missing
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_governance_policies_updated_at
BEFORE UPDATE ON governance_policies
FOR EACH ROW
EXECUTE PROCEDURE update_updated_at_column();
