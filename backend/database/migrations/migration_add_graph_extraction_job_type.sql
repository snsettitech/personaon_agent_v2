-- Migration: Add graph_extraction job type
-- Purpose: Support graph extraction jobs in the jobs table

-- Drop the old constraint
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS valid_job_type;

-- Add constraint as a superset so reruns are safe even after later job-type migrations.
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

