-- Add notification flow operations to graph_outbox.
-- Carries forward the full latest operation list from
-- 20260619000100_graph_outbox_ops_send_followup.sql.

ALTER TABLE public.graph_outbox DROP CONSTRAINT IF EXISTS graph_outbox_operation_check;

ALTER TABLE public.graph_outbox ADD CONSTRAINT graph_outbox_operation_check
  CHECK (operation IN (
    -- current GraphOperationType enum
    'create_claims',
    'create_episode',
    'create_relationship',
    'delete_twin_graph',
    'enhance_notes',
    'enrich_from_web',
    'enrich_twin_responses',
    'evaluate_contradictions',
    'extract_claims',
    'extract_commitments',
    'extract_memory_candidates',
    'firecrawl_extract',
    'generate_deep_brief',
    'generate_meeting_briefing',
    'generate_meeting_followup',
    'generate_meeting_summary',
    'generate_weekly_digest',
    'index_meeting_transcript',
    'link_meeting_contacts',
    'persona_research',
    'prep_meeting_context',
    'process_desktop_sdk_recording',
    'process_meeting_transcript',
    'recall_calendar_sync',
    'recap_timeout_check',
    'refresh_snapshot',
    'resolve_meeting_speakers',
    'route_recap_edit_to_store',
    'schedule_meeting_bot',
    'send_action_item_reminder',
    'send_followup_draft',
    'send_lifecycle_email',
    'stripe_meter_event',
    'update_claim_status',
    'warm_meeting_cache',
    'run_notification_flow',
    'process_notification_event',
    'measure_notification_outcome',
    -- legacy operations retained for back-compat with existing rows
    'action_item_reminder',
    'bot',
    'desktop_sdk',
    'manual',
    'post_meeting_followup',
    'pre_meeting_briefing',
    'weekly_digest'
  ));
