'use client';

import React from 'react';
import Link from 'next/link';
import { useMeetingsV2 } from '@/lib/features/meetingsV2';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MeetingCardData {
  id: string;
  title: string | null;
  status: string;
  meet_link: string | null;
  meeting_start: string | null;
  meeting_end: string | null;
  duration_seconds: number | null;
  summary: string | null;
  attendees_json?: Attendee[] | null;
  twin_attends?: boolean | null;
  recall_bot_id?: string | null;
}

interface Attendee {
  email?: string | null;
  name?: string | null;
  display_name?: string | null;
  organizer?: boolean;
  self?: boolean;
}

interface MeetingCardProps {
  meeting: MeetingCardData;
  twinId: string;
  isNext?: boolean;
  showDayPrefix?: boolean;
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

function formatTimeOnly(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

function formatDayPrefix(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleDateString(undefined, { weekday: 'short' });
}

function formatDurationMin(start: string | null, end: string | null, durationSec: number | null): string {
  if (durationSec != null && durationSec > 0) {
    const mins = Math.round(durationSec / 60);
    return mins < 60 ? `${mins} min` : `${Math.floor(mins / 60)} hr ${mins % 60 ? `${mins % 60} min` : ''}`.trim();
  }
  if (start && end) {
    const ms = new Date(end).getTime() - new Date(start).getTime();
    if (!isNaN(ms) && ms > 0) {
      const mins = Math.round(ms / 60_000);
      return mins < 60 ? `${mins} min` : `${Math.floor(mins / 60)} hr ${mins % 60 ? `${mins % 60} min` : ''}`.trim();
    }
  }
  return '';
}

function computeCountdown(iso: string | null): { text: string; urgent: boolean } | null {
  if (!iso) return null;
  const start = new Date(iso).getTime();
  if (isNaN(start)) return null;
  const now = Date.now();
  const diffMin = Math.round((start - now) / 60_000);
  if (diffMin < 0 || diffMin > 60 * 24) return null;
  if (diffMin < 1) return { text: 'now', urgent: true };
  if (diffMin < 60) return { text: `in ${diffMin} min`, urgent: diffMin <= 30 };
  const hours = Math.round(diffMin / 60);
  return { text: `in ${hours} hr`, urgent: false };
}

function dedupedAttendees(list: Attendee[] | null | undefined, maxShown: number): {
  shown: Attendee[];
  overflow: number;
} {
  if (!list || list.length === 0) return { shown: [], overflow: 0 };
  const filtered = list.filter((a) => !a.self);
  const seen = new Set<string>();
  const shown: Attendee[] = [];
  for (const a of filtered) {
    const key = (a.email || a.name || a.display_name || '').toLowerCase().trim();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    shown.push(a);
    if (shown.length >= maxShown) break;
  }
  const overflow = Math.max(0, filtered.length - shown.length);
  return { shown, overflow };
}

function attendeeLabel(a: Attendee): string {
  const name = a.display_name || a.name || a.email || '';
  return name.includes('@') ? name.split('@')[0] : name;
}

// ---------------------------------------------------------------------------
// Status chip
// ---------------------------------------------------------------------------

interface StatusStyle {
  bg: string;
  fg: string;
  label: string;
  pulse: boolean;
}

const STATUS_MAP: Record<string, StatusStyle> = {
  scheduled:   { bg: 'var(--fog)',          fg: 'var(--fg-2)',  label: 'SCHEDULED', pulse: false },
  bot_joining: { bg: 'rgba(0,102,204,.12)', fg: 'var(--signal)', label: 'JOINING',    pulse: true  },
  joining:     { bg: 'rgba(0,102,204,.12)', fg: 'var(--signal)', label: 'JOINING',    pulse: true  },
  recording:   { bg: 'rgba(229,72,77,.10)', fg: 'var(--rec)',    label: 'RECORDING',  pulse: true  },
  processing:  { bg: 'rgba(224,162,26,.12)', fg: 'var(--warn)',  label: 'PROCESSING', pulse: true  },
  completed:   { bg: 'rgba(43,182,115,.12)', fg: 'var(--ok)',    label: 'COMPLETED',  pulse: false },
  failed:      { bg: 'rgba(229,72,77,.10)',  fg: 'var(--rec)',   label: 'FAILED',     pulse: false },
  canceled:    { bg: 'var(--fog)',           fg: 'var(--fg-3)',  label: 'CANCELED',   pulse: false },
  // Bug 4 fix: derived status for past-dated meetings where the bot never
  // joined. Not a DB value — computed at render time. See deriveEffectiveStatus().
  missed:      { bg: 'var(--fog)',           fg: 'var(--fg-3)',  label: 'MISSED',    pulse: false },
};

/**
 * Compute the effective display status. A meeting whose start time has passed
 * but whose status is still 'scheduled' and which never got a bot is treated
 * visually as 'missed'. The DB row stays 'scheduled' — only the UI is corrected
 * until a backend reconcile worker flips it for real.
 *
 * Gate strictly on `meeting_end < now - 5min` (with a `meeting_start + 1h`
 * fallback when end is missing) to avoid flashing MISSED during the live
 * window of an in-progress meeting.
 */
function deriveEffectiveStatus(meeting: MeetingCardData): string {
  if (meeting.status !== 'scheduled') return meeting.status;
  if (meeting.recall_bot_id) return meeting.status;
  const nowMs = Date.now();
  let endMs: number | null = null;
  if (meeting.meeting_end) {
    const t = new Date(meeting.meeting_end).getTime();
    if (!isNaN(t)) endMs = t;
  }
  if (endMs == null && meeting.meeting_start) {
    const start = new Date(meeting.meeting_start).getTime();
    if (!isNaN(start)) endMs = start + 60 * 60_000;
  }
  if (endMs != null && endMs < nowMs - 5 * 60_000) {
    return 'missed';
  }
  return meeting.status;
}

function StatusChip({ status }: { status: string }): React.JSX.Element {
  const s = STATUS_MAP[status] ?? STATUS_MAP.scheduled;
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-medium uppercase"
      style={{
        backgroundColor: s.bg,
        color: s.fg,
        fontFamily: 'var(--font-geist-mono, JetBrains Mono, monospace)',
        letterSpacing: '0.04em',
      }}
    >
      <span
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{
          backgroundColor: 'currentColor',
          animation: s.pulse ? 'mc-pulse 1.2s ease-in-out infinite' : undefined,
        }}
      />
      {s.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// CTA logic
// ---------------------------------------------------------------------------

interface CTASpec {
  label: string;
  href: string;
  outline: boolean;
}

function resolveCTA(meeting: MeetingCardData, twinId: string, isNext: boolean): CTASpec | null {
  if (meeting.status === 'completed') {
    return { label: 'View summary →', href: `/dashboard/meetings/${meeting.id}?twin=${twinId}`, outline: false };
  }
  if (meeting.status === 'recording' || meeting.status === 'bot_joining' || meeting.status === 'joining') {
    return { label: 'Watch live →', href: `/dashboard/meetings/${meeting.id}/live?twin=${twinId}`, outline: false };
  }
  if (meeting.status === 'processing') {
    return { label: 'View progress →', href: `/dashboard/meetings/${meeting.id}?twin=${twinId}`, outline: false };
  }
  // Scheduled with a meet_link: prioritize attendance opt-in over prep.
  // (A) Persona already attending — link to brief (or detail if not next)
  // (B) Not attending yet — surface "Send persona" filled CTA so user can
  //     enable bot dispatch from the card. Links into the detail page where
  //     the toggle lives.
  if (meeting.status === 'scheduled' && meeting.meet_link) {
    if (meeting.twin_attends) {
      if (isNext) {
        return { label: 'View brief →', href: `/dashboard/meetings/${meeting.id}/brief?twin=${twinId}`, outline: false };
      }
      return { label: '✓ Attending', href: `/dashboard/meetings/${meeting.id}?twin=${twinId}`, outline: true };
    }
    return { label: 'Send your persona →', href: `/dashboard/meetings/${meeting.id}?twin=${twinId}`, outline: false };
  }
  if (isNext) {
    return { label: 'View brief →', href: `/dashboard/meetings/${meeting.id}/brief?twin=${twinId}`, outline: false };
  }
  return { label: 'Add prep', href: `/dashboard/meetings/${meeting.id}/prep?twin=${twinId}`, outline: true };
}

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

export default function MeetingCard({
  meeting,
  twinId,
  isNext = false,
  showDayPrefix = false,
}: MeetingCardProps): React.JSX.Element {
  const time = formatTimeOnly(meeting.meeting_start);
  const dayPrefix = showDayPrefix ? formatDayPrefix(meeting.meeting_start) : '';
  const duration = formatDurationMin(meeting.meeting_start, meeting.meeting_end, meeting.duration_seconds);
  const countdown = computeCountdown(meeting.meeting_start);
  const { shown, overflow } = dedupedAttendees(meeting.attendees_json, 3);
  // effectiveStatus folds the missed-meeting derivation so both the chip and
  // the CTA see a consistent view of state. The DB row is untouched.
  const effectiveStatus = deriveEffectiveStatus(meeting);
  const meetingsV2 = useMeetingsV2();
  // Slice 3: clean one-card list — the per-card "Send persona / Attending" CTA moves
  // to the event page in v2, so the card just shows who/when.
  const cta = meetingsV2 ? null : resolveCTA({ ...meeting, status: effectiveStatus }, twinId, isNext);
  const cardHref = `/dashboard/meetings/${meeting.id}?twin=${twinId}`;
  const title = meeting.title?.trim() || 'Untitled meeting';

  return (
    <>
      <style jsx>{`
        @keyframes mc-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
      <Link
        href={cardHref}
        className="group relative grid items-center gap-4 rounded-3xl border px-5 py-4 transition-all hover:-translate-y-0.5"
        style={{
          gridTemplateColumns: '84px 1fr auto',
          backgroundColor: isNext ? 'rgba(0,102,204,0.04)' : 'var(--fog-2)',
          borderColor: isNext ? 'rgba(0,102,204,0.20)' : 'transparent',
          color: 'inherit',
          textDecoration: 'none',
          boxShadow: '0 4px 14px rgba(29,29,31,.05)',
        }}
      >
        {/* Time block */}
        <div className="flex flex-col gap-1.5">
          <div
            className="text-[15px] font-semibold leading-tight"
            style={{ color: 'var(--ink)', letterSpacing: '-0.015em' }}
          >
            {dayPrefix ? `${dayPrefix} · ${time}` : time}
          </div>
          {duration && (
            <div
              className="text-[11px]"
              style={{
                color: 'var(--fg-2)',
                fontFamily: 'var(--font-geist-mono, JetBrains Mono, monospace)',
              }}
            >
              {duration}
            </div>
          )}
          {countdown && (
            <span
              className="inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-medium"
              style={{
                backgroundColor: countdown.urgent ? 'rgba(224,162,26,.12)' : 'rgba(43,182,115,.12)',
                color: countdown.urgent ? 'var(--warn)' : 'var(--ok)',
                fontFamily: 'var(--font-geist-mono, JetBrains Mono, monospace)',
              }}
            >
              <span
                className="inline-block h-[5px] w-[5px] rounded-full"
                style={{
                  backgroundColor: 'currentColor',
                  animation: countdown.urgent ? 'mc-pulse 1.5s ease-in-out infinite' : undefined,
                }}
              />
              {countdown.text}
            </span>
          )}
        </div>

        {/* Body — title + attendees */}
        <div className="min-w-0">
          <div
            className="truncate text-[15.5px] font-medium leading-tight"
            style={{ color: 'var(--ink)', letterSpacing: '-0.012em', marginBottom: '6px' }}
          >
            {title}
          </div>
          {(shown.length > 0 || overflow > 0) && (
            <div className="flex flex-wrap items-center gap-1.5">
              {shown.map((a, i) => (
                <span
                  key={`${a.email || a.name || i}-${i}`}
                  className="inline-flex items-center rounded-full px-2.5 py-0.5 text-[12px]"
                  style={{ backgroundColor: 'var(--fog)', color: 'var(--ink-2)' }}
                >
                  {attendeeLabel(a)}
                </span>
              ))}
              {overflow > 0 && (
                <span
                  className="inline-flex items-center rounded-full px-2.5 py-0.5 text-[12px]"
                  style={{ backgroundColor: 'var(--fog)', color: 'var(--fg-3)' }}
                >
                  +{overflow} more
                </span>
              )}
            </div>
          )}
        </div>

        {/* Right — status + CTA */}
        <div className="flex items-center gap-3">
          <StatusChip status={effectiveStatus} />
          {cta && (
            <span
              className="inline-flex items-center rounded-full px-3.5 py-2 text-[13px] font-medium transition-all"
              style={{
                backgroundColor: cta.outline ? 'transparent' : 'var(--ink)',
                color: cta.outline ? 'var(--ink)' : '#fff',
                border: cta.outline ? '1px solid var(--fog-line-2)' : '1px solid transparent',
                letterSpacing: '-0.005em',
              }}
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                window.location.href = cta.href;
              }}
            >
              {cta.label}
            </span>
          )}
        </div>
      </Link>
    </>
  );
}
