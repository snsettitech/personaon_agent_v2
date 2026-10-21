-- Waitlist table for collecting early interest signups
-- No auth required — public insert, admin-only read

CREATE TABLE IF NOT EXISTS public.waitlist (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    full_name text NOT NULL,
    email text NOT NULL,
    role text,                -- e.g. "Founder", "Marketing Director"
    created_at timestamptz DEFAULT now() NOT NULL,
    CONSTRAINT waitlist_email_unique UNIQUE (email)
);

-- RLS: allow anonymous inserts, block reads from non-service-role
ALTER TABLE public.waitlist ENABLE ROW LEVEL SECURITY;

-- Anyone can insert (public waitlist form)
CREATE POLICY "waitlist_insert_public"
    ON public.waitlist
    FOR INSERT
    WITH CHECK (true);

-- Only service_role can read (admin/export)
CREATE POLICY "waitlist_select_service_role"
    ON public.waitlist
    FOR SELECT
    USING (auth.role() = 'service_role');

-- Index for fast duplicate check
CREATE INDEX IF NOT EXISTS idx_waitlist_email ON public.waitlist (email);
