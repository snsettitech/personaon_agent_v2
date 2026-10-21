-- Fan-out search RPC using pg_trgm word similarity (%> operator).
-- The %> operator uses the GIN trigram indexes from 20260607000000.
-- Requires pg_trgm (above migration).
DROP FUNCTION IF EXISTS public.search_twin_all(uuid, text);

CREATE OR REPLACE FUNCTION public.search_twin_all(p_twin uuid, p_q text)
RETURNS TABLE (kind text, id uuid, label text, hint text, ord real)
LANGUAGE sql STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT
    'person'::text AS kind,
    c.id,
    c.name AS label,
    COALESCE(c.email, '') AS hint,
    word_similarity(c.name, p_q) AS ord
  FROM public.contacts c
  WHERE c.twin_id = p_twin
    AND c.name %> p_q
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
  ORDER BY ord DESC
  LIMIT 40;
$$;

GRANT EXECUTE ON FUNCTION public.search_twin_all(uuid, text) TO authenticated, service_role;
