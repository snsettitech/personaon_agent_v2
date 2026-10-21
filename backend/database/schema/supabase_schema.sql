-- ============================================================================
-- PersonaOn AI - Database Schema Reference
-- ============================================================================
-- 
-- NOTE: This file contains a REFERENCE schema up to Phase 5.
-- For production use, run migrations in order from backend/database/migrations/:
--  1. This base schema (or apply migrations phase by phase)
--  2. migration_phase4_verified_qna.sql
--  3. migration_phase5_access_groups.sql
--  4. migration_phase6_mind_ops.sql
--  5. migration_phase7_omnichannel.sql
--  6. migration_phase8_actions_engine.sql
--  7. migration_phase9_governance.sql
--
-- Migrations are the source of truth and include all tables, columns, and indexes.
-- ============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Tenants table
CREATE TABLE tenants (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Twins table (each tenant can have multiple AI personas)
CREATE TABLE twins (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  settings JSONB DEFAULT '{"system_prompt": null}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (tenant_id, name)
);

-- Users table
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  email TEXT UNIQUE NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('owner', 'viewer')) DEFAULT 'viewer',
  dashboard_walkthrough_completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Sources table (knowledge base files)
CREATE TABLE sources (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  file_url TEXT,
  content_text TEXT,
  file_size BIGINT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processed', 'error')),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Chunks table (for vector storage reference)
CREATE TABLE chunks (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  vector_id TEXT, -- ID in Pinecone
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Conversations table
CREATE TABLE conversations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Messages table
CREATE TABLE messages (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  citations JSONB, -- List of chunk IDs or source names
  confidence_score FLOAT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Escalations table
CREATE TABLE escalations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'ignored')),
  resolved_by UUID REFERENCES users(id),
  resolved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Escalation Replies table (Owner responses)
CREATE TABLE escalation_replies (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  escalation_id UUID NOT NULL REFERENCES escalations(id) ON DELETE CASCADE,
  owner_id UUID REFERENCES users(id),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Verified QnA table: Canonical verified answers
CREATE TABLE verified_qna (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  question_embedding TEXT, -- JSON array of floats (optional, for semantic matching via Pinecone)
  visibility TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'shared', 'public')),
  created_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  is_active BOOLEAN NOT NULL DEFAULT true
);

-- Answer Patches table: Version history for edits
CREATE TABLE answer_patches (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  verified_qna_id UUID NOT NULL REFERENCES verified_qna(id) ON DELETE CASCADE,
  previous_answer TEXT NOT NULL,
  new_answer TEXT NOT NULL,
  reason TEXT,
  patched_by UUID REFERENCES users(id),
  patched_at TIMESTAMPTZ DEFAULT NOW()
);

-- Citations table: Source links for verified answers
CREATE TABLE citations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  verified_qna_id UUID NOT NULL REFERENCES verified_qna(id) ON DELETE CASCADE,
  source_id TEXT,
  chunk_id TEXT,
  citation_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Phase 5: Access Groups Tables
-- Access Groups table
CREATE TABLE IF NOT EXISTS access_groups (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  is_default BOOLEAN NOT NULL DEFAULT false,
  is_public BOOLEAN NOT NULL DEFAULT false,
  settings JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (twin_id, name)
);

-- Group Memberships table (one group per user per twin)
CREATE TABLE IF NOT EXISTS group_memberships (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  group_id UUID NOT NULL REFERENCES access_groups(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (user_id, twin_id)
);

-- Content Permissions table (many-to-many relationship)
CREATE TABLE IF NOT EXISTS content_permissions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  group_id UUID NOT NULL REFERENCES access_groups(id) ON DELETE CASCADE,
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  content_type TEXT NOT NULL CHECK (content_type IN ('source', 'verified_qna')),
  content_id UUID NOT NULL,
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

-- Add group_id column to conversations table
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS group_id UUID REFERENCES access_groups(id) ON DELETE SET NULL;

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_access_groups_twin_default ON access_groups(twin_id, is_default);
CREATE INDEX IF NOT EXISTS idx_group_memberships_user_twin ON group_memberships(user_id, twin_id, is_active);
CREATE INDEX IF NOT EXISTS idx_content_permissions_group_content ON content_permissions(group_id, content_type, content_id);
CREATE INDEX IF NOT EXISTS idx_content_permissions_content ON content_permissions(content_type, content_id);
CREATE INDEX IF NOT EXISTS idx_conversations_group ON conversations(group_id);
