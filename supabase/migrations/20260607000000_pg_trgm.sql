-- Enable trigram extension for fuzzy search in the ⌘K palette.
-- The %> operator (word similarity) uses these GIN indexes.
-- CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
-- The "No transaction" directive disables Supabase's automatic BEGIN/COMMIT wrapping.
-- No transaction

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_name_trgm
  ON public.contacts USING gin (name gin_trgm_ops);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_meetings_title_trgm
  ON public.meetings USING gin (COALESCE(title, '') gin_trgm_ops);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_mcommit_text_trgm
  ON public.meeting_commitments USING gin (text gin_trgm_ops);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_mcand_text_trgm
  ON public.memory_candidates USING gin (text gin_trgm_ops);
