-- Add iCalendar UID column + new cross-platform stable unique index on meetings.
--
-- Background: the existing unique index
--
--   idx_meetings_provider_event_unique
--   ON public.meetings(twin_id, provider,
--                      COALESCE(provider_calendar_id, ''),
--                      provider_event_id,
--                      COALESCE(provider_event_instance_id, ''))
--   WHERE provider IS NOT NULL AND provider_event_id IS NOT NULL;
--
-- includes provider_calendar_id in the key. Recall.ai assigns a NEW
-- recall_calendar_id (which we store as provider_calendar_id) every time
-- a user disconnects+reconnects their calendar. The SAME underlying Google
-- or Outlook event therefore inserts a NEW row under each Recall calendar
-- id, producing duplicate meeting rows for the same real-world meeting.
--
-- iCalendar UID (RFC 5545) is a stable, provider-independent identifier
-- for the underlying calendar event. Recall normalizes both Google's
-- iCalUID and Outlook's iCalUId into the top-level `ical_uid` field.
-- Keying meetings uniqueness by (twin_id, ical_uid, instance) eliminates
-- the cross-calendar duplication while keeping recurring event instances
-- distinct.
--
-- Rollout is additive:
--   * Add the column (NULL allowed during transition / for non-calendar rows).
--   * Add the new partial unique index (only enforces when ical_uid IS NOT NULL).
--   * Old unique index stays in place; new code writes both keys, lookups
--     prefer ical_uid then fall back to legacy. Once backfill + dedup
--     scripts have run and all calendar-synced rows carry ical_uid, a
--     follow-up migration can drop the legacy index.

ALTER TABLE public.meetings ADD COLUMN IF NOT EXISTS ical_uid TEXT;

-- New cross-platform stable uniqueness key. Partial so it only enforces
-- on calendar-synced rows; booking-flow / desktop-recording meetings (which
-- legitimately have ical_uid = NULL) are unaffected.
--
-- provider_event_instance_id is included so individual occurrences of a
-- recurring series stay distinct (the master series shares one ical_uid
-- across all instances; instance_id is what distinguishes occurrences).
CREATE UNIQUE INDEX IF NOT EXISTS idx_meetings_ical_uid_unique
    ON public.meetings(
        twin_id,
        ical_uid,
        COALESCE(provider_event_instance_id, '')
    )
    WHERE ical_uid IS NOT NULL;

-- Lookup index for the backfill script + ad-hoc reporting.
CREATE INDEX IF NOT EXISTS idx_meetings_ical_uid
    ON public.meetings(ical_uid)
    WHERE ical_uid IS NOT NULL;
