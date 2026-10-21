-- Execution board 0.8 — Handle uniqueness (DB-level enforcement).
--
-- Handle uniqueness was previously application-layer-only: routers/handles.py
-- fetched every twin, computed a "taken" set in Python, and picked the first
-- free candidate. Two /handles/claim requests racing within the same second
-- can both read the same "taken" set before either write commits, so both
-- can pick the identical handle and both writes succeed — silent duplicate,
-- no error. This migration adds a database-level guarantee so at most one
-- of the two writes can ever succeed; the application handles the resulting
-- unique-violation as a clean collision response (see routers/handles.py).
--
-- The handle is stored in twins.settings->>'handle' (JSONB), not a plain
-- column — there is no dedicated `handle` column in the twins table. A
-- functional unique index on the JSON path is the correct DB-level
-- equivalent of a UNIQUE constraint here.
--
-- NOTE: plain CREATE INDEX takes a brief ACCESS EXCLUSIVE lock while
-- building. The twins table is small; for a much larger future table prefer
-- CREATE INDEX CONCURRENTLY (which cannot run inside a transaction block).
--
-- CAUTION FOR THE HUMAN REVIEWER APPLYING THIS MIGRATION: if any environment
-- already has two twins with the same lower(settings->>'handle') value, this
-- CREATE UNIQUE INDEX will fail. Run this check first and resolve duplicates
-- (rename or clear one twin's handle) before applying:
--
--   SELECT lower(settings->>'handle') AS handle, array_agg(id) AS twin_ids
--   FROM twins
--   WHERE settings->>'handle' IS NOT NULL
--   GROUP BY lower(settings->>'handle')
--   HAVING count(*) > 1;

CREATE UNIQUE INDEX IF NOT EXISTS idx_twins_handle_unique
    ON twins (lower(settings->>'handle'))
    WHERE settings->>'handle' IS NOT NULL;

-- =============================================================================
-- Reserved-words guard (defense in depth — routers/handles.py already checks
-- this list in application code before it ever reaches the database; this
-- CHECK constraint is a backstop against any write path that bypasses the
-- router, e.g. a future admin script, RPC, or direct SQL).
--
-- List is the union of routers/handles.py's RESERVED_HANDLES plus every
-- top-level route segment under frontend/app/ (about, admin, api, auth,
-- blog, dashboard, experience, help, legal, m, marketplace, onboarding, p,
-- pricing, share, v2, widget), plus a small set of conventional reserved
-- infra words (www, static, assets, null, undefined, favicon, robots,
-- sitemap). Keep this list and RESERVED_HANDLES in sync — if you add a
-- route segment to frontend/app/, add it here too, and vice versa.
--
-- DROP-then-ADD (repo convention, CLAUDE.md) so re-running this migration
-- (or a future migration that extends the list) never hits a duplicate
-- constraint-name error.

ALTER TABLE twins DROP CONSTRAINT IF EXISTS twins_handle_not_reserved;

ALTER TABLE twins ADD CONSTRAINT twins_handle_not_reserved CHECK (
    settings->>'handle' IS NULL
    OR lower(settings->>'handle') NOT IN (
        'admin', 'api', 'app', 'auth', 'dashboard', 'login', 'signup',
        'settings', 'help', 'support', 'about', 'terms', 'privacy', 'p',
        'blog', 'experience', 'legal', 'm', 'marketplace', 'onboarding',
        'pricing', 'share', 'v2', 'widget',
        'www', 'static', 'assets', 'null', 'undefined', 'favicon',
        'robots', 'sitemap'
    )
);
