-- Add last_active_at column to users table
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active_at TIMESTAMPTZ;

-- Create index for performance on sorting by activity
CREATE INDEX IF NOT EXISTS idx_users_last_active_at ON users(last_active_at DESC);
