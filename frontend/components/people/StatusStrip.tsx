'use client';

import React from 'react';

interface StatusStripProps {
  lastTalkedLabel: string;   // "12d ago" / "never" / "today"
  youOweLabel: string;       // "reply re: dashboard" / "—"
  nextLabel: string;         // "coffee Thu" / "—"
}

/**
 * The Status Strip — three pills directly under the hero on the person profile.
 * Answers the One Question above the fold: do I owe them or do they owe me?
 *
 * Single row, middot-separated, never multi-line on desktop. Each pill
 * truncates at ~30 chars to keep the line tight.
 */
export default function StatusStrip({
  lastTalkedLabel,
  youOweLabel,
  nextLabel,
}: StatusStripProps): React.JSX.Element {
  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl px-4 py-3"
      style={{
        backgroundColor: 'var(--fog)',
        border: '1px solid var(--fog-line)',
      }}
    >
      <Pill label="Last talked" value={lastTalkedLabel} variant="neutral" />
      <Separator />
      <Pill
        label="You owe"
        value={youOweLabel}
        variant={youOweLabel === '—' ? 'neutral' : 'warn'}
      />
      <Separator />
      <Pill label="Next" value={nextLabel} variant="neutral" />
    </div>
  );
}

interface PillProps {
  label: string;
  value: string;
  variant: 'neutral' | 'warn' | 'ok';
}

function Pill({ label, value, variant }: PillProps): React.JSX.Element {
  const valueColor =
    variant === 'warn'
      ? 'var(--warn)'
      : variant === 'ok'
        ? 'var(--ok)'
        : 'var(--ink)';
  return (
    <span
      className="inline-flex items-baseline gap-1.5 text-[13px]"
      style={{ color: 'var(--fg-2)' }}
    >
      <span
        className="uppercase tracking-wide"
        style={{
          fontFamily: 'var(--font-geist-mono, JetBrains Mono, monospace)',
          fontSize: '10.5px',
          letterSpacing: '0.08em',
          color: 'var(--fg-3)',
        }}
      >
        {label}
      </span>
      <span style={{ color: valueColor, fontWeight: 500 }}>{value}</span>
    </span>
  );
}

function Separator(): React.JSX.Element {
  return (
    <span aria-hidden style={{ color: 'var(--fg-3)' }}>
      ·
    </span>
  );
}
