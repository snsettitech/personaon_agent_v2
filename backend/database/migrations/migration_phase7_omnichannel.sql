-- Phase 7: Omnichannel Distribution Migration
-- This migration creates tables for API keys, sessions, rate limiting, and user invitations

-- 1. API Keys Table
CREATE TABLE IF NOT EXISTS twin_api_keys (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  group_id UUID REFERENCES access_groups(id) ON DELETE SET NULL,
  key_hash TEXT NOT NULL UNIQUE,
  key_prefix TEXT NOT NULL,
  name TEXT NOT NULL,
  allowed_domains JSONB DEFAULT '[]'::jsonb,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  last_used_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_twin_api_keys_twin ON twin_api_keys(twin_id);
CREATE INDEX IF NOT EXISTS idx_twin_api_keys_hash ON twin_api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_twin_api_keys_active ON twin_api_keys(twin_id, is_active);

-- 2. Sessions Table
CREATE TABLE IF NOT EXISTS sessions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  group_id UUID REFERENCES access_groups(id) ON DELETE SET NULL,
  session_type TEXT NOT NULL CHECK (session_type IN ('anonymous', 'authenticated')),
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  ip_address TEXT,
  user_agent TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  last_active_at TIMESTAMPTZ DEFAULT NOW(),
  expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_twin ON sessions(twin_id);
CREATE INDEX IF NOT EXISTS idx_sessions_type ON sessions(session_type);
CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

-- 3. Rate Limit Tracking Table
CREATE TABLE IF NOT EXISTS rate_limit_tracking (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tracking_key TEXT NOT NULL,
  tracking_type TEXT NOT NULL CHECK (tracking_type IN ('api_key', 'session')),
  window_start TIMESTAMPTZ NOT NULL,
  request_count INTEGER NOT NULL DEFAULT 0,
  limit_type TEXT NOT NULL CHECK (limit_type IN ('requests_per_hour', 'requests_per_day'))
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_tracking_key ON rate_limit_tracking(tracking_key, tracking_type);
CREATE INDEX IF NOT EXISTS idx_rate_limit_tracking_window ON rate_limit_tracking(tracking_key, tracking_type, window_start);
CREATE INDEX IF NOT EXISTS idx_rate_limit_tracking_cleanup ON rate_limit_tracking(window_start);

-- 4. User Invitations Table
CREATE TABLE IF NOT EXISTS user_invitations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  invitation_token UUID NOT NULL UNIQUE DEFAULT uuid_generate_v4(),
  invited_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('owner', 'viewer')) DEFAULT 'viewer',
  status TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'expired')) DEFAULT 'pending',
  expires_at TIMESTAMPTZ NOT NULL,
  accepted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (tenant_id, email)
);

CREATE INDEX IF NOT EXISTS idx_user_invitations_token ON user_invitations(invitation_token);
CREATE INDEX IF NOT EXISTS idx_user_invitations_tenant ON user_invitations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_user_invitations_email ON user_invitations(email);
CREATE INDEX IF NOT EXISTS idx_user_invitations_status ON user_invitations(status);

-- 5. Conversations Table Update
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS session_id UUID REFERENCES sessions(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id);

-- 6. Users Table Enhancement
ALTER TABLE users ADD COLUMN IF NOT EXISTS invited_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS invitation_id UUID REFERENCES user_invitations(id) ON DELETE SET NULL;

-- Note: Twin settings extensions (widget_settings.domain_allowlist, etc.) 
-- are stored in JSONB and don't require schema changes. They will be handled in application code.
