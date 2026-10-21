'use client';

/**
 * Phase B (slice 2) — the Brief, embedded as an in-page tab on the unified meeting
 * page (no more navigating to a separate /brief route). Reuses the existing brief
 * section components; skips BriefHero/DeepResearch (the unified page owns the header).
 * See docs/product/meetings-spec-and-plan.md.
 */
import React, { useEffect, useState } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';
import type { BriefContract } from '@/lib/types/brief';
import { ParticipantInsightsCard } from '@/components/meetings/brief/ParticipantInsightsCard';
import { HeadsUpSection } from '@/components/meetings/brief/HeadsUpSection';
import { TalkingPointsSection } from '@/components/meetings/brief/TalkingPointsSection';
import { SuggestedAgendaSection } from '@/components/meetings/brief/SuggestedAgendaSection';
import { PreviousInteractionsSection } from '@/components/meetings/brief/PreviousInteractionsSection';
import { OpenCommitmentsSection } from '@/components/meetings/brief/OpenCommitmentsSection';
import { SourcesUsedFooter } from '@/components/meetings/brief/SourcesUsedFooter';

interface BriefTabContentProps {
  twinId: string;
  meetingId: string;
}

type State =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; brief: BriefContract };

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-3xl p-6 text-center text-sm" style={{ backgroundColor: 'var(--fog-2, #f7f7f8)', color: 'var(--text-secondary, #666)' }}>
      {children}
    </div>
  );
}

export default function BriefTabContent({ twinId, meetingId }: BriefTabContentProps): React.JSX.Element {
  const apiBaseUrl = resolveApiBaseUrl();
  const [state, setState] = useState<State>({ kind: 'loading' });

  useEffect(() => {
    if (!twinId || !meetingId) return;
    let cancelled = false;
    setState({ kind: 'loading' });
    void (async () => {
      try {
        const res = await authFetchStandalone(`${apiBaseUrl}/v2/meetings/${twinId}/${meetingId}/brief`);
        if (cancelled) return;
        if (!res.ok) {
          setState({ kind: 'error', message: res.status === 404 ? 'Meeting not found' : 'Brief unavailable' });
          return;
        }
        const payload = (await res.json()) as { data?: BriefContract };
        const brief = payload?.data;
        if (!brief) {
          setState({ kind: 'error', message: 'Brief unavailable' });
          return;
        }
        // Defensive defaults (W9c): sections read .length/.map on v1 fields.
        brief.hooks = brief.hooks ?? [];
        brief.prior_meetings = brief.prior_meetings ?? [];
        brief.open_commitments = brief.open_commitments ?? [];
        setState({ kind: 'ready', brief });
      } catch (err) {
        if (cancelled) return;
        setState({ kind: 'error', message: err instanceof Error ? err.message : 'Unknown error' });
      }
    })();
    return () => { cancelled = true; };
  }, [twinId, meetingId, apiBaseUrl]);

  if (state.kind === 'loading') return <Notice>Loading brief…</Notice>;
  if (state.kind === 'error') return <Notice>{state.message}</Notice>;

  const brief = state.brief;
  // Slice 5a: adaptive — rich for a new contact, a light "you know them" strip for recurring.
  const priorCount = brief.prior_meetings?.length ?? 0;
  return (
    <div className="space-y-4">
      <div className="rounded-2xl px-4 py-2.5 text-sm" style={{ backgroundColor: 'var(--fog, #f3f4f6)', color: 'var(--text-secondary, #555)' }}>
        {priorCount > 0
          ? `You’ve met ${priorCount} time${priorCount === 1 ? '' : 's'} before.`
          : 'New contact — your first meeting.'}
      </div>
      <ParticipantInsightsCard brief={brief} />
      <HeadsUpSection notes={brief.caution_notes} />
      <TalkingPointsSection brief={brief} />
      <SuggestedAgendaSection items={brief.suggested_agenda} />
      <PreviousInteractionsSection brief={brief} />
      <OpenCommitmentsSection commitments={brief.open_commitments} />
      <SourcesUsedFooter sources={brief.sources_used} />
    </div>
  );
}
