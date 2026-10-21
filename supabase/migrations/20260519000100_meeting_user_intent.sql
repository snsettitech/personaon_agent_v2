-- Phase 30-J: Per-meeting user intent capture.
-- user_goal: 1-line target the user states ahead of the meeting (e.g. "lock in pricing tier")
-- user_context: optional free-text background (e.g. "investor I met at Antler Day 4 — wants to lead seed")
-- Both feed the persona_core.recap engine prompt as ground-truth intent.

ALTER TABLE public.meetings
    ADD COLUMN IF NOT EXISTS user_goal TEXT,
    ADD COLUMN IF NOT EXISTS user_context TEXT;
