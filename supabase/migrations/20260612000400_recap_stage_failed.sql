-- =============================================================================
-- Granola QG2 fix (smoothness H1): allow recap_stage = 'failed'.
--
-- The Batch 5 watchdog (_process_recap_timeout_check) flips a stuck recap to
-- status='failed' + enhanced_notes_status='failed', but COULD NOT also set
-- recap_stage='failed' because the original CHECK (20260611000000) did not
-- include 'failed'. With recap_stage left at e.g. 'enhancing', the frontend's
-- isRecapInProgress() stayed true and the UI rendered a perpetual skeleton.
--
-- This migration drops and recreates the recap_stage CHECK with the full
-- existing stage list PLUS 'failed', so the watchdog can mark the stage as a
-- terminal failure state and the UI can stop showing skeletons.
--
-- Idempotent: drops the constraint IF EXISTS before recreating it.
-- =============================================================================

ALTER TABLE meetings
  DROP CONSTRAINT IF EXISTS meetings_recap_stage_check;

ALTER TABLE meetings
  ADD CONSTRAINT meetings_recap_stage_check
    CHECK (recap_stage IN
      ('uploaded','transcribing','transcript_ready','summarizing',
       'summary_ready','enhancing','enhanced_ready','completed','failed'));

-- QG2 M1: backfill legacy completed rows whose recap_stage is NULL. Pre-Batch-4
-- rows never had recap_stage written; with status='completed' + recap_stage=NULL
-- the client treated them as in-progress and rendered a skeleton until the
-- watchdog fired. Stamp them as 'completed' so the UI settles immediately.
UPDATE meetings
   SET recap_stage = 'completed',
       recap_progress = COALESCE(recap_progress, 100)
 WHERE status = 'completed'
   AND recap_stage IS NULL;
