ALTER TABLE public.graph_outbox DROP CONSTRAINT IF EXISTS graph_outbox_operation_check;
ALTER TABLE public.graph_outbox ADD CONSTRAINT graph_outbox_operation_check
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
    'process_desktop_sdk_recording',
    'send_action_item_reminder',
    'route_recap_edit_to_store',
    'link_meeting_contacts',            -- Phase F.2: People surface identity linking
    'extract_commitments'               -- Batch A: Extract action-item commitments
]::text[]));
