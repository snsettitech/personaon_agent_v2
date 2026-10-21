-- Granola Batch 5: register the `recap_timeout_check` graph_outbox operation.
-- A reliability watchdog: a delayed job enqueued at Stop that flips a recording
-- stuck in a non-terminal recap state past a timeout to a failed state, so the
-- UI shows "failed" instead of an eternal spinner. It NEVER touches a row that
-- is already completed/ready (precondition guard lives in the handler).
--
-- A user-visible failure reason the watchdog stamps when it flips a stuck
-- recording, so the UI can render WHY enhancement failed (not just a red state).
-- recap_stage intentionally gets NO 'failed' value: its CHECK constraint
-- (20260611000000) only allows the forward-progress stages, so status='failed'
-- + enhanced_notes_status='failed' are the authoritative terminal signals.
ALTER TABLE public.meetings
  ADD COLUMN IF NOT EXISTS recap_error_reason text;

-- CHECK constraints cannot be altered in place, so DROP-before-ADD the FULL
-- operation allowlist, carrying forward every op from
-- 20260612000200_graph_outbox_ops_enhance.sql plus recap_timeout_check.
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
    'extract_commitments',              -- Batch A: Extract action-item commitments
    'extract_memory_candidates',        -- Batch B: Extract memory candidates
    'recall_calendar_sync',             -- Phase 30-D: Recall.ai Calendar V2 sync
    'resolve_meeting_speakers',         -- Phase 30-K: resolve meeting speakers
    'generate_deep_brief',              -- staging: deep-brief generation
    'enhance_notes',                    -- Granola Batch 3: AI-merge enhanced notes
    'recap_timeout_check'               -- Granola Batch 5: stuck-recap watchdog
]::text[]));
