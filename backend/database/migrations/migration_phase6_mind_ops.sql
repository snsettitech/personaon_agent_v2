-- Phase 6: Mind Ops Layer Migration
-- This migration creates the staging workflow, training jobs, health checks, and observability tables

-- 1. Training Jobs table
CREATE TABLE IF NOT EXISTS training_jobs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'processing', 'needs_attention', 'complete', 'failed')),
  job_type TEXT NOT NULL CHECK (job_type IN ('ingestion', 'reindex', 'health_check')),
  priority INTEGER NOT NULL DEFAULT 0,
  error_message TEXT,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ
);

-- 2. Ingestion Logs table
CREATE TABLE IF NOT EXISTS ingestion_logs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  log_level TEXT NOT NULL CHECK (log_level IN ('info', 'warning', 'error')),
  message TEXT NOT NULL,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Content Health Checks table
CREATE TABLE IF NOT EXISTS content_health_checks (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  check_type TEXT NOT NULL CHECK (check_type IN ('empty_extraction', 'duplicate', 'chunk_anomaly', 'missing_metadata')),
  status TEXT NOT NULL CHECK (status IN ('pass', 'fail', 'warning')),
  message TEXT,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Modify sources table - Add new columns
ALTER TABLE sources ADD COLUMN IF NOT EXISTS staging_status TEXT CHECK (staging_status IN ('staged', 'approved', 'rejected', 'training', 'live')) DEFAULT 'staged';
ALTER TABLE sources ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS publish_date TIMESTAMPTZ;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS author TEXT;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS citation_url TEXT;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS keep_synced BOOLEAN DEFAULT false;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS sync_config JSONB DEFAULT '{}'::jsonb;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS health_status TEXT CHECK (health_status IN ('healthy', 'needs_attention', 'failed')) DEFAULT 'healthy';
ALTER TABLE sources ADD COLUMN IF NOT EXISTS chunk_count INTEGER;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS extracted_text_length INTEGER;

-- Extend status enum to include new values
-- Note: PostgreSQL doesn't support ALTER TYPE easily, so we'll use a CHECK constraint instead
-- First, drop the old constraint if it exists
ALTER TABLE sources DROP CONSTRAINT IF EXISTS sources_status_check;
-- Add new constraint with extended values
ALTER TABLE sources ADD CONSTRAINT sources_status_check CHECK (status IN ('pending', 'processing', 'processed', 'error', 'staged', 'approved', 'rejected', 'training', 'live', 'needs_attention'));

-- 5. Create indexes
CREATE INDEX IF NOT EXISTS idx_training_jobs_status_twin ON training_jobs(status, twin_id);
CREATE INDEX IF NOT EXISTS idx_training_jobs_source ON training_jobs(source_id);
CREATE INDEX IF NOT EXISTS idx_ingestion_logs_source ON ingestion_logs(source_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sources_staging_status ON sources(twin_id, staging_status);
CREATE INDEX IF NOT EXISTS idx_sources_content_hash ON sources(twin_id, content_hash);
CREATE INDEX IF NOT EXISTS idx_content_health_checks_source ON content_health_checks(source_id);

-- 6. Migration: Set existing sources to 'live' status
-- For backward compatibility, existing sources should be marked as 'live'
UPDATE sources 
SET 
  staging_status = 'live',
  status = CASE 
    WHEN status = 'processed' THEN 'live'
    WHEN status = 'pending' THEN 'staged'
    WHEN status = 'processing' THEN 'training'
    ELSE status
  END,
  health_status = 'healthy'
WHERE staging_status IS NULL;

-- 7. Add updated_at trigger for training_jobs
CREATE OR REPLACE FUNCTION update_training_jobs_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER training_jobs_updated_at
  BEFORE UPDATE ON training_jobs
  FOR EACH ROW
  EXECUTE FUNCTION update_training_jobs_updated_at();

-- 8. Add updated_at trigger for content_health_checks
CREATE OR REPLACE FUNCTION update_content_health_checks_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER content_health_checks_updated_at
  BEFORE UPDATE ON content_health_checks
  FOR EACH ROW
  EXECUTE FUNCTION update_content_health_checks_updated_at();

