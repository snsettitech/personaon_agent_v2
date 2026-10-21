-- Persistent trial-used marker so a no-card trial cannot be reused after expiry.
-- The lazy-downgrade in quota.py and plan_guard.py clears trial_kind + trial_ends_at
-- when an expired trial is detected, which previously left the user able to call
-- POST /billing/start-trial-no-card again. This column is set on first trial start
-- and never cleared — it's the lifetime "trial consumed" marker.

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS no_card_trial_used_at TIMESTAMPTZ;

-- Backfill: any user who currently has trial_kind='no_card' has already consumed
-- their trial; mark them now so the new gate works for them too.
UPDATE public.users
SET no_card_trial_used_at = COALESCE(no_card_trial_used_at, trial_ends_at, NOW())
WHERE trial_kind = 'no_card' AND no_card_trial_used_at IS NULL;
