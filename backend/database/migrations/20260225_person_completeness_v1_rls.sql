-- ============================================================================
-- Person Completeness Layer v1 - RLS Hardening
-- ============================================================================
-- Enables row-level security and tenant isolation policies for all
-- person_* tables introduced in 20260225_person_completeness_v1_core.sql.
--
-- NOTE:
-- - Application writes use service-role credentials.
-- - Authenticated end-user access is restricted by tenant via twins.tenant_id.
-- ============================================================================

ALTER TABLE IF EXISTS person_source_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS person_claims ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS person_claim_evidence_spans ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS person_timeline_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS person_topic_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS person_style_profile ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS person_contradictions ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS person_answerability_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS person_runtime_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS person_completeness_runs ENABLE ROW LEVEL SECURITY;

-- --------------------------------------------------------------------------
-- Drop existing policies (idempotent)
-- --------------------------------------------------------------------------

DROP POLICY IF EXISTS "Tenant Isolation: View Person Source Registry" ON person_source_registry;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Person Source Registry" ON person_source_registry;
DROP POLICY IF EXISTS "Tenant Isolation: View Person Claims" ON person_claims;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Person Claims" ON person_claims;
DROP POLICY IF EXISTS "Tenant Isolation: View Person Claim Evidence Spans" ON person_claim_evidence_spans;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Person Claim Evidence Spans" ON person_claim_evidence_spans;
DROP POLICY IF EXISTS "Tenant Isolation: View Person Timeline Events" ON person_timeline_events;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Person Timeline Events" ON person_timeline_events;
DROP POLICY IF EXISTS "Tenant Isolation: View Person Topic Profiles" ON person_topic_profiles;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Person Topic Profiles" ON person_topic_profiles;
DROP POLICY IF EXISTS "Tenant Isolation: View Person Style Profile" ON person_style_profile;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Person Style Profile" ON person_style_profile;
DROP POLICY IF EXISTS "Tenant Isolation: View Person Contradictions" ON person_contradictions;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Person Contradictions" ON person_contradictions;
DROP POLICY IF EXISTS "Tenant Isolation: View Person Answerability Scores" ON person_answerability_scores;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Person Answerability Scores" ON person_answerability_scores;
DROP POLICY IF EXISTS "Tenant Isolation: View Person Runtime Policies" ON person_runtime_policies;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Person Runtime Policies" ON person_runtime_policies;
DROP POLICY IF EXISTS "Tenant Isolation: View Person Completeness Runs" ON person_completeness_runs;
DROP POLICY IF EXISTS "Tenant Isolation: Modify Person Completeness Runs" ON person_completeness_runs;

-- --------------------------------------------------------------------------
-- Tenant-isolated SELECT policies
-- --------------------------------------------------------------------------

CREATE POLICY "Tenant Isolation: View Person Source Registry" ON person_source_registry
FOR SELECT
USING (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_source_registry.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: View Person Claims" ON person_claims
FOR SELECT
USING (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_claims.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: View Person Claim Evidence Spans" ON person_claim_evidence_spans
FOR SELECT
USING (
  EXISTS (
    SELECT 1
    FROM person_claims pc
    JOIN person_source_registry psr ON psr.id = person_claim_evidence_spans.source_registry_id
    JOIN twins t ON t.id = pc.twin_id
    WHERE pc.id = person_claim_evidence_spans.claim_id
      AND psr.twin_id = pc.twin_id
      AND t.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: View Person Timeline Events" ON person_timeline_events
FOR SELECT
USING (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_timeline_events.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: View Person Topic Profiles" ON person_topic_profiles
FOR SELECT
USING (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_topic_profiles.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: View Person Style Profile" ON person_style_profile
FOR SELECT
USING (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_style_profile.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: View Person Contradictions" ON person_contradictions
FOR SELECT
USING (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_contradictions.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: View Person Answerability Scores" ON person_answerability_scores
FOR SELECT
USING (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_answerability_scores.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: View Person Runtime Policies" ON person_runtime_policies
FOR SELECT
USING (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_runtime_policies.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: View Person Completeness Runs" ON person_completeness_runs
FOR SELECT
USING (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_completeness_runs.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

-- --------------------------------------------------------------------------
-- Tenant-isolated write policies
-- --------------------------------------------------------------------------

CREATE POLICY "Tenant Isolation: Modify Person Source Registry" ON person_source_registry
FOR ALL
USING (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_source_registry.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_source_registry.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Person Claims" ON person_claims
FOR ALL
USING (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_claims.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_claims.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Person Claim Evidence Spans" ON person_claim_evidence_spans
FOR ALL
USING (
  EXISTS (
    SELECT 1
    FROM person_claims pc
    JOIN person_source_registry psr ON psr.id = person_claim_evidence_spans.source_registry_id
    JOIN twins t ON t.id = pc.twin_id
    WHERE pc.id = person_claim_evidence_spans.claim_id
      AND psr.twin_id = pc.twin_id
      AND t.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1
    FROM person_claims pc
    JOIN person_source_registry psr ON psr.id = person_claim_evidence_spans.source_registry_id
    JOIN twins t ON t.id = pc.twin_id
    WHERE pc.id = person_claim_evidence_spans.claim_id
      AND psr.twin_id = pc.twin_id
      AND t.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Person Timeline Events" ON person_timeline_events
FOR ALL
USING (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_timeline_events.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_timeline_events.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Person Topic Profiles" ON person_topic_profiles
FOR ALL
USING (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_topic_profiles.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_topic_profiles.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Person Style Profile" ON person_style_profile
FOR ALL
USING (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_style_profile.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_style_profile.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Person Contradictions" ON person_contradictions
FOR ALL
USING (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_contradictions.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_contradictions.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Person Answerability Scores" ON person_answerability_scores
FOR ALL
USING (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_answerability_scores.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_answerability_scores.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Person Runtime Policies" ON person_runtime_policies
FOR ALL
USING (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_runtime_policies.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_runtime_policies.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

CREATE POLICY "Tenant Isolation: Modify Person Completeness Runs" ON person_completeness_runs
FOR ALL
USING (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_completeness_runs.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
)
WITH CHECK (
  EXISTS (
    SELECT 1
    FROM twins
    WHERE twins.id = person_completeness_runs.twin_id
      AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

-- ============================================================================
-- Migration complete
-- ============================================================================
