-- Meeting transcript live buffer — stores real-time transcript events
-- received from Recall.ai realtime webhook during a meeting.
-- Used by Phase 29 voice agent pipeline.

CREATE TABLE IF NOT EXISTS public.meeting_transcript_live (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  bot_id text NOT NULL,
  speaker text,
  text text NOT NULL,
  timestamp text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_meeting_transcript_live_bot_id
  ON public.meeting_transcript_live(bot_id);

CREATE INDEX IF NOT EXISTS idx_meeting_transcript_live_created_at
  ON public.meeting_transcript_live(created_at DESC);
