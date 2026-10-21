/**
 * Public meeting recap viewer — Wave 5.
 *
 * Anonymous, server-rendered. No auth header. Backend RLS gates the data.
 * Reuses the recap layout but strips owner-only affordances (Share, Edit,
 * persona/voice controls). Adds a "Shared by ..." footer watermark.
 */

import React from 'react';
import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { resolveApiBaseUrl } from '@/lib/api';

interface PublicMeeting {
  id: string;
  title: string | null;
  status: string;
  meeting_start: string | null;
  meeting_end: string | null;
  duration_seconds: number | null;
  summary: string | null;
  recap: string | null;
  recap_version: number | null;
  recap_corrected_at: string | null;
  intent_vs_outcome: { intent: string | null; outcome: string | null } | null;
  action_items: Array<{ owner: string; description: string; due?: string }> | null;
  commitments: Array<{ by: string; to?: string; what: string; due?: string }> | null;
  decisions: string[] | null;
  topics: string[] | null;
  unanswered_questions: string[] | null;
  people_observed: Array<{ name: string; role_hint?: string }> | null;
  attendees: Array<{ name: string }>;
  summary_json: {
    topics?: string[] | null;
    action_items?: Array<{ text: string; assignee: string }> | null;
    key_questions?: string[] | null;
    tldr?: string | null;
  } | null;
}

interface PublicResponse {
  status: string;
  data: {
    meeting: PublicMeeting;
    owner: { name: string };
  };
}

async function fetchShare(token: string): Promise<PublicResponse | null> {
  const apiBase = resolveApiBaseUrl();
  try {
    const res = await fetch(`${apiBase}/m/${encodeURIComponent(token)}`, {
      // No auth — anonymous route. Cache short so revocation/edits propagate fast.
      cache: 'no-store',
    });
    if (!res.ok) return null;
    return await res.json() as PublicResponse;
  } catch {
    return null;
  }
}

export async function generateMetadata(
  { params }: { params: Promise<{ shareToken: string }> },
): Promise<Metadata> {
  const { shareToken } = await params;
  const payload = await fetchShare(shareToken);
  if (!payload) {
    return { title: 'PersonaOn · Shared recap', robots: { index: false } };
  }
  const { meeting, owner } = payload.data;
  const title = meeting.title ? `${meeting.title} · Recap` : 'Meeting recap';
  const description = (meeting.recap || meeting.summary || `Shared by ${owner.name}`).slice(0, 200);
  return {
    title,
    description,
    openGraph: { title, description, type: 'article' },
    twitter: { card: 'summary_large_image', title, description },
    robots: { index: false }, // never SEO-index a per-meeting share link
  };
}

function formatLongDate(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatDurationMin(seconds: number | null): string {
  if (!seconds || seconds <= 0) return '';
  const mins = Math.round(seconds / 60);
  if (mins < 60) return `${mins} min`;
  const h = Math.floor(mins / 60);
  const r = mins % 60;
  return r ? `${h} hr ${r} min` : `${h} hr`;
}

export default async function PublicMeetingRecapPage(
  { params }: { params: Promise<{ shareToken: string }> },
): Promise<React.JSX.Element> {
  const { shareToken } = await params;
  const payload = await fetchShare(shareToken);
  if (!payload) {
    notFound();
  }

  const { meeting, owner } = payload.data;

  // Recap text: prefer typed `recap`, fall back to legacy summary/summary_json.tldr.
  const recapText = meeting.recap || meeting.summary_json?.tldr || meeting.summary;
  const intent = meeting.intent_vs_outcome?.intent;
  const outcome = meeting.intent_vs_outcome?.outcome;

  // Choose the other-person name for the hero — same rule as the owner-only recap page.
  const otherPersonName = (() => {
    const observed = (meeting.people_observed || [])
      .find((p) => p.name && p.name.toLowerCase() !== 'you')?.name;
    if (observed) return observed;
    const attendee = (meeting.attendees || [])[0]?.name;
    if (attendee) return attendee;
    const title = meeting.title?.trim() ?? '';
    if (title && title.toLowerCase() !== 'untitled meeting') {
      const m = title.match(/(?:with|w\/)\s+([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+)?)/);
      if (m) return m[1];
      const first = title.split(/[\/|·•]/)[0].trim();
      if (first && first.length <= 40) return first;
    }
    return 'this person';
  })();

  const isProcessing = meeting.status === 'processing' && !recapText;

  return (
    <div
      style={{
        minHeight: '100vh',
        backgroundColor: 'var(--fog, #f5f5f7)',
        padding: '40px 16px',
      }}
    >
      <div style={{ maxWidth: 760, margin: '0 auto' }}>
        {/* Brand strip */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            marginBottom: 24,
            color: 'var(--fg-3, #888)',
            fontSize: 12,
            fontFamily: "'JetBrains Mono', monospace",
            letterSpacing: '0.10em',
            textTransform: 'uppercase',
          }}
        >
          <span style={{ fontWeight: 600, color: 'var(--ink, #1d1d1f)' }}>PersonaOn</span>
          <span>·</span>
          <span>Shared recap</span>
        </div>

        {/* Hero */}
        <div
          style={{
            backgroundColor: 'var(--fog-2, #fff)',
            borderRadius: 24,
            padding: '28px 32px',
            boxShadow: '0 4px 14px rgba(29,29,31,0.05)',
            marginBottom: 14,
          }}
        >
          {isProcessing ? (
            <>
              <div
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '4px 12px',
                  borderRadius: 9999,
                  background: 'rgba(224,162,26,.12)',
                  color: '#B07D12',
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 11,
                  letterSpacing: '0.10em',
                  textTransform: 'uppercase',
                  marginBottom: 12,
                }}
              >
                Processing
              </div>
              <h1 style={{ fontSize: 24, margin: 0, color: 'var(--ink, #1d1d1f)' }}>
                {meeting.title || 'Untitled meeting'}
              </h1>
              <p style={{ marginTop: 8, color: 'var(--fg-2, #444)', fontSize: 14 }}>
                The recap is still being generated. Check back in a few minutes.
              </p>
            </>
          ) : (
            <>
              <div
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '4px 12px',
                  borderRadius: 9999,
                  background: 'rgba(43,182,115,.12)',
                  color: '#2BB673',
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 11,
                  letterSpacing: '0.10em',
                  textTransform: 'uppercase',
                  marginBottom: 12,
                }}
              >
                Completed
                {meeting.recap_version != null && (
                  <span style={{ opacity: 0.7, marginLeft: 4 }}>· v{meeting.recap_version}</span>
                )}
              </div>
              <h1
                style={{
                  fontSize: 'clamp(28px, 4vw, 38px)',
                  fontFamily: "'Newsreader', Georgia, serif",
                  fontWeight: 600,
                  letterSpacing: '-0.02em',
                  lineHeight: 1.15,
                  margin: 0,
                  color: 'var(--ink, #1d1d1f)',
                }}
              >
                You × {otherPersonName}
              </h1>
              <p style={{ marginTop: 8, color: 'var(--fg-2, #444)', fontSize: 14 }}>
                {meeting.title && meeting.title !== 'Untitled meeting' && (
                  <span style={{ color: 'var(--ink-2, #2a2a2e)', marginRight: 8 }}>
                    {meeting.title} ·
                  </span>
                )}
                {formatLongDate(meeting.meeting_start)}
                {meeting.duration_seconds && (
                  <span style={{ color: 'var(--fg-3, #888)' }}>
                    {' '}· {formatDurationMin(meeting.duration_seconds)}
                  </span>
                )}
              </p>
            </>
          )}
        </div>

        {/* Recap narrative */}
        {recapText && (
          <Section title="Recap">
            <p style={{ margin: 0, lineHeight: 1.7, color: 'var(--ink, #1d1d1f)' }}>{recapText}</p>
          </Section>
        )}

        {/* Intent vs outcome */}
        {(intent || outcome) && (
          <Section title="Intent vs outcome">
            <div style={{ display: 'grid', gap: 12, gridTemplateColumns: '1fr 1fr' }}>
              {intent && (
                <div>
                  <Label>Intent</Label>
                  <p style={{ margin: '4px 0 0', lineHeight: 1.5 }}>{intent}</p>
                </div>
              )}
              {outcome && (
                <div>
                  <Label>Outcome</Label>
                  <p style={{ margin: '4px 0 0', lineHeight: 1.5 }}>{outcome}</p>
                </div>
              )}
            </div>
          </Section>
        )}

        {/* Decisions */}
        {meeting.decisions && meeting.decisions.length > 0 && (
          <Section title="Decisions">
            <ul style={{ margin: 0, paddingLeft: 20, lineHeight: 1.7 }}>
              {meeting.decisions.map((d, i) => (
                <li key={i}>{d}</li>
              ))}
            </ul>
          </Section>
        )}

        {/* Action items */}
        {meeting.action_items && meeting.action_items.length > 0 && (
          <Section title="Action items">
            <ul style={{ margin: 0, paddingLeft: 20, lineHeight: 1.7 }}>
              {meeting.action_items.map((a, i) => (
                <li key={i}>
                  <strong>{a.owner}</strong>: {a.description}
                  {a.due && <span style={{ color: 'var(--fg-3, #888)' }}> · due {a.due}</span>}
                </li>
              ))}
            </ul>
          </Section>
        )}

        {/* Commitments */}
        {meeting.commitments && meeting.commitments.length > 0 && (
          <Section title="Commitments">
            <ul style={{ margin: 0, paddingLeft: 20, lineHeight: 1.7 }}>
              {meeting.commitments.map((c, i) => (
                <li key={i}>
                  <strong>{c.by}</strong>{c.to ? ` → ${c.to}` : ''}: {c.what}
                  {c.due && <span style={{ color: 'var(--fg-3, #888)' }}> · {c.due}</span>}
                </li>
              ))}
            </ul>
          </Section>
        )}

        {/* Unanswered questions */}
        {meeting.unanswered_questions && meeting.unanswered_questions.length > 0 && (
          <Section title="Open questions">
            <ul style={{ margin: 0, paddingLeft: 20, lineHeight: 1.7 }}>
              {meeting.unanswered_questions.map((q, i) => (
                <li key={i}>{q}</li>
              ))}
            </ul>
          </Section>
        )}

        {/* Topics */}
        {meeting.topics && meeting.topics.length > 0 && (
          <Section title="Topics">
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {meeting.topics.map((t, i) => (
                <span
                  key={i}
                  style={{
                    padding: '4px 10px',
                    borderRadius: 9999,
                    backgroundColor: 'var(--fog, #f5f5f7)',
                    fontSize: 13,
                  }}
                >
                  {t}
                </span>
              ))}
            </div>
          </Section>
        )}

        {/* Attendees */}
        {meeting.attendees && meeting.attendees.length > 0 && (
          <Section title="Attendees">
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {meeting.attendees.map((a, i) => (
                <span
                  key={i}
                  style={{
                    padding: '4px 10px',
                    borderRadius: 9999,
                    backgroundColor: 'var(--fog, #f5f5f7)',
                    fontSize: 13,
                  }}
                >
                  {a.name}
                </span>
              ))}
            </div>
          </Section>
        )}

        {/* Footer watermark */}
        <div
          style={{
            marginTop: 32,
            paddingTop: 16,
            borderTop: '1px solid rgba(29,29,31,0.10)',
            textAlign: 'center',
            color: 'var(--fg-3, #888)',
            fontSize: 12,
          }}
        >
          Shared by <strong style={{ color: 'var(--ink-2, #2a2a2e)' }}>{owner.name}</strong> via{' '}
          <a
            href="https://personaon.com"
            target="_blank"
            rel="noopener"
            style={{ color: 'var(--signal, #0066cc)', textDecoration: 'none' }}
          >
            PersonaOn
          </a>
          {meeting.recap_corrected_at && (
            <div style={{ marginTop: 4, fontSize: 11 }}>
              Last updated {new Date(meeting.recap_corrected_at).toLocaleDateString()}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }): React.JSX.Element {
  return (
    <div
      style={{
        backgroundColor: 'var(--fog-2, #fff)',
        borderRadius: 24,
        padding: '24px 32px',
        marginBottom: 14,
        boxShadow: '0 4px 14px rgba(29,29,31,0.05)',
      }}
    >
      <h2
        style={{
          fontSize: 11,
          textTransform: 'uppercase',
          letterSpacing: '0.12em',
          color: 'var(--fg-2, #555)',
          fontFamily: "'JetBrains Mono', monospace",
          fontWeight: 600,
          margin: '0 0 12px 0',
        }}
      >
        {title}
      </h2>
      {children}
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <span
      style={{
        fontSize: 11,
        textTransform: 'uppercase',
        letterSpacing: '0.10em',
        color: 'var(--fg-3, #888)',
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      {children}
    </span>
  );
}
