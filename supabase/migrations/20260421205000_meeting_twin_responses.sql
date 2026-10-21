-- meeting_twin_responses: real-time capture of twin Q&A during meetings.
-- Written by _write_twin_response() in meeting_adk_session.py.
-- Enriched by ENRICH_TWIN_RESPONSES worker job (adds confidence + sources).

create table if not exists meeting_twin_responses (
    id              uuid primary key default gen_random_uuid(),
    meeting_id      uuid not null references meetings(id) on delete cascade,
    twin_id         uuid not null references twins(id)    on delete cascade,
    turn_seq        integer not null,
    question_text   text,
    response_text   text not null,
    -- null until ENRICH_TWIN_RESPONSES runs; mean(top-k pgvector scores) or null if no hits
    confidence      float,
    -- null until ENRICH; top-3 KB chunks [{text, score, source_id, filename, url}]
    sources         jsonb,
    is_deferral     boolean not null default false,
    responded_at    timestamptz not null,
    created_at      timestamptz not null default now(),
    constraint uq_meeting_twin_turn unique (meeting_id, turn_seq)
);

create index if not exists idx_meeting_twin_responses_meeting_id
    on meeting_twin_responses (meeting_id);

create index if not exists idx_meeting_twin_responses_twin_id
    on meeting_twin_responses (twin_id);
