-- Phase 8: Actions Engine Migration
-- Creates tables for event-driven action automation with approval workflow

-- ============================================================================
-- EVENTS TABLE
-- Stores all system events that can trigger actions
-- ============================================================================
CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    -- Event types: message_received, answer_sent, escalation_created, 
    -- escalation_resolved, idle_timeout, source_ingested, confidence_low
    payload JSONB DEFAULT '{}',
    -- Payload contains event-specific data:
    -- message_received: { conversation_id, user_message, user_id }
    -- answer_sent: { conversation_id, response, confidence_score, citations }
    -- escalation_created: { escalation_id, question, reason }
    -- idle_timeout: { session_id, duration_seconds }
    source_context JSONB DEFAULT '{}',
    -- Additional context for trigger matching (group_id, channel, user info)
    created_at TIMESTAMPTZ DEFAULT now(),
    
    -- Indexes for efficient querying
    CONSTRAINT events_type_check CHECK (event_type IN (
        'message_received', 'answer_sent', 'escalation_created', 
        'escalation_resolved', 'idle_timeout', 'source_ingested', 
        'confidence_low', 'action_executed', 'action_failed'
    ))
);

CREATE INDEX IF NOT EXISTS idx_events_twin_id ON events(twin_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_twin_type_time ON events(twin_id, event_type, created_at DESC);

-- ============================================================================
-- TOOL CONNECTORS TABLE
-- Stores OAuth/API configurations for external services
-- ============================================================================
CREATE TABLE IF NOT EXISTS tool_connectors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    connector_type VARCHAR(50) NOT NULL,
    -- Connector types: gmail, google_calendar, slack, notion, composio
    name VARCHAR(100) NOT NULL,
    -- User-friendly name for this connector instance
    config JSONB DEFAULT '{}',
    -- Non-sensitive configuration (scopes, settings)
    credentials_encrypted TEXT,
    -- Encrypted OAuth tokens or API keys (use pgcrypto or app-level encryption)
    is_active BOOLEAN DEFAULT true,
    last_used_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    
    -- Unique constraint: one connector type per twin per name
    CONSTRAINT unique_connector_per_twin UNIQUE (twin_id, connector_type, name)
);

CREATE INDEX IF NOT EXISTS idx_connectors_twin_id ON tool_connectors(twin_id);
CREATE INDEX IF NOT EXISTS idx_connectors_type ON tool_connectors(connector_type);

-- ============================================================================
-- ACTION TRIGGERS TABLE
-- Configurable rules that map events to actions with conditions
-- ============================================================================
CREATE TABLE IF NOT EXISTS action_triggers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    event_type VARCHAR(50) NOT NULL,
    -- Which event type this trigger listens for
    conditions JSONB DEFAULT '{}',
    -- Condition rules: { "intent_contains": ["schedule", "meeting"], 
    --                    "confidence_below": 0.7, 
    --                    "group_id": "uuid",
    --                    "keywords": ["urgent", "asap"] }
    connector_id UUID REFERENCES tool_connectors(id) ON DELETE SET NULL,
    -- Optional: which connector to use for the action
    action_type VARCHAR(50) NOT NULL,
    -- Action types: draft_email, draft_calendar_event, notify_owner, 
    -- escalate, send_message, create_task
    action_config JSONB DEFAULT '{}',
    -- Action-specific configuration:
    -- draft_email: { to_template, subject_template, body_template }
    -- draft_calendar_event: { title_template, duration_minutes, attendees_template }
    -- notify_owner: { channel, template }
    requires_approval BOOLEAN DEFAULT true,
    -- If true, creates a draft for approval; if false, executes immediately
    is_active BOOLEAN DEFAULT true,
    priority INTEGER DEFAULT 0,
    -- Higher priority triggers are evaluated first
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    
    CONSTRAINT trigger_event_check CHECK (event_type IN (
        'message_received', 'answer_sent', 'escalation_created', 
        'escalation_resolved', 'idle_timeout', 'source_ingested', 
        'confidence_low', 'action_executed', 'action_failed'
    )),
    CONSTRAINT trigger_action_check CHECK (action_type IN (
        'draft_email', 'draft_calendar_event', 'notify_owner',
        'escalate', 'send_message', 'create_task', 'webhook'
    ))
);

CREATE INDEX IF NOT EXISTS idx_triggers_twin_id ON action_triggers(twin_id);
CREATE INDEX IF NOT EXISTS idx_triggers_event_type ON action_triggers(event_type);
CREATE INDEX IF NOT EXISTS idx_triggers_active ON action_triggers(is_active) WHERE is_active = true;

-- ============================================================================
-- ACTION DRAFTS TABLE
-- Pending action proposals awaiting owner approval
-- ============================================================================
CREATE TABLE IF NOT EXISTS action_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_id UUID REFERENCES action_triggers(id) ON DELETE SET NULL,
    event_id UUID REFERENCES events(id) ON DELETE SET NULL,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    status VARCHAR(20) DEFAULT 'pending',
    -- Status: pending, approved, rejected, expired, executed
    proposed_action JSONB NOT NULL,
    -- The full action to be executed:
    -- { action_type, connector_id, params: { to, subject, body } for email }
    context JSONB DEFAULT '{}',
    -- Context for decision-making:
    -- { conversation_excerpt, user_query, trigger_name, match_reason }
    approval_note TEXT,
    -- Optional note from approver
    approved_by UUID,
    -- User who approved/rejected
    expires_at TIMESTAMPTZ,
    -- When this draft expires (optional, for time-sensitive actions)
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    
    CONSTRAINT draft_status_check CHECK (status IN (
        'pending', 'approved', 'rejected', 'expired', 'executed', 'responded'
    ))
);

CREATE INDEX IF NOT EXISTS idx_drafts_twin_id ON action_drafts(twin_id);
CREATE INDEX IF NOT EXISTS idx_drafts_status ON action_drafts(status);
CREATE INDEX IF NOT EXISTS idx_drafts_pending ON action_drafts(twin_id, status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_drafts_created_at ON action_drafts(created_at DESC);

-- ============================================================================
-- ACTION EXECUTIONS TABLE
-- Immutable log of all executed actions with full context for replay
-- ============================================================================
CREATE TABLE IF NOT EXISTS action_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id UUID REFERENCES action_drafts(id) ON DELETE SET NULL,
    trigger_id UUID REFERENCES action_triggers(id) ON DELETE SET NULL,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    connector_id UUID REFERENCES tool_connectors(id) ON DELETE SET NULL,
    action_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    -- Status: success, failed, partial
    inputs JSONB NOT NULL,
    -- Full inputs sent to the connector/action
    outputs JSONB DEFAULT '{}',
    -- Response from the connector/action
    error_message TEXT,
    -- Error details if failed
    execution_duration_ms INTEGER,
    -- How long the execution took
    executed_by UUID,
    -- User who triggered the execution (via approval)
    executed_at TIMESTAMPTZ DEFAULT now(),
    
    CONSTRAINT execution_status_check CHECK (status IN ('success', 'failed', 'partial'))
);

CREATE INDEX IF NOT EXISTS idx_executions_twin_id ON action_executions(twin_id);
CREATE INDEX IF NOT EXISTS idx_executions_status ON action_executions(status);
CREATE INDEX IF NOT EXISTS idx_executions_action_type ON action_executions(action_type);
CREATE INDEX IF NOT EXISTS idx_executions_executed_at ON action_executions(executed_at DESC);

-- ============================================================================
-- ROW LEVEL SECURITY POLICIES
-- ============================================================================

-- Enable RLS on all tables
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE tool_connectors ENABLE ROW LEVEL SECURITY;
ALTER TABLE action_triggers ENABLE ROW LEVEL SECURITY;
ALTER TABLE action_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE action_executions ENABLE ROW LEVEL SECURITY;

-- Service role bypass policies (allows backend with service key to access all rows)
-- The service role in Supabase automatically bypasses RLS, but we add explicit policies
-- for the anon/authenticated roles

-- Events: Allow all operations (service role bypasses, authenticated users checked by app)
CREATE POLICY events_all_access ON events FOR ALL USING (true) WITH CHECK (true);

-- Tool Connectors: Allow all operations  
CREATE POLICY connectors_all_access ON tool_connectors FOR ALL USING (true) WITH CHECK (true);

-- Action Triggers: Allow all operations
CREATE POLICY triggers_all_access ON action_triggers FOR ALL USING (true) WITH CHECK (true);

-- Action Drafts: Allow all operations
CREATE POLICY drafts_all_access ON action_drafts FOR ALL USING (true) WITH CHECK (true);

-- Action Executions: Allow all operations
CREATE POLICY executions_all_access ON action_executions FOR ALL USING (true) WITH CHECK (true);

-- NOTE: Application-level authorization is handled by the backend (verify_owner dependency)
-- For production, you can replace these with more restrictive policies that use auth.uid()

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to check if a trigger's conditions match an event
CREATE OR REPLACE FUNCTION match_trigger_conditions(
    trigger_conditions JSONB,
    event_payload JSONB,
    event_context JSONB
) RETURNS BOOLEAN AS $$
DECLARE
    intent_keywords TEXT[];
    keywords TEXT[];
    confidence_threshold NUMERIC;
    group_filter UUID;
    keyword TEXT;
BEGIN
    -- Check intent_contains condition
    IF trigger_conditions ? 'intent_contains' THEN
        intent_keywords := ARRAY(SELECT jsonb_array_elements_text(trigger_conditions->'intent_contains'));
        IF NOT EXISTS (
            SELECT 1 FROM unnest(intent_keywords) k
            WHERE lower(event_payload->>'user_message') LIKE '%' || lower(k) || '%'
        ) THEN
            RETURN FALSE;
        END IF;
    END IF;
    
    -- Check keywords condition (any match)
    IF trigger_conditions ? 'keywords' THEN
        keywords := ARRAY(SELECT jsonb_array_elements_text(trigger_conditions->'keywords'));
        IF NOT EXISTS (
            SELECT 1 FROM unnest(keywords) k
            WHERE lower(event_payload->>'user_message') LIKE '%' || lower(k) || '%'
        ) THEN
            RETURN FALSE;
        END IF;
    END IF;
    
    -- Check confidence_below condition
    IF trigger_conditions ? 'confidence_below' THEN
        confidence_threshold := (trigger_conditions->>'confidence_below')::NUMERIC;
        IF (event_payload->>'confidence_score')::NUMERIC >= confidence_threshold THEN
            RETURN FALSE;
        END IF;
    END IF;
    
    -- Check group_id condition
    IF trigger_conditions ? 'group_id' THEN
        group_filter := (trigger_conditions->>'group_id')::UUID;
        IF (event_context->>'group_id')::UUID != group_filter THEN
            RETURN FALSE;
        END IF;
    END IF;
    
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function to expire old drafts
CREATE OR REPLACE FUNCTION expire_old_drafts() RETURNS void AS $$
BEGIN
    UPDATE action_drafts
    SET status = 'expired', updated_at = now()
    WHERE status = 'pending' 
      AND expires_at IS NOT NULL 
      AND expires_at < now();
END;
$$ LANGUAGE plpgsql;
