-- Add a lifecycle preference gate for announcement emails.

ALTER TABLE public.notification_preferences
    ADD COLUMN IF NOT EXISTS announcements_enabled BOOLEAN NOT NULL DEFAULT TRUE;
