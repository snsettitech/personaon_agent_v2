-- Phase 5: Quota counters on subscriptions + users, plus believer_seats tracking.
-- All ADD COLUMN IF NOT EXISTS — safe to re-run.

-- ── 1. Quota counters on subscriptions ───────────────────────────────────
ALTER TABLE public.subscriptions
    ADD COLUMN IF NOT EXISTS messages_this_period       INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS voice_minutes_this_period  INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS bot_minutes_this_period    INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS period_started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS subscriptions_user_id_period_idx
    ON public.subscriptions(user_id, period_started_at DESC);

-- ── 2. Free-tier quota tracking on users (no subscriptions row exists) ─
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS messages_this_period       INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS voice_minutes_this_period  INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS period_started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- ── 3. Believer seat tracking ─────────────────────────────────────────────
-- Single-row table that atomically counts sold Believer seats.
CREATE TABLE IF NOT EXISTS public.believer_seats (
    id          INTEGER     PRIMARY KEY DEFAULT 1,
    seats_sold  INTEGER     NOT NULL DEFAULT 0,
    seats_cap   INTEGER     NOT NULL DEFAULT 50,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT believer_seats_single_row CHECK (id = 1),
    CONSTRAINT believer_seats_within_cap CHECK (seats_sold <= seats_cap)
);

INSERT INTO public.believer_seats (id) VALUES (1)
    ON CONFLICT (id) DO NOTHING;

ALTER TABLE public.believer_seats ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "believer_seats_public_read" ON public.believer_seats;
CREATE POLICY "believer_seats_public_read" ON public.believer_seats
    FOR SELECT USING (true);

DROP POLICY IF EXISTS "believer_seats_service_write" ON public.believer_seats;
CREATE POLICY "believer_seats_service_write" ON public.believer_seats
    FOR ALL USING (auth.role() = 'service_role');
