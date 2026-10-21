-- =============================================================================
-- Granola note-taking loop — Batch 0 (concern 2/2): meeting_transcript_segments
-- Append-only, row-per-utterance live transcript mirror. Idempotent on
-- (meeting_id, seq) so the desktop client can retry/upsert across reconnects.
-- This is the source the recap/enhance workers read at Stop (NOT transcript_url).
-- RLS mirrors the EXISTING meetings pattern (20260415000000_meetings.sql:64-90):
-- owner access via tenant_id = auth.uid() + a service_role bypass. There is NO
-- `owner` column anywhere. No realtime publication here (deferred to Batch 4).
-- =============================================================================

CREATE TABLE IF NOT EXISTS meeting_transcript_segments (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id uuid NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  tenant_id  uuid NOT NULL,
  seq        bigint NOT NULL,
  speaker    text,
  text       text NOT NULL,
  is_final   boolean NOT NULL DEFAULT false,
  start_ms   integer,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Idempotency: the desktop client upserts ON CONFLICT (meeting_id, seq).
CREATE UNIQUE INDEX IF NOT EXISTS uq_seg_meeting_seq
  ON meeting_transcript_segments (meeting_id, seq);

-- Ordered reads of a meeting's transcript.
CREATE INDEX IF NOT EXISTS ix_seg_meeting_seq
  ON meeting_transcript_segments (meeting_id, seq);

-- RLS: mirror the EXISTING meetings pattern exactly.
ALTER TABLE meeting_transcript_segments ENABLE ROW LEVEL SECURITY;

-- Owner access: tenant can read/write their own segments.
DROP POLICY IF EXISTS seg_owner_all ON meeting_transcript_segments;
CREATE POLICY seg_owner_all ON meeting_transcript_segments
  FOR ALL
  USING (tenant_id = auth.uid())
  WITH CHECK (tenant_id = auth.uid());

-- Service role: backend worker (service key) full access.
DROP POLICY IF EXISTS seg_service_all ON meeting_transcript_segments;
CREATE POLICY seg_service_all ON meeting_transcript_segments
  FOR ALL
  USING (auth.role() = 'service_role');

-- NOTE: do NOT re-touch meetings RLS — it already has tenant + service policies.
-- NOTE: do NOT add any table to supabase_realtime here. Realtime is deferred to
-- Batch 4 behind `granola_realtime` and requires a renderer Supabase client +
-- a verified auth.uid()/tenant_id linkage first.
