-- Add organization and linkedin_url fields to waitlist for richer lead context
ALTER TABLE public.waitlist
    ADD COLUMN IF NOT EXISTS organization text,
    ADD COLUMN IF NOT EXISTS linkedin_url text;
