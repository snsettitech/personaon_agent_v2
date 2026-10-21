-- PR4: mark captured emails as unverified (no double opt-in on the public surface).
-- Lets the owner UI / hot-lead alert flag a contact as unconfirmed, and is a guard
-- against email-injection abuse (a captured address is not proven to belong to the
-- sender). ADD COLUMN IF NOT EXISTS — safe to re-run on existing production tables.

ALTER TABLE public.widget_leads
    ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT false;
