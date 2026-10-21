'use client';

import React from 'react';
import Link from 'next/link';

export interface PersonTimelineMeeting {
  id: string;
  title: string | null;
  meeting_start: string | null;
  meeting_end: string | null;
  status: string | null;
  has_recap: boolean;
  has_recording: boolean;
}

interface PersonTimelineProps {
  meetings: PersonTimelineMeeting[];
  twinId: string;
}

function formatDateShort(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function formatRelativeDay(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  const now = new Date();
  const startOfDay = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((startOfDay(d) - startOfDay(now)) / 86_400_000);
  if (days === 0) return 'today';
  if (days === 1) return 'tomorrow';
  if (days === -1) return 'yesterday';
  return '';
}

function StatusDot({ status }: { status: string | null }): React.JSX.Element | null {
  if (!status) return null;
  const map: Record<string, { bg: string; label: string }> = {
    completed:   { bg: 'var(--ok)',     label: 'Completed' },
    scheduled:   { bg: 'var(--fg-3)',   label: 'Scheduled' },
    bot_joining: { bg: 'var(--signal)', label: 'Joining'   },
    joining:     { bg: 'var(--signal)', label: 'Joining'   },
    recording:   { bg: 'var(--rec)',    label: 'Recording' },
    processing:  { bg: 'var(--warn)',   label: 'Processing'},
    failed:      { bg: 'var(--rec)',    label: 'Failed'    },
    canceled:    { bg: 'var(--fg-3)',   label: 'Canceled'  },
  };
  const s = map[status] ?? map.scheduled;
  return (
    <span
      className="inline-flex items-center gap-1 text-[11px]"
      style={{
        color: s.bg,
        fontFamily: 'var(--font-geist-mono, JetBrains Mono, monospace)',
      }}
    >
      <span
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ backgroundColor: 'currentColor' }}
      />
      {s.label.toUpperCase()}
    </span>
  );
}

export default function PersonTimeline({
  meetings,
  twinId,
}: PersonTimelineProps): React.JSX.Element {
  if (meetings.length === 0) {
    return (
      <div
        className="rounded-3xl px-6 py-12 text-center"
        style={{
          backgroundColor: 'var(--fog-2)',
          border: '1px solid var(--fog-line)',
        }}
      >
        <p className="text-sm font-medium" style={{ color: 'var(--ink-2)' }}>
          No recordings yet
        </p>
        <p className="mt-1 text-xs" style={{ color: 'var(--fg-3)' }}>
          Calendar-only meetings will appear here.
        </p>
      </div>
    );
  }

  return (
    <div
      className="rounded-3xl"
      style={{
        backgroundColor: 'var(--fog-2)',
        border: '1px solid var(--fog-line)',
        overflow: 'hidden',
      }}
    >
      {meetings.map((m, i) => {
        const dateShort = formatDateShort(m.meeting_start);
        const relative = formatRelativeDay(m.meeting_start);
        return (
          <Link
            key={m.id}
            href={`/dashboard/meetings/${m.id}?twin=${twinId}`}
            className="grid grid-cols-[100px_1fr_auto] items-center gap-4 px-5 py-4 transition-colors hover:bg-black/[0.02]"
            style={{
              color: 'inherit',
              textDecoration: 'none',
              borderTop: i === 0 ? 'none' : '1px solid var(--fog-line)',
            }}
          >
            <div className="flex flex-col">
              <span
                className="text-[13px] font-medium"
                style={{
                  color: 'var(--ink)',
                  fontFamily: 'var(--font-geist-mono, JetBrains Mono, monospace)',
                }}
              >
                {dateShort}
              </span>
              {relative && (
                <span
                  className="text-[10.5px] uppercase"
                  style={{
                    color: 'var(--fg-3)',
                    fontFamily: 'var(--font-geist-mono, JetBrains Mono, monospace)',
                    letterSpacing: '0.10em',
                  }}
                >
                  {relative}
                </span>
              )}
            </div>
            <div className="min-w-0">
              <div
                className="truncate text-[14px]"
                style={{ color: 'var(--ink)' }}
              >
                {m.title || 'Untitled meeting'}
              </div>
              {!m.has_recording && (
                <div
                  className="mt-0.5 text-[11px]"
                  style={{ color: 'var(--fg-3)' }}
                >
                  Calendar only · not recorded
                </div>
              )}
            </div>
            <div className="flex items-center gap-2">
              <StatusDot status={m.status} />
              <span style={{ color: 'var(--fg-3)' }}>→</span>
            </div>
          </Link>
        );
      })}
    </div>
  );
}
