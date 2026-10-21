-- Phase 30-K: Allow resolve_meeting_speakers operation in graph_outbox.
-- On Recall bot.done, the meetings webhook enqueues this job alongside the
-- existing process_meeting_transcript job to resolve diarization labels
-- (speaker_0, speaker_1, ...) to person entities (nodes table) using the
-- participant list from GET /api/v1/bot/{bot_id}.
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
    'recall_calendar_sync',
    'resolve_meeting_speakers'
]::text[]));
