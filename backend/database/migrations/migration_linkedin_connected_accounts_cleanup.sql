-- Normalize legacy LinkedIn connected accounts to linkedin_oidc and
-- remove synthetic profile URLs created from opaque provider IDs.

-- If both legacy linkedin and linkedin_oidc rows exist for the same user,
-- keep the linkedin_oidc row and drop the legacy duplicate first.
DELETE FROM connected_accounts legacy
USING connected_accounts canonical
WHERE legacy.user_id = canonical.user_id
  AND legacy.provider = 'linkedin'
  AND canonical.provider = 'linkedin_oidc';

-- Rename remaining legacy provider rows.
UPDATE connected_accounts
SET provider = 'linkedin_oidc'
WHERE provider = 'linkedin';

-- Remove fake LinkedIn profile URLs that were synthesized from provider IDs.
UPDATE connected_accounts
SET profile_snapshot = COALESCE(profile_snapshot, '{}'::jsonb) - 'profile_url'
WHERE provider = 'linkedin_oidc'
  AND provider_user_id IS NOT NULL
  AND profile_snapshot ->> 'profile_url' = CONCAT('https://www.linkedin.com/in/', provider_user_id);
