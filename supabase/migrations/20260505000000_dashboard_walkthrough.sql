-- Account-level dismissal for the first-run dashboard sidebar walkthrough.
ALTER TABLE public.users
ADD COLUMN IF NOT EXISTS dashboard_walkthrough_completed_at TIMESTAMPTZ;

COMMENT ON COLUMN public.users.dashboard_walkthrough_completed_at IS
  'Set when a user completes or skips the dashboard sidebar walkthrough.';
