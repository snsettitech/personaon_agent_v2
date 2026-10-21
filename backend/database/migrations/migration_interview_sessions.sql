-- Migration: Interview Sessions for Intent-First Controller
-- Creates table to track interview state machine per session

CREATE TABLE IF NOT EXISTS interview_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    
    -- State machine
    stage TEXT NOT NULL DEFAULT 'opening',
    -- 'opening' | 'intent_capture' | 'confirm_intent' | 'deep_interview' | 'complete'
    
    -- Intent tracking
    intent_confirmed BOOLEAN DEFAULT FALSE,
    intent_summary TEXT,  -- Host's summary for confirmation
    
    -- Interview blueprint (generated after intent confirmation)
    blueprint_json JSONB DEFAULT '{}',
    -- Stores: { selected_packs: [], slot_order: [], intent_tags: [] }
    
    -- Progress tracking
    asked_template_ids TEXT[] DEFAULT '{}',
    turn_count INTEGER DEFAULT 0,
    slots_filled INTEGER DEFAULT 0,
    total_required_slots INTEGER DEFAULT 0,
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- Ensure required columns exist when this migration runs on partially
-- provisioned schemas.
ALTER TABLE interview_sessions
ADD COLUMN IF NOT EXISTS conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
ADD COLUMN IF NOT EXISTS stage TEXT NOT NULL DEFAULT 'opening',
ADD COLUMN IF NOT EXISTS intent_confirmed BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS intent_summary TEXT,
ADD COLUMN IF NOT EXISTS blueprint_json JSONB DEFAULT '{}',
ADD COLUMN IF NOT EXISTS asked_template_ids TEXT[] DEFAULT '{}',
ADD COLUMN IF NOT EXISTS turn_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS slots_filled INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS total_required_slots INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW(),
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW(),
ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS clarification_attempts INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS current_question_id TEXT,
ADD COLUMN IF NOT EXISTS last_repair_strategy TEXT,
ADD COLUMN IF NOT EXISTS response_quality_scores JSONB DEFAULT '[]'::jsonb,
ADD COLUMN IF NOT EXISTS skipped_slots TEXT[] DEFAULT '{}';

-- Index for fast lookup by twin
CREATE INDEX IF NOT EXISTS idx_interview_sessions_twin_id ON interview_sessions(twin_id);
CREATE INDEX IF NOT EXISTS idx_interview_sessions_conversation_id ON interview_sessions(conversation_id);

-- Enable RLS
ALTER TABLE interview_sessions ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Users can manage sessions for their twins
DROP POLICY IF EXISTS "interview_sessions_tenant_isolation" ON interview_sessions;
CREATE POLICY "interview_sessions_tenant_isolation" ON interview_sessions
    FOR ALL USING (
        twin_id IN (
            SELECT id FROM twins WHERE tenant_id = auth.uid()
        )
    );

-- System RPC: Create or get session (bypasses RLS for service operations)
CREATE OR REPLACE FUNCTION get_or_create_interview_session(
    t_id UUID,
    conv_id UUID DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    session_record interview_sessions%ROWTYPE;
BEGIN
    -- First, check if there's a completed session from the last 24 hours
    -- Return it so the interview can continue conversationally
    SELECT * INTO session_record
    FROM interview_sessions
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
    INSERT INTO interview_sessions (twin_id, conversation_id, stage)
    VALUES (t_id, conv_id, 'opening')
    RETURNING * INTO session_record;
    
    RETURN to_jsonb(session_record);
END;
$$;

-- System RPC: Update session state
DROP FUNCTION IF EXISTS update_interview_session(
    UUID, TEXT, BOOLEAN, TEXT, JSONB, TEXT, BOOLEAN, INTEGER, INTEGER
);
CREATE OR REPLACE FUNCTION update_interview_session(
    session_id UUID,
    new_stage TEXT DEFAULT NULL,
    new_intent_confirmed BOOLEAN DEFAULT NULL,
    new_intent_summary TEXT DEFAULT NULL,
    new_blueprint JSONB DEFAULT NULL,
    add_template_id TEXT DEFAULT NULL,
    increment_turn BOOLEAN DEFAULT FALSE,
    new_slots_filled INTEGER DEFAULT NULL,
    new_total_slots INTEGER DEFAULT NULL,
    new_clarification_attempts INTEGER DEFAULT NULL,
    new_current_question_id TEXT DEFAULT NULL,
    new_last_repair_strategy TEXT DEFAULT NULL,
    append_quality_score JSONB DEFAULT NULL,
    reset_clarification_attempts BOOLEAN DEFAULT FALSE,
    add_skipped_slot TEXT DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    session_record interview_sessions%ROWTYPE;
    current_quality_scores JSONB;
BEGIN
    SELECT response_quality_scores INTO current_quality_scores
    FROM interview_sessions
    WHERE id = session_id;
    
    IF current_quality_scores IS NULL THEN
        current_quality_scores := '[]'::jsonb;
    END IF;
    
    UPDATE interview_sessions
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
        clarification_attempts = CASE
            WHEN reset_clarification_attempts THEN 0
            WHEN new_clarification_attempts IS NOT NULL THEN new_clarification_attempts
            ELSE clarification_attempts
        END,
        current_question_id = COALESCE(new_current_question_id, current_question_id),
        last_repair_strategy = COALESCE(new_last_repair_strategy, last_repair_strategy),
        response_quality_scores = CASE
            WHEN append_quality_score IS NOT NULL THEN current_quality_scores || jsonb_build_array(append_quality_score)
            ELSE response_quality_scores
        END,
        skipped_slots = CASE
            WHEN add_skipped_slot IS NOT NULL THEN array_append(skipped_slots, add_skipped_slot)
            ELSE skipped_slots
        END,
        updated_at = NOW(),
        completed_at = CASE WHEN new_stage = 'complete' THEN NOW() ELSE completed_at END
    WHERE id = session_id
    RETURNING * INTO session_record;
    
    RETURN to_jsonb(session_record);
END;
$$;

-- Grant execute to service role
GRANT EXECUTE ON FUNCTION get_or_create_interview_session(UUID, UUID) TO service_role;
GRANT EXECUTE ON FUNCTION update_interview_session(
    UUID, TEXT, BOOLEAN, TEXT, JSONB, TEXT, BOOLEAN, INTEGER, INTEGER,
    INTEGER, TEXT, TEXT, JSONB, BOOLEAN, TEXT
) TO service_role;
