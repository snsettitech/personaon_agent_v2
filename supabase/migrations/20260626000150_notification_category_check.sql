-- Expand lifecycle email categories for account and announcement notifications.
-- This must land before code emits account/announcements rows; otherwise the
-- lifecycle claim helper treats CHECK failures like duplicate claims.

ALTER TABLE public.lifecycle_email_events
    DROP CONSTRAINT IF EXISTS lifecycle_email_events_category_check;

ALTER TABLE public.lifecycle_email_events
    ADD CONSTRAINT lifecycle_email_events_category_check
    CHECK (category IN (
        'product_education',
        'daily_activity',
        'weekly_report',
        'hot_lead_alert',
        'meeting_recap',
        'meeting_brief',
        'account',
        'announcements'
    ));
