'use client';

import React from 'react';
import type { SourcesUsed } from '@/lib/types/brief';

/**
 * W9c — Sources-used footer.
 *
 * Renders the small muted line "Built from N notes, M past meetings,
 * K web sources" at the bottom of the brief. Only includes parts that
 * are non-zero, so a brief built only from past meetings reads
 * "Built from 3 past meetings" without trailing zeros.
 *
 * Hidden entirely when all counts are zero — e.g. v1 briefs (no
 * sources_used field) or completely cold-start briefs. Per the W9
 * design contract, no "Built from nothing" placeholder.
 *
 * The footer is the citation surface for the WHOLE brief (Heads Up
 * has per-note citations; this is the aggregate). Matches the Granola
 * pattern from the UX research: "every brief shows its work."
 */

interface SourcesUsedFooterProps {
  sources: SourcesUsed | undefined;
}

export function SourcesUsedFooter({
  sources,
}: SourcesUsedFooterProps): React.JSX.Element | null {
  if (!sources) return null;
  const parts: string[] = [];
  if (sources.kb_chunks > 0) {
    parts.push(`${sources.kb_chunks} note${sources.kb_chunks === 1 ? '' : 's'}`);
  }
  if (sources.past_meetings > 0) {
    parts.push(
      `${sources.past_meetings} past meeting${sources.past_meetings === 1 ? '' : 's'}`,
    );
  }
  if (sources.web_results > 0) {
    parts.push(
      `${sources.web_results} web source${sources.web_results === 1 ? '' : 's'}`,
    );
  }
  if (parts.length === 0) return null;

  return (
    /* AUDIT FIX (W9c):
       - --text-muted (0.40 alpha = ~2.9:1 on white) failed WCAG AA at 11px;
         switched to --text-secondary (0.58 alpha = ~5.2:1)
       - dropped uppercase: the all-caps mono treatment read as a server log
         line. Keep font-mono for the "receipt" feel (matches dates elsewhere)
         but case-normal so it reads as a friendly footnote, not an audit log. */
    <div
      className="mt-4 text-center font-mono text-[11px]"
      style={{ color: 'var(--text-secondary)' }}
    >
      Built from {parts.join(' · ')}
    </div>
  );
}
