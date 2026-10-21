-- Backfill Gemini Live voice selection for existing twins.
-- Runtime still defaults to Kore, but this makes the default explicit in data.

UPDATE public.twins
SET settings = jsonb_set(
  COALESCE(settings, '{}'::jsonb),
  '{gemini_voice}',
  '"Kore"'::jsonb,
  true
)
WHERE COALESCE(settings->>'gemini_voice', '') = '';
