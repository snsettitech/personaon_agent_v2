'use client';

import React from 'react';
import type { CautionNote, CautionSource } from '@/lib/types/brief';
import { Section } from './Section';

/**
 * W9b/c — "Heads Up" caution notes.
 *
 * Per the W9 design contract this is the trickiest UI surface in the
 * whole stack — wrong tone is a trust killer. Discipline:
 *
 *   1. Returns null when notes is empty. NEVER show "no concerns" or
 *      "all clear" — that creates a false safety signal. The Heads Up
 *      section either has content or doesn't exist at all.
 *
 *   2. Quiet amber tone (var(--accent-trust-light) + var(--border-trust))
 *      via Section tone="amber" — not alarming red, not exclamation marks.
 *
 *   3. Each note is collapsed by default with a <details>/<summary>
 *      citation chevron. Click expands the source.quote inline so the
 *      user can always click through to the receipt — citation is the
 *      snark antidote per the UX research.
 *
 *   4. Tone is enforced upstream (heads_up_prompt SYSTEM_PROMPT + the
 *      heads_up_safety blocklist). The UI presumes the rewriter output
 *      passes the eval contract and renders it verbatim.
 */

interface HeadsUpSectionProps {
  notes: CautionNote[] | undefined;
}

export function HeadsUpSection({
  notes,
}: HeadsUpSectionProps): React.JSX.Element | null {
  if (!notes || notes.length === 0) return null;

  return (
    <Section eyebrow="Heads up" tone="amber">
      <ul className="space-y-2 list-none p-0 m-0">
        {notes.map((note, i) => (
          // AUDIT FIX (PR #132 post-merge): composite key includes source
          // identity so React reconciles by note identity, not list index.
          // Without this, expanding note A and then receiving a new brief
          // (deep-research completion) where notes reorder leaves the
          // <details> open on the wrong note.
          <li key={`${note.source.kind}-${note.source.ref}-${i}`}>
            <CautionNoteItem note={note} />
          </li>
        ))}
      </ul>
    </Section>
  );
}

function CautionNoteItem({ note }: { note: CautionNote }): React.JSX.Element {
  return (
    <details className="group">
      {/*
        AUDIT FIX (W9c):
        - min-h-[44px] + py-2 gives a 44px tap target per WCAG 2.5.5
        - hover bg + decoration-dotted under the note text signals the row
          is clickable; users were missing the chevron affordance entirely
        - ring-offset-color matches the amber card so the focus ring halo
          renders on the parent's bg, not a stray white square
        - "Show source" microcopy makes the receipt discoverable on first
          paint, not buried behind a tiny chevron
      */}
      <summary
        className="cursor-pointer list-none flex items-start gap-2 min-h-[44px] py-2 px-1 -mx-1 rounded-md outline-none transition-colors hover:bg-black/[0.03] focus-visible:ring-2 focus-visible:ring-offset-2"
        style={
          {
            color: 'var(--text-primary)',
            // ring-offset color must match the amber Section bg so the halo
            // doesn't render on a stray white square.
            '--tw-ring-offset-color': 'var(--accent-trust-light)',
            '--tw-ring-color': 'var(--accent-trust-dark)',
          } as React.CSSProperties
        }
      >
        <span
          aria-hidden
          className="mt-1 inline-block transition-transform group-open:rotate-90 text-xs font-mono"
          style={{ color: 'var(--accent-trust-dark)' }}
        >
          ▸
        </span>
        <span className="flex-1 min-w-0">
          <span className="text-sm leading-relaxed">{note.text}</span>
          <span
            aria-hidden
            className="ml-2 text-[10px] font-mono uppercase tracking-[0.15em] group-open:hidden"
            style={{ color: 'var(--accent-trust-dark)' }}
          >
            Show source
          </span>
        </span>
      </summary>
      <CitationPanel source={note.source} />
    </details>
  );
}

function CitationPanel({
  source,
}: {
  source: CautionSource;
}): React.JSX.Element | null {
  // AUDIT FIX (W9c): suppress the entire panel when there's no real quote.
  // Rendering "—" in italic smart-quotes read as "the system has nothing
  // to back this up" — corrosive to the citation-trust contract.
  const hasQuote = (source.quote || '').trim().length > 0;
  if (!hasQuote && !source.ref) return null;
  return (
    <div
      role="region"
      aria-label="Source citation"
      className="mt-2 ml-5 p-3 rounded-md text-xs break-words"
      style={{
        backgroundColor: 'var(--bg-card)',
        border: '1px solid var(--border-subtle)',
        // AUDIT FIX (W9c): --text-secondary (0.58 alpha = ~5.2:1 on white)
        // instead of --text-muted (0.40 = ~2.9:1, fails AA at 10-12px).
        color: 'var(--text-secondary)',
      }}
    >
      <div
        className="font-mono text-[10px] uppercase tracking-[0.15em] mb-1.5"
        style={{ color: 'var(--accent-trust-dark)' }}
      >
        {sourceLabel(source)}
      </div>
      {hasQuote && (
        <div className="italic leading-relaxed break-words">
          &ldquo;{source.quote}&rdquo;
        </div>
      )}
    </div>
  );
}

/**
 * Friendly source label for the citation panel. The user sees these
 * verbatim, so they must read like an ally surfacing a receipt — not
 * like a database column name. Falls back to a neutral 'Source' for
 * unknown kinds.
 *
 * AUDIT FIX (W9c UX review): a few labels read clinically — "Pattern
 * across past meetings", "Unresolved across past meetings", "Context
 * for this meeting". Rewritten to temporal/observational phrasing.
 */
function sourceLabel(source: CautionSource): string {
  switch (source.kind) {
    case 'kb_private_hit':
      return 'From your private notes';
    case 'open_commitment':
      return 'From a past meeting';
    case 'action_item_pending':
      return source.ref_type === 'meeting_id'
        ? 'From a past meeting'
        : 'From your notes';
    case 'pdl_change':
      return 'Profile change since you last met';
    case 'agenda_signal_other_organizer':
      return 'From your last meeting together';
    case 'reschedule_pattern':
      return 'Calendar history';
    case 'prior_topic_tension':
      return 'From a past meeting';
    case 'news_event':
      return 'Recent news';
    case 'meeting_outcome_pattern':
      return 'From your last few meetings with them';
    case 'personal_context':
      return 'From a recent message';
    case 'unresolved_topic':
      return 'Across your last few meetings';
    default:
      return 'Source';
  }
}
