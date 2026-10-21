-- Phase 30-K: Speaker resolution — link diarization labels to person nodes.
-- Recall.ai's diarized transcript labels speakers as speaker_0, speaker_1, etc.
-- This migration adds the columns needed to (a) record those labels and (b)
-- resolve them to nodes entities via attendee emails.
-- Source data: GET /api/v1/bot/{bot_id} returns the participant list with name
-- and (since May 2026 Participant Emails feature) email when calendar-linked.

ALTER TABLE public.meeting_participants
    ADD COLUMN IF NOT EXISTS diarization_label TEXT,
    ADD COLUMN IF NOT EXISTS person_node_id UUID;

CREATE INDEX IF NOT EXISTS idx_meeting_participants_diarization
    ON public.meeting_participants(meeting_id, diarization_label)
    WHERE diarization_label IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_meeting_participants_node
    ON public.meeting_participants(person_node_id)
    WHERE person_node_id IS NOT NULL;
