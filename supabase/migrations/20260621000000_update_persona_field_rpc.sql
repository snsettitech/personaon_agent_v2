-- update_persona_field — atomic single-field merge into settings.public_profile.
--
-- Backs the chief-of-staff `update_persona` chat tool (Home v1). Doing the merge
-- in SQL avoids the read-modify-write race (two quick edits silently clobbering
-- each other) and the full-settings-blob round-trip. Called from the backend on
-- the service-key client, so it bypasses RLS (the #230 frontend save is broken;
-- this path is not).
--
-- Safe on null settings and null public_profile, and preserves every other
-- settings key and every other public_profile key (the `||` merges one field).
-- DROP-before-CREATE per the migration lint (function signature management).

DROP FUNCTION IF EXISTS public.update_persona_field(uuid, text, text) CASCADE;

CREATE OR REPLACE FUNCTION public.update_persona_field(
  p_twin_id uuid,
  p_field   text,
  p_value   text
) RETURNS void
LANGUAGE sql
AS $$
  UPDATE public.twins
  SET settings = jsonb_set(
        COALESCE(settings, '{}'::jsonb),
        ARRAY['public_profile'],
        COALESCE(settings -> 'public_profile', '{}'::jsonb)
          || jsonb_build_object(p_field, to_jsonb(p_value)),
        true
      )
  WHERE id = p_twin_id;
$$;
