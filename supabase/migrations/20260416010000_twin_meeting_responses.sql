-- Phase 29: Active Twin in Meetings
-- Stores twin responses during meetings for post-meeting review

-- Add twin_attends column to meetings table (default true per CONTEXT.md)
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS twin_attends BOOLEAN NOT NULL DEFAULT true;

-- Twin responses table for post-meeting review
CREATE TABLE IF NOT EXISTS twin_meeting_responses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  twin_id UUID NOT NULL,
  tenant_id UUID NOT NULL,
  question_text TEXT NOT NULL,
  response_text TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.0,
  sources JSONB DEFAULT '[]'::jsonb,
  is_deferral BOOLEAN NOT NULL DEFAULT false,
  responded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_twin_meeting_responses_meeting
  ON twin_meeting_responses(meeting_id);
CREATE INDEX IF NOT EXISTS idx_twin_meeting_responses_twin
  ON twin_meeting_responses(twin_id, meeting_id);
