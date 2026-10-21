'use client';

import React, { useMemo } from 'react';
import MeetingCard, { MeetingCardData } from './MeetingCard';
import DayHeader from './DayHeader';

type Variant = 'upcoming' | 'past';

interface MeetingsListProps {
  meetings: MeetingCardData[];
  twinId: string;
  variant: Variant;
  emptyTitle: string;
  emptySubtitle?: string;
  emptyAction?: React.ReactNode;
}

interface DayBucket {
  key: string;
  label: string;
  meta: string;
  meetings: MeetingCardData[];
  showDayPrefix: boolean;
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

function formatMeta(d: Date): string {
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}

function bucketUpcoming(meetings: MeetingCardData[]): DayBucket[] {
  const now = new Date();
  const todayStart = startOfDay(now);
  const tomorrowStart = todayStart + 24 * 60 * 60 * 1000;
  const dayAfterTomorrowStart = todayStart + 2 * 24 * 60 * 60 * 1000;
  const weekEnd = todayStart + 7 * 24 * 60 * 60 * 1000;

  const today: MeetingCardData[] = [];
  const tomorrow: MeetingCardData[] = [];
  const week: MeetingCardData[] = [];
  const later: MeetingCardData[] = [];

  for (const m of meetings) {
    if (!m.meeting_start) {
      later.push(m);
      continue;
    }
    const t = new Date(m.meeting_start).getTime();
    if (isNaN(t)) {
      later.push(m);
      continue;
    }
    if (t < tomorrowStart) today.push(m);
    else if (t < dayAfterTomorrowStart) tomorrow.push(m);
    else if (t < weekEnd) week.push(m);
    else later.push(m);
  }

  const buckets: DayBucket[] = [];
  if (today.length) {
    buckets.push({
      key: 'today',
      label: 'Today',
      meta: formatMeta(new Date(todayStart)),
      meetings: today,
      showDayPrefix: false,
    });
  }
  if (tomorrow.length) {
    buckets.push({
      key: 'tomorrow',
      label: 'Tomorrow',
      meta: formatMeta(new Date(tomorrowStart)),
      meetings: tomorrow,
      showDayPrefix: false,
    });
  }
  if (week.length) {
    buckets.push({
      key: 'week',
      label: 'This week',
      meta: `${week.length} meeting${week.length === 1 ? '' : 's'}`,
      meetings: week,
      showDayPrefix: true,
    });
  }
  if (later.length) {
    buckets.push({
      key: 'later',
      label: 'Later',
      meta: `${later.length} meeting${later.length === 1 ? '' : 's'}`,
      meetings: later,
      showDayPrefix: true,
    });
  }
  return buckets;
}

function bucketPast(meetings: MeetingCardData[]): DayBucket[] {
  const now = new Date();
  const todayStart = startOfDay(now);
  const yesterdayStart = todayStart - 24 * 60 * 60 * 1000;
  const weekStart = todayStart - 7 * 24 * 60 * 60 * 1000;

  const today: MeetingCardData[] = [];
  const yesterday: MeetingCardData[] = [];
  const week: MeetingCardData[] = [];
  const earlier: MeetingCardData[] = [];

  for (const m of meetings) {
    if (!m.meeting_start) {
      earlier.push(m);
      continue;
    }
    const t = new Date(m.meeting_start).getTime();
    if (isNaN(t)) {
      earlier.push(m);
      continue;
    }
    if (t >= todayStart) today.push(m);
    else if (t >= yesterdayStart) yesterday.push(m);
    else if (t >= weekStart) week.push(m);
    else earlier.push(m);
  }

  const buckets: DayBucket[] = [];
  if (today.length) {
    buckets.push({
      key: 'today',
      label: 'Today',
      meta: formatMeta(new Date(todayStart)),
      meetings: today,
      showDayPrefix: false,
    });
  }
  if (yesterday.length) {
    buckets.push({
      key: 'yesterday',
      label: 'Yesterday',
      meta: formatMeta(new Date(yesterdayStart)),
      meetings: yesterday,
      showDayPrefix: false,
    });
  }
  if (week.length) {
    buckets.push({
      key: 'week',
      label: 'This week',
      meta: `${week.length} meeting${week.length === 1 ? '' : 's'}`,
      meetings: week,
      showDayPrefix: true,
    });
  }
  if (earlier.length) {
    buckets.push({
      key: 'earlier',
      label: 'Earlier',
      meta: `${earlier.length} meeting${earlier.length === 1 ? '' : 's'}`,
      meetings: earlier,
      showDayPrefix: true,
    });
  }
  return buckets;
}

export default function MeetingsList({
  meetings,
  twinId,
  variant,
  emptyTitle,
  emptySubtitle,
  emptyAction,
}: MeetingsListProps): React.JSX.Element {
  const buckets = useMemo(() => {
    return variant === 'upcoming' ? bucketUpcoming(meetings) : bucketPast(meetings);
  }, [meetings, variant]);

  // Find the soonest upcoming meeting id for the "next" highlight.
  // `Date.now()` here is intentionally "now" at render — meetings change rarely,
  // so the slight impurity is fine; the dep array keeps memo stable within a render.
  const nextMeetingId = useMemo(() => {
    if (variant !== 'upcoming') return null;
    // eslint-disable-next-line react-hooks/purity
    const now = Date.now();
    const sorted = meetings
      .filter((m) => m.meeting_start && new Date(m.meeting_start).getTime() >= now)
      .sort((a, b) => new Date(a.meeting_start!).getTime() - new Date(b.meeting_start!).getTime());
    return sorted[0]?.id ?? null;
  }, [meetings, variant]);

  if (meetings.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center rounded-3xl px-6 py-16 text-center"
        style={{ backgroundColor: 'var(--fog-2)', border: '1px solid var(--fog-line)' }}
      >
        <p className="text-sm font-medium" style={{ color: 'var(--ink-2)' }}>
          {emptyTitle}
        </p>
        {emptySubtitle && (
          <p className="mt-1.5 max-w-md text-xs" style={{ color: 'var(--fg-3)' }}>
            {emptySubtitle}
          </p>
        )}
        {emptyAction && <div className="mt-4">{emptyAction}</div>}
      </div>
    );
  }

  return (
    <div className="space-y-7">
      {buckets.map((b) => (
        <div key={b.key}>
          <DayHeader label={b.label} meta={b.meta} />
          <div className="space-y-2.5">
            {b.meetings.map((m) => (
              <MeetingCard
                key={m.id}
                meeting={m}
                twinId={twinId}
                isNext={m.id === nextMeetingId}
                showDayPrefix={b.showDayPrefix}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
