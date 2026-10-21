-- Corrective migration: repair the graph_outbox_operation_check regression.
--
-- Several prior migrations (20260527 desktop_sdk, the graph_outbox_ops_* set)
-- redefined this CHECK with operation lists that REGRESSED — they dropped live
-- operations such as `send_lifecycle_email` and `persona_research` that the
-- worker still uses. On a database with rows for those ops, the ADD CONSTRAINT
-- fails; on an empty one it silently narrows what the worker may enqueue,
-- breaking those job types going forward.
--
-- This sets the constraint to the complete superset: the current
-- GraphOperationType enum (backend/modules/graph_outbox.py) plus every legacy
-- operation present in prior migrations / live data. A superset CHECK rejects
-- nothing valid and breaks no worker. DROP-then-ADD per the repo convention
-- (see 20260601000100_graph_outbox_ops_link_contacts.sql).

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
    'send_lifecycle_email',
    'stripe_meter_event',
    'update_claim_status',
    'warm_meeting_cache',
    -- legacy operations retained for back-compat with existing rows
    'action_item_reminder',
    'bot',
    'desktop_sdk',
    'manual',
    'post_meeting_followup',
    'pre_meeting_briefing',
    'weekly_digest'
  ));
