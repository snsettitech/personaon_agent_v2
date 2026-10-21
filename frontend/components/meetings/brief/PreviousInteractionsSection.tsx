'use client';

import React from 'react';
import type {
  BriefContract,
  PreviousInteraction,
} from '@/lib/types/brief';
import { Section } from './Section';

/**
 * W9c — Previous interactions (was v1 "Your history with X").
 *
 * Reads ``brief.previous_interactions`` (v2) which carries each prior
 * meeting's ``open_items[]`` — the action_items that the v1 UI fetched
 * and threw away. Falls back to ``brief.prior_meetings`` (v1) when the
 * v2 array is missing.
 *
 * Returns null when both arrays are empty.
 */

interface PreviousInteractionsSectionProps {
  brief: BriefContract;
}

export function PreviousInteractionsSection({
  brief,
}: PreviousInteractionsSectionProps): React.JSX.Element | null {
  const interactions: PreviousInteraction[] = (() => {
    if (brief.previous_interactions && brief.previous_interactions.length > 0) {
      return brief.previous_interactions;
    }
    // v1 fallback: synthesize from prior_meetings (no open_items available).
    return brief.prior_meetings.map((m) => ({
      meeting_id: m.meeting_id,
      date: m.date,
      meeting_title: m.title,
      summary: m.summary,
      open_items: [],
    }));
  })();

  if (interactions.length === 0) return null;

  return (
    <Section title="From last time">
      <ul className="space-y-5 list-none p-0 m-0">
        {interactions.map((it, i) => (
          <li
            key={it.meeting_id || i}
            className="pb-4"
            style={{
              borderBottom:
                i < interactions.length - 1
                  ? '1px solid var(--border-subtle)'
                  : 'none',
            }}
          >
            <div className="flex items-baseline justify-between gap-3 mb-1.5">
              <span
                className="text-sm font-semibold truncate"
                style={{ color: 'var(--text-primary)' }}
              >
                {it.meeting_title || 'Untitled meeting'}
              </span>
              {it.date && (
                <span
                  className="font-mono text-[11px] flex-shrink-0"
                  style={{ color: 'var(--text-muted)' }}
                >
                  {formatDate(it.date)}
                </span>
              )}
            </div>
            {it.summary && (
              <p
                className="text-sm leading-relaxed mb-2"
                style={{ color: 'var(--text-secondary)' }}
              >
                {it.summary}
              </p>
            )}
            {it.open_items.length > 0 && (
              <ul className="mt-2 space-y-1 list-none p-0 m-0">
                {it.open_items.map((item, k) => (
                  <li
                    key={k}
                    className="text-xs flex items-baseline gap-2"
                    style={{ color: 'var(--text-secondary)' }}
                  >
                    <span
                      aria-hidden
                      style={{ color: 'var(--accent-trust-dark)' }}
                    >
                      •
                    </span>
                    <span>Open: {item}</span>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </Section>
  );
}

function formatDate(iso: string): string {
  // Expect YYYY-MM-DD; reformat to "May 8" / "Apr 22, 2025" for older dates.
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const now = new Date();
  const sameYear = d.getFullYear() === now.getFullYear();
  const month = d.toLocaleDateString('en-US', { month: 'short' });
  const day = d.getDate();
  return sameYear ? `${month} ${day}` : `${month} ${day}, ${d.getFullYear()}`;
}
