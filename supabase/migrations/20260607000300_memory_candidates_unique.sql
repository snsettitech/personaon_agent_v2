-- Fix: memory_candidates had no unique constraint on (meeting_id, text, kind).
-- Worker retries produced duplicate candidate rows (up to max_attempts duplicates).
-- Using a unique index (not ALTER TABLE ADD CONSTRAINT) because left(text,500)
-- is an expression and Postgres requires CREATE UNIQUE INDEX for expression-based uniqueness.
CREATE UNIQUE INDEX IF NOT EXISTS memory_candidates_meeting_text_kind_unique
  ON public.memory_candidates (meeting_id, twin_id, kind, left(text, 500));
