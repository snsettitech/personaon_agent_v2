-- Phase 30-D: Allow recall_calendar_sync operation in graph_outbox.
-- Webhook from Recall.ai Calendar V2 enqueues this job to fetch updated
-- calendar events (GET /api/v2/calendars/{id}/calendar-events/?updated_at__gte=...)
-- and upsert them into the meetings table.
--
-- Migration linter requires DROP-before-CREATE for CHECK constraints.

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
    'prep_meeting_context',
    'stripe_meter_event',
    'send_lifecycle_email',
    'recall_calendar_sync'
]::text[]));
