-- Fix: search_twin_all SECURITY DEFINER was missing tenant ownership check.
-- Any authenticated user could query any twin's data by passing an arbitrary p_twin.
-- This migration replaces the function with one that validates the caller owns p_twin.

DROP FUNCTION IF EXISTS public.search_twin_all(uuid, text);

CREATE OR REPLACE FUNCTION public.search_twin_all(p_twin uuid, p_q text)
RETURNS TABLE (kind text, id uuid, label text, hint text, ord real)
LANGUAGE sql STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  -- Security: caller must own this twin. auth.uid() is the Supabase JWT subject.
  -- If the caller does not own p_twin, the subquery returns no rows and nothing is returned.
  WITH ownership_check AS (
    SELECT 1
    FROM public.twins t
    WHERE t.id = p_twin
      AND t.tenant_id = (SELECT auth.uid())
  )
  SELECT
    'person'::text AS kind,
    c.id,
    c.name AS label,
    COALESCE(c.email, '') AS hint,
    word_similarity(c.name, p_q) AS ord
  FROM public.contacts c
  WHERE c.twin_id = p_twin
    AND c.name %> p_q
    AND EXISTS (SELECT 1 FROM ownership_check)
  UNION ALL
  SELECT
    'meeting'::text,
    m.id,
    COALESCE(m.title, 'Untitled meeting'),
    '',
    word_similarity(COALESCE(m.title, ''), p_q)
  FROM public.meetings m
  WHERE m.twin_id = p_twin
    AND COALESCE(m.title, '') %> p_q
    AND EXISTS (SELECT 1 FROM ownership_check)
  UNION ALL
  SELECT
    'commitment'::text,
    mc.id,
    mc.text,
    mc.direction,
    word_similarity(mc.text, p_q)
  FROM public.meeting_commitments mc
  WHERE mc.twin_id = p_twin
    AND mc.text %> p_q
    AND EXISTS (SELECT 1 FROM ownership_check)
  UNION ALL
  SELECT
    'memory'::text,
    cand.id,
    cand.text,
    cand.subject,
    word_similarity(cand.text, p_q)
  FROM public.memory_candidates cand
  WHERE cand.twin_id = p_twin
    AND cand.status = 'approved'
    AND cand.text %> p_q
    AND EXISTS (SELECT 1 FROM ownership_check)
  ORDER BY ord DESC
  LIMIT 40;
$$;

GRANT EXECUTE ON FUNCTION public.search_twin_all(uuid, text) TO authenticated, service_role;
