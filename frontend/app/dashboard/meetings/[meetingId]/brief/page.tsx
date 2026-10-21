'use client';

import React, { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';
import { useTwin } from '@/lib/context/TwinContext';
import { useMeetingsV2 } from '@/lib/features/meetingsV2';
import type { BriefContract } from '@/lib/types/brief';
import { BriefHero } from '@/components/meetings/brief/BriefHero';
import { ParticipantInsightsCard } from '@/components/meetings/brief/ParticipantInsightsCard';
import { HeadsUpSection } from '@/components/meetings/brief/HeadsUpSection';
import { TalkingPointsSection } from '@/components/meetings/brief/TalkingPointsSection';
import { SuggestedAgendaSection } from '@/components/meetings/brief/SuggestedAgendaSection';
import { PreviousInteractionsSection } from '@/components/meetings/brief/PreviousInteractionsSection';
import { OpenCommitmentsSection } from '@/components/meetings/brief/OpenCommitmentsSection';
import { SourcesUsedFooter } from '@/components/meetings/brief/SourcesUsedFooter';
import { DeepResearchButton } from '@/components/meetings/brief/DeepResearchButton';

/**
 * W9c — Pre-meeting brief page.
 *
 * Thin composer of per-section components under
 * ``frontend/components/meetings/brief/``. Each section component owns
 * its own backwards-compat (v1 ↔ v2) logic; this page just fetches
 * brief_json and passes it down.
 *
 * Scroll order (new in W9c):
 *   1. Hero (You × X + countdown)
 *   2. Participant insights (multi-attendee, v2)
 *   3. Goal + Context (existing IntentCard grid)
 *   4. Heads Up (NEW — hidden if empty, amber + citation chevron)
 *   5. Talking Points (was 'Hooks to lead with')
 *   6. Suggested Agenda (NEW)
 *   7. From last time (was 'Your history with X', with open_items)
 *   8. Still Open (was 'Open from last time')
 *   9. Join CTA
 *  10. Sources used footer (NEW)
 */

// ---------------------------------------------------------------------------
// Local types — page-internal only. Brief shape lives in @/lib/types/brief.
// ---------------------------------------------------------------------------

interface ApiEnvelope {
  status: string;
  data: BriefContract;
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; brief: BriefContract };

interface CountdownState {
  label: string;
  isImminent: boolean;
  isPast: boolean;
}

// ---------------------------------------------------------------------------
// Helpers (page-local; section components handle their own formatting)
// ---------------------------------------------------------------------------

function formatMeetingDateTime(
  iso: string | null | undefined,
): { dateLabel: string; timeLabel: string } {
  if (!iso) return { dateLabel: '', timeLabel: '' };
  const d = new Date(iso);
  if (Number.isNaN(d.valueOf())) return { dateLabel: '', timeLabel: '' };
  return {
    dateLabel: d.toLocaleDateString(undefined, {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    }),
    timeLabel: d.toLocaleTimeString(undefined, {
      hour: 'numeric',
      minute: '2-digit',
    }),
  };
}

function buildCountdown(
  iso: string | null | undefined,
  nowMs: number,
): CountdownState | null {
  if (!iso) return null;
  const startMs = new Date(iso).valueOf();
  if (Number.isNaN(startMs)) return null;
  const diffMs = startMs - nowMs;
  const isPast = diffMs < 0;
  const absMin = Math.round(Math.abs(diffMs) / 60_000);
  if (isPast) {
    if (absMin < 60) return { label: `${absMin} min ago`, isImminent: false, isPast };
    return { label: `${Math.round(absMin / 60)}h ago`, isImminent: false, isPast };
  }
  if (absMin < 60) return { label: `in ${absMin} min`, isImminent: true, isPast };
  if (absMin < 24 * 60) {
    return { label: `in ${Math.round(absMin / 60)}h`, isImminent: false, isPast };
  }
  return {
    label: `in ${Math.round(absMin / (60 * 24))}d`,
    isImminent: false,
    isPast,
  };
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function MeetingBriefPage(): React.JSX.Element {
  const params = useParams();
  const meetingId = String(params?.meetingId ?? '');
  const { activeTwin } = useTwin();
  const apiBaseUrl = resolveApiBaseUrl();
  const router = useRouter();
  const meetingsV2 = useMeetingsV2();

  // Phase B: the brief is now an in-page tab on the unified meeting page; send v2
  // users there so a meeting is one URL (no separate /brief route).
  useEffect(() => {
    if (meetingsV2 && meetingId) {
      router.replace(`/dashboard/meetings/${meetingId}?view=brief${activeTwin?.id ? `&twin=${activeTwin.id}` : ''}`);
    }
  }, [meetingsV2, meetingId, activeTwin?.id, router]);

  const [state, setState] = useState<LoadState>({ kind: 'loading' });
  const [reloadKey, setReloadKey] = useState(0);
  const [now, setNow] = useState<number>(() => Date.now());

  useEffect(() => {
    const handle = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(handle);
  }, []);

  useEffect(() => {
    if (!activeTwin?.id || !meetingId) return;
    let cancelled = false;
    setState({ kind: 'loading' });
    void (async () => {
      try {
        const res = await authFetchStandalone(
          `${apiBaseUrl}/v2/meetings/${activeTwin.id}/${meetingId}/brief`,
        );
        if (cancelled) return;
        if (!res.ok) {
          const message =
            res.status === 404
              ? 'Meeting not found'
              : res.status === 403
                ? 'You do not have access to this meeting'
                : 'Brief unavailable';
          setState({ kind: 'error', message });
          return;
        }
        const payload = (await res.json()) as ApiEnvelope;
        const brief = payload?.data;
        if (!brief) {
          setState({ kind: 'error', message: 'Brief unavailable' });
          return;
        }
        // AUDIT FIX (W9c): defensive defaults for the v1 fields the page
        // accesses without optional chaining downstream. A schema-breaking
        // backend response (empty arrays omitted) would otherwise crash
        // when sections read .length or .map. v2 fields stay optional —
        // section components own their own ?? defaults.
        brief.hooks = brief.hooks ?? [];
        brief.prior_meetings = brief.prior_meetings ?? [];
        brief.open_commitments = brief.open_commitments ?? [];
        setState({ kind: 'ready', brief });
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : 'Unknown error';
        setState({ kind: 'error', message });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeTwin?.id, meetingId, apiBaseUrl, reloadKey]);

  const countdown = useMemo(() => {
    if (state.kind !== 'ready') return null;
    return buildCountdown(state.brief.meeting_start, now);
  }, [state, now]);

  if (state.kind === 'loading') {
    return (
      <PageShell>
        <BackLink meetingId={meetingId} />
        <div className="py-12 text-center text-sm" style={{ color: 'var(--text-secondary)' }}>
          Preparing brief…
        </div>
      </PageShell>
    );
  }

  if (state.kind === 'error') {
    return (
      <PageShell>
        <BackLink meetingId={meetingId} />
        <div className="py-8" style={{ color: 'var(--text-primary)', fontSize: 15 }}>
          <div className="font-semibold mb-2">{state.message}</div>
          <button
            type="button"
            onClick={() => setReloadKey((k) => k + 1)}
            className="mt-3 px-4 py-2 rounded-full bg-transparent text-sm cursor-pointer"
            style={{
              border: '1px solid var(--border-default)',
              color: 'var(--text-primary)',
            }}
          >
            Try again
          </button>
        </div>
      </PageShell>
    );
  }

  const { brief } = state;
  const { dateLabel, timeLabel } = formatMeetingDateTime(brief.meeting_start);
  const isEnriched =
    (brief.participant_insights?.length ?? 0) > 0 ||
    Boolean(brief.person?.bio || brief.person?.role) ||
    brief.hooks.length > 0 ||
    brief.prior_meetings.length > 0;
  const isJoinable = countdown?.isImminent === true && !countdown?.isPast;

  return (
    <PageShell>
      <BackLink meetingId={meetingId} />

      <BriefHero
        brief={brief}
        dateLabel={dateLabel}
        timeLabel={timeLabel}
        countdown={countdown}
        isEnriched={isEnriched}
      />

      <ParticipantInsightsCard brief={brief} />

      {/* Goal + Context grid — page-local IntentCard for the dashed-empty
          pattern that links to /prep. */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <IntentCard
          label="Your goal"
          value={brief.your_goal}
          meetingId={meetingId}
        />
        <IntentCard
          label="Your context"
          value={brief.your_context}
          meetingId={meetingId}
        />
      </div>

      <HeadsUpSection notes={brief.caution_notes} />
      <TalkingPointsSection brief={brief} />
      <SuggestedAgendaSection items={brief.suggested_agenda} />
      <PreviousInteractionsSection brief={brief} />
      <OpenCommitmentsSection commitments={brief.open_commitments} />

      {isJoinable && (
        <div className="mt-9 text-center">
          <Link
            href={`/dashboard/meetings/${meetingId}/live`}
            className="inline-flex items-center gap-2.5 px-7 py-3.5 rounded-full no-underline font-medium text-[15px]"
            style={{
              background: 'var(--text-primary)',
              color: 'white',
              letterSpacing: '-0.005em',
              boxShadow: '0 4px 16px rgba(29,29,31,.18)',
            }}
          >
            Join meeting{timeLabel ? ` at ${timeLabel}` : ''}
            <span className="font-mono">→</span>
          </Link>
        </div>
      )}

      <SourcesUsedFooter sources={brief.sources_used} />

      {activeTwin?.id && (
        <DeepResearchButton
          twinId={activeTwin.id}
          meetingId={meetingId}
          brief={brief}
          onDeepBriefReady={(deepBrief) =>
            setState({ kind: 'ready', brief: deepBrief })
          }
        />
      )}

      <style jsx global>{`
        @keyframes personaPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: .4; }
        }
      `}</style>
    </PageShell>
  );
}

// ---------------------------------------------------------------------------
// Page-local presentational helpers (used only here)
// ---------------------------------------------------------------------------

function PageShell({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <div
      className="min-h-full"
      style={{ background: 'var(--bg-page, var(--fog))', padding: '48px 24px 96px' }}
    >
      <div style={{ maxWidth: 820, margin: '0 auto' }}>{children}</div>
    </div>
  );
}

function BackLink({ meetingId }: { meetingId: string }): React.JSX.Element {
  return (
    /* AUDIT FIX (W9c): py-2 + min-h-[44px] meets the WCAG 2.5.5 / Apple HIG
       44x44 tap target. Previous version was a single 13px line with no
       padding — sub-20px tall on mobile, hard to hit. */
    <Link
      href={`/dashboard/meetings/${meetingId}`}
      className="inline-flex items-center gap-1.5 no-underline text-[13px] py-2 min-h-[44px] mb-4 -ml-1 px-1 rounded"
      style={{ color: 'var(--text-secondary)', letterSpacing: '-0.005em' }}
    >
      <span aria-hidden className="font-mono">←</span>
      Back to meeting
    </Link>
  );
}

interface IntentCardProps {
  label: string;
  value: string | null;
  meetingId: string;
}

function IntentCard({ label, value, meetingId }: IntentCardProps): React.JSX.Element {
  const filled = (value || '').trim();
  if (filled) {
    return (
      <div
        className="rounded-[30px] p-6"
        style={{
          background: 'var(--bg-card)',
          boxShadow: 'var(--shadow-card)',
        }}
      >
        <div
          className="font-mono text-[11px] uppercase tracking-[0.15em] mb-2.5"
          style={{ color: 'var(--text-secondary)' }}
        >
          {label}
        </div>
        <div
          className="text-[15px] leading-relaxed"
          style={{ color: 'var(--text-primary)', letterSpacing: '-0.005em' }}
        >
          {filled}
        </div>
      </div>
    );
  }
  return (
    <Link
      href={`/dashboard/meetings/${meetingId}/prep`}
      className="block rounded-[30px] p-6 no-underline"
      style={{
        background: 'transparent',
        border: '1.5px dashed var(--border-default)',
      }}
    >
      <div
        className="font-mono text-[11px] uppercase tracking-[0.15em] mb-2.5"
        style={{ color: 'var(--text-muted)' }}
      >
        {label}
      </div>
      <div
        className="text-[15px] leading-relaxed italic"
        style={{ color: 'var(--text-secondary)' }}
      >
        Add prep →
      </div>
    </Link>
  );
}
