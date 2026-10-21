-- Phase 4: Billing schema
-- All ADD COLUMN IF NOT EXISTS and CREATE TABLE IF NOT EXISTS — safe to re-run.

-- ── 1. Add billing columns to users ─────────────────────────────────────
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS plan TEXT NOT NULL DEFAULT 'free',
    ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;

ALTER TABLE public.users
    DROP CONSTRAINT IF EXISTS users_plan_check;
ALTER TABLE public.users
    ADD CONSTRAINT users_plan_check
        CHECK (plan IN ('free', 'pro', 'business', 'believer'));

-- ── 2. Subscriptions table ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.subscriptions (
    id                     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                UUID        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    stripe_customer_id     TEXT        NOT NULL,
    stripe_subscription_id TEXT,
    price_lookup_key       TEXT,
    tier                   TEXT        NOT NULL DEFAULT 'free',
    status                 TEXT        NOT NULL DEFAULT 'inactive',
    current_period_end     TIMESTAMPTZ,
    cancel_at_period_end   BOOLEAN     NOT NULL DEFAULT false,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS subscriptions_user_id_idx
    ON public.subscriptions(user_id);

CREATE UNIQUE INDEX IF NOT EXISTS subscriptions_stripe_sub_id_idx
    ON public.subscriptions(stripe_subscription_id)
    WHERE stripe_subscription_id IS NOT NULL;

ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "subscriptions_owner_select" ON public.subscriptions;
CREATE POLICY "subscriptions_owner_select" ON public.subscriptions
    FOR SELECT USING (user_id = auth.uid());

DROP POLICY IF EXISTS "subscriptions_service_all" ON public.subscriptions;
CREATE POLICY "subscriptions_service_all" ON public.subscriptions
    FOR ALL USING (auth.role() = 'service_role');

-- ── 3. Webhook idempotency table ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.stripe_webhook_events (
    stripe_event_id TEXT        PRIMARY KEY,
    event_type      TEXT        NOT NULL,
    processed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.stripe_webhook_events ENABLE ROW LEVEL SECURITY;
-- backend uses service key for all access; no user-facing policy needed (deny-by-default)

-- ── 4. Unique index on stripe_customer_id ────────────────────────────────
CREATE UNIQUE INDEX IF NOT EXISTS users_stripe_customer_id_idx
    ON public.users(stripe_customer_id)
    WHERE stripe_customer_id IS NOT NULL;
