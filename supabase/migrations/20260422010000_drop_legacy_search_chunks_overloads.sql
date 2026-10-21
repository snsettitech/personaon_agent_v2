-- =============================================================================
-- Drop legacy search_chunks overloads superseded by 20260421_search_chunks_tiers
--
-- Why this migration exists:
--   20260421_search_chunks_tiers.sql introduced new 5-arg forms of
--   search_chunks() and search_chunks_global() that add privacy_level tier
--   filtering and a min_similarity floor. Because `CREATE OR REPLACE FUNCTION`
--   only replaces a function with an identical signature, the pre-existing
--   3-arg search_chunks (from 20260412_pgvector_schema) and 4-arg
--   search_chunks_global (from 20260413_marketplace_global_search) remained in
--   the database as separate overloads. Any caller passing 3 positional args
--   (where int/float have implicit defaults on the new form) hits
--   `AmbiguousFunctionError`, which is what broke the staging meeting test.
--
-- Idempotent & reversible via re-running the superseded create migrations if
-- required. DROP IF EXISTS is a no-op on environments where the old overloads
-- were already dropped manually (e.g. staging during incident recovery).
-- =============================================================================

DROP FUNCTION IF EXISTS search_chunks(vector, uuid, integer);
DROP FUNCTION IF EXISTS search_chunks_global(vector, uuid[], integer, integer);
