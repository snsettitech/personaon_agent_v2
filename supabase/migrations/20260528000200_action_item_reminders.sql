-- Phase 30 / Commit C1: action item reminder preferences + notification type.

ALTER TABLE public.notification_preferences
    ADD COLUMN IF NOT EXISTS action_item_reminders_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS action_item_lead_time_minutes INT NOT NULL DEFAULT 60
        CHECK (action_item_lead_time_minutes >= 0 AND action_item_lead_time_minutes <= 10080);

-- TEAM DEBT (F5.2 review fix; mirrors the same note on
-- graph_outbox_operation_check in 20260528000000_recap_edits_and_extras.sql):
-- this DROP+ADD pattern requires every future migration that adds a
-- notification_type to copy the full enum list below. If two migrations land
-- out of order the later one silently drops the earlier addition.
-- Canonicalise via a single-source enum or a dedicated lookup table when
-- bandwidth allows.
ALTER TABLE public.meeting_notifications
    DROP CONSTRAINT IF EXISTS meeting_notifications_notification_type_check;

ALTER TABLE public.meeting_notifications
    ADD CONSTRAINT meeting_notifications_notification_type_check
    CHECK (notification_type IN (
        'pre_meeting_briefing',
        'post_meeting_followup',
        'weekly_digest',
        'action_item_reminder'
    ));
