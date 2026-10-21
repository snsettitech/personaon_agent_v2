-- Migration: Add avatar_url column to users table
-- Purpose: Store user avatar URLs from OAuth providers
-- Status: CRITICAL BLOCKER - Auth endpoint requires this column

-- Add avatar_url column if it doesn't exist
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT;

-- Add comment for documentation
COMMENT ON COLUMN users.avatar_url IS 'User avatar URL from OAuth provider (Supabase Auth)';

-- Create index for potential future lookups
CREATE INDEX IF NOT EXISTS idx_users_avatar_url ON users(avatar_url) WHERE avatar_url IS NOT NULL;

-- Verification query (run this to confirm the fix worked)
-- SELECT column_name, data_type FROM information_schema.columns 
-- WHERE table_name = 'users' AND column_name = 'avatar_url';
