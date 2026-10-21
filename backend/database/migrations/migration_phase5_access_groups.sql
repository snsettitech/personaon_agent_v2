-- Phase 5: Access Groups Migration
-- This migration creates the access groups system for audience segmentation

-- Access Groups table
CREATE TABLE IF NOT EXISTS access_groups (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  is_default BOOLEAN NOT NULL DEFAULT false,
  is_public BOOLEAN NOT NULL DEFAULT false, -- Public groups for anonymous users
  settings JSONB DEFAULT '{}'::jsonb, -- Group-specific agent instructions, tone, etc.
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (twin_id, name)
);

-- Group Memberships table (one group per user per twin)
CREATE TABLE IF NOT EXISTS group_memberships (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  group_id UUID NOT NULL REFERENCES access_groups(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE, -- Denormalized for easier queries
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (user_id, twin_id) -- One group per user per twin
);

-- Content Permissions table (many-to-many relationship)
CREATE TABLE IF NOT EXISTS content_permissions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  group_id UUID NOT NULL REFERENCES access_groups(id) ON DELETE CASCADE,
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  content_type TEXT NOT NULL CHECK (content_type IN ('source', 'verified_qna')),
  content_id UUID NOT NULL, -- References sources.id or verified_qna.id
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (group_id, content_type, content_id)
);

-- Group Limits table
CREATE TABLE IF NOT EXISTS group_limits (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  group_id UUID NOT NULL REFERENCES access_groups(id) ON DELETE CASCADE,
  limit_type TEXT NOT NULL CHECK (limit_type IN ('requests_per_hour', 'requests_per_day', 'tokens_per_request', 'tokens_per_day')),
  limit_value INTEGER NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (group_id, limit_type)
);

-- Group Overrides table
CREATE TABLE IF NOT EXISTS group_overrides (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  group_id UUID NOT NULL REFERENCES access_groups(id) ON DELETE CASCADE,
  override_type TEXT NOT NULL CHECK (override_type IN ('system_prompt', 'temperature', 'max_tokens', 'tool_access')),
  override_value JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (group_id, override_type)
);

-- Add group_id column to conversations table (nullable for backward compatibility)
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS group_id UUID REFERENCES access_groups(id) ON DELETE SET NULL;

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_access_groups_twin_default ON access_groups(twin_id, is_default);
CREATE INDEX IF NOT EXISTS idx_group_memberships_user_twin ON group_memberships(user_id, twin_id, is_active);
CREATE INDEX IF NOT EXISTS idx_content_permissions_group_content ON content_permissions(group_id, content_type, content_id);
CREATE INDEX IF NOT EXISTS idx_content_permissions_content ON content_permissions(content_type, content_id);
CREATE INDEX IF NOT EXISTS idx_conversations_group ON conversations(group_id);
