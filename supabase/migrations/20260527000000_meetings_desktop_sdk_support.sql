-- =============================================================================
-- Layer 1 / Commit 1: Extend `meetings` table to support Recall.ai Desktop SDK
-- recordings alongside the existing meeting-bot pipeline.
--
-- Adds:
--   * recall_sdk_upload_id   (UNIQUE)  webhook lookup key for SDK-path uploads
--   * recall_recording_id              Recall's recording UUID (both paths)
--   * source                 ('bot' | 'desktop_sdk' | 'manual')
--   * platform               raw window/meeting platform string
--   * transcript_url, transcript_provider, video_url, speaker_timeline_url
--                            cached signed URLs from Recall.ai
--
-- Loosens twin_id (NOT NULL -> nullable) so ad-hoc desktop audio captures
-- without a tied twin are storable. RLS still gates rows by tenant_id.
--
-- Extends meetings.status to include 'uploading' (between recording and
-- processing) and 'deleted' (soft-delete).
--
-- Extends graph_outbox_operation_check to allow the new
-- 'process_desktop_sdk_recording' worker operation.
-- =============================================================================

-- New columns
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS recall_sdk_upload_id   text;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS recall_recording_id    text;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS source                 text NOT NULL DEFAULT 'bot';
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS platform               text;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS transcript_url         text;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS transcript_provider    text;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS video_url              text;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS speaker_timeline_url   text;

-- Uniqueness on the SDK upload id (idempotent: skip if already present from a
-- previous partial run). NULL-friendly.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'meetings_recall_sdk_upload_id_key'
    ) THEN
        ALTER TABLE meetings
            ADD CONSTRAINT meetings_recall_sdk_upload_id_key
            UNIQUE (recall_sdk_upload_id);
    END IF;
END $$;

-- Twin association is optional for ad-hoc desktop recordings
ALTER TABLE meetings ALTER COLUMN twin_id DROP NOT NULL;

-- Source discriminator
ALTER TABLE meetings DROP CONSTRAINT IF EXISTS meetings_source_check;
ALTER TABLE meetings ADD CONSTRAINT meetings_source_check
    CHECK (source IN ('bot', 'desktop_sdk', 'manual'));

-- Extend status lifecycle.
-- Previous CHECK allowed only: scheduled, bot_joining, recording, processing,
-- completed, failed. We add 'uploading' (Recall is still streaming chunks to
-- S3) and 'deleted' (soft delete).
ALTER TABLE meetings DROP CONSTRAINT IF EXISTS meetings_status_check;
ALTER TABLE meetings ADD CONSTRAINT meetings_status_check
    CHECK (status IN (
        'scheduled',
        'bot_joining',
        'recording',
        'uploading',
        'processing',
        'completed',
        'failed',
        'deleted'
    ));

-- Webhook lookup indexes (partial — only rows that actually have these IDs)
CREATE INDEX IF NOT EXISTS idx_meetings_recall_sdk_upload_id
    ON meetings(recall_sdk_upload_id)
    WHERE recall_sdk_upload_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_meetings_recall_recording_id
    ON meetings(recall_recording_id)
    WHERE recall_recording_id IS NOT NULL;

-- Listing query support: per-tenant, newest-first, hide soft-deleted.
CREATE INDEX IF NOT EXISTS idx_meetings_tenant_created
    ON meetings(tenant_id, created_at DESC)
    WHERE status <> 'deleted';

-- =============================================================================
-- Extend graph_outbox_operation_check to allow process_desktop_sdk_recording.
-- Mirrors the pattern in 20260421230000_graph_outbox_operation_check_extend.sql
-- =============================================================================

ALTER TABLE graph_outbox DROP CONSTRAINT IF EXISTS graph_outbox_operation_check;

ALTER TABLE graph_outbox ADD CONSTRAINT graph_outbox_operation_check
CHECK (operation = ANY (ARRAY[
    'create_episode',
    'create_claims',
    'update_claim_status',
    'create_relationship',
    'delete_twin_graph',
    'extract_claims',
    'evaluate_contradictions',
    'refresh_snapshot',
    'persona_research',
    'firecrawl_extract',
    'enrich_from_web',
    'schedule_meeting_bot',
    'process_meeting_transcript',
    'generate_meeting_summary',
    'warm_meeting_cache',
    'index_meeting_transcript',
    'generate_meeting_briefing',
    'generate_meeting_followup',
    'generate_weekly_digest',
    'enrich_twin_responses',
    'process_desktop_sdk_recording'
]::text[]));
