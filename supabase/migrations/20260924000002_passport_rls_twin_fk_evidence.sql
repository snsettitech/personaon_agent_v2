-- PON-7 follow-up: RLS via users.tenant_id, twin composite FK, evidence twin
-- check, and supersedes ON DELETE SET NULL (supersedes_claim_id only).
-- Idempotent against staging already on 000000+000001.

-- twins (id, tenant_id) for professional_profiles composite FK
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.twins'::regclass
      AND contype = 'u'
      AND pg_get_constraintdef(oid) LIKE '%(id, tenant_id)%'
  ) THEN
    ALTER TABLE public.twins
      ADD CONSTRAINT twins_id_tenant_key UNIQUE (id, tenant_id);
  END IF;
END $$;

-- Drop legacy single-column twin FK; add composite (twin_id, tenant_id)
ALTER TABLE public.professional_profiles
  DROP CONSTRAINT IF EXISTS professional_profiles_twin_id_fkey;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.professional_profiles'::regclass
      AND contype = 'f'
      AND pg_get_constraintdef(oid) LIKE '%(twin_id, tenant_id)%'
  ) THEN
    ALTER TABLE public.professional_profiles
      ADD CONSTRAINT professional_profiles_twin_tenant_fkey
      FOREIGN KEY (twin_id, tenant_id)
      REFERENCES public.twins(id, tenant_id)
      ON DELETE CASCADE;
  END IF;
END $$;

-- Recreate supersedes FK with column-specific SET NULL (PG15+)
ALTER TABLE public.profile_claims
  DROP CONSTRAINT IF EXISTS profile_claims_supersedes_tenant_fkey;
-- Also drop auto-named composite from greenfield 000000 if present
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'public.profile_claims'::regclass
      AND contype = 'f'
      AND pg_get_constraintdef(oid) LIKE '%(supersedes_claim_id, tenant_id)%'
  LOOP
    EXECUTE format('ALTER TABLE public.profile_claims DROP CONSTRAINT %I', r.conname);
  END LOOP;
END $$;

ALTER TABLE public.profile_claims
  ADD CONSTRAINT profile_claims_supersedes_tenant_fkey
  FOREIGN KEY (supersedes_claim_id, tenant_id)
  REFERENCES public.profile_claims(id, tenant_id)
  ON DELETE SET NULL (supersedes_claim_id);

-- Evidence source must share the claim's twin (sources has twin_id, not tenant_id)
CREATE OR REPLACE FUNCTION public.claim_evidence_source_twin_check()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
  v_claim_twin uuid;
  v_source_twin uuid;
BEGIN
  IF NEW.source_id IS NULL THEN
    RETURN NEW;
  END IF;

  SELECT pp.twin_id INTO v_claim_twin
  FROM public.profile_claims pc
  JOIN public.professional_profiles pp
    ON pp.id = pc.profile_id AND pp.tenant_id = pc.tenant_id
  WHERE pc.id = NEW.claim_id
    AND pc.tenant_id = NEW.tenant_id;

  IF v_claim_twin IS NULL THEN
    RAISE EXCEPTION 'claim_evidence: claim not found for tenant';
  END IF;

  SELECT s.twin_id INTO v_source_twin
  FROM public.sources s
  WHERE s.id = NEW.source_id;

  IF v_source_twin IS NULL THEN
    RAISE EXCEPTION 'claim_evidence: source not found';
  END IF;

  IF v_source_twin IS DISTINCT FROM v_claim_twin THEN
    RAISE EXCEPTION 'claim_evidence: source twin does not match claim twin';
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_claim_evidence_source_twin ON public.claim_evidence;
CREATE TRIGGER trg_claim_evidence_source_twin
  BEFORE INSERT OR UPDATE OF source_id, claim_id, tenant_id
  ON public.claim_evidence
  FOR EACH ROW
  EXECUTE FUNCTION public.claim_evidence_source_twin_check();

-- correct_profile_claim: authorize via users.tenant_id membership
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
     AND NOT EXISTS (
       SELECT 1 FROM public.users u
       WHERE u.id = auth.uid() AND u.tenant_id = p_tenant_id
     ) THEN
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

-- RLS: replace auth.uid()=tenant_id with users.tenant_id membership
DROP POLICY IF EXISTS pprof_owner_select ON public.professional_profiles;
CREATE POLICY pprof_owner_select ON public.professional_profiles FOR SELECT
  USING (
    tenant_id = (SELECT u.tenant_id FROM public.users u WHERE u.id = (SELECT auth.uid()))
  );
DROP POLICY IF EXISTS pprof_owner_insert ON public.professional_profiles;
CREATE POLICY pprof_owner_insert ON public.professional_profiles FOR INSERT
  WITH CHECK (
    tenant_id = (SELECT u.tenant_id FROM public.users u WHERE u.id = (SELECT auth.uid()))
  );
DROP POLICY IF EXISTS pprof_owner_update ON public.professional_profiles;
CREATE POLICY pprof_owner_update ON public.professional_profiles FOR UPDATE
  USING (
    tenant_id = (SELECT u.tenant_id FROM public.users u WHERE u.id = (SELECT auth.uid()))
  );

DROP POLICY IF EXISTS pclaim_owner_select ON public.profile_claims;
CREATE POLICY pclaim_owner_select ON public.profile_claims FOR SELECT
  USING (
    tenant_id = (SELECT u.tenant_id FROM public.users u WHERE u.id = (SELECT auth.uid()))
  );
DROP POLICY IF EXISTS pclaim_owner_insert ON public.profile_claims;
CREATE POLICY pclaim_owner_insert ON public.profile_claims FOR INSERT
  WITH CHECK (
    tenant_id = (SELECT u.tenant_id FROM public.users u WHERE u.id = (SELECT auth.uid()))
  );
DROP POLICY IF EXISTS pclaim_owner_update ON public.profile_claims;
CREATE POLICY pclaim_owner_update ON public.profile_claims FOR UPDATE
  USING (
    tenant_id = (SELECT u.tenant_id FROM public.users u WHERE u.id = (SELECT auth.uid()))
  );

DROP POLICY IF EXISTS cev_owner_select ON public.claim_evidence;
CREATE POLICY cev_owner_select ON public.claim_evidence FOR SELECT
  USING (
    tenant_id = (SELECT u.tenant_id FROM public.users u WHERE u.id = (SELECT auth.uid()))
  );
DROP POLICY IF EXISTS cev_owner_insert ON public.claim_evidence;
CREATE POLICY cev_owner_insert ON public.claim_evidence FOR INSERT
  WITH CHECK (
    tenant_id = (SELECT u.tenant_id FROM public.users u WHERE u.id = (SELECT auth.uid()))
  );

DROP POLICY IF EXISTS pview_owner_select ON public.profile_views;
CREATE POLICY pview_owner_select ON public.profile_views FOR SELECT
  USING (
    tenant_id = (SELECT u.tenant_id FROM public.users u WHERE u.id = (SELECT auth.uid()))
  );
DROP POLICY IF EXISTS pview_owner_write ON public.profile_views;
CREATE POLICY pview_owner_write ON public.profile_views FOR ALL
  USING (
    tenant_id = (SELECT u.tenant_id FROM public.users u WHERE u.id = (SELECT auth.uid()))
  );
