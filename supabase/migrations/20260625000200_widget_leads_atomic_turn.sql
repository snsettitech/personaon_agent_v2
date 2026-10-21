-- Atomic widget-lead turn counting + per-conversation dedup.
--
-- Fixes two races in routers/widget.py:_get_or_create_lead:
--   1) turn_count was read-modify-write (SELECT, then UPDATE +1) → lost updates
--      under concurrent turns. Replaced by a single atomic UPDATE (RPC below).
--   2) concurrent first turns on the same conversation could INSERT duplicate
--      lead rows. A partial unique index now makes the DB reject the dup; the
--      caller's existing try/except keeps chat alive for the rare loser.

-- 1) Dedup existing (twin_id, conversation_id) collisions BEFORE adding the
--    unique index (else index creation fails). Keep the most-engaged row
--    (highest turn_count, then earliest). Legacy form leads have NULL
--    conversation_id and are untouched; capture rows are near-zero today, so in
--    practice this deletes nothing.
WITH ranked AS (
    SELECT id,
           row_number() OVER (
               PARTITION BY twin_id, conversation_id
               ORDER BY turn_count DESC, created_at ASC
           ) AS rn
    FROM public.widget_leads
    WHERE conversation_id IS NOT NULL
)
DELETE FROM public.widget_leads wl
USING ranked
WHERE wl.id = ranked.id
  AND ranked.rn > 1;

-- 2) One lead per (twin_id, conversation_id). Partial — NULL conversation_id
--    (legacy form leads) stays unconstrained.
CREATE UNIQUE INDEX IF NOT EXISTS widget_leads_twin_conv_uniq
    ON public.widget_leads (twin_id, conversation_id)
    WHERE conversation_id IS NOT NULL;

-- 3) Atomic per-turn increment, tenant-scoped. One statement = no lost update.
--    Returns the post-increment row so the caller needs no extra SELECT. Empty
--    result means the lead_id does not belong to this twin (caller then inserts).
DROP FUNCTION IF EXISTS public.increment_widget_lead_turn(uuid, uuid) CASCADE;
CREATE FUNCTION public.increment_widget_lead_turn(
    p_lead_id uuid,
    p_twin_id uuid
)
RETURNS TABLE (id uuid, offer_state text, turn_count integer, visitor_email text)
LANGUAGE sql
SECURITY INVOKER  -- explicit: runs as caller, so widget_leads RLS still applies
AS $$
    UPDATE public.widget_leads
    SET turn_count = turn_count + 1
    WHERE id = p_lead_id AND twin_id = p_twin_id
    RETURNING id, offer_state, turn_count, visitor_email;
$$;

-- Service-role only: the widget backend calls this with the service key. Strip the
-- implicit PUBLIC grant so anon/authenticated cannot mutate lead turn counts directly.
REVOKE EXECUTE ON FUNCTION public.increment_widget_lead_turn(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.increment_widget_lead_turn(uuid, uuid) TO service_role;
