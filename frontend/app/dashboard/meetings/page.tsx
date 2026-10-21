'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useTwin } from '@/lib/context/TwinContext';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';
import { formatPersonaDisplayName } from '@/lib/branding/personaName';
import BookingsInbox from '@/components/meetings/BookingsInbox';
import CalendarConnection from '@/components/meetings/CalendarConnection';
import ThreadsList from '@/components/meetings/ThreadsList';
import MeetingsList from '@/components/meetings/MeetingsList';
import type { MeetingCardData } from '@/components/meetings/MeetingCard';

type MeetingsTab = 'upcoming' | 'past' | 'threads' | 'bookings';

// ---------------------------------------------------------------------------
// Local types — keep the API-facing shape but extend MeetingCardData
// ---------------------------------------------------------------------------

interface ApiMeeting extends MeetingCardData {
  twin_attends?: boolean;
  created_at?: string;
}

// ---------------------------------------------------------------------------
// Lifecycle partitioning
// ---------------------------------------------------------------------------

const PAST_STATUSES = new Set(['completed', 'failed', 'canceled', 'cancelled']);

function partitionMeetings(meetings: ApiMeeting[]): { upcoming: ApiMeeting[]; past: ApiMeeting[] } {
  const upcoming: ApiMeeting[] = [];
  const past: ApiMeeting[] = [];
  const now = Date.now();
  for (const m of meetings) {
    if (PAST_STATUSES.has(m.status)) {
      past.push(m);
      continue;
    }
    // Active live states always count as upcoming, even if the start time has passed.
    // NOTE: 'processing' is NOT a live state — the meeting already ended and is just
    // generating its recap, so it must follow the past-if-start-passed rule below.
    // (Keeping it here parked stale/stuck-processing meetings in "Upcoming → Today"
    // with a wrong date — e.g. a 3-week-old bot meeting wedged in processing.)
    if (m.status === 'recording' || m.status === 'bot_joining' || m.status === 'joining') {
      upcoming.push(m);
      continue;
    }
    // Anything else whose start time is in the past = treat as past. Covers
    // 'scheduled' no-shows AND 'processing' recaps for meetings that already happened.
    if (m.meeting_start && new Date(m.meeting_start).getTime() < now) {
      past.push(m);
      continue;
    }
    upcoming.push(m);
  }
  // Sort: upcoming by start asc, past by start desc
  upcoming.sort((a, b) => {
    const ta = a.meeting_start ? new Date(a.meeting_start).getTime() : Infinity;
    const tb = b.meeting_start ? new Date(b.meeting_start).getTime() : Infinity;
    return ta - tb;
  });
  past.sort((a, b) => {
    const ta = a.meeting_start ? new Date(a.meeting_start).getTime() : 0;
    const tb = b.meeting_start ? new Date(b.meeting_start).getTime() : 0;
    return tb - ta;
  });
  return { upcoming, past };
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function MeetingsPage(): React.JSX.Element {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { activeTwin, isLoading: twinsLoading } = useTwin();
  const [meetings, setMeetings] = useState<ApiMeeting[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [meetLink, setMeetLink] = useState('');
  const [joinBusy, setJoinBusy] = useState(false);
  const [joinError, setJoinError] = useState<string | null>(null);

  const apiBase = resolveApiBaseUrl();

  // Tabs: Upcoming | Past | Threads | Bookings. Default Upcoming.
  // Honor legacy ?tab=room by redirecting to upcoming.
  const tabParam = searchParams?.get('tab');
  const initialTab: MeetingsTab =
    tabParam === 'past' ? 'past' :
    tabParam === 'threads' ? 'threads' :
    tabParam === 'bookings' ? 'bookings' :
    'upcoming';
  const [activeTab, setActiveTab] = useState<MeetingsTab>(initialTab);

  // ── "Send bot to meeting" handler ─────────────────────────────────────────
  const sendBotToMeeting = useCallback(async (twinId: string) => {
    if (!meetLink.trim()) {
      setJoinError('Paste a Zoom / Google Meet / Teams link first.');
      return;
    }
    setJoinBusy(true);
    setJoinError(null);
    try {
      const res = await authFetchStandalone(`${apiBase}/v2/meetings/${twinId}/join-now`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ meet_link: meetLink.trim() }),
      });
      if (!res.ok) {
        const msg = await res.text().catch(() => String(res.status));
        setJoinError(`Failed: ${msg}`);
        return;
      }
      const data = await res.json() as { status: string; data?: { meeting_id?: string } };
      if (data?.data?.meeting_id) {
        router.push(`/dashboard/meetings/${data.data.meeting_id}/live?twin=${twinId}`);
      } else {
        setMeetLink('');
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Network error';
      setJoinError(msg);
    } finally {
      setJoinBusy(false);
    }
  }, [apiBase, meetLink, router]);

  const fetchMeetings = useCallback(async (twinId: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetchStandalone(`${apiBase}/v2/meetings/${twinId}`);
      if (!res.ok) {
        const msg = await res.text().catch(() => String(res.status));
        setError(`Failed to load meetings: ${msg}`);
        return;
      }
      const data = await res.json() as { status: string; data: ApiMeeting[] };
      setMeetings(data.data || []);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Network error';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    if (!twinsLoading && activeTwin?.id) {
      void fetchMeetings(activeTwin.id);
    }
  }, [twinsLoading, activeTwin?.id, fetchMeetings]);

  // Partition once per meeting set change
  const { upcoming, past } = useMemo(() => partitionMeetings(meetings), [meetings]);

  // ── Loading twin context ─────────────────────────────────────────────────
  if (twinsLoading) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <div
          className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent"
          style={{ borderColor: 'var(--brand-primary)', borderTopColor: 'transparent' }}
        />
      </div>
    );
  }

  if (!activeTwin) {
    return (
      <div className="flex min-h-[400px] flex-col items-center justify-center gap-2 text-center px-6">
        <p className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>
          Select a persona first
        </p>
        <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
          Choose a persona from the sidebar to view its meetings.
        </p>
      </div>
    );
  }

  const activePersonaName = formatPersonaDisplayName(activeTwin.name);

  // Empty-state action for Upcoming tab: paste-a-link affordance
  const upcomingEmptyAction = (
    <div className="flex flex-col gap-2 sm:flex-row max-w-md">
      <input
        type="url"
        value={meetLink}
        onChange={(e) => setMeetLink(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !joinBusy) void sendBotToMeeting(activeTwin.id);
        }}
        placeholder="https://meet.google.com/abc-defg-hij"
        disabled={joinBusy}
        className="flex-1 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2"
        style={{
          backgroundColor: 'var(--fog-2)',
          border: '1px solid var(--fog-line-2)',
          color: 'var(--ink)',
        }}
      />
      <button
        onClick={() => void sendBotToMeeting(activeTwin.id)}
        disabled={joinBusy || !meetLink.trim()}
        className="rounded-xl px-4 py-2 text-sm font-medium transition-opacity disabled:opacity-50"
        style={{ backgroundColor: 'var(--ink)', color: '#fff' }}
      >
        {joinBusy ? 'Sending…' : 'Send your persona'}
      </button>
      {joinError && (
        <p className="text-xs" style={{ color: 'var(--rec)' }}>{joinError}</p>
      )}
    </div>
  );

  const tabSpecs: Array<{ id: MeetingsTab; label: string; count?: number }> = [
    { id: 'upcoming', label: 'Upcoming', count: upcoming.length },
    { id: 'past', label: 'Past', count: past.length },
    { id: 'threads', label: 'Threads' },
    { id: 'bookings', label: 'Bookings' },
  ];

  return (
    <div className="pb-12 pt-4 space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--ink)' }}>
          Meetings
        </h1>
        <p className="mt-0.5 text-sm" style={{ color: 'var(--fg-2)' }}>
          Your upcoming + past meetings, threaded by person — for{' '}
          <span className="font-medium">{activePersonaName}</span>.
        </p>
      </div>

      <CalendarConnection twinId={activeTwin.id} />

      {/* Sub-tabs */}
      <div className="flex flex-wrap gap-2 border-b border-black/[0.06] pb-3" role="tablist">
        {tabSpecs.map((t) => {
          const active = activeTab === t.id;
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setActiveTab(t.id)}
              className={`inline-flex items-center gap-2 rounded-full px-5 py-2 text-sm font-semibold transition-all ${
                active
                  ? 'bg-[#1d1d1f] text-white shadow-md'
                  : 'border border-black/10 bg-white text-[#1d1d1f] hover:bg-black/[0.03]'
              }`}
            >
              {t.label}
              {t.count != null && (
                <span
                  className="rounded-full px-2 py-0.5 text-[11px]"
                  style={{
                    backgroundColor: active ? 'rgba(255,255,255,.16)' : 'var(--fog)',
                    color: active ? 'rgba(255,255,255,.9)' : 'var(--fg-2)',
                    fontFamily: 'var(--font-geist-mono, JetBrains Mono, monospace)',
                  }}
                >
                  {t.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div
            className="h-6 w-6 animate-spin rounded-full border-2 border-t-transparent"
            style={{ borderColor: 'var(--signal)', borderTopColor: 'transparent' }}
          />
        </div>
      ) : error ? (
        <div className="rounded-3xl px-6 py-10 text-center" style={{ backgroundColor: 'var(--fog-2)' }}>
          <p className="text-sm" style={{ color: 'var(--rec)' }}>{error}</p>
          <button
            onClick={() => void fetchMeetings(activeTwin.id)}
            className="mt-3 rounded-xl px-4 py-1.5 text-xs font-medium"
            style={{ border: '1px solid var(--fog-line-2)', color: 'var(--fg-2)' }}
          >
            Retry
          </button>
        </div>
      ) : (
        <>
          {activeTab === 'upcoming' && (
            <MeetingsList
              meetings={upcoming}
              twinId={activeTwin.id}
              variant="upcoming"
              emptyTitle="No upcoming meetings."
              emptySubtitle="Once your calendar is connected, scheduled events appear here automatically. You can also send your persona into a meeting manually:"
              emptyAction={upcomingEmptyAction}
            />
          )}

          {activeTab === 'past' && (
            <MeetingsList
              meetings={past}
              twinId={activeTwin.id}
              variant="past"
              emptyTitle="No past meetings yet."
              emptySubtitle="Completed meetings and recaps will appear here after your persona attends a call."
            />
          )}

          {activeTab === 'threads' && (
            <ThreadsList twinId={activeTwin.id} />
          )}

          {activeTab === 'bookings' && (
            <BookingsInbox twinId={activeTwin.id} />
          )}
        </>
      )}
    </div>
  );
}
