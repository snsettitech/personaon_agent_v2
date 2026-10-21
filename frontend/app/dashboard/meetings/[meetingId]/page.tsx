'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';
import { useToast } from '@/components/ui/Toast';
import { useTwin } from '@/lib/context/TwinContext';
import TwinActivityReview from '@/components/meetings/TwinActivityReview';
import type { TwinResponse } from '@/components/meetings/TwinActivityReview';
import TwinAttendanceToggle from '@/components/meetings/TwinAttendanceToggle';
import ShareRecapModal from '@/components/meetings/ShareRecapModal';
import EditableSection from '@/components/meetings/EditableSection';
import MeetingPageV2 from '@/components/meetings/MeetingPageV2';
import { useMeetingsV2 } from '@/lib/features/meetingsV2';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

// Legacy summary_json shape (kept for backward compat with meetings created
// before the typed-column recap engine landed in P1.4.A).
interface LegacyActionItem {
  text: string;
  assignee: string;
  context: string;
}

interface SummaryJson {
  topics: string[] | null;
  action_items: LegacyActionItem[] | null;
  key_questions: string[] | null;
  tldr: string | null;
}

// New typed sub-shapes for the 10 LLM-output JSONB columns produced by the
// P1.4.A recap engine. All optional fields use `?` because the recap engine
// is allowed to omit them.
interface IntentOutcome {
  intent: string | null;
  outcome: string | null;
}

interface ActionItem {
  owner: string;
  description: string;
  due?: string | null;
}

interface Commitment {
  by: string;
  to: string;
  what: string;
  due?: string | null;
}

interface PersonObserved {
  name: string;
  role_hint?: string | null;
}

interface Position {
  subject: string;
  stance: string;
  supersedes?: string | null;
}

interface SpeakerAnalytics {
  participant_name: string;
  talk_time_seconds: number;
  talk_time_pct: number;
  word_count: number;
  words_per_minute: number;
  filler_word_count: number;
  sentiment_label: string;
  sentiment_score: number;
}

interface MeetingParticipant {
  participant_name: string | null;
  participant_email: string | null;
  is_host: boolean | null;
}

interface MeetingDetail {
  id: string;
  title: string | null;
  status: string;
  summary: string | null;
  summary_json: SummaryJson | null;
  // Note: legacy `action_items` shape from old summary_json.
  // The NEW typed `action_items` column below shadows it for v2 meetings;
  // we read the new column first and fall back to summary_json.action_items.
  analytics: SpeakerAnalytics[] | null;
  participants: MeetingParticipant[] | null;
  twin_responses: TwinResponse[] | null;
  meeting_start: string | null;
  meeting_end: string | null;
  duration_seconds: number | null;
  // Per-meeting user intent capture (Task P1.1.F).
  user_goal: string | null;
  user_context: string | null;
  // ── New typed recap columns (Task P1.4.A) ────────────────────────────
  recap: string | null;
  intent_vs_outcome: IntentOutcome | null;
  action_items: ActionItem[] | null;
  commitments: Commitment[] | null;
  decisions: string[] | null;
  topics: string[] | null;
  unanswered_questions: string[] | null;
  people_observed: PersonObserved[] | null;
  my_positions: Position[] | null;
  style_sample: string | null;
  // ── Recap metadata (Task P1.4.A) ─────────────────────────────────────
  recap_version: number | null;
  recap_corrected_at: string | null;
  // ── Attendance + bot dispatch (Task PV.3) ─────────────────────────────
  twin_attends: boolean | null;
  meet_link: string | null;
  recall_bot_id: string | null;
  // Full transcript text (from get_meeting's select("*")); consumed by the v2
  // Transcript tab. Declared here so the type matches the runtime payload.
  transcript_text: string | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString(undefined, {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function formatDuration(seconds: number | null): string {
  if (seconds == null || seconds <= 0) return '—';
  const mins = Math.round(seconds / 60);
  if (mins < 60) return `${mins} min`;
  const hrs = Math.floor(mins / 60);
  const rem = mins % 60;
  return rem > 0 ? `${hrs} hr ${rem} min` : `${hrs} hr`;
}

function formatPct(pct: number): string {
  return `${Math.round(pct)}%`;
}

function formatWpm(wpm: number): string {
  return `${Math.round(wpm)} wpm`;
}

// Cheap urgent detection for due pill — keeps it simple per spec.
function isDueUrgent(due: string | null | undefined): boolean {
  if (!due) return false;
  const d = due.toLowerCase();
  return d.includes('fri') || d.includes('today') || d.includes('tomorrow');
}

// Detect "you" / "me" / "I" assignee for solid ink chip styling.
// Compares against the literal pronouns AND the active twin/user display name
// so recap entries that name the user explicitly ("Sai Setti") are still flagged.
function isAssigneeYou(owner: string | null | undefined, youAliases?: Set<string>): boolean {
  if (!owner) return false;
  const o = owner.trim().toLowerCase();
  if (o === 'you' || o === 'me' || o === 'i' || o === 'self') return true;
  if (youAliases && youAliases.has(o)) return true;
  return false;
}

// Returns true when the meeting was processed by the v1+ typed-recap engine
// (P1.4.A onward). Switching on ``recap_version`` rather than array-content
// sniffing means even a sparse v1 recap (e.g. model returned no positions or
// decisions) still renders in the new layout — sparse is still v1, not legacy.
// Pre-v1 meetings with only summary_json fall through to the legacy renderer.
function hasNewRecapData(m: MeetingDetail): boolean {
  if (m.recap_version != null) return true;
  // Legacy safety net: if some recap columns are populated but recap_version
  // was never written (older partial migration), prefer new layout.
  return Boolean(
    m.recap ||
    m.intent_vs_outcome ||
    (m.action_items && m.action_items.length > 0) ||
    (m.commitments && m.commitments.length > 0) ||
    (m.decisions && m.decisions.length > 0) ||
    (m.topics && m.topics.length > 0) ||
    (m.unanswered_questions && m.unanswered_questions.length > 0) ||
    (m.people_observed && m.people_observed.length > 0) ||
    (m.my_positions && m.my_positions.length > 0) ||
    m.style_sample,
  );
}

// ---------------------------------------------------------------------------
// Sentiment badge
// ---------------------------------------------------------------------------

function SentimentBadge({ label }: { label: string }): React.JSX.Element {
  const styleMap: Record<string, { bg: string; color: string }> = {
    positive: { bg: 'var(--accent-emerald-light)', color: 'var(--accent-emerald)' },
    neutral:  { bg: 'var(--bg-surface)',           color: 'var(--text-muted)' },
    negative: { bg: '#fee2e2',                     color: '#991b1b' },
  };
  const s = styleMap[label] ?? styleMap['neutral'];
  return (
    <span
      className="inline-block rounded-full px-2 py-0.5 text-[10px] font-medium leading-tight capitalize"
      style={{ backgroundColor: s.bg, color: s.color }}
    >
      {label || 'neutral'}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }): React.JSX.Element {
  const styleMap: Record<string, { bg: string; color: string }> = {
    scheduled:   { bg: 'var(--bg-surface)',           color: 'var(--text-secondary)' },
    bot_joining: { bg: 'var(--accent-trust-light)',   color: 'var(--accent-trust-dark)' },
    recording:   { bg: 'var(--accent-emerald-light)',  color: 'var(--accent-emerald)' },
    processing:  { bg: 'var(--primary-50)',            color: 'var(--primary-700)' },
    completed:   { bg: 'var(--accent-emerald-light)',  color: 'var(--accent-emerald)' },
    failed:      { bg: '#fee2e2',                      color: '#991b1b' },
  };
  const s = styleMap[status] ?? { bg: 'var(--bg-surface)', color: 'var(--text-muted)' };
  return (
    <span
      className="inline-block rounded-full px-2 py-0.5 text-[10px] font-medium leading-tight capitalize"
      style={{ backgroundColor: s.bg, color: s.color }}
    >
      {status.replace(/_/g, ' ')}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Section card wrapper
// ---------------------------------------------------------------------------

function Section({
  title,
  count,
  children,
}: {
  title: string;
  count?: number;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <div
      className="rounded-2xl"
      style={{
        backgroundColor: 'var(--bg-card)',
        border: '1px solid var(--border-subtle)',
        padding: '24px 28px',
        marginBottom: '14px',
      }}
    >
      <div className="flex items-baseline justify-between" style={{ marginBottom: '14px' }}>
        <h2
          className="font-medium"
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: '11px',
            letterSpacing: '.15em',
            textTransform: 'uppercase',
            color: 'var(--text-muted)',
          }}
        >
          {title}
        </h2>
        {typeof count === 'number' && (
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: '11px',
              letterSpacing: '.14em',
              color: 'var(--text-muted)',
            }}
          >
            {count}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function MeetingDetailPage(): React.JSX.Element {
  const params = useParams();
  const searchParams = useSearchParams();
  const meetingId = params['meetingId'] as string;
  const twinId = searchParams.get('twin');
  const { showToast } = useToast();
  const router = useRouter();
  const meetingsV2 = useMeetingsV2();

  const [meeting, setMeeting] = useState<MeetingDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const apiBase = resolveApiBaseUrl();
  const { activeTwin } = useTwin();

  // Twin id resolution: prefer URL ?twin= param, but fall back to the active
  // twin from context so deep links / back-nav don't dead-end on "Missing persona".
  const twinIdResolved = twinId ?? activeTwin?.id ?? null;

  // Aliases the recap engine may use for the current user. We compare
  // assignees against this set to apply the "you" treatment (ink chip).
  // Includes literal pronouns ("you", "me", ...) plus the twin's display
  // name so explicit-name assignments still match the user.
  const youAliases = useMemo(() => {
    const aliases = new Set<string>(['you', 'me', 'i', 'self']);
    const candidates = [activeTwin?.name, (activeTwin as { persona_name?: string })?.persona_name];
    for (const c of candidates) {
      if (!c) continue;
      const norm = c.toLowerCase().trim();
      if (norm) aliases.add(norm);
    }
    return aliases;
  }, [activeTwin]);

  const fetchMeeting = useCallback(async () => {
    if (!twinIdResolved || !meetingId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await authFetchStandalone(`${apiBase}/v2/meetings/${twinIdResolved}/${meetingId}`);
      if (!res.ok) {
        const msg = await res.text().catch(() => String(res.status));
        setError(`Failed to load meeting: ${msg}`);
        return;
      }
      const body = await res.json() as { status: string; data: MeetingDetail };
      setMeeting(body.data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Network error';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [apiBase, twinIdResolved, meetingId]);

  useEffect(() => {
    void fetchMeeting();
  }, [fetchMeeting]);

  const [shareOpen, setShareOpen] = useState(false);
  const handleShareClick = useCallback(() => {
    setShareOpen(true);
  }, []);

  // ── Missing twin param ───────────────────────────────────────────────────
  if (!twinIdResolved) {
    return (
      <div className="flex min-h-[400px] flex-col items-center justify-center gap-2 text-center px-6">
        <p className="text-sm font-medium" style={{ color: '#dc2626' }}>
          Missing persona parameter.
        </p>
        <Link
          href="/dashboard/meetings"
          className="text-xs underline"
          style={{ color: 'var(--text-secondary)' }}
        >
          Go back to meetings list
        </Link>
      </div>
    );
  }

  // ── Loading ──────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <div
          className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent"
          style={{ borderColor: 'var(--brand-primary)', borderTopColor: 'transparent' }}
        />
      </div>
    );
  }

  // ── Error ────────────────────────────────────────────────────────────────
  if (error || !meeting) {
    return (
      <div className="flex min-h-[400px] flex-col items-center justify-center gap-3 text-center px-6">
        <p className="text-sm" style={{ color: '#dc2626' }}>{error || 'Meeting not found.'}</p>
        <div className="flex gap-3">
          <button
            onClick={() => void fetchMeeting()}
            className="rounded-xl px-4 py-1.5 text-xs font-medium cursor-pointer"
            style={{ border: '1px solid var(--border-default)', color: 'var(--text-secondary)' }}
          >
            Retry
          </button>
          <Link
            href={`/dashboard/meetings`}
            className="rounded-xl px-4 py-1.5 text-xs font-medium"
            style={{ border: '1px solid var(--border-default)', color: 'var(--text-secondary)', textDecoration: 'none' }}
          >
            Back to list
          </Link>
        </div>
      </div>
    );
  }

  const sj = meeting.summary_json;
  const hasRecap = hasNewRecapData(meeting);

  // Backward-compat: prefer new typed columns, fall back to summary_json.
  const recapNarrative: string | null = meeting.recap ?? sj?.tldr ?? null;
  const topics: string[] = (meeting.topics ?? sj?.topics ?? []);
  const actionItems: ActionItem[] = meeting.action_items ?? [];
  const legacyActionItems: LegacyActionItem[] = sj?.action_items ?? [];
  const commitments: Commitment[] = meeting.commitments ?? [];
  const decisions: string[] = meeting.decisions ?? [];
  const unansweredQuestions: string[] = meeting.unanswered_questions ?? sj?.key_questions ?? [];
  const peopleObserved: PersonObserved[] = meeting.people_observed ?? [];
  const positions: Position[] = meeting.my_positions ?? [];

  // First non-"you" attendee name for the my_positions tagline + recap hero.
  // Fallback chain: people_observed (recap engine) → participants table →
  // organizer email (extracted) → title parse → "this person".
  const otherPersonName: string = (() => {
    const fromObserved = peopleObserved.find((p) => !isAssigneeYou(p.name, youAliases))?.name;
    if (fromObserved) return fromObserved;
    const fromParticipants = (meeting.participants ?? [])
      .map((p) => p.participant_name)
      .filter((n): n is string => Boolean(n) && !isAssigneeYou(n, youAliases))[0];
    if (fromParticipants) return fromParticipants;
    // Try title parse: "Chaitanya / sainath" → "Chaitanya"; "Coffee with Alex" → "Alex"
    const title = meeting.title?.trim() ?? '';
    if (title && title !== 'Untitled meeting') {
      const withMatch = title.match(/(?:with|w\/)\s+([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+)?)/);
      if (withMatch) return withMatch[1];
      const slashFirst = title.split(/[\/|·•]/)[0].trim();
      if (slashFirst && !isAssigneeYou(slashFirst, youAliases) && slashFirst.length <= 40) {
        return slashFirst;
      }
    }
    return 'this person';
  })();

  // Phase B: unified, phase-aware meeting page (flagged). Legacy layout below is untouched.
  if (meetingsV2) {
    return (
      <MeetingPageV2
        meeting={meeting}
        twinId={twinIdResolved ?? ''}
        otherPersonName={otherPersonName !== 'this person' ? otherPersonName : undefined}
        onBack={() => router.push('/dashboard/meetings')}
      />
    );
  }

  return (
    <div className="pb-12 pt-4" style={{ display: 'flex', flexDirection: 'column' }}>

      {/* Back link */}
      <Link
        href="/dashboard/meetings"
        className="inline-flex items-center gap-1.5 text-xs"
        style={{ color: 'var(--text-muted)', textDecoration: 'none', marginBottom: '20px' }}
      >
        <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
        All meetings
      </Link>

      {/* ── Header ─────────────────────────────────────────────────────── */}
      {meeting.status === 'completed' && otherPersonName !== 'this person' ? (
        // Recap hero: emotional opener composed from people_observed
        <div
          className="rounded-2xl"
          style={{
            backgroundColor: 'var(--bg-card)',
            border: '1px solid var(--border-subtle)',
            padding: '24px 28px',
            marginBottom: '14px',
          }}
        >
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1"
                style={{
                  backgroundColor: 'rgba(43,182,115,.12)',
                  color: 'var(--ok)',
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: '10.5px',
                  letterSpacing: '0.04em',
                  textTransform: 'uppercase',
                }}
              >
                <span
                  className="inline-block h-1.5 w-1.5 rounded-full"
                  style={{ backgroundColor: 'currentColor' }}
                />
                Completed
                {meeting.recap_version != null && (
                  <span style={{ opacity: 0.7, marginLeft: '6px' }}>· v{meeting.recap_version}</span>
                )}
              </div>
              <h1
                className="mt-2 text-3xl font-bold"
                style={{
                  color: 'var(--ink)',
                  letterSpacing: '-0.02em',
                  fontFamily: "'Newsreader', Georgia, serif",
                  lineHeight: 1.15,
                }}
              >
                You × {otherPersonName}
              </h1>
              <p
                className="mt-1.5 text-sm"
                style={{ color: 'var(--fg-2)' }}
              >
                {meeting.title && meeting.title !== 'Untitled meeting' && (
                  <span style={{ marginRight: '8px', color: 'var(--ink-2)' }}>{meeting.title} ·</span>
                )}
                {formatDate(meeting.meeting_start)}
                {meeting.duration_seconds != null && (
                  <span style={{ color: 'var(--text-muted)' }}>
                    {' '}· {formatDuration(meeting.duration_seconds)}
                  </span>
                )}
                {peopleObserved.length > 0 && (
                  <span style={{ color: 'var(--text-muted)' }}>
                    {' '}· {peopleObserved.length} attendee{peopleObserved.length === 1 ? '' : 's'}
                  </span>
                )}
              </p>
            </div>
            <button
              type="button"
              onClick={handleShareClick}
              className="inline-flex items-center gap-2"
              style={{
                padding: '8px 16px',
                borderRadius: '9999px',
                backgroundColor: 'var(--bg-card)',
                color: 'var(--text-primary)',
                fontSize: '13px',
                fontWeight: 500,
                letterSpacing: '-0.005em',
                border: '1px solid var(--border-subtle)',
                boxShadow: '0 6px 24px rgba(0,0,0,.05), 0 1px 0 rgba(29,29,31,.04)',
                cursor: 'pointer',
              }}
            >
              Share recap
              <span style={{ fontFamily: "'JetBrains Mono', monospace", opacity: 0.6 }}>↗</span>
            </button>
          </div>
        </div>
      ) : ['bot_joining', 'joining', 'recording', 'processing'].includes(meeting.status) ? (
        // Bug 6 fix: in-progress state (bot joining / recording / processing)
        // gets a dedicated card. Previously only `processing` was handled, and
        // only when !hasRecap — but a partial `recap_version=1` row would fall
        // through to the empty recap layout for bot_joining/recording. Now all
        // in-flight states render the same "meeting in progress" card.
        <div
          className="rounded-2xl"
          style={{
            backgroundColor: 'var(--bg-card)',
            border: '1px solid var(--border-subtle)',
            padding: '24px',
            marginBottom: '14px',
          }}
        >
          <div className="flex items-start gap-3">
            <div
              className="mt-1 h-2 w-2 flex-shrink-0 rounded-full"
              style={{
                backgroundColor:
                  meeting.status === 'recording' ? 'var(--rec)' :
                  meeting.status === 'processing' ? 'var(--warn)' :
                  'var(--signal)',
                animation: 'pulse 1.5s ease-in-out infinite',
              }}
            />
            <div style={{ flex: 1, minWidth: 0 }}>
              <h1
                className="text-xl font-bold"
                style={{ color: 'var(--ink)' }}
              >
                {meeting.title || 'Untitled meeting'}
              </h1>
              <p className="mt-1 text-sm" style={{ color: 'var(--fg-2)' }}>
                {meeting.status === 'processing' && 'Recap generating…'}
                {meeting.status === 'recording' && 'Persona is in the meeting now — recording.'}
                {(meeting.status === 'bot_joining' || meeting.status === 'joining') && 'Persona is joining the meeting…'}
              </p>
              <p className="mt-2 text-xs" style={{ color: 'var(--fg-3)' }}>
                {meeting.status === 'processing'
                  ? "This usually finishes within a few minutes of the meeting ending. We'll email you when it's ready."
                  : "The recap will appear here once the meeting ends and the transcript is processed."}
              </p>
            </div>
            <StatusBadge status={meeting.status} />
          </div>
        </div>
      ) : (
        // Default header — for scheduled / joining / recording / failed / canceled
        <div
          className="rounded-2xl"
          style={{
            backgroundColor: 'var(--bg-card)',
            border: '1px solid var(--border-subtle)',
            padding: '20px',
            marginBottom: '14px',
          }}
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1" style={{ flex: 1, minWidth: 0 }}>
              <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>
                {meeting.title || 'Untitled Meeting'}
              </h1>
              <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
                {formatDate(meeting.meeting_start)}
                {meeting.duration_seconds != null && (
                  <span style={{ color: 'var(--text-muted)' }}>
                    {' '}· {formatDuration(meeting.duration_seconds)}
                  </span>
                )}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {(meeting.status === 'recording' || meeting.status === 'bot_joining') && twinIdResolved && (
                <Link
                  href={`/dashboard/meetings/${meetingId}/live?twin=${twinIdResolved}`}
                  className="rounded-xl px-4 py-1.5 text-sm font-bold"
                  style={{
                    backgroundColor: 'var(--primary-500)',
                    color: '#FFFFFF',
                    textDecoration: 'none',
                  }}
                >
                  View Live
                </Link>
              )}
              <StatusBadge status={meeting.status} />
              <button
                type="button"
                onClick={handleShareClick}
                className="inline-flex items-center gap-2"
                style={{
                  padding: '8px 16px',
                  borderRadius: '9999px',
                  backgroundColor: 'var(--bg-card)',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                  fontWeight: 500,
                  letterSpacing: '-0.005em',
                  border: '1px solid var(--border-subtle)',
                  boxShadow: '0 6px 24px rgba(0,0,0,.05), 0 1px 0 rgba(29,29,31,.04)',
                  cursor: 'pointer',
                }}
              >
                Share recap
                <span style={{ fontFamily: "'JetBrains Mono', monospace", opacity: 0.6 }}>↗</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Persona attendance (upcoming meetings with a meet_link) ─────── */}
      {meeting.status === 'scheduled' && meeting.meet_link && twinIdResolved && (
        <div
          className="rounded-2xl"
          style={{
            backgroundColor: meeting.twin_attends ? 'rgba(43,182,115,.06)' : 'var(--bg-surface)',
            border: `1px solid ${meeting.twin_attends ? 'rgba(43,182,115,.20)' : 'var(--border-subtle)'}`,
            padding: '16px',
            marginBottom: '14px',
          }}
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div style={{ flex: 1, minWidth: 0 }}>
              <h3
                className="text-xs font-semibold uppercase tracking-wide"
                style={{ color: 'var(--text-muted)' }}
              >
                Persona attendance
              </h3>
              <p
                className="mt-1 text-sm"
                style={{ color: 'var(--text-primary)' }}
              >
                {meeting.twin_attends
                  ? meeting.recall_bot_id
                    ? '✓ Persona will join this meeting as a bot to record and recap.'
                    : 'Dispatching bot…'
                  : 'Toggle on and your persona will join, listen, and produce a recap.'}
              </p>
            </div>
            <TwinAttendanceToggle
              twinId={twinIdResolved}
              meetingId={meeting.id}
              initialAttend={Boolean(meeting.twin_attends)}
            />
          </div>
        </div>
      )}

      {/* ── Your prep (user_goal + user_context) ───────────────────────── */}
      {(meeting.user_goal || meeting.user_context) ? (
        <div
          className="rounded-2xl"
          style={{
            backgroundColor: 'var(--bg-surface)',
            border: '1px solid var(--border-subtle)',
            padding: '16px',
            marginBottom: '14px',
          }}
        >
          <div className="flex items-center justify-between">
            <h3
              className="text-xs font-semibold uppercase tracking-wide"
              style={{ color: 'var(--text-muted)' }}
            >
              Your prep
            </h3>
            <Link
              href={`/dashboard/meetings/${meeting.id}/prep?twin=${twinIdResolved}`}
              className="text-xs hover:underline"
              style={{ color: 'var(--text-muted)' }}
            >
              Edit
            </Link>
          </div>
          {meeting.user_goal && (
            <p
              className="mt-2 text-sm font-medium"
              style={{ color: 'var(--text-primary)' }}
            >
              Goal: {meeting.user_goal}
            </p>
          )}
          {meeting.user_context && (
            <p
              className="mt-1 text-sm whitespace-pre-wrap"
              style={{ color: 'var(--text-secondary)' }}
            >
              {meeting.user_context}
            </p>
          )}
        </div>
      ) : (
        <Link
          href={`/dashboard/meetings/${meeting.id}/prep`}
          className="inline-block rounded-xl px-3 py-1.5 text-xs hover:bg-black/[0.03]"
          style={{
            border: '1px dashed var(--border-default)',
            color: 'var(--text-muted)',
            textDecoration: 'none',
            marginBottom: '14px',
            alignSelf: 'flex-start',
          }}
        >
          + Add prep
        </Link>
      )}

      {/* ============================================================== */}
      {/* NEW RECAP LAYOUT (10 typed columns from P1.4.A recap engine)   */}
      {/* ============================================================== */}
      {/* Bug 6 fix: don't render the recap layout while the meeting is still
          in flight. A pre-set recap_version=1 on a bot_joining/recording row
          would otherwise render empty sections with em-dashes — confusing
          for a meeting that just started. The header conditional above
          renders a dedicated "in progress" card for these states. */}
      {hasRecap && !['bot_joining', 'joining', 'recording', 'processing'].includes(meeting.status) ? (
        <>
          {/* 1. Hero recap narrative ─────────────────────────────────── */}
          {twinIdResolved && (
            <div
              className="rounded-2xl"
              style={{
                backgroundColor: 'var(--bg-card)',
                border: '1px solid var(--border-subtle)',
                padding: '40px 44px',
                marginBottom: '14px',
                position: 'relative',
              }}
            >
              <EditableSection<string | null>
                twinId={twinIdResolved}
                meetingId={meeting.id}
                field="recap"
                fieldLabel="Recap"
                value={recapNarrative}
                recapVersion={meeting.recap_version ?? 1}
                onSaved={(newValue, newVersion) => {
                  setMeeting((prev) =>
                    prev
                      ? { ...prev, recap: newValue, recap_version: newVersion, recap_corrected_at: new Date().toISOString() }
                      : prev,
                  );
                }}
              >
                <div
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: '11px',
                    letterSpacing: '.15em',
                    textTransform: 'uppercase',
                    color: 'var(--text-muted)',
                    marginBottom: '14px',
                  }}
                >
                  Recap
                </div>
                <p
                  style={{
                    fontFamily: "'Newsreader', Georgia, serif",
                    fontSize: '22px',
                    lineHeight: 1.45,
                    color: 'var(--text-primary)',
                    letterSpacing: '-0.005em',
                    fontWeight: 400,
                  }}
                >
                  {recapNarrative || '—'}
                </p>
              </EditableSection>
            </div>
          )}

          {/* 2. Intent vs Outcome ─────────────────────────────────────── */}
          {meeting.intent_vs_outcome && (meeting.intent_vs_outcome.intent || meeting.intent_vs_outcome.outcome) && (
            <div
              className="rounded-2xl"
              style={{
                backgroundColor: 'var(--bg-card)',
                border: '1px solid var(--border-subtle)',
                padding: '28px 32px',
                marginBottom: '14px',
              }}
            >
              <div
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: '11px',
                  letterSpacing: '.15em',
                  textTransform: 'uppercase',
                  color: 'var(--text-muted)',
                  marginBottom: '18px',
                }}
              >
                Intent vs outcome
              </div>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr auto 1fr',
                  gap: '24px',
                  alignItems: 'stretch',
                }}
              >
                <div style={{ padding: '8px 0' }}>
                  <div
                    style={{
                      fontFamily: "'JetBrains Mono', monospace",
                      fontSize: '10.5px',
                      letterSpacing: '.12em',
                      textTransform: 'uppercase',
                      color: 'var(--text-muted)',
                      marginBottom: '8px',
                    }}
                  >
                    You went in for
                  </div>
                  <p
                    style={{
                      fontSize: '15.5px',
                      lineHeight: 1.55,
                      color: 'var(--text-primary)',
                      letterSpacing: '-0.005em',
                    }}
                  >
                    {meeting.intent_vs_outcome.intent || '—'}
                  </p>
                </div>
                <div
                  style={{
                    color: 'var(--border-default)',
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: '22px',
                    display: 'flex',
                    alignItems: 'center',
                    userSelect: 'none',
                  }}
                >
                  →
                </div>
                <div style={{ padding: '8px 0' }}>
                  <div
                    style={{
                      fontFamily: "'JetBrains Mono', monospace",
                      fontSize: '10.5px',
                      letterSpacing: '.12em',
                      textTransform: 'uppercase',
                      color: 'var(--text-muted)',
                      marginBottom: '8px',
                    }}
                  >
                    What actually happened
                  </div>
                  <p
                    style={{
                      fontSize: '15.5px',
                      lineHeight: 1.55,
                      color: 'var(--text-primary)',
                      letterSpacing: '-0.005em',
                    }}
                  >
                    {meeting.intent_vs_outcome.outcome || '—'}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* 3. Action items ──────────────────────────────────────────── */}
          {actionItems.length > 0 && (
            <Section title="Action items" count={actionItems.length}>
              <div>
                {actionItems.map((item, i) => {
                  const youOwn = isAssigneeYou(item.owner, youAliases);
                  const urgent = isDueUrgent(item.due);
                  return (
                    <div
                      key={i}
                      style={{
                        display: 'grid',
                        gridTemplateColumns: '24px 1fr auto auto',
                        gap: '12px',
                        padding: '12px 0',
                        borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)',
                        paddingTop: i === 0 ? '4px' : '12px',
                        alignItems: 'center',
                      }}
                    >
                      <div
                        role="checkbox"
                        aria-checked="false"
                        style={{
                          width: '18px',
                          height: '18px',
                          border: '1.5px solid var(--border-default)',
                          borderRadius: '5px',
                        }}
                      />
                      <div
                        style={{
                          fontSize: '14.5px',
                          color: 'var(--text-primary)',
                          letterSpacing: '-0.005em',
                        }}
                      >
                        {item.description}
                      </div>
                      <span
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          padding: '3px 10px',
                          borderRadius: '9999px',
                          backgroundColor: youOwn ? 'var(--text-primary)' : 'rgba(0, 102, 204, 0.08)',
                          color: youOwn ? '#FFFFFF' : '#0066cc',
                          fontSize: '12px',
                          fontWeight: 500,
                          letterSpacing: '-0.005em',
                        }}
                      >
                        {item.owner || '—'}
                      </span>
                      <span
                        style={{
                          color: urgent ? '#E0A21A' : 'var(--text-muted)',
                          fontFamily: "'JetBrains Mono', monospace",
                          fontSize: '11.5px',
                          letterSpacing: '-0.005em',
                        }}
                      >
                        {item.due || '—'}
                      </span>
                    </div>
                  );
                })}
              </div>
            </Section>
          )}

          {/* 4. Commitments ───────────────────────────────────────────── */}
          {commitments.length > 0 && (
            <Section title="Commitments" count={commitments.length}>
              <div>
                {commitments.map((c, i) => (
                  <div
                    key={i}
                    style={{
                      padding: '12px 0',
                      borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)',
                      paddingTop: i === 0 ? '4px' : '12px',
                      fontSize: '14.5px',
                      color: 'var(--text-secondary)',
                      lineHeight: 1.55,
                      letterSpacing: '-0.005em',
                    }}
                  >
                    <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{c.by}</span>
                    <span
                      style={{
                        color: 'var(--text-muted)',
                        margin: '0 6px',
                        fontFamily: "'JetBrains Mono', monospace",
                        fontSize: '13px',
                      }}
                    >
                      →
                    </span>
                    <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{c.to}</span>
                    <span
                      style={{
                        color: 'var(--text-muted)',
                        margin: '0 6px',
                        fontFamily: "'JetBrains Mono', monospace",
                        fontSize: '13px',
                      }}
                    >
                      ·
                    </span>
                    <span style={{ fontStyle: 'italic', color: 'var(--text-secondary)' }}>
                      {c.what}
                    </span>
                    {c.due && (
                      <span
                        style={{
                          color: 'var(--text-muted)',
                          fontFamily: "'JetBrains Mono', monospace",
                          fontSize: '12px',
                          marginLeft: '6px',
                        }}
                      >
                        {c.due}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* 5. Decisions ─────────────────────────────────────────────── */}
          {decisions.length > 0 && (
            <Section title="Decisions" count={decisions.length}>
              <div>
                {decisions.map((d, i) => (
                  <div
                    key={i}
                    style={{
                      display: 'flex',
                      gap: '12px',
                      alignItems: 'flex-start',
                      padding: '10px 0',
                      borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)',
                      paddingTop: i === 0 ? '4px' : '10px',
                    }}
                  >
                    <span
                      style={{
                        color: '#2BB673',
                        flexShrink: 0,
                        paddingTop: '2px',
                        fontFamily: "'JetBrains Mono', monospace",
                        fontSize: '14px',
                      }}
                    >
                      ✓
                    </span>
                    <p
                      style={{
                        fontSize: '14.5px',
                        color: 'var(--text-primary)',
                        lineHeight: 1.55,
                        letterSpacing: '-0.005em',
                      }}
                    >
                      {d}
                    </p>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* 6. My Positions — THE MOAT ───────────────────────────────── */}
          {positions.length > 0 && (
            <div
              className="rounded-2xl"
              style={{
                backgroundColor: 'var(--bg-card)',
                border: '1px solid var(--border-subtle)',
                borderLeft: '4px solid #0066cc',
                padding: '32px 36px',
                marginBottom: '14px',
                position: 'relative',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'flex-start',
                  marginBottom: '6px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <span
                    style={{
                      fontFamily: "'JetBrains Mono', monospace",
                      fontSize: '11px',
                      letterSpacing: '.15em',
                      textTransform: 'uppercase',
                      color: '#0066cc',
                      fontWeight: 600,
                    }}
                  >
                    My positions
                  </span>
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '6px',
                      padding: '3px 10px',
                      borderRadius: '9999px',
                      backgroundColor: 'rgba(0, 102, 204, 0.08)',
                      color: '#0066cc',
                      fontSize: '11px',
                      letterSpacing: '-0.005em',
                      fontWeight: 500,
                    }}
                  >
                    ⚡ Trains your persona
                  </span>
                </div>
                <span
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: '11px',
                    letterSpacing: '.14em',
                    color: 'var(--text-muted)',
                  }}
                >
                  {positions.length}
                </span>
              </div>
              <p
                style={{
                  color: 'var(--text-secondary)',
                  fontSize: '13.5px',
                  marginBottom: '20px',
                  letterSpacing: '-0.005em',
                }}
              >
                Your first-person views from this meeting. Edit them and your persona learns — your next brief, your public persona, and the recap of your next call with {otherPersonName} all reflect the change.
              </p>
              {positions.map((p, i) => (
                <div
                  key={i}
                  style={{
                    padding: '16px 0',
                    borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)',
                    paddingTop: i === 0 ? '4px' : '16px',
                  }}
                >
                  <div
                    style={{
                      fontFamily: "'JetBrains Mono', monospace",
                      fontSize: '11px',
                      letterSpacing: '.12em',
                      textTransform: 'uppercase',
                      color: 'var(--text-muted)',
                      marginBottom: '6px',
                    }}
                  >
                    {p.subject}
                  </div>
                  <blockquote
                    style={{
                      fontFamily: "'Newsreader', Georgia, serif",
                      fontStyle: 'italic',
                      fontSize: '17px',
                      color: 'var(--text-primary)',
                      lineHeight: 1.55,
                      letterSpacing: '-0.005em',
                      paddingLeft: '16px',
                      borderLeft: '2px solid rgba(0, 102, 204, 0.40)',
                      margin: 0,
                    }}
                  >
                    {p.stance}
                  </blockquote>
                  {/* TODO P2 — wire edit handler for position correction. */}
                  <button
                    type="button"
                    onClick={() => showToast('Position editing coming soon.', 'info')}
                    style={{
                      marginTop: '8px',
                      fontSize: '12.5px',
                      color: 'var(--text-muted)',
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                      padding: 0,
                    }}
                  >
                    Edit →
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* 7. Open questions ────────────────────────────────────────── */}
          {unansweredQuestions.length > 0 && (
            <Section title="Open questions" count={unansweredQuestions.length}>
              <div>
                {unansweredQuestions.map((q, i) => (
                  <div
                    key={i}
                    style={{
                      display: 'flex',
                      gap: '14px',
                      alignItems: 'flex-start',
                      padding: '10px 0',
                      borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)',
                      paddingTop: i === 0 ? '4px' : '10px',
                    }}
                  >
                    <span
                      style={{
                        color: '#E0A21A',
                        flexShrink: 0,
                        fontFamily: "'JetBrains Mono', monospace",
                        fontSize: '15px',
                        paddingTop: '1px',
                      }}
                    >
                      ?
                    </span>
                    <p
                      style={{
                        fontSize: '14.5px',
                        color: 'var(--text-secondary)',
                        lineHeight: 1.55,
                        letterSpacing: '-0.005em',
                      }}
                    >
                      {q}
                    </p>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* 8. People in this meeting ────────────────────────────────── */}
          {peopleObserved.length > 0 && (
            <Section title="People in this meeting" count={peopleObserved.length}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
                {peopleObserved.map((p, i) => {
                  const youOwn = isAssigneeYou(p.name, youAliases);
                  return (
                    <span
                      key={i}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '8px',
                        padding: '6px 14px',
                        backgroundColor: 'var(--bg-surface)',
                        borderRadius: '9999px',
                        fontSize: '13.5px',
                        color: 'var(--text-primary)',
                        letterSpacing: '-0.005em',
                      }}
                    >
                      {p.name}
                      {youOwn ? (
                        <span style={{ color: 'var(--text-muted)', fontSize: '12px', fontStyle: 'italic' }}>
                          you
                        </span>
                      ) : p.role_hint ? (
                        <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>
                          · {p.role_hint}
                        </span>
                      ) : null}
                    </span>
                  );
                })}
              </div>
            </Section>
          )}

          {/* 9. Topics covered ────────────────────────────────────────── */}
          {topics.length > 0 && (
            <Section title="Topics covered" count={topics.length}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                {topics.map((t, i) => (
                  <span
                    key={i}
                    style={{
                      padding: '4px 12px',
                      backgroundColor: 'rgba(0, 102, 204, 0.04)',
                      borderRadius: '9999px',
                      fontSize: '12.5px',
                      color: '#0057ad',
                      letterSpacing: '-0.005em',
                    }}
                  >
                    {t}
                  </span>
                ))}
              </div>
            </Section>
          )}

          {/* 10. Voice sample (collapsed) ─────────────────────────────── */}
          {meeting.style_sample && (
            <details
              className="rounded-2xl"
              style={{
                backgroundColor: 'var(--bg-card)',
                border: '1px solid var(--border-subtle)',
                marginBottom: '14px',
                overflow: 'hidden',
              }}
            >
              <summary
                style={{
                  listStyle: 'none',
                  cursor: 'pointer',
                  padding: '20px 28px',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <span
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: '11px',
                    letterSpacing: '.15em',
                    textTransform: 'uppercase',
                    color: 'var(--text-muted)',
                  }}
                >
                  Voice sample — how you sounded
                </span>
                <span
                  style={{
                    color: 'var(--text-muted)',
                    fontFamily: "'JetBrains Mono', monospace",
                  }}
                >
                  ▸
                </span>
              </summary>
              <div style={{ padding: '0 28px 24px' }}>
                <blockquote
                  style={{
                    fontFamily: "'Newsreader', Georgia, serif",
                    fontStyle: 'italic',
                    fontSize: '15.5px',
                    color: 'var(--text-secondary)',
                    lineHeight: 1.55,
                    paddingLeft: '16px',
                    borderLeft: '2px solid var(--border-default)',
                    margin: 0,
                  }}
                >
                  {meeting.style_sample}
                </blockquote>
              </div>
            </details>
          )}
        </>
      ) : (
        // ────────────────────────────────────────────────────────────────
        // LEGACY FALLBACK — old 4-field summary_json shape for meetings
        // created before the P1.4.A recap engine landed.
        // ────────────────────────────────────────────────────────────────
        <>
          {sj ? (
            <Section title="TL;DR">
              <p className="text-sm leading-relaxed" style={{ color: 'var(--text-primary)' }}>
                {sj.tldr || '—'}
              </p>
            </Section>
          ) : (
            <Section title="Summary">
              <p className="text-sm italic" style={{ color: 'var(--text-muted)' }}>
                {meeting.status === 'completed'
                  ? 'No summary available.'
                  : 'Summary generating…'}
              </p>
            </Section>
          )}

          {sj && (sj.topics ?? []).length > 0 && (
            <Section title="Topics Covered">
              <ul className="space-y-1.5 pl-1">
                {(sj.topics ?? []).map((topic, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm" style={{ color: 'var(--text-primary)' }}>
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: 'var(--brand-primary)' }} />
                    {topic}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {legacyActionItems.length > 0 && (
            <Section title="Action Items">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      {(['Action', 'Assignee', 'Context'] as const).map((h) => (
                        <th
                          key={h}
                          className="pb-2 pr-4 text-left text-[11px] font-semibold uppercase tracking-wide"
                          style={{ color: 'var(--text-muted)' }}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y" style={{ borderColor: 'var(--border-subtle)' }}>
                    {legacyActionItems.map((item, i) => (
                      <tr
                        key={i}
                        style={{
                          backgroundColor: item.assignee ? 'var(--primary-50)' : 'transparent',
                        }}
                      >
                        <td className="py-2 pr-4" style={{ color: 'var(--text-primary)' }}>
                          {item.text}
                        </td>
                        <td className="py-2 pr-4 whitespace-nowrap">
                          {item.assignee ? (
                            <span
                              className="rounded-full px-2 py-0.5 text-[11px] font-medium"
                              style={{ backgroundColor: 'var(--accent-trust-light)', color: 'var(--accent-trust-dark)' }}
                            >
                              {item.assignee}
                            </span>
                          ) : (
                            <span style={{ color: 'var(--text-muted)' }}>—</span>
                          )}
                        </td>
                        <td className="py-2" style={{ color: 'var(--text-secondary)' }}>
                          {item.context || '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
          )}

          {sj && (sj.key_questions ?? []).length > 0 && (
            <Section title="Key Questions">
              <ul className="space-y-1.5 pl-1">
                {(sj.key_questions ?? []).map((q, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm" style={{ color: 'var(--text-primary)' }}>
                    <span className="mt-0.5 shrink-0 text-xs font-bold" style={{ color: 'var(--text-muted)' }}>Q</span>
                    {q}
                  </li>
                ))}
              </ul>
            </Section>
          )}
        </>
      )}

      {/* ── Speaker Analytics ──────────────────────────────────────────── */}
      {(meeting.analytics ?? []).length > 0 && (
        <Section title="Speaker Analytics">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  {(['Speaker', 'Talk Time', 'Talk %', 'WPM', 'Filler Words', 'Sentiment'] as const).map((h) => (
                    <th
                      key={h}
                      className="pb-2 pr-4 text-left text-[11px] font-semibold uppercase tracking-wide"
                      style={{ color: 'var(--text-muted)' }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y" style={{ borderColor: 'var(--border-subtle)' }}>
                {(meeting.analytics ?? []).map((row, i) => (
                  <tr key={i}>
                    <td className="py-2.5 pr-4 font-medium" style={{ color: 'var(--text-primary)' }}>
                      {row.participant_name}
                    </td>
                    <td className="py-2.5 pr-4" style={{ color: 'var(--text-secondary)' }}>
                      {formatDuration(row.talk_time_seconds)}
                    </td>
                    <td className="py-2.5 pr-4" style={{ color: 'var(--text-secondary)' }}>
                      {formatPct(row.talk_time_pct)}
                    </td>
                    <td className="py-2.5 pr-4" style={{ color: 'var(--text-secondary)' }}>
                      {formatWpm(row.words_per_minute)}
                    </td>
                    <td className="py-2.5 pr-4" style={{ color: 'var(--text-secondary)' }}>
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
        </Section>
      )}

      {/* Empty analytics state */}
      {(meeting.analytics ?? []).length === 0 && meeting.status === 'completed' && (
        <Section title="Speaker Analytics">
          <p className="text-sm italic" style={{ color: 'var(--text-muted)' }}>
            No speaker analytics available for this meeting.
          </p>
        </Section>
      )}

      {/* ── Twin Activity Review ──────────────────────────────────────── */}
      <TwinActivityReview responses={meeting.twin_responses ?? []} status={meeting.status} />

      {/* ── Share recap modal (W5) ────────────────────────────────────── */}
      {twinIdResolved && (
        <ShareRecapModal
          open={shareOpen}
          onClose={() => setShareOpen(false)}
          twinId={twinIdResolved}
          meetingId={meeting.id}
        />
      )}
    </div>
  );
}
