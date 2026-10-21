-- =====================================================
-- Fix OAuth User Creation Error
-- =====================================================
-- This migration fixes the "Database error saving new user" error
-- that occurs when users sign up via OAuth.
--
-- Problem:
-- - The `users` table requires `tenant_id` (NOT NULL)
-- - When OAuth signup happens, Supabase tries to create a user record
-- - But `tenant_id` doesn't exist yet (it's created by /auth/sync-user)
-- - This causes a constraint violation: "Database error saving new user"
--
-- Solution:
-- - Make `tenant_id` nullable in the `users` table
-- - Update the /auth/sync-user endpoint to create tenant first, then update user
-- - This allows OAuth signup to succeed even if tenant doesn't exist yet
-- =====================================================

-- Step 1: Make tenant_id nullable in users table
ALTER TABLE users 
    ALTER COLUMN tenant_id DROP NOT NULL;

-- Step 2: Add a comment to document why tenant_id is nullable
COMMENT ON COLUMN users.tenant_id IS 
    'Nullable to allow OAuth signup before tenant creation. Set by /auth/sync-user endpoint.';

-- Note: The /auth/sync-user endpoint logic should be updated to:
-- 1. Check if user exists (if yes, return existing user)
-- 2. If user doesn't exist:
--    a. Create tenant first
--    b. Create user with tenant_id
--    c. OR create user without tenant_id, then update it after tenant creation

