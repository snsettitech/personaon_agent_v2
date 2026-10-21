'use client';

import React from 'react';
import type { OpenCommitment } from '@/lib/types/brief';
import { Section } from './Section';

/**
 * W9c — Open commitments (was v1 "Open from last time").
 *
 * Shape unchanged from v1 — backend ``_extract_open_commitments`` still
 * emits ``{description, days_open, from_meeting_id, ...}``. The only
 * change from v1 is the visual treatment via shared Section primitive
 * and the days-open pill colour-coded by staleness.
 *
 * Returns null when array is empty.
 */

interface OpenCommitmentsSectionProps {
  commitments: OpenCommitment[];
}

export function OpenCommitmentsSection({
  commitments,
}: OpenCommitmentsSectionProps): React.JSX.Element | null {
  if (!commitments || commitments.length === 0) return null;

  return (
    /* AUDIT FIX (W9c UX): title was "Still open" which collided with
       the LLM Heads Up note prefix "Still open —" emitted for
       action_item_pending candidates. Same words on the same page,
       unrelated sections — confusing. Renamed to "Still on your list"
       so commitments-the-section and "Still open"-the-note-prefix are
       distinct surfaces. */
    <Section title="Still on your list">
      <ul className="space-y-3 list-none p-0 m-0">
        {commitments.map((c, i) => (
          <li key={i} className="flex items-start gap-3">
            <DaysOpenPill days={c.days_open} />
            <span
              className="text-sm leading-relaxed"
              style={{ color: 'var(--text-primary)' }}
            >
              {c.description}
            </span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function DaysOpenPill({ days }: { days: number }): React.JSX.Element {
  // Stale color thresholds mirror the Heads Up rule threshold (7) so the
  // visual cue and the rule-firing line up. > 7 days = amber pill,
  // <= 7 = neutral. We never use red here per the W9 design contract
  // (no alarm signals).
  const isStale = days > 7;
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full font-mono text-[10px] uppercase tracking-[0.15em] flex-shrink-0 mt-0.5"
      style={{
        background: isStale
          ? 'var(--accent-trust-light)'
          : 'var(--bg-surface)',
        color: isStale
          ? 'var(--accent-trust-dark)'
          : 'var(--text-secondary)',
      }}
    >
      {days}d
    </span>
  );
}
