-- =============================================================================
-- Phase 28: Proactive Notifications — meeting_notifications table
-- Tracks all email notifications sent (briefings, followups, weekly digests).
-- Unique constraints prevent duplicate sends for the same meeting/notification.
-- =============================================================================

CREATE TABLE IF NOT EXISTS meeting_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    meeting_id UUID REFERENCES meetings(id) ON DELETE SET NULL,
    notification_type TEXT NOT NULL
        CHECK (notification_type IN ('pre_meeting_briefing', 'post_meeting_followup', 'weekly_digest')),
    status TEXT NOT NULL DEFAULT 'sent'
        CHECK (status IN ('sent', 'skipped', 'failed')),
    resend_message_id TEXT,
    error_message TEXT,
    -- Populated for weekly_digest rows to enforce once-per-week uniqueness.
    -- Set to the Monday (start) of the current ISO week (UTC) by the worker.
    -- NULL for meeting-specific notification types.
    week_of DATE,
    sent_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (twin_id, meeting_id, notification_type)
);

-- Prevent sending more than one weekly digest per twin per calendar week.
-- Uses a plain DATE column (week_of) to avoid IMMUTABLE function requirement.
CREATE UNIQUE INDEX IF NOT EXISTS meeting_notifications_weekly_digest_unique
    ON meeting_notifications (twin_id, notification_type, week_of)
    WHERE notification_type = 'weekly_digest';

-- Query indexes
CREATE INDEX IF NOT EXISTS idx_meeting_notifications_twin_id
    ON meeting_notifications (twin_id);
CREATE INDEX IF NOT EXISTS idx_meeting_notifications_meeting_id
    ON meeting_notifications (meeting_id)
    WHERE meeting_id IS NOT NULL;

-- Row-level security
ALTER TABLE meeting_notifications ENABLE ROW LEVEL SECURITY;
CREATE POLICY meeting_notifications_tenant_policy ON meeting_notifications
    FOR ALL USING (tenant_id = auth.uid()) WITH CHECK (tenant_id = auth.uid());
CREATE POLICY meeting_notifications_service_policy ON meeting_notifications
    FOR ALL USING (auth.role() = 'service_role');
