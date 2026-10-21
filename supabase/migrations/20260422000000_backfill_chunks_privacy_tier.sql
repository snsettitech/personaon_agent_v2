-- =============================================================================
-- Backfill privacy_level for pre-existing chunks ingested before tier tagging
-- was wired through upsert_text_chunks callers.
--
-- Strategy: only UPGRADE privacy (tighter), never downgrade. Chunks whose
-- source strongly suggests non-public provenance get flipped from the default
-- `public` to `team`. Everything else stays as-is.
--
-- Scope:
--   capture_tools.py                   source LIKE 'captured_%'
--   meeting_indexer.py                 source LIKE 'meeting:%'
-- User-uploaded documents (ingestion.py) are indistinguishable from scraped
-- profile sources by source label alone (both use arbitrary strings), so they
-- are NOT backfilled here. Future uploads are tagged `team` at write time.
--
-- Safe to re-run: no-op on rows already at `team` or stricter.
-- =============================================================================

UPDATE chunks
SET privacy_level = 'team'
WHERE privacy_level = 'public'
  AND (
    metadata->>'source' LIKE 'captured\_%'
    OR metadata->>'source' LIKE 'meeting:%'
  );
