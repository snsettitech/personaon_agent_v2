-- =============================================================================
-- PersonaOn Base Schema Bootstrap
-- =============================================================================
-- Applies all schema that predates the Supabase migration pipeline.
-- Must run before all other migrations in this directory.
--
-- Sources:
--   backend/database/schema/supabase_schema.sql  (core tables)
--   backend/database/migrations/* (pre-pipeline column additions)
-- =============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Core tables ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tenants (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS twins (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  settings JSONB DEFAULT '{"system_prompt": null}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  email TEXT UNIQUE NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('owner', 'viewer')) DEFAULT 'viewer',
  dashboard_walkthrough_completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sources (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  file_url TEXT,
  content_text TEXT,
  file_size BIGINT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processed', 'error')),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chunks (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  vector_id TEXT,
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  citations JSONB,
  confidence_score FLOAT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS escalations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'ignored')),
  resolved_by UUID REFERENCES users(id),
  resolved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS escalation_replies (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  escalation_id UUID NOT NULL REFERENCES escalations(id) ON DELETE CASCADE,
  owner_id UUID REFERENCES users(id),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS verified_qna (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  question_embedding TEXT,
  visibility TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'shared', 'public')),
  created_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  is_active BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS answer_patches (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  verified_qna_id UUID NOT NULL REFERENCES verified_qna(id) ON DELETE CASCADE,
  previous_answer TEXT NOT NULL,
  new_answer TEXT NOT NULL,
  reason TEXT,
  patched_by UUID REFERENCES users(id),
  patched_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS citations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  verified_qna_id UUID NOT NULL REFERENCES verified_qna(id) ON DELETE CASCADE,
  source_id TEXT,
  chunk_id TEXT,
  citation_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

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

CREATE TABLE IF NOT EXISTS group_memberships (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  group_id UUID NOT NULL REFERENCES access_groups(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (user_id, twin_id)
);

CREATE TABLE IF NOT EXISTS content_permissions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  group_id UUID NOT NULL REFERENCES access_groups(id) ON DELETE CASCADE,
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  content_type TEXT NOT NULL CHECK (content_type IN ('source', 'verified_qna')),
  content_id UUID NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (group_id, content_type, content_id)
);

CREATE TABLE IF NOT EXISTS group_limits (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  group_id UUID NOT NULL REFERENCES access_groups(id) ON DELETE CASCADE,
  limit_type TEXT NOT NULL CHECK (limit_type IN ('requests_per_hour', 'requests_per_day', 'tokens_per_request', 'tokens_per_day')),
  limit_value INTEGER NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (group_id, limit_type)
);

CREATE TABLE IF NOT EXISTS group_overrides (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  group_id UUID NOT NULL REFERENCES access_groups(id) ON DELETE CASCADE,
  override_type TEXT NOT NULL CHECK (override_type IN ('system_prompt', 'temperature', 'max_tokens', 'tool_access')),
  override_value JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (group_id, override_type)
);

ALTER TABLE conversations ADD COLUMN IF NOT EXISTS group_id UUID REFERENCES access_groups(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_access_groups_twin_default ON access_groups(twin_id, is_default);
CREATE INDEX IF NOT EXISTS idx_group_memberships_user_twin ON group_memberships(user_id, twin_id, is_active);
CREATE INDEX IF NOT EXISTS idx_content_permissions_group_content ON content_permissions(group_id, content_type, content_id);
CREATE INDEX IF NOT EXISTS idx_content_permissions_content ON content_permissions(content_type, content_id);
CREATE INDEX IF NOT EXISTS idx_conversations_group ON conversations(group_id);

-- ── Connected accounts (OAuth providers) ─────────────────────────────────────

CREATE TABLE IF NOT EXISTS connected_accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    provider_user_id TEXT,
    profile_snapshot JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_connected_accounts_user_id ON connected_accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_connected_accounts_provider ON connected_accounts(provider);

-- ── Column additions (pre-pipeline migrations) ────────────────────────────────

-- users: make tenant_id nullable (OAuth signup happens before tenant creation)
ALTER TABLE users ALTER COLUMN tenant_id DROP NOT NULL;

-- users: identity fields from OAuth metadata
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name TEXT;

-- twins: creator namespace
ALTER TABLE twins ADD COLUMN IF NOT EXISTS creator_id TEXT;
CREATE INDEX IF NOT EXISTS idx_twins_creator_id ON twins(creator_id);
CREATE INDEX IF NOT EXISTS idx_twins_tenant_creator ON twins(tenant_id, creator_id);

-- twins: lifecycle columns
ALTER TABLE twins ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE twins ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE twins ADD COLUMN IF NOT EXISTS creation_mode TEXT DEFAULT 'manual';
ALTER TABLE twins ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'draft';

ALTER TABLE twins DROP CONSTRAINT IF EXISTS twins_creation_mode_check;
ALTER TABLE twins ADD CONSTRAINT twins_creation_mode_check
  CHECK (creation_mode IN ('manual', 'link_first', 'name_first', 'onboarding'));

ALTER TABLE twins DROP CONSTRAINT IF EXISTS twins_status_check;
ALTER TABLE twins ADD CONSTRAINT twins_status_check CHECK (
  status IN (
    'draft', 'building', 'ingesting', 'claims_ready', 'clarification_pending',
    'persona_built', 'active', 'live', 'needs_attention', 'failed', 'archived'
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_twins_tenant_owner_user_single_profile
  ON twins (tenant_id, (settings->>'owner_user_id'))
  WHERE (settings->>'owner_user_id') IS NOT NULL AND (settings->>'deleted_at') IS NULL;

CREATE INDEX IF NOT EXISTS idx_twins_tenant_status_created
  ON twins (tenant_id, status, created_at DESC);

-- ── Booking + Meetings (required before 20260415 supabase migrations) ────────

CREATE TABLE IF NOT EXISTS booking_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    visitor_name VARCHAR(200) NOT NULL,
    visitor_email VARCHAR(200) NOT NULL,
    visitor_message TEXT,
    visitor_timezone VARCHAR(100),
    proposed_start TIMESTAMPTZ NOT NULL,
    proposed_end TIMESTAMPTZ NOT NULL,
    slot_duration_minutes INT DEFAULT 30,
    status VARCHAR(20) DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled', 'expired')),
    approved_at TIMESTAMPTZ,
    rejected_at TIMESTAMPTZ,
    rejection_reason TEXT,
    gcal_event_id VARCHAR(200),
    meet_link VARCHAR(500),
    event_link VARCHAR(500),
    conversation_id UUID,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ DEFAULT (now() + interval '48 hours')
);

CREATE INDEX IF NOT EXISTS idx_booking_twin ON booking_requests(twin_id, status);
CREATE INDEX IF NOT EXISTS idx_booking_start ON booking_requests(proposed_start);

CREATE TABLE IF NOT EXISTS meetings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    booking_id UUID REFERENCES booking_requests(id),
    recall_bot_id TEXT,
    meet_link TEXT,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'scheduled'
        CHECK (status IN ('scheduled', 'bot_joining', 'recording', 'processing', 'completed', 'failed')),
    transcript_raw JSONB,
    transcript_text TEXT,
    summary TEXT,
    action_items JSONB,
    meeting_start TIMESTAMPTZ,
    meeting_end TIMESTAMPTZ,
    duration_seconds INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_meetings_twin_id ON meetings(twin_id);
CREATE INDEX IF NOT EXISTS idx_meetings_tenant_id ON meetings(tenant_id);
CREATE INDEX IF NOT EXISTS idx_meetings_recall_bot_id ON meetings(recall_bot_id);
CREATE INDEX IF NOT EXISTS idx_meetings_status ON meetings(status);

CREATE TABLE IF NOT EXISTS meeting_participants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    participant_name TEXT,
    participant_email TEXT,
    is_host BOOLEAN DEFAULT FALSE,
    talk_time_seconds FLOAT,
    word_count INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_meeting_participants_meeting_id ON meeting_participants(meeting_id);

CREATE TABLE IF NOT EXISTS meeting_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    meeting_id UUID REFERENCES meetings(id) ON DELETE SET NULL,
    notification_type TEXT NOT NULL
        CHECK (notification_type IN ('pre_meeting_briefing', 'post_meeting_followup', 'weekly_digest')),
    status TEXT NOT NULL DEFAULT 'sent'
        CHECK (status IN ('sent', 'skipped', 'failed')),
    resend_message_id TEXT,
    error_message TEXT,
    week_of DATE,
    sent_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (twin_id, meeting_id, notification_type)
);

-- ── graph_outbox (background job queue) ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS graph_outbox (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL,
    twin_id UUID NOT NULL,
    operation TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    priority INTEGER DEFAULT 0,
    attempt_count INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 5,
    correlation_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    result JSONB
);

CREATE INDEX IF NOT EXISTS idx_graph_outbox_status_priority ON graph_outbox(status, priority DESC, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_graph_outbox_twin_id ON graph_outbox(twin_id);
CREATE INDEX IF NOT EXISTS idx_graph_outbox_tenant_id ON graph_outbox(tenant_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_outbox_idempotency ON graph_outbox(idempotency_key) WHERE status IN ('pending', 'processing');
