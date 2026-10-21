'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useTwin } from '@/lib/context/TwinContext';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';
import StatusStrip from '@/components/people/StatusStrip';
import OpenLoopsPanel, { OpenLoopCommitment } from '@/components/people/OpenLoopsPanel';
import PersonTimeline, { PersonTimelineMeeting } from '@/components/people/PersonTimeline';

interface PersonProfile {
  person: {
    id: string;
    name: string;
    email: string | null;
    meeting_count: number;
    recorded_count: number;
    first_met_at: string | null;
    last_met_at: string | null;
  };
  status_strip: {
    last_talked_label: string;
    you_owe_label: string;
    next_label: string;
  };
  open_commitments: {
    you_owe: OpenLoopCommitment[];
    they_owe: OpenLoopCommitment[];
  };
  timeline: PersonTimelineMeeting[];
}

function getInitials(name: string): string {
  const clean = (name || '').trim();
  if (!clean) return '?';
  const parts = clean.split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return (parts[0]![0] + parts[parts.length - 1]![0]).toUpperCase();
}

export default function PersonProfilePage(): React.JSX.Element {
  const params = useParams();
  const personId = String(params?.personId ?? '');
  const { activeTwin, isLoading: twinsLoading } = useTwin();
  const apiBase = resolveApiBaseUrl();

  const [profile, setProfile] = useState<PersonProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchProfile = useCallback(async () => {
    if (!activeTwin?.id || !personId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await authFetchStandalone(
        `${apiBase}/v2/people/${activeTwin.id}/${personId}`,
      );
      if (!res.ok) {
        setError(res.status === 404 ? 'Person not found' : 'Failed to load profile');
        return;
      }
      const body = await res.json() as { status: string; data: PersonProfile };
      setProfile(body.data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Network error';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [apiBase, activeTwin?.id, personId]);

  useEffect(() => {
    void fetchProfile();
  }, [fetchProfile]);

  if (twinsLoading || loading) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <div
          className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent"
          style={{ borderColor: 'var(--signal)', borderTopColor: 'transparent' }}
        />
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="flex min-h-[400px] flex-col items-center justify-center gap-3 text-center">
        <p className="text-sm font-medium" style={{ color: 'var(--rec)' }}>
          {error ?? 'Could not load this person'}
        </p>
        <Link
          href="/dashboard/meetings?tab=threads"
          className="text-xs underline"
          style={{ color: 'var(--text-secondary)' }}
        >
          Back to Threads
        </Link>
      </div>
    );
  }

  const { person, status_strip, open_commitments, timeline } = profile;
  const initials = getInitials(person.name);
  const subline =
    person.email
      ? `${person.email} · Met ${person.meeting_count} time${person.meeting_count === 1 ? '' : 's'}`
      : `Met ${person.meeting_count} time${person.meeting_count === 1 ? '' : 's'}`;

  return (
    <div className="pb-12 pt-4 space-y-6">
      {/* Back link */}
      <Link
        href="/dashboard/meetings?tab=threads"
        className="inline-flex items-center gap-1.5 text-xs"
        style={{ color: 'var(--text-muted)', textDecoration: 'none' }}
      >
        <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
        All threads
      </Link>

      {/* Hero — identity only (no KPIs, no scores) */}
      <div className="flex items-center gap-4">
        <div
          className="flex h-14 w-14 items-center justify-center rounded-full text-base font-semibold"
          style={{
            backgroundColor: 'var(--fog)',
            color: 'var(--ink)',
          }}
        >
          {initials}
        </div>
        <div className="min-w-0">
          <h1
            className="truncate text-2xl font-bold"
            style={{ color: 'var(--ink)', letterSpacing: '-0.02em' }}
          >
            {person.name}
          </h1>
          <p className="mt-0.5 text-sm" style={{ color: 'var(--fg-2)' }}>
            {subline}
          </p>
        </div>
      </div>

      {/* Status Strip — the One Question answer */}
      <StatusStrip
        lastTalkedLabel={status_strip.last_talked_label}
        youOweLabel={status_strip.you_owe_label}
        nextLabel={status_strip.next_label}
      />

      {/* Two-column on desktop: Timeline + Open Loops rail; stacks on mobile */}
      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="min-w-0">
          <h2
            className="mb-3 text-[11px] font-semibold uppercase"
            style={{
              color: 'var(--fg-2)',
              fontFamily: 'var(--font-geist-mono, JetBrains Mono, monospace)',
              letterSpacing: '0.12em',
            }}
          >
            Timeline · {person.meeting_count}
          </h2>
          <PersonTimeline meetings={timeline} twinId={activeTwin!.id} />
        </div>

        <div>
          <OpenLoopsPanel
            youOwe={open_commitments.you_owe}
            theyOwe={open_commitments.they_owe}
            twinId={activeTwin!.id}
          />
        </div>
      </div>
    </div>
  );
}
