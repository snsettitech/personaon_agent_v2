'use client';

import React from 'react';
import { Section } from './Section';

/**
 * W9c — Suggested agenda (numbered list).
 *
 * Backend (``persona_core/brief._generate_agenda``) produces a rule-based
 * ordering: warm-up reference → top open commitments → user's stated
 * goal → top talking points → "next steps + timing". Capped at 6 items.
 *
 * Frontend just renders the list verbatim. Returns null when empty so
 * the section disappears for briefs with no signals.
 *
 * Per the W9 design contract this is a SUGGESTION, not a contract.
 * Future enhancement (deferred): inline "dismiss" button so the user
 * can clear items without a backend round-trip — requires localStorage
 * or a per-twin state column, punt to follow-up.
 */

interface SuggestedAgendaSectionProps {
  items: string[] | undefined;
}

export function SuggestedAgendaSection({
  items,
}: SuggestedAgendaSectionProps): React.JSX.Element | null {
  if (!items || items.length === 0) return null;

  return (
    <Section title="Suggested agenda">
      <ol className="space-y-2 list-none p-0 m-0">
        {items.map((item, i) => (
          <li key={i} className="flex items-baseline gap-3">
            <span
              className="font-mono text-xs flex-shrink-0 w-5 text-right"
              style={{ color: 'var(--text-muted)' }}
              aria-hidden
            >
              {i + 1}.
            </span>
            <span
              className="text-sm leading-relaxed"
              style={{ color: 'var(--text-primary)' }}
            >
              {item}
            </span>
          </li>
        ))}
      </ol>
    </Section>
  );
}
