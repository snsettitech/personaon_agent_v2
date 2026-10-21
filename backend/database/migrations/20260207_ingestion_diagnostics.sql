-- 20260207_ingestion_diagnostics.sql
-- Unified ingestion diagnostics:
-- - sources.last_* fields for UI surfacing
-- - source_events timeline for step-by-step debugging

-- Ensure UUID generator exists (Supabase usually provides it).
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1) Extend sources with diagnostics fields
ALTER TABLE sources
  ADD COLUMN IF NOT EXISTS last_provider TEXT,
  ADD COLUMN IF NOT EXISTS last_step TEXT,
  ADD COLUMN IF NOT EXISTS last_error JSONB,
  ADD COLUMN IF NOT EXISTS last_error_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS last_event_at TIMESTAMPTZ;

COMMENT ON COLUMN sources.last_provider IS 'Last ingestion provider that updated this source (youtube/x/linkedin/web/file/podcast).';
COMMENT ON COLUMN sources.last_step IS 'Last ingestion step reached (queued/fetching/parsed/chunked/embedded/indexed/live/error).';
COMMENT ON COLUMN sources.last_error IS 'Last ingestion error object (sanitized).';
COMMENT ON COLUMN sources.last_error_at IS 'Timestamp of last_error.';
COMMENT ON COLUMN sources.last_event_at IS 'Timestamp of the most recent ingestion step event.';

-- 2) Step timeline table
CREATE TABLE IF NOT EXISTS source_events (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  step TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('started', 'completed', 'error')),
  message TEXT,
  metadata JSONB DEFAULT '{}'::jsonb,
  error JSONB,
  correlation_id TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ended_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_source_events_source_created_at ON source_events(source_id, created_at);
CREATE INDEX IF NOT EXISTS idx_source_events_twin_created_at ON source_events(twin_id, created_at);

-- 3) Security: prevent diagnostics data leakage via Supabase REST.
ALTER TABLE source_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant Isolation: View Source Events" ON source_events;

CREATE POLICY "Tenant Isolation: View Source Events" ON source_events
FOR SELECT
USING (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = source_events.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);
