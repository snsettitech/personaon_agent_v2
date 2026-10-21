-- =====================================================
-- Connected Accounts (LinkedIn, etc.)
-- =====================================================
-- Stores OAuth-connected social accounts for users.
-- Used for "Connect LinkedIn" in onboarding and profile badges.
-- =====================================================

CREATE TABLE IF NOT EXISTS connected_accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    provider_user_id TEXT,
    profile_snapshot JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_connected_accounts_user_id ON connected_accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_connected_accounts_provider ON connected_accounts(provider);

-- RLS: users can only access their own connected accounts
ALTER TABLE connected_accounts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS connected_accounts_select_own ON connected_accounts;
CREATE POLICY connected_accounts_select_own ON connected_accounts
    FOR SELECT USING (user_id = auth.uid());

DROP POLICY IF EXISTS connected_accounts_insert_own ON connected_accounts;
CREATE POLICY connected_accounts_insert_own ON connected_accounts
    FOR INSERT WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS connected_accounts_update_own ON connected_accounts;
CREATE POLICY connected_accounts_update_own ON connected_accounts
    FOR UPDATE USING (user_id = auth.uid());

DROP POLICY IF EXISTS connected_accounts_delete_own ON connected_accounts;
CREATE POLICY connected_accounts_delete_own ON connected_accounts
    FOR DELETE USING (user_id = auth.uid());
