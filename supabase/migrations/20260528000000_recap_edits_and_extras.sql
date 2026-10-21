-- =============================================================================
-- Layer 2 / Commit A1: recap_edits audit table + graph_outbox op extension.
--
-- Adds infrastructure for:
--   * Capturing every user edit to a meeting recap (issue #105: "every edit
--     trains the twin"). Append-only audit log; each row records the field
--     that was edited, the before/after snapshots, and which of the five
--     twin stores it should train (Facts | Positions | Style | Boundaries
--     | Relationships per issue #108). The store_routing column is set by
--     a downstream LLM-routing worker (Phase D).
--   * Two new graph_outbox operations:
--       - send_action_item_reminder        (Phase C: deferred email reminder)
--       - route_recap_edit_to_store        (Phase D: LLM-classified routing)
--
-- meetings.summary_json + meetings.action_items already exist (added in
-- 20260416_meeting_analytics.sql) — no additive column work needed here.
-- =============================================================================

-- 1. recap_edits — append-only audit of every recap correction.
CREATE TABLE IF NOT EXISTS recap_edits (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id uuid NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    tenant_id uuid NOT NULL,
    user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
    -- Which recap field was edited. Mirrors keys in meetings.summary_json
    -- plus the leadership-spec extras (intent, what_happened, commitments).
    field text NOT NULL CHECK (field IN (
        'tldr',
        'topics',
        'action_items',
        'key_questions',
        'intent',
        'what_happened',
        'commitments'
    )),
    before jsonb,           -- snapshot of summary_json[field] before this edit
    after  jsonb NOT NULL,  -- snapshot after this edit
    -- Which twin store this edit will train (per issue #108).
    -- NULL until the LLM-routing worker (Phase D) classifies it.
    store_routing text CHECK (store_routing IS NULL OR store_routing IN (
        'facts',
        'positions',
        'style',
        'boundaries',
        'relationships'
    )),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Per-meeting timeline (newest first)
CREATE INDEX IF NOT EXISTS idx_recap_edits_meeting
    ON recap_edits(meeting_id, created_at DESC);

-- Worker queue: find unrouted edits per tenant, oldest first
CREATE INDEX IF NOT EXISTS idx_recap_edits_unrouted
    ON recap_edits(tenant_id, created_at ASC)
    WHERE store_routing IS NULL;

ALTER TABLE recap_edits ENABLE ROW LEVEL SECURITY;

-- Owners can read their own edit history (useful for audit / undo UI later).
CREATE POLICY recap_edits_owner_read ON recap_edits FOR SELECT
    USING (auth.uid() = tenant_id);

-- Writes go through the backend service-role key. RLS allows it implicitly
-- (service role bypasses); no explicit service policy needed for INSERT —
-- documented here for clarity. Direct user inserts are not allowed (no INSERT
-- policy for the owner) so the audit trail cannot be forged client-side.

-- =============================================================================
-- 2. Extend graph_outbox_operation_check.
--
-- TEAM DEBT (carried forward from 25b7d6f): this DROP+ADD pattern requires
-- every future migration that adds an operation to copy the full list. If
-- two migrations land out of order the later one silently drops the earlier
-- addition. Canonicalise via a single-source migration when bandwidth allows.
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
    'prep_meeting_context',
    'stripe_meter_event',
    'send_lifecycle_email',
    'process_desktop_sdk_recording',   -- Layer 1
    'send_action_item_reminder',        -- Layer 2, Phase C
    'route_recap_edit_to_store'         -- Layer 2, Phase D
]::text[]));
