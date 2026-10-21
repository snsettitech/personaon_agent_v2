-- Phase G.1: visitor_sessions table — cross-surface aggregation of anonymous
-- chats with the owner's twin (widget + public + future surfaces). Populated by
-- _persist_chat_turn for every non-owner turn (G.2).
--
-- "Needs attention" is computed at read time via JOIN with queued_questions —
-- we don't denormalize the flag onto this table because the owner can answer
-- queued questions, which changes the status without rewriting visitor_sessions.

CREATE TABLE IF NOT EXISTS public.visitor_sessions (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id            uuid NOT NULL,
  twin_id              uuid NOT NULL REFERENCES public.twins(id) ON DELETE CASCADE,
  visitor_id           text NOT NULL,            -- client-generated opaque id (from widget JS, public share token, etc.)
  surface              text NOT NULL CHECK (surface IN ('widget', 'public', 'widget_lead', 'other')),
  contact_id           uuid REFERENCES public.contacts(id) ON DELETE SET NULL,
  first_message_at     timestamptz NOT NULL DEFAULT now(),
  last_message_at      timestamptz NOT NULL DEFAULT now(),
  message_count        integer NOT NULL DEFAULT 0,
  visitor_name         text,
  visitor_email        text,
  source_domain        text,                     -- for widget visitors only; the host page
  metadata             jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (twin_id, visitor_id, surface)          -- one row per visitor per twin per surface
);

CREATE INDEX IF NOT EXISTS idx_vs_twin_last ON public.visitor_sessions(twin_id, last_message_at DESC);
CREATE INDEX IF NOT EXISTS idx_vs_visitor ON public.visitor_sessions(twin_id, visitor_id);
CREATE INDEX IF NOT EXISTS idx_vs_tenant ON public.visitor_sessions(tenant_id);

ALTER TABLE public.visitor_sessions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS vs_owner_read ON public.visitor_sessions;
CREATE POLICY vs_owner_read
  ON public.visitor_sessions FOR SELECT
  USING ((SELECT auth.uid()) = tenant_id);

DROP POLICY IF EXISTS vs_service_all ON public.visitor_sessions;
CREATE POLICY vs_service_all
  ON public.visitor_sessions FOR ALL
  USING (auth.role() = 'service_role');
