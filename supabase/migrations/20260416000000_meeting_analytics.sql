-- =============================================================================
-- Phase 26: Meeting Summaries — meeting_analytics table + summary_json column
-- Stores per-speaker analytics: talk time, WPM, filler words, sentiment.
-- =============================================================================

-- COLUMN-01: add summary_json to meetings for full structured Gemini output
-- (meetings.summary TEXT stores the tldr shortcut; summary_json stores full output)
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS summary_json JSONB;

-- TABLE-01: meeting_analytics — one row per participant per meeting
CREATE TABLE IF NOT EXISTS meeting_analytics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    participant_name TEXT NOT NULL,
    -- Talk time
    talk_time_seconds FLOAT,
    talk_time_pct FLOAT,        -- 0-100
    -- Pace
    word_count INT,
    words_per_minute FLOAT,
    -- Vocabulary
    filler_word_count INT,
    -- Sentiment (populated by Gemini analysis)
    sentiment_label TEXT CHECK (sentiment_label IN ('positive', 'neutral', 'negative')),
    sentiment_score FLOAT,      -- 0.0-1.0
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Unique: one analytics row per participant per meeting
    UNIQUE (meeting_id, participant_name)
);

-- INDEX-01: fast lookup by meeting
CREATE INDEX IF NOT EXISTS idx_meeting_analytics_meeting_id ON meeting_analytics(meeting_id);

-- INDEX-02: fast lookup by tenant (ownership queries)
CREATE INDEX IF NOT EXISTS idx_meeting_analytics_tenant_id ON meeting_analytics(tenant_id);

-- RLS
ALTER TABLE meeting_analytics ENABLE ROW LEVEL SECURITY;

-- RLS-01: meeting_analytics — tenant can read/write own rows
CREATE POLICY meeting_analytics_tenant_policy ON meeting_analytics
    FOR ALL
    USING (tenant_id = auth.uid())
    WITH CHECK (tenant_id = auth.uid());

-- RLS-02: service role gets full access (worker writes analytics rows)
CREATE POLICY meeting_analytics_service_policy ON meeting_analytics
    FOR ALL
    USING (auth.role() = 'service_role');
