'use client';

import React from 'react';
import type { Database } from '@/lib/database.types';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TwinResponseSource {
  text: string;
  source_id?: string;
}

// TwinResponse shape is derived directly from the DB row type, with `sources`
// narrowed from `Json | null` to its runtime structure. The nullability of
// question_text, confidence, and sources comes from the schema generator;
// if the DB changes (e.g. a column becomes NOT NULL), re-run
// scripts/regen-db-types.sh and the compiler will update consumers.
type TwinResponseRow = Database['public']['Tables']['meeting_twin_responses']['Row'];
export type TwinResponse = Omit<TwinResponseRow, 'sources' | 'meeting_id' | 'twin_id' | 'turn_seq' | 'id' | 'created_at'> & {
  sources: TwinResponseSource[] | null;
};

interface TwinActivityReviewProps {
  responses: TwinResponse[];
  /**
   * Meeting status. Used to gate the empty state — "Persona did not participate"
   * is only meaningful for a completed meeting. For in-flight or unstarted
   * meetings we hide the section entirely to avoid the misleading copy.
   */
  status?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function computeStats(responses: TwinResponse[]): {
  answered: number;
  deferred: number;
  avgConfidence: number;
} {
  const answered = responses.filter((r) => !r.is_deferral).length;
  const deferred = responses.filter((r) => r.is_deferral).length;
  // Only include responses with a known confidence in the average; null
  // confidence (e.g., before enrich completes) is excluded rather than
  // treated as zero, which would skew the reported number down.
  const scored = responses.filter((r) => !r.is_deferral && typeof r.confidence === 'number');
  const avgConfidence =
    scored.length > 0
      ? scored.reduce((sum, r) => sum + (r.confidence ?? 0), 0) / scored.length
      : 0;
  return { answered, deferred, avgConfidence };
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatCard({ value, label }: { value: string; label: string }): React.JSX.Element {
  return (
    <div className="flex flex-col">
      <span className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>
        {value}
      </span>
      <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
        {label}
      </span>
    </div>
  );
}

function SourcePills({ sources }: { sources: TwinResponseSource[] }): React.JSX.Element {
  const visible = sources.slice(0, 3);
  const overflow = sources.length - 3;

  return (
    <div className="flex flex-wrap gap-1">
      {visible.map((src, i) => (
        <span
          key={i}
          className="inline-block rounded-full px-2 py-0.5 text-xs font-bold truncate max-w-[100px]"
          style={{
            backgroundColor: 'var(--accent-trust-light)',
            color: 'var(--accent-trust-dark)',
          }}
          title={src.text}
        >
          {src.text}
        </span>
      ))}
      {overflow > 0 && (
        <span
          className="inline-block rounded-full px-2 py-0.5 text-xs font-bold"
          style={{ color: 'var(--text-muted)' }}
        >
          +{overflow} more
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function TwinActivityReview({ responses, status }: TwinActivityReviewProps): React.JSX.Element | null {
  // Empty state. Bug 7 fix: only show "did not participate" once the meeting
  // is actually complete. For scheduled / in-flight states the section is
  // hidden entirely — the in-progress card in the header tells the user
  // attendance is happening.
  if (responses.length === 0) {
    if (status !== 'completed' && status !== 'failed') {
      return null;
    }
    return (
      <div
        className="rounded-2xl p-5 space-y-3"
        style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
      >
        <h2
          className="text-xs font-bold uppercase tracking-wide"
          style={{ color: 'var(--text-muted)' }}
        >
          Your persona in this meeting
        </h2>
        <p className="text-sm italic" style={{ color: 'var(--text-muted)' }}>
          Your persona didn’t speak in this meeting.
        </p>
      </div>
    );
  }

  const { answered, deferred, avgConfidence } = computeStats(responses);

  return (
    <div
      className="rounded-2xl p-5 space-y-4"
      style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
    >
      {/* Section title */}
      <h2
        className="text-xs font-bold uppercase tracking-wide"
        style={{ color: 'var(--text-muted)' }}
      >
        Your persona in this meeting
      </h2>

      {/* Summary stats */}
      <div className="flex gap-4 flex-wrap">
        <StatCard value={String(answered)} label="Questions Answered" />
        <StatCard value={String(deferred)} label="Topics Deferred" />
        <StatCard
          value={avgConfidence > 0 ? `${(avgConfidence * 100).toFixed(1)}%` : 'N/A'}
          label="Avg Confidence"
        />
      </div>

      {/* Response table — desktop */}
      <div className="overflow-x-auto hidden md:block">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
              {['Question', 'Response', 'Confidence', 'Sources'].map((h) => (
                <th
                  key={h}
                  className="pb-2 pr-4 text-left text-xs font-bold uppercase tracking-wide"
                  style={{ color: 'var(--text-muted)' }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y" style={{ borderColor: 'var(--border-subtle)' }}>
            {responses.map((r, i) => {
              const sources = r.sources ?? [];
              const hasConfidence = typeof r.confidence === 'number';
              const confidencePct = hasConfidence ? Math.round((r.confidence ?? 0) * 100) : 0;
              return (
              <tr
                key={i}
                style={{
                  backgroundColor: r.is_deferral
                    ? 'rgba(254, 243, 199, 0.3)'
                    : 'transparent',
                }}
              >
                {/* Question */}
                <td
                  className="py-2.5 pr-4 align-top"
                  style={{ color: 'var(--text-primary)', maxWidth: '200px' }}
                >
                  <span className="line-clamp-2">{r.question_text ?? '—'}</span>
                </td>
                {/* Response */}
                <td
                  className="py-2.5 pr-4 align-top"
                  style={{
                    color: 'var(--text-primary)',
                    fontStyle: r.is_deferral ? 'italic' : 'normal',
                  }}
                >
                  {r.response_text}
                </td>
                {/* Confidence */}
                <td className="py-2.5 pr-4 align-top" style={{ minWidth: '100px' }}>
                  {r.is_deferral || !hasConfidence ? (
                    <span className="text-xs" style={{ color: 'var(--text-muted)' }}>N/A</span>
                  ) : (
                    <div className="flex flex-col gap-1">
                      <div
                        className="h-1 w-full rounded-full"
                        style={{ backgroundColor: 'var(--bg-surface)' }}
                      >
                        <div
                          className="h-1 rounded-full"
                          style={{
                            backgroundColor: 'var(--primary-400)',
                            width: `${confidencePct}%`,
                          }}
                        />
                      </div>
                      <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                        {confidencePct}%
                      </span>
                    </div>
                  )}
                </td>
                {/* Sources */}
                <td className="py-2.5 align-top">
                  {sources.length > 0 ? (
                    <SourcePills sources={sources} />
                  ) : (
                    <span className="text-xs" style={{ color: 'var(--text-muted)' }}>—</span>
                  )}
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Response list — mobile */}
      <div className="md:hidden space-y-3">
        {responses.map((r, i) => {
          const sources = r.sources ?? [];
          const hasConfidence = typeof r.confidence === 'number';
          const confidencePct = hasConfidence ? Math.round((r.confidence ?? 0) * 100) : 0;
          return (
          <div
            key={i}
            className="rounded-xl p-3 space-y-2"
            style={{
              backgroundColor: r.is_deferral
                ? 'rgba(254, 243, 199, 0.3)'
                : 'var(--bg-surface)',
            }}
          >
            <p className="text-sm font-bold line-clamp-2" style={{ color: 'var(--text-primary)' }}>
              {r.question_text ?? '—'}
            </p>
            <p
              className="text-sm"
              style={{
                color: 'var(--text-primary)',
                fontStyle: r.is_deferral ? 'italic' : 'normal',
              }}
            >
              {r.response_text}
            </p>
            <div className="flex items-center gap-3">
              {r.is_deferral || !hasConfidence ? (
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Confidence: N/A</span>
              ) : (
                <div className="flex items-center gap-1.5">
                  <div
                    className="h-1 rounded-full"
                    style={{ backgroundColor: 'var(--bg-surface)', width: '60px' }}
                  >
                    <div
                      className="h-1 rounded-full"
                      style={{
                        backgroundColor: 'var(--primary-400)',
                        width: `${confidencePct}%`,
                      }}
                    />
                  </div>
                  <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {confidencePct}%
                  </span>
                </div>
              )}
              {sources.length > 0 && <SourcePills sources={sources} />}
            </div>
          </div>
          );
        })}
      </div>
    </div>
  );
}
