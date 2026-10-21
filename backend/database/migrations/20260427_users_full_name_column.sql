-- Add full_name column to public.users so OAuth metadata can be persisted.
--
-- Context: backend/routers/auth.py sync_user computes full_name from OAuth
-- metadata (Google name, LinkedIn display_name, etc.) and returns it in the
-- SyncUserResponse, but the schema had no column to store it. Result: every
-- internal feature reading public.users (admin tools, billing emails, lead
-- capture) saw NULL identity for OAuth users.
--
-- This migration is idempotent and NULL-safe. Existing rows remain unchanged
-- and pick up full_name on next /auth/sync-user call (the returning-user
-- path in auth.py backfills NULL columns from OAuth metadata).

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS full_name TEXT;

COMMENT ON COLUMN public.users.full_name IS
    'User display name from OAuth metadata or self-set. May be NULL for legacy rows.';
