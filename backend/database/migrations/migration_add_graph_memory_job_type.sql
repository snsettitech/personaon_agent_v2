-- Migration: Add graph_memory job type
-- Purpose: Prevent jobs-table constraint failures when graph-memory jobs are inserted.

ALTER TABLE jobs DROP CONSTRAINT IF EXISTS valid_job_type;

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

