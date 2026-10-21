-- Migration: Add feedback_learning job type
-- Purpose: Support async persona feedback-learning jobs in the jobs table

-- Drop old constraint so we can extend the enum-like check.
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS valid_job_type;

-- Recreate as a superset so reruns are safe even after other job-type migrations.
ALTER TABLE jobs ADD CONSTRAINT valid_job_type CHECK (
    job_type IN (
        'ingestion',
        'reindex',
        'health_check',
        'other',
        'realtime_ingestion',
        'graph_extraction',
        'content_extraction',
        'feedback_learning',
        'graph_memory'
    )
);
