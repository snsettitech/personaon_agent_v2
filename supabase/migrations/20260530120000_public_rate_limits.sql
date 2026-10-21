-- H2: shared-store rate limiting for the public (unauthenticated) chat endpoint.
-- The previous limiter was an in-process dict, so limits reset per Cloud Run
-- instance and per restart — effectively no limit in production. This moves the
-- counter to Postgres (shared across all instances).
--
-- Infra table (keyed by IP/twin bucket, pre-auth) — intentionally NOT
-- tenant-scoped; the standard tenant_id/RLS-by-tenant convention does not apply.

CREATE TABLE IF NOT EXISTS public.public_rate_limits (
  bucket text NOT NULL,
  window_start timestamptz NOT NULL,
  hits integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (bucket, window_start)
);

-- Stale-window cleanup helper index (sweep job can delete old windows).
CREATE INDEX IF NOT EXISTS idx_prl_window ON public.public_rate_limits (window_start);

ALTER TABLE public.public_rate_limits ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS public_rate_limits_service ON public.public_rate_limits;
CREATE POLICY public_rate_limits_service ON public.public_rate_limits
  FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');

-- Atomic fixed-window increment. Returns the post-increment hit count for the
-- bucket's current window. SECURITY DEFINER so it works regardless of the
-- caller's role (bypasses the service-role RLS above).
DROP FUNCTION IF EXISTS public.bump_public_rate_limit(text, integer) CASCADE;
CREATE OR REPLACE FUNCTION public.bump_public_rate_limit(p_bucket text, p_window_seconds integer)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_window timestamptz;
  v_hits integer;
BEGIN
  v_window := to_timestamp(floor(extract(epoch from now()) / p_window_seconds) * p_window_seconds);
  INSERT INTO public.public_rate_limits (bucket, window_start, hits)
    VALUES (p_bucket, v_window, 1)
  ON CONFLICT (bucket, window_start)
    DO UPDATE SET hits = public.public_rate_limits.hits + 1
  RETURNING hits INTO v_hits;
  RETURN v_hits;
END;
$$;
