-- Public share columns for desktop recordings (meetings.source='desktop_sdk').
alter table public.meetings
  add column if not exists public_share_token   text,
  add column if not exists public_share_enabled boolean not null default false,
  add column if not exists public_shared_at      timestamptz;

create unique index if not exists meetings_public_share_token_key
  on public.meetings (public_share_token)
  where public_share_token is not null;
