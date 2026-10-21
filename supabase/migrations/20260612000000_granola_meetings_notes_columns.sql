-- =============================================================================
-- Granola note-taking loop — Batch 0 (concern 1/2): meetings note/recap columns
-- Adds user-notes + enhanced-notes artifacts and a progressive recap-stage
-- machine to public.meetings. Idempotent (IF NOT EXISTS); backfills existing
-- completed meetings so they never render as "processing".
-- =============================================================================

ALTER TABLE meetings
  ADD COLUMN IF NOT EXISTS user_notes_json        jsonb,
  ADD COLUMN IF NOT EXISTS notes_updated_at       timestamptz,
  ADD COLUMN IF NOT EXISTS enhanced_notes_json    jsonb,
  ADD COLUMN IF NOT EXISTS enhanced_notes_status  text
      DEFAULT 'pending'
      CHECK (enhanced_notes_status IN
        ('pending','generating','ready','failed','skipped')),
  ADD COLUMN IF NOT EXISTS recap_stage            text DEFAULT 'uploaded'
      CHECK (recap_stage IN
        ('uploaded','transcribing','transcript_ready','summarizing',
         'summary_ready','enhancing','enhanced_ready','completed')),
  ADD COLUMN IF NOT EXISTS recap_progress         smallint DEFAULT 0;

-- Backfill: existing completed meetings must not render as "processing".
-- Only touches rows still sitting at the default 'uploaded' stage.
UPDATE meetings
   SET recap_stage = 'completed',
       recap_progress = 100
 WHERE status = 'completed'
   AND recap_stage = 'uploaded';
