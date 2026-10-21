-- Wave 5 + Wave 7 shared schema migration.
--
-- W5 — Meeting share tokens: anonymous public read of a recap via a tokenized
--      URL. Columns + unique index + RLS policy.
-- W7 — Recap edit audit log: every user-driven recap field edit is captured
--      with old/new values, optionally a natural-language prompt.
--
-- All operations additive + idempotent. Safe to apply on staging or prod.

-- ── W5: Meeting share tokens ────────────────────────────────────────────
ALTER TABLE public.meetings
    ADD COLUMN IF NOT EXISTS share_token UUID,
    ADD COLUMN IF NOT EXISTS share_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS share_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS share_created_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS share_revoked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS share_view_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS share_last_viewed_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS idx_meetings_share_token
    ON public.meetings(share_token) WHERE share_token IS NOT NULL;

-- Public-read RLS policy: anyone (anon role) can SELECT a meeting only when
-- the share is enabled, not revoked, not expired, and the token is set.
-- The application layer additionally filters the WHERE share_token = $1.
DROP POLICY IF EXISTS meetings_public_share_read ON public.meetings;
CREATE POLICY meetings_public_share_read ON public.meetings
    FOR SELECT
    USING (
        share_enabled = TRUE
        AND share_revoked_at IS NULL
        AND (share_expires_at IS NULL OR share_expires_at > now())
        AND share_token IS NOT NULL
    );

-- ── W7: Recap edit audit log ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.meeting_recap_edits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID NOT NULL REFERENCES public.meetings(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    field TEXT NOT NULL,
    old_value JSONB,
    new_value JSONB,
    edit_reason TEXT,
    nl_prompt TEXT,
    edited_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    edited_by UUID
);

CREATE INDEX IF NOT EXISTS idx_recap_edits_meeting
    ON public.meeting_recap_edits(meeting_id);

CREATE INDEX IF NOT EXISTS idx_recap_edits_tenant_time
    ON public.meeting_recap_edits(tenant_id, edited_at DESC);

ALTER TABLE public.meeting_recap_edits ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS recap_edits_tenant_policy ON public.meeting_recap_edits;
CREATE POLICY recap_edits_tenant_policy ON public.meeting_recap_edits
    FOR ALL
    USING (tenant_id = (auth.jwt()->>'tenant_id')::UUID);
