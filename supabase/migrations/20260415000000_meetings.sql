-- =============================================================================
-- Phase 25: Meeting Intelligence — meetings + meeting_participants tables
-- Stores Recall.ai bot lifecycle, diarized transcripts, and participant data.
-- =============================================================================

-- TABLE-01: meetings — core meeting record linked to twin + booking
CREATE TABLE IF NOT EXISTS meetings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    booking_id UUID REFERENCES booking_requests(id),
    -- Recall.ai integration
    recall_bot_id TEXT,
    meet_link TEXT,
    title TEXT,
    -- Status lifecycle: scheduled → bot_joining → recording → processing → completed
    status TEXT NOT NULL DEFAULT 'scheduled'
        CHECK (status IN ('scheduled', 'bot_joining', 'recording', 'processing', 'completed', 'failed')),
    -- Content (populated by PROCESS_MEETING_TRANSCRIPT worker)
    transcript_raw JSONB,
    transcript_text TEXT,
    summary TEXT,
    action_items JSONB,
    -- Timing
    meeting_start TIMESTAMPTZ,
    meeting_end TIMESTAMPTZ,
    duration_seconds INT,
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- INDEX-01: fast lookup by twin
CREATE INDEX IF NOT EXISTS idx_meetings_twin_id ON meetings(twin_id);
-- INDEX-02: fast lookup by tenant (ownership queries)
CREATE INDEX IF NOT EXISTS idx_meetings_tenant_id ON meetings(tenant_id);
-- INDEX-03: webhook lookup by Recall.ai bot ID
CREATE INDEX IF NOT EXISTS idx_meetings_recall_bot_id ON meetings(recall_bot_id);
-- INDEX-04: status filtering
CREATE INDEX IF NOT EXISTS idx_meetings_status ON meetings(status);

-- TABLE-02: meeting_participants — per-participant metadata
CREATE TABLE IF NOT EXISTS meeting_participants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    participant_name TEXT,
    participant_email TEXT,
    is_host BOOLEAN DEFAULT FALSE,
    -- Analytics (populated by Phase 26)
    talk_time_seconds FLOAT,
    word_count INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- INDEX-05: participants by meeting
CREATE INDEX IF NOT EXISTS idx_meeting_participants_meeting_id
    ON meeting_participants(meeting_id);

-- RLS
ALTER TABLE meetings ENABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_participants ENABLE ROW LEVEL SECURITY;

-- RLS-01: meetings — tenant can read/write own meetings
CREATE POLICY meetings_tenant_policy ON meetings
    FOR ALL
    USING (tenant_id = auth.uid())
    WITH CHECK (tenant_id = auth.uid());

-- RLS-02: meeting_participants — accessible via meeting ownership
CREATE POLICY meeting_participants_tenant_policy ON meeting_participants
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM meetings m
            WHERE m.id = meeting_participants.meeting_id
            AND m.tenant_id = auth.uid()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM meetings m
            WHERE m.id = meeting_participants.meeting_id
            AND m.tenant_id = auth.uid()
        )
    );

-- SERVICE ROLE: allow backend (service key) full access
CREATE POLICY meetings_service_policy ON meetings
    FOR ALL
    USING (auth.role() = 'service_role');

CREATE POLICY meeting_participants_service_policy ON meeting_participants
    FOR ALL
    USING (auth.role() = 'service_role');
