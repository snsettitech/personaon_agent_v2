-- PON-7 follow-up: composite tenant FKs + atomic correct RPC.
-- Staging already applied 20260924000000 without composite FKs; this upgrades
-- that environment. Fresh applies of the updated 20260924000000 already include
-- these objects — this file is a no-op when they already exist.

-- Parent uniqueness for composite FK targets
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.professional_profiles'::regclass
      AND contype = 'u'
      AND pg_get_constraintdef(oid) LIKE '%(id, tenant_id)%'
  ) THEN
    ALTER TABLE public.professional_profiles
      ADD CONSTRAINT professional_profiles_id_tenant_key UNIQUE (id, tenant_id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.profile_claims'::regclass
      AND contype = 'u'
      AND pg_get_constraintdef(oid) LIKE '%(id, tenant_id)%'
  ) THEN
    ALTER TABLE public.profile_claims
      ADD CONSTRAINT profile_claims_id_tenant_key UNIQUE (id, tenant_id);
  END IF;
END $$;

-- Drop legacy single-column FKs (staging-applied 000000 names)
ALTER TABLE public.profile_claims
  DROP CONSTRAINT IF EXISTS profile_claims_profile_id_fkey;
ALTER TABLE public.profile_claims
  DROP CONSTRAINT IF EXISTS profile_claims_supersedes_claim_id_fkey;
ALTER TABLE public.claim_evidence
  DROP CONSTRAINT IF EXISTS claim_evidence_claim_id_fkey;
ALTER TABLE public.profile_views
  DROP CONSTRAINT IF EXISTS profile_views_profile_id_fkey;

-- Add composite FKs only when no matching composite FK already exists
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.profile_claims'::regclass
      AND contype = 'f'
      AND pg_get_constraintdef(oid) LIKE '%(profile_id, tenant_id)%'
      AND pg_get_constraintdef(oid) LIKE '%professional_profiles%'
  ) THEN
    ALTER TABLE public.profile_claims
      ADD CONSTRAINT profile_claims_profile_tenant_fkey
      FOREIGN KEY (profile_id, tenant_id)
      REFERENCES public.professional_profiles(id, tenant_id)
      ON DELETE CASCADE;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.profile_claims'::regclass
      AND contype = 'f'
      AND pg_get_constraintdef(oid) LIKE '%(supersedes_claim_id, tenant_id)%'
  ) THEN
    ALTER TABLE public.profile_claims
      ADD CONSTRAINT profile_claims_supersedes_tenant_fkey
      FOREIGN KEY (supersedes_claim_id, tenant_id)
      REFERENCES public.profile_claims(id, tenant_id)
      ON DELETE SET NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.claim_evidence'::regclass
      AND contype = 'f'
      AND pg_get_constraintdef(oid) LIKE '%(claim_id, tenant_id)%'
  ) THEN
    ALTER TABLE public.claim_evidence
      ADD CONSTRAINT claim_evidence_claim_tenant_fkey
      FOREIGN KEY (claim_id, tenant_id)
      REFERENCES public.profile_claims(id, tenant_id)
      ON DELETE CASCADE;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.profile_views'::regclass
      AND contype = 'f'
      AND pg_get_constraintdef(oid) LIKE '%(profile_id, tenant_id)%'
  ) THEN
    ALTER TABLE public.profile_views
      ADD CONSTRAINT profile_views_profile_tenant_fkey
      FOREIGN KEY (profile_id, tenant_id)
      REFERENCES public.professional_profiles(id, tenant_id)
      ON DELETE CASCADE;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION public.correct_profile_claim(
  p_claim_id uuid,
  p_tenant_id uuid,
  p_profile_id uuid,
  p_claim_type text,
  p_value_json jsonb,
  p_value_text text,
  p_reviewed_by uuid,
  p_confidence real DEFAULT NULL,
  p_fingerprint text DEFAULT NULL
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_state text;
  v_new_id uuid := gen_random_uuid();
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role'
     AND auth.uid() IS DISTINCT FROM p_tenant_id THEN
    RAISE EXCEPTION 'correct_profile_claim: forbidden';
  END IF;

  SELECT state INTO v_state
  FROM public.profile_claims
  WHERE id = p_claim_id
    AND tenant_id = p_tenant_id
    AND profile_id = p_profile_id
  FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'correct_profile_claim: claim not found';
  END IF;

  IF v_state NOT IN ('approved', 'proposed') THEN
    RAISE EXCEPTION 'correct_profile_claim: cannot correct state=%', v_state;
  END IF;

  UPDATE public.profile_claims
  SET state = 'superseded',
      updated_at = now()
  WHERE id = p_claim_id
    AND tenant_id = p_tenant_id;

  INSERT INTO public.profile_claims (
    id, tenant_id, profile_id, claim_type, value_json, value_text,
    state, created_by, supersedes_claim_id, confidence, fingerprint
  ) VALUES (
    v_new_id, p_tenant_id, p_profile_id, p_claim_type, p_value_json, p_value_text,
    'proposed', 'owner', p_claim_id, p_confidence, p_fingerprint
  );

  RETURN v_new_id;
END;
$$;

REVOKE ALL ON FUNCTION public.correct_profile_claim(
  uuid, uuid, uuid, text, jsonb, text, uuid, real, text
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.correct_profile_claim(
  uuid, uuid, uuid, text, jsonb, text, uuid, real, text
) TO authenticated, service_role;
