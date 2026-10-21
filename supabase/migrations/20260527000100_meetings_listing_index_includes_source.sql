-- =============================================================================
-- Follow-up to 20260527000000_meetings_desktop_sdk_support.sql.
--
-- The original migration's listing index `idx_meetings_tenant_created
-- (tenant_id, created_at DESC) WHERE status <> 'deleted'` cannot satisfy
-- the source = 'desktop_sdk' filter used by /v2/desktop-recordings/.
-- Postgres uses the partial index to narrow by tenant, then applies source
-- as a heap filter — wasted I/O for tenants whose meetings mix sources.
--
-- Replace with a three-column index so the listing query becomes an
-- index-only scan with no heap filter step.
--
-- TEAM DEBT: the graph_outbox_operation_check pattern in the parent migration
-- (DROP + ADD with the full ARRAY of operations hardcoded) is fragile when
-- multiple migrations land out of order — the later migration silently drops
-- the earlier's addition. Canonicalise via a single-source migration when
-- bandwidth allows. Tracked for follow-up.
-- =============================================================================

DROP INDEX IF EXISTS idx_meetings_tenant_created;

CREATE INDEX IF NOT EXISTS idx_meetings_tenant_source_created
    ON meetings(tenant_id, source, created_at DESC)
    WHERE status <> 'deleted';
