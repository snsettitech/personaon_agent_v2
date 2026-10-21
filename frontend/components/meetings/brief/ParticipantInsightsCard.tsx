'use client';

import React from 'react';
import type {
  BriefContract,
  ParticipantInsight,
} from '@/lib/types/brief';
import { Section } from './Section';

/**
 * W9c — Multi-attendee participant insights card.
 *
 * Renders one row per attendee, up to 4 (matches the backend
 * ``_extract_participant_insights`` cap). When ``participant_insights``
 * is missing or empty AND the v1 ``person`` block has data, falls back
 * to a single legacy row so old briefs continue to render.
 *
 * Per the W9 design contract, the user is excluded from this list
 * (backend handles the self-exclusion before sending) — so this card
 * shows OTHER attendees, never the user themselves.
 */

interface ParticipantInsightsCardProps {
  brief: BriefContract;
}

export function ParticipantInsightsCard({
  brief,
}: ParticipantInsightsCardProps): React.JSX.Element | null {
  const insights = brief.participant_insights ?? [];

  // v1 fallback: synthesize a single-entry list from person + meeting
  // attendees so legacy briefs (or v2 briefs where the rule didn't fire)
  // still show the primary attendee in the same UI shell.
  const rows: ParticipantInsight[] =
    insights.length > 0 ? insights : v1FallbackRows(brief);

  if (rows.length === 0) return null;

  // AUDIT FIX (W9c): overflow derived from rows.length (the union of v2
  // insights AND v1 fallback) so the counter stays consistent regardless
  // of which path produced the visible list. Previous version used
  // insights.length which would drift if a future code path populates both.
  const overflow = rows.length > 4 ? rows.length - 4 : 0;
  const visible = rows.slice(0, 4);

  return (
    <Section title="Who you're meeting">
      <ul className="space-y-4 list-none p-0 m-0">
        {visible.map((p, i) => {
          // AUDIT FIX (W9c): evaluate pdlLine ONCE per row instead of twice.
          const pdl = pdlLine(p);
          return (
          <li key={p.email || i} className="flex items-start gap-5">
            <Avatar name={p.name} />
            <div className="flex-1 min-w-0">
              <div
                className="text-xl font-semibold tracking-tight"
                style={{ color: 'var(--text-primary)' }}
              >
                {p.name || p.email || 'Unknown attendee'}
              </div>
              {pdl && (
                <div
                  className="text-sm mt-0.5"
                  style={{ color: 'var(--text-secondary)' }}
                >
                  {pdl}
                </div>
              )}
              {p.background && (
                <p
                  className="text-sm mt-2 leading-relaxed"
                  style={{ color: 'var(--text-secondary)' }}
                >
                  {p.background}
                </p>
              )}
            </div>
          </li>
          );
        })}
      </ul>
      {overflow > 0 && (
        <div
          className="mt-3 text-xs font-mono"
          style={{ color: 'var(--text-muted)' }}
        >
          + {overflow} more attendee{overflow === 1 ? '' : 's'}
        </div>
      )}
    </Section>
  );
}

function Avatar({ name }: { name: string }): React.JSX.Element {
  return (
    <div
      aria-hidden
      className="w-14 h-14 rounded-full flex-shrink-0 flex items-center justify-center text-white font-semibold text-xl"
      style={{
        background: 'linear-gradient(135deg, #0066cc 0%, #5b9bf6 100%)',
        letterSpacing: '-0.02em',
      }}
    >
      {getInitials(name)}
    </div>
  );
}

function getInitials(name: string): string {
  const trimmed = (name || '').trim();
  if (!trimmed) return '?';
  const parts = trimmed.split(/\s+/);
  if (parts.length === 1) return parts[0][0].toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function pdlLine(p: ParticipantInsight): string {
  const fromSnapshot = p.pdl_snapshot;
  const role = (fromSnapshot?.role ?? p.role ?? '').trim();
  const company = (fromSnapshot?.company ?? '').trim();
  return [role, company].filter(Boolean).join(' · ');
}

function v1FallbackRows(brief: BriefContract): ParticipantInsight[] {
  const person = brief.person;
  if (!person?.name && !person?.email) return [];
  // AUDIT FIX (W9c): use ?? null coalescing instead of `as string` coercion.
  // BriefPerson has a [key: string]: unknown index signature so a renamed
  // backend field would slip past these reads — fail open with null rather
  // than silently casting unknown to string.
  const personRole = typeof person.role === 'string' ? person.role : null;
  const personCompany =
    typeof person.company === 'string' ? person.company : null;
  return [
    {
      name: typeof person.name === 'string' ? person.name : '',
      email: typeof person.email === 'string' ? person.email : '',
      role: personRole,
      background: typeof person.bio === 'string' ? person.bio : null,
      recent_activities: [],
      web_sources: [],
      pdl_snapshot: personCompany
        ? { company: personCompany, role: personRole }
        : null,
    },
  ];
}
