-- =============================================================================
-- Layer 2 / Phase 30 review fix — RLS policy on recap_edits
--
-- The original policy in 20260528000000_recap_edits_and_extras.sql used
-- `USING (auth.uid() = tenant_id)`. That's functionally correct today
-- because single-user tenants have tenant_id == auth.uid(), but it's
-- unsafe once multi-seat tenants land (every user sharing a tenant would
-- see every other user's edit history).
--
-- This migration:
--   1. Switches the SELECT policy to filter on `user_id` (the column the
--      table already stores for every row — see migration 20260528000000
--      lines 22-24). user_id is always the specific user who made the
--      edit; correct under both single-user and future multi-seat models.
--   2. Wraps `auth.uid()` in `(SELECT auth.uid())` so Postgres evaluates
--      the call ONCE per query instead of per row. Standard Supabase
--      perf pattern.
--
-- The recap_edits table has no INSERT policy by design — inserts go
-- through the backend service role only, so the audit trail can't be
-- forged from a client.
-- =============================================================================

DROP POLICY IF EXISTS recap_edits_owner_read ON recap_edits;

CREATE POLICY recap_edits_owner_read ON recap_edits
    FOR SELECT
    USING ((SELECT auth.uid()) = user_id);

-- Index on user_id so the RLS USING clause doesn't degrade to a sequential
-- scan as recap_edits grows (F6.8 review fix). Partial index excludes the
-- rare orphaned-user rows (user_id is `ON DELETE SET NULL`) — they're
-- intentionally invisible to RLS reads anyway.
CREATE INDEX IF NOT EXISTS idx_recap_edits_user_id
    ON recap_edits(user_id)
    WHERE user_id IS NOT NULL;
