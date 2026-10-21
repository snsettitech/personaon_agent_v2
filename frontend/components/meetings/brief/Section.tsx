'use client';

import React from 'react';

/**
 * W9c — Generic brief section card.
 *
 * Wraps content in a rounded card with an optional uppercase eyebrow label.
 * Two tones:
 *   - `default` — neutral card (var(--bg-card))
 *   - `amber`   — Heads Up treatment (var(--accent-trust-light) +
 *                 var(--border-trust))
 *
 * Migrates the brief page off hardcoded hex colours to the CSS token
 * system in `globals.css`, so dark mode + future theming come for free.
 */

interface SectionProps {
  /** Small uppercase label rendered above the title. */
  eyebrow?: string;
  /** Optional H2 inside the card. */
  title?: string;
  /** Tone variant: default neutral, or amber for Heads Up. */
  tone?: 'default' | 'amber';
  /** Card body. */
  children: React.ReactNode;
}

export function Section({
  eyebrow,
  title,
  tone = 'default',
  children,
}: SectionProps): React.JSX.Element {
  const isAmber = tone === 'amber';
  return (
    <section
      // AUDIT FIX (W9c): amber Heads Up card keeps a subtle shadow so it
      // has visual weight equal to the neutral cards below. Without it the
      // section reads as a flat banner and users skim past — bad outcome
      // for the highest-stakes surface in the brief.
      className="rounded-[30px] p-5 md:p-7 mb-4"
      style={{
        backgroundColor: isAmber
          ? 'var(--accent-trust-light)'
          : 'var(--bg-card)',
        border: `1px solid ${
          isAmber ? 'var(--border-trust)' : 'var(--border-subtle)'
        }`,
        boxShadow: 'var(--shadow-card)',
      }}
    >
      {eyebrow && (
        <div
          className="font-mono text-[11px] uppercase tracking-[0.15em] mb-3"
          style={{
            color: isAmber
              ? 'var(--accent-trust-dark)'
              : 'var(--text-muted)',
          }}
        >
          {eyebrow}
        </div>
      )}
      {title && (
        <h2
          className="text-lg font-semibold mb-3"
          style={{ color: 'var(--text-primary)' }}
        >
          {title}
        </h2>
      )}
      {children}
    </section>
  );
}
