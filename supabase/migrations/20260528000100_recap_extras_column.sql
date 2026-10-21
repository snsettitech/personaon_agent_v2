-- Phase 30 / Commit A3: leadership recap extras for desktop SDK meetings.
-- Base summary_json already stores tldr/topics/action_items/key_questions.
-- This additive JSONB column stores intent/what_happened/commitments from a
-- second Gemini pass without changing the shared analyze_meeting() contract.

ALTER TABLE meetings
    ADD COLUMN IF NOT EXISTS recap_extras_json jsonb;
