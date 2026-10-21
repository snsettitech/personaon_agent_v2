'use client';

import React from 'react';
import type { BriefContract } from '@/lib/types/brief';
import { primaryDisplayName } from '@/lib/types/brief';

/**
 * W9c — Pre-meeting brief hero.
 *
 * Renders the "You × {primary attendee}" headline plus a date/time line
 * with an optional countdown pill. The brief's enriched-state eyebrow
 * (Brief · ready vs Brief · partial) lives here too.
 *
 * Reads ``participant_insights[0].name`` first via ``primaryDisplayName``
 * so v2 briefs with no PDL enrichment still show the calendar display
 * name. Falls back to ``person.name`` (v1) then to "this person".
 */

interface CountdownState {
  /** Compact label like "starts in 12m" or "happening now". */
  label: string;
  /** True when within the ~15 minute join window. */
  isImminent: boolean;
  /** True when the meeting start time is already in the past. */
  isPast: boolean;
}

interface BriefHeroProps {
  brief: BriefContract;
  dateLabel: string;
  timeLabel: string;
  countdown?: CountdownState | null;
  /** True when ANY signal was found (hooks, prior meetings, PDL). */
  isEnriched: boolean;
}

export function BriefHero({
  brief,
  dateLabel,
  timeLabel,
  countdown,
  isEnriched,
}: BriefHeroProps): React.JSX.Element {
  const personName = primaryDisplayName(brief);
  const eyebrowLabel = isEnriched ? 'Brief · ready' : 'Brief · partial';

  return (
    <div className="mb-8">
      <span
        className="inline-flex items-center gap-2 px-3 py-1 rounded-full mb-4 font-mono text-[11px] uppercase tracking-[0.15em]"
        style={{
          // signal-soft tint isn't tokenized in globals.css; mirror the
          // existing rgba used elsewhere in the brief page.
          background: isEnriched
            ? 'rgba(0, 102, 204, 0.08)'
            : 'var(--accent-trust-light)',
          color: isEnriched
            ? 'var(--signal)'
            : 'var(--accent-trust-dark)',
        }}
      >
        <span
          aria-hidden
          className="w-1.5 h-1.5 rounded-full"
          style={{
            background: 'currentColor',
            animation: isEnriched
              ? 'personaPulse 1.5s ease-in-out infinite'
              : undefined,
          }}
        />
        {eyebrowLabel}
      </span>
      <h1
        className="font-semibold tracking-tight m-0"
        style={{
          fontSize: 'clamp(32px, 4vw, 44px)',
          lineHeight: 1.05,
          color: 'var(--text-primary)',
        }}
      >
        You ×{' '}
        <span style={{ color: 'var(--text-muted)', fontWeight: 500 }}>
          {personName}
        </span>
      </h1>
      <p
        className="mt-3 text-[15px]"
        style={{ color: 'var(--text-secondary)', letterSpacing: '-0.005em' }}
      >
        {[dateLabel, timeLabel].filter(Boolean).join(' · ')}
        {countdown && (
          <span
            className="inline-flex items-center gap-1.5 ml-1.5 px-2.5 py-0.5 rounded-full font-mono text-xs font-medium"
            style={{
              background: countdown.isImminent
                ? 'var(--accent-emerald-light)'
                : 'var(--bg-surface)',
              color: countdown.isImminent
                ? 'var(--ok)'
                : 'var(--text-secondary)',
            }}
          >
            ● {countdown.label}
          </span>
        )}
      </p>
    </div>
  );
}
