'use client';

import React from 'react';

export interface OpenLoopCommitment {
  what: string;
  from_meeting_id: string | null;
  from_meeting_title: string | null;
  from_meeting_date: string | null;   // "2026-05-20"
  days_open: number;
}

interface OpenLoopsPanelProps {
  youOwe: OpenLoopCommitment[];
  theyOwe: OpenLoopCommitment[];
  twinId: string;
}

/**
 * Right rail on desktop, below timeline on mobile.
 * The page's primary answer: "do I owe them, or do they owe me?"
 *
 * Each commitment row is one line: bullet + what + dimmed meeting attribution.
 * Days-open chip turns amber > 14d, never red unless > 30d.
 */
export default function OpenLoopsPanel({
  youOwe,
  theyOwe,
  twinId,
}: OpenLoopsPanelProps): React.JSX.Element {
  const total = youOwe.length + theyOwe.length;

  if (total === 0) {
    return (
      <div
        className="rounded-3xl px-5 py-6 text-center"
        style={{
          backgroundColor: 'var(--fog-2)',
          border: '1px solid var(--fog-line)',
        }}
      >
        <p className="text-sm font-medium" style={{ color: 'var(--ok)' }}>
          All clear ✓
        </p>
        <p className="mt-1 text-xs" style={{ color: 'var(--fg-3)' }}>
          No open commitments either way.
        </p>
      </div>
    );
  }

  return (
    <div
      className="rounded-3xl px-5 py-5"
      style={{
        backgroundColor: 'var(--fog-2)',
        border: '1px solid var(--fog-line)',
      }}
    >
      <div className="mb-4 flex items-baseline justify-between">
        <h3
          className="text-[11px] font-semibold uppercase"
          style={{
            color: 'var(--fg-2)',
            fontFamily: 'var(--font-geist-mono, JetBrains Mono, monospace)',
            letterSpacing: '0.12em',
          }}
        >
          Open loops
        </h3>
        <span
          className="text-[11px]"
          style={{
            color: 'var(--fg-3)',
            fontFamily: 'var(--font-geist-mono, JetBrains Mono, monospace)',
          }}
        >
          {total}
        </span>
      </div>

      {youOwe.length > 0 && (
        <CommitmentSection
          heading="You owe"
          items={youOwe}
          accent="warn"
          twinId={twinId}
        />
      )}

      {youOwe.length > 0 && theyOwe.length > 0 && (
        <div className="my-3" style={{ borderTop: '1px solid var(--fog-line)' }} />
      )}

      {theyOwe.length > 0 && (
        <CommitmentSection
          heading="They owe"
          items={theyOwe}
          accent="signal"
          twinId={twinId}
        />
      )}
    </div>
  );
}

interface CommitmentSectionProps {
  heading: string;
  items: OpenLoopCommitment[];
  accent: 'warn' | 'signal';
  twinId: string;
}

function CommitmentSection({
  heading,
  items,
  accent,
  twinId,
}: CommitmentSectionProps): React.JSX.Element {
  const accentColor =
    accent === 'warn' ? 'var(--warn)' : 'var(--signal)';
  return (
    <div>
      <p
        className="mb-2 text-[10.5px] uppercase"
        style={{
          color: accentColor,
          fontFamily: 'var(--font-geist-mono, JetBrains Mono, monospace)',
          letterSpacing: '0.10em',
        }}
      >
        {heading}
      </p>
      <ul className="space-y-2">
        {items.map((c, i) => (
          <li key={`${c.from_meeting_id ?? 'm'}-${i}`} className="text-[13px]">
            <a
              href={
                c.from_meeting_id
                  ? `/dashboard/meetings/${c.from_meeting_id}?twin=${twinId}`
                  : '#'
              }
              className="block transition-colors"
              style={{ color: 'var(--ink)', textDecoration: 'none' }}
            >
              <span style={{ color: accentColor, marginRight: '6px' }}>•</span>
              {c.what}
              <span
                className="ml-2 text-[11px]"
                style={{
                  color: c.days_open > 30 ? 'var(--rec)' : c.days_open > 14 ? 'var(--warn)' : 'var(--fg-3)',
                  fontFamily: 'var(--font-geist-mono, JetBrains Mono, monospace)',
                }}
              >
                {c.days_open === 0 ? 'today' : `${c.days_open}d open`}
              </span>
              {c.from_meeting_title && (
                <div
                  className="mt-0.5 truncate text-[11px]"
                  style={{ color: 'var(--fg-3)', paddingLeft: '14px' }}
                >
                  {c.from_meeting_title}
                </div>
              )}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
