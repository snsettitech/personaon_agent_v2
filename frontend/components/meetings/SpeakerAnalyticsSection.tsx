'use client';

/**
 * Speaker Analytics — talk-time / WPM / filler / sentiment table for a completed
 * meeting. Extracted verbatim (data + helpers) from the legacy meeting page so the
 * unified v2 Recap tab can render it without duplicating logic. Self-contained:
 * owns its own collapsible card + formatting helpers + sentiment badge.
 * See docs/product/meetings-spec-and-plan.md §9 (Phase B-final port).
 */
import React, { useState } from 'react';

export interface SpeakerAnalytics {
  participant_name: string;
  talk_time_seconds: number;
  talk_time_pct: number;
  word_count: number;
  words_per_minute: number;
  filler_word_count: number;
  sentiment_label: string;
  sentiment_score: number;
}

function formatDuration(seconds: number | null): string {
  if (seconds == null || seconds <= 0) return '0s';
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  if (mins <= 0) return `${secs}s`;
  return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
}

function formatPct(pct: number): string {
  return `${Math.round(pct)}%`;
}

function formatWpm(wpm: number): string {
  return `${Math.round(wpm)}`;
}

function SentimentBadge({ label }: { label: string }): React.JSX.Element {
  const tone = (label || '').toLowerCase();
  const color =
    tone === 'positive' ? { bg: '#e6f7ee', fg: '#1a7f4b' }
      : tone === 'negative' ? { bg: '#fdeaea', fg: '#c0392b' }
        : { bg: 'var(--fog, #f3f4f6)', fg: 'var(--text-secondary, #555)' };
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium capitalize"
      style={{ backgroundColor: color.bg, color: color.fg }}
    >
      {label || 'neutral'}
    </span>
  );
}

interface SpeakerAnalyticsSectionProps {
  analytics: SpeakerAnalytics[] | null | undefined;
}

/**
 * Renders the analytics table when rows exist; returns null when there are none
 * (the unified page shows no orphan "no analytics" card — consistent with the
 * other v2 sections that disappear cleanly when empty).
 */
export default function SpeakerAnalyticsSection({
  analytics,
}: SpeakerAnalyticsSectionProps): React.JSX.Element | null {
  const [open, setOpen] = useState(false);
  const rows = analytics ?? [];
  if (rows.length === 0) return null;

  return (
    <div className="rounded-2xl border border-black/[0.06]" style={{ backgroundColor: 'var(--bg-card, #fff)' }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-5 py-3 text-left text-sm font-semibold"
        style={{ color: 'var(--text-primary, #111)' }}
      >
        <span>Speaker analytics</span>
        <span style={{ color: 'var(--text-muted, #888)' }}>{open ? '–' : '+'}</span>
      </button>
      {open && (
        <div className="px-5 pb-4">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-subtle, #eee)' }}>
                  {(['Speaker', 'Talk time', 'Talk %', 'WPM', 'Filler', 'Sentiment'] as const).map((h) => (
                    <th
                      key={h}
                      className="pb-2 pr-4 text-left text-[11px] font-semibold uppercase tracking-wide"
                      style={{ color: 'var(--text-muted, #888)' }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y" style={{ borderColor: 'var(--border-subtle, #eee)' }}>
                {rows.map((row, i) => (
                  <tr key={i}>
                    <td className="py-2.5 pr-4 font-medium" style={{ color: 'var(--text-primary, #111)' }}>
                      {row.participant_name}
                    </td>
                    <td className="py-2.5 pr-4" style={{ color: 'var(--text-secondary, #555)' }}>
                      {formatDuration(row.talk_time_seconds)}
                    </td>
                    <td className="py-2.5 pr-4" style={{ color: 'var(--text-secondary, #555)' }}>
                      {formatPct(row.talk_time_pct)}
                    </td>
                    <td className="py-2.5 pr-4" style={{ color: 'var(--text-secondary, #555)' }}>
                      {formatWpm(row.words_per_minute)}
                    </td>
                    <td className="py-2.5 pr-4" style={{ color: 'var(--text-secondary, #555)' }}>
                      {row.filler_word_count}
                    </td>
                    <td className="py-2.5">
                      <SentimentBadge label={row.sentiment_label} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
