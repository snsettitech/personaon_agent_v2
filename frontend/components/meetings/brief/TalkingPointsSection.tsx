'use client';

import React from 'react';
import type { BriefContract, TalkingPoint } from '@/lib/types/brief';
import { Section } from './Section';

/**
 * W9c — Talking points (was v1 "Hooks to lead with").
 *
 * Reads ``brief.talking_points`` (v2 ``{topic, rationale}``). Falls
 * back to mapping v1 ``brief.hooks[]`` (``{label, text}``) when v2
 * array is missing — keeps legacy briefs rendering.
 *
 * Returns null when both arrays are empty so the section disappears
 * cleanly (no "no talking points" placeholder).
 */

interface TalkingPointsSectionProps {
  brief: BriefContract;
}

export function TalkingPointsSection({
  brief,
}: TalkingPointsSectionProps): React.JSX.Element | null {
  const points: TalkingPoint[] =
    brief.talking_points && brief.talking_points.length > 0
      ? brief.talking_points
      : brief.hooks.map((h) => ({
          topic: h.text || '',
          rationale: h.label || '',
        }));

  const visible = points.filter((p) => (p.topic || '').trim().length > 0);
  if (visible.length === 0) return null;

  return (
    <Section title="Talking points">
      <ul className="space-y-3 list-none p-0 m-0">
        {visible.map((p, i) => (
          <li key={i} className="flex items-start gap-3">
            {p.rationale && (
              <span
                className="inline-flex items-center px-2 py-0.5 rounded-full font-mono text-[10px] uppercase tracking-[0.15em] flex-shrink-0 mt-0.5"
                style={{
                  background: 'var(--bg-surface)',
                  color: 'var(--text-secondary)',
                }}
              >
                {p.rationale}
              </span>
            )}
            <span
              className="text-sm leading-relaxed"
              style={{ color: 'var(--text-primary)' }}
            >
              {p.topic}
            </span>
          </li>
        ))}
      </ul>
    </Section>
  );
}
