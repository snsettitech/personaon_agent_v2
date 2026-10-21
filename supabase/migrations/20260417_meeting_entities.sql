-- =============================================================================
-- Phase 27: Meeting Knowledge Base — meeting_entities + chunks metadata GIN index
-- =============================================================================

-- TABLE-01: meeting_entities — extracted people, companies, topics from meetings
CREATE TABLE IF NOT EXISTS meeting_entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('people', 'companies', 'topics')),
    entity_value TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Unique constraint for idempotent upsert
    UNIQUE (twin_id, entity_type, entity_value)
);

-- INDEX-01: entities by meeting
CREATE INDEX IF NOT EXISTS idx_meeting_entities_meeting_id
    ON meeting_entities(meeting_id);

-- INDEX-02: entities by twin (cross-meeting entity lookup)
CREATE INDEX IF NOT EXISTS idx_meeting_entities_twin_id
    ON meeting_entities(twin_id);

-- INDEX-03: entity value search
CREATE INDEX IF NOT EXISTS idx_meeting_entities_value
    ON meeting_entities(entity_value);

-- INDEX-04: GIN index on chunks.metadata for source_type filtering (MTG-17, MTG-20)
CREATE INDEX IF NOT EXISTS idx_chunks_metadata_gin
    ON chunks USING gin (metadata jsonb_path_ops);

-- RLS
ALTER TABLE meeting_entities ENABLE ROW LEVEL SECURITY;

-- RLS-01: tenant can read/write own entities
CREATE POLICY meeting_entities_tenant_policy ON meeting_entities
    FOR ALL
    USING (tenant_id = auth.uid())
    WITH CHECK (tenant_id = auth.uid());

-- RLS-02: service role full access
CREATE POLICY meeting_entities_service_policy ON meeting_entities
    FOR ALL
    USING (auth.role() = 'service_role');

-- SQL FUNCTION: search_meeting_chunks — vector search filtered to meeting source_type
-- LINT-ALLOW: new-overload  (first definition of search_meeting_chunks; no prior to drop)
CREATE OR REPLACE FUNCTION search_meeting_chunks(
    query_embedding vector(768),
    p_twin_id UUID,
    p_top_k INT DEFAULT 10
)
RETURNS TABLE (
    id UUID,
    content TEXT,
    metadata JSONB,
    similarity FLOAT
)
LANGUAGE sql STABLE
AS $$
    SELECT
        c.id,
        c.content,
        c.metadata,
        1 - (c.embedding <=> query_embedding) AS similarity
    FROM chunks c
    WHERE c.twin_id = p_twin_id
      AND c.metadata->>'source_type' = 'meeting'
    ORDER BY c.embedding <=> query_embedding
    LIMIT p_top_k;
$$;
