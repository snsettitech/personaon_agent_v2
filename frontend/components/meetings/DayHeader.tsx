'use client';

import React from 'react';

interface DayHeaderProps {
  label: string;
  meta?: string;
}

export default function DayHeader({ label, meta }: DayHeaderProps): React.JSX.Element {
  return (
    <div className="mb-3 flex items-baseline gap-3.5 pl-1">
      <span
        className="text-[11px] font-medium uppercase"
        style={{
          color: 'var(--fg-2)',
          fontFamily: 'var(--font-geist-mono, JetBrains Mono, monospace)',
          letterSpacing: '0.15em',
        }}
      >
        {label}
      </span>
      {meta && (
        <span
          className="text-[12px]"
          style={{
            color: 'var(--fg-3)',
            fontFamily: 'var(--font-geist-mono, JetBrains Mono, monospace)',
          }}
        >
          {meta}
        </span>
      )}
    </div>
  );
}
