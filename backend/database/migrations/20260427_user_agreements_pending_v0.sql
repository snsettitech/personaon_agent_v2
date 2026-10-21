-- Temporary onboarding consent capture.
-- Final legal document versioning will reuse this table with real versions.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS user_agreements (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  terms_version TEXT NOT NULL,
  privacy_version TEXT NOT NULL,
  consent_text TEXT NOT NULL,
  accepted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ip_address TEXT,
  user_agent TEXT,
  auth_provider TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (user_id, terms_version, privacy_version)
);

CREATE INDEX IF NOT EXISTS idx_user_agreements_user_id
  ON user_agreements(user_id);

CREATE INDEX IF NOT EXISTS idx_user_agreements_versions
  ON user_agreements(terms_version, privacy_version);
