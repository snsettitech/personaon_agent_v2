-- Phase II notification loop: outcome measurement + memory retrieval support.

ALTER TABLE public.agent_memory
    ADD COLUMN IF NOT EXISTS source_run_id UUID,
    ADD COLUMN IF NOT EXISTS source_event_id UUID;

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_memory_notification_outcome_run
    ON public.agent_memory (agent_slug, kind, source_run_id)
    WHERE source_run_id IS NOT NULL AND kind = 'outcome';

CREATE INDEX IF NOT EXISTS idx_agent_memory_notification_match
    ON public.agent_memory (agent_slug, kind, tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_lifecycle_email_events_scope_status_created
    ON public.lifecycle_email_events (scope_id, status, created_at);

CREATE INDEX IF NOT EXISTS idx_lifecycle_email_events_resend_message
    ON public.lifecycle_email_events (resend_message_id)
    WHERE resend_message_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_resend_webhook_events_message_type_received
    ON public.resend_webhook_events (resend_message_id, event_type, received_at)
    WHERE resend_message_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_memory_embedding_hnsw
    ON public.agent_memory USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

CREATE OR REPLACE FUNCTION public.match_agent_memory(
    query_embedding vector(768),
    match_agent_slug text,
    match_kind text DEFAULT 'outcome',
    match_count int DEFAULT 5,
    match_tenant_id uuid DEFAULT NULL
)
RETURNS TABLE (
    id uuid,
    content text,
    meta jsonb,
    similarity double precision
)
LANGUAGE sql
STABLE
AS $$
    SELECT
        agent_memory.id,
        agent_memory.content,
        agent_memory.meta,
        1 - (agent_memory.embedding <=> query_embedding) AS similarity
    FROM public.agent_memory
    WHERE agent_memory.embedding IS NOT NULL
      AND agent_memory.agent_slug = match_agent_slug
      AND agent_memory.kind = match_kind
      AND (match_tenant_id IS NULL OR agent_memory.tenant_id = match_tenant_id)
    ORDER BY agent_memory.embedding <=> query_embedding
    LIMIT LEAST(GREATEST(match_count, 1), 20);
$$;

REVOKE ALL ON FUNCTION public.match_agent_memory(vector(768), text, text, int, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.match_agent_memory(vector(768), text, text, int, uuid) FROM anon;
REVOKE ALL ON FUNCTION public.match_agent_memory(vector(768), text, text, int, uuid) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.match_agent_memory(vector(768), text, text, int, uuid) TO service_role;
