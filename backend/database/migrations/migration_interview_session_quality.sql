-- Migration: Interview Session Quality Tracking
-- Adds quality tracking columns to interview_sessions table

-- Add new columns for quality tracking
ALTER TABLE interview_sessions
ADD COLUMN IF NOT EXISTS clarification_attempts INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS current_question_id TEXT,
ADD COLUMN IF NOT EXISTS last_repair_strategy TEXT,
ADD COLUMN IF NOT EXISTS response_quality_scores JSONB DEFAULT '[]'::jsonb,
ADD COLUMN IF NOT EXISTS skipped_slots TEXT[] DEFAULT '{}';

-- Replace the legacy signature explicitly to avoid overload ambiguity on reruns.
DROP FUNCTION IF EXISTS update_interview_session(
    UUID, TEXT, BOOLEAN, TEXT, JSONB, TEXT, BOOLEAN, INTEGER, INTEGER
);

-- Update the update_interview_session function to support new fields
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
    -- Get current quality scores for appending
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
GRANT EXECUTE ON FUNCTION update_interview_session(
    UUID, TEXT, BOOLEAN, TEXT, JSONB, TEXT, BOOLEAN, INTEGER, INTEGER,
    INTEGER, TEXT, TEXT, JSONB, BOOLEAN, TEXT
) TO service_role;
