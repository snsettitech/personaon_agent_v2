-- Passport thin stack (PON-7 / ADR-001 Approach B)
-- Apply to STAGING first. Prod blocked by docs/engineering/SPRINT_1_GATE.md
--
-- Child rows carry tenant_id and reference parent via composite
-- (id, tenant_id) FKs so a caller cannot attach claims/evidence/views to
-- another tenant's profile by guessing UUIDs.
-- RLS authorizes via public.users.tenant_id (not auth.uid() = tenant_id),
-- matching resolve_tenant_id which may mint a distinct tenant UUID.

-- twins (id, tenant_id) target for professional_profiles composite FK
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

CREATE TABLE IF NOT EXISTS public.professional_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL,
  twin_id uuid NOT NULL,
  owner_user_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'active', 'archived')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (twin_id),
  UNIQUE (tenant_id, owner_user_id),
  UNIQUE (id, tenant_id),
  FOREIGN KEY (twin_id, tenant_id)
    REFERENCES public.twins(id, tenant_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pprof_tenant ON public.professional_profiles(tenant_id);
CREATE INDEX IF NOT EXISTS idx_pprof_owner ON public.professional_profiles(owner_user_id);

CREATE TABLE IF NOT EXISTS public.profile_claims (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL,
  profile_id uuid NOT NULL,
  claim_type text NOT NULL CHECK (claim_type IN (
    'full_name', 'headline', 'bio', 'work_experience', 'education',
    'skill', 'project', 'credential', 'preference', 'social_link'
  )),
  value_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  value_text text NOT NULL DEFAULT '',
  state text NOT NULL DEFAULT 'proposed'
    CHECK (state IN ('proposed', 'approved', 'rejected', 'superseded')),
  confidence real CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  extraction_version text,
  fingerprint text,
  supersedes_claim_id uuid,
  created_by text NOT NULL DEFAULT 'system'
    CHECK (created_by IN ('import', 'owner', 'agent', 'system')),
  reviewed_at timestamptz,
  reviewed_by uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, tenant_id),
  FOREIGN KEY (profile_id, tenant_id)
    REFERENCES public.professional_profiles(id, tenant_id) ON DELETE CASCADE,
  -- PG15+: null only the history pointer; tenant_id stays NOT NULL
  FOREIGN KEY (supersedes_claim_id, tenant_id)
    REFERENCES public.profile_claims(id, tenant_id)
    ON DELETE SET NULL (supersedes_claim_id)
);

CREATE INDEX IF NOT EXISTS idx_pclaim_profile ON public.profile_claims(profile_id);
CREATE INDEX IF NOT EXISTS idx_pclaim_profile_state ON public.profile_claims(profile_id, state);
CREATE INDEX IF NOT EXISTS idx_pclaim_profile_type ON public.profile_claims(profile_id, claim_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pclaim_fingerprint_active
  ON public.profile_claims(profile_id, fingerprint)
  WHERE fingerprint IS NOT NULL AND state IN ('proposed', 'approved');

CREATE TABLE IF NOT EXISTS public.claim_evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL,
  claim_id uuid NOT NULL,
  source_id uuid REFERENCES public.sources(id) ON DELETE SET NULL,
  excerpt text,
  locator jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (claim_id, tenant_id)
    REFERENCES public.profile_claims(id, tenant_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cev_claim ON public.claim_evidence(claim_id);
CREATE INDEX IF NOT EXISTS idx_cev_source ON public.claim_evidence(source_id);

-- sources has twin_id but no tenant_id; enforce same-twin provenance via trigger.
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

CREATE TABLE IF NOT EXISTS public.profile_views (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL,
  profile_id uuid NOT NULL,
  view_key text NOT NULL
    CHECK (view_key IN ('public', 'link_only', 'private')),
  is_active boolean NOT NULL DEFAULT false,
  projection_version int NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (profile_id, view_key),
  FOREIGN KEY (profile_id, tenant_id)
    REFERENCES public.professional_profiles(id, tenant_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pview_profile ON public.profile_views(profile_id);

CREATE INDEX IF NOT EXISTS idx_pclaim_tenant ON public.profile_claims(tenant_id);
CREATE INDEX IF NOT EXISTS idx_cev_tenant ON public.claim_evidence(tenant_id);
CREATE INDEX IF NOT EXISTS idx_pview_tenant ON public.profile_views(tenant_id);

-- Atomic correct: supersede old + insert replacement in one transaction.
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
  -- Service role (backend) or users.tenant_id membership (not auth.uid()=tenant_id).
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

ALTER TABLE public.professional_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profile_claims ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.claim_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profile_views ENABLE ROW LEVEL SECURITY;

-- Owner policies: membership via users.tenant_id (resolve_tenant_id may != auth.uid())
-- professional_profiles
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
DROP POLICY IF EXISTS pprof_service_all ON public.professional_profiles;
CREATE POLICY pprof_service_all ON public.professional_profiles FOR ALL
  USING (auth.role() = 'service_role');

-- profile_claims
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
DROP POLICY IF EXISTS pclaim_service_all ON public.profile_claims;
CREATE POLICY pclaim_service_all ON public.profile_claims FOR ALL
  USING (auth.role() = 'service_role');

-- claim_evidence
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
DROP POLICY IF EXISTS cev_service_all ON public.claim_evidence;
CREATE POLICY cev_service_all ON public.claim_evidence FOR ALL
  USING (auth.role() = 'service_role');

-- profile_views
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
DROP POLICY IF EXISTS pview_service_all ON public.profile_views;
CREATE POLICY pview_service_all ON public.profile_views FOR ALL
  USING (auth.role() = 'service_role');
