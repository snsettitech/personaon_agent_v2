-- Trial tracking columns on users table.
-- Supports two trial paths:
--   1. card_required (Stripe-managed): users.subscription_status='trialing' on subscriptions row, no extra column needed
--   2. no_card (DB-only, 7 days): trial_ends_at + trial_kind='no_card' set on users row, no Stripe involvement
--
-- plan_guard reads users.trial_ends_at when trial_kind='no_card' and treats user as Pro tier
-- if trial_ends_at > now(), else falls back to free.

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS trial_kind TEXT;

ALTER TABLE public.users
    DROP CONSTRAINT IF EXISTS users_trial_kind_check;
ALTER TABLE public.users
    ADD CONSTRAINT users_trial_kind_check
        CHECK (trial_kind IS NULL OR trial_kind IN ('no_card', 'card_required'));

-- Index for cron job that downgrades expired no-card trials.
CREATE INDEX IF NOT EXISTS users_trial_ends_at_idx
    ON public.users(trial_ends_at)
    WHERE trial_kind = 'no_card' AND trial_ends_at IS NOT NULL;
