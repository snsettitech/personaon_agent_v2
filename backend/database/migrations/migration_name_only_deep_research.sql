-- ============================================================================
-- Name-Only Deep Research (Production Flow)
-- ============================================================================
-- Adds persistence for:
-- - research runs
-- - discovered/crawled sources
-- - extracted page content
-- - final JSON artifact
--
-- Created: 2026-02-25
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Runs
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS name_deep_research_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    created_by TEXT NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'created',

    input_name TEXT NOT NULL,
    input_location TEXT,
    input_company TEXT,
    input_website TEXT,
    idempotency_key TEXT,

    queries_used JSONB NOT NULL DEFAULT '[]'::jsonb,
    urls_considered INTEGER NOT NULL DEFAULT 0,
    urls_crawled INTEGER NOT NULL DEFAULT 0,
    urls_blocked INTEGER NOT NULL DEFAULT 0,
    words_extracted INTEGER NOT NULL DEFAULT 0,
    sources_used_in_final INTEGER NOT NULL DEFAULT 0,

    selected_model TEXT,
    error_message TEXT,

    run_started_at TIMESTAMPTZ,
    run_completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT valid_name_research_status CHECK (
        status IN (
            'created',
            'searching',
            'crawling',
            'extracting',
            'synthesizing',
            'completed',
            'failed'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_name_research_runs_tenant_created
ON name_deep_research_runs(tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_name_research_runs_status
ON name_deep_research_runs(status);

CREATE UNIQUE INDEX IF NOT EXISTS idx_name_research_runs_idempotency
ON name_deep_research_runs(tenant_id, idempotency_key)
WHERE idempotency_key IS NOT NULL;

-- ----------------------------------------------------------------------------
-- Sources
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS name_deep_research_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES name_deep_research_runs(id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,

    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    title TEXT,
    source_type VARCHAR(40) NOT NULL DEFAULT 'other',
    published_at TIMESTAMPTZ,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    content_quality VARCHAR(40) NOT NULL DEFAULT 'partial',
    identity_match_confidence FLOAT NOT NULL DEFAULT 0.0,
    used_in_final BOOLEAN NOT NULL DEFAULT FALSE,
    blocked_reason TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT valid_name_research_source_type CHECK (
        source_type IN ('website', 'linkedin', 'youtube', 'news', 'podcast', 'profile', 'other')
    ),
    CONSTRAINT valid_name_research_quality CHECK (
        content_quality IN ('full', 'partial', 'blocked', 'manual_needed')
    ),
    CONSTRAINT valid_identity_match_confidence CHECK (
        identity_match_confidence >= 0.0 AND identity_match_confidence <= 1.0
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_name_research_sources_unique
ON name_deep_research_sources(run_id, canonical_url);

CREATE INDEX IF NOT EXISTS idx_name_research_sources_run
ON name_deep_research_sources(run_id);

CREATE INDEX IF NOT EXISTS idx_name_research_sources_used
ON name_deep_research_sources(run_id, used_in_final)
WHERE used_in_final = TRUE;

-- ----------------------------------------------------------------------------
-- Pages
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS name_deep_research_pages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES name_deep_research_runs(id) ON DELETE CASCADE,
    source_id UUID REFERENCES name_deep_research_sources(id) ON DELETE SET NULL,
    tenant_id TEXT NOT NULL,

    canonical_url TEXT NOT NULL,
    extracted_text TEXT NOT NULL DEFAULT '',
    extracted_word_count INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_name_research_pages_run
ON name_deep_research_pages(run_id);

CREATE INDEX IF NOT EXISTS idx_name_research_pages_source
ON name_deep_research_pages(source_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_name_research_pages_run_url
ON name_deep_research_pages(run_id, canonical_url);

-- ----------------------------------------------------------------------------
-- Final Artifact
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS name_deep_research_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL UNIQUE REFERENCES name_deep_research_runs(id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT 'v1',
    result_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_name_research_artifacts_tenant
ON name_deep_research_artifacts(tenant_id, created_at DESC);

-- ----------------------------------------------------------------------------
-- Trigger: updated_at maintenance
-- ----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_name_research_updated_at') THEN
        CREATE FUNCTION update_name_research_updated_at()
        RETURNS TRIGGER AS $func$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $func$ LANGUAGE plpgsql;
    END IF;
END $$;

DROP TRIGGER IF EXISTS trigger_name_research_runs_updated_at ON name_deep_research_runs;
CREATE TRIGGER trigger_name_research_runs_updated_at
    BEFORE UPDATE ON name_deep_research_runs
    FOR EACH ROW
    EXECUTE FUNCTION update_name_research_updated_at();

DROP TRIGGER IF EXISTS trigger_name_research_sources_updated_at ON name_deep_research_sources;
CREATE TRIGGER trigger_name_research_sources_updated_at
    BEFORE UPDATE ON name_deep_research_sources
    FOR EACH ROW
    EXECUTE FUNCTION update_name_research_updated_at();

DROP TRIGGER IF EXISTS trigger_name_research_pages_updated_at ON name_deep_research_pages;
CREATE TRIGGER trigger_name_research_pages_updated_at
    BEFORE UPDATE ON name_deep_research_pages
    FOR EACH ROW
    EXECUTE FUNCTION update_name_research_updated_at();

DROP TRIGGER IF EXISTS trigger_name_research_artifacts_updated_at ON name_deep_research_artifacts;
CREATE TRIGGER trigger_name_research_artifacts_updated_at
    BEFORE UPDATE ON name_deep_research_artifacts
    FOR EACH ROW
    EXECUTE FUNCTION update_name_research_updated_at();

-- ----------------------------------------------------------------------------
-- Comments
-- ----------------------------------------------------------------------------
COMMENT ON TABLE name_deep_research_runs IS
'Name-only deep research pipeline run state.';

COMMENT ON TABLE name_deep_research_sources IS
'Discovered and crawled sources for a name-only run.';

COMMENT ON TABLE name_deep_research_pages IS
'Extracted page-level content and metadata for name-only runs.';

COMMENT ON TABLE name_deep_research_artifacts IS
'Final grounded JSON result for a name-only deep research run.';

-- ----------------------------------------------------------------------------
-- Rollback (manual)
-- ----------------------------------------------------------------------------
-- DROP TABLE IF EXISTS name_deep_research_artifacts CASCADE;
-- DROP TABLE IF EXISTS name_deep_research_pages CASCADE;
-- DROP TABLE IF EXISTS name_deep_research_sources CASCADE;
-- DROP TABLE IF EXISTS name_deep_research_runs CASCADE;
-- DROP FUNCTION IF EXISTS update_name_research_updated_at() CASCADE;
