-- Fix: replace partial unique index on stripe_subscription_id with a proper UNIQUE constraint.
-- PostgREST's upsert (ON CONFLICT col) cannot use partial indexes; it requires a full constraint.
-- Postgres UNIQUE constraints allow multiple NULLs, so behaviour is identical to the partial index.

DROP INDEX IF EXISTS subscriptions_stripe_sub_id_idx;

ALTER TABLE public.subscriptions
    DROP CONSTRAINT IF EXISTS subscriptions_stripe_sub_id_key;

ALTER TABLE public.subscriptions
    ADD CONSTRAINT subscriptions_stripe_sub_id_key
        UNIQUE (stripe_subscription_id);
