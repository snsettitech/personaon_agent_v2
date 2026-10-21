'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';

interface ThreadMeeting {
  id: string;
  title: string | null;
  meeting_start: string | null;
  created_at: string;
}

interface Thread {
  person_email: string | null;
  person_name: string | null;
  person_node_id: string | null;
  meeting_count: number;
  last_met_at: string | null;
  meetings: ThreadMeeting[];
}

type LoadState = 'loading' | 'loaded' | 'error' | 'empty';

interface ThreadsListProps {
  twinId: string;
}

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  } catch {
    return iso;
  }
}

export default function ThreadsList({ twinId }: ThreadsListProps): React.JSX.Element {
  const apiBaseUrl = resolveApiBaseUrl();
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [threads, setThreads] = useState<Thread[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);

  const fetchThreads = useCallback(async () => {
    setLoadState('loading');
    try {
      const res = await authFetchStandalone(`${apiBaseUrl}/v2/meetings/${twinId}/threads`);
      if (!res.ok) {
        setLoadState('error');
        return;
      }
      const payload = await res.json();
      const data: Thread[] = payload?.data ?? [];
      setThreads(data);
      setLoadState(data.length === 0 ? 'empty' : 'loaded');
    } catch {
      setLoadState('error');
    }
  }, [apiBaseUrl, twinId]);

  useEffect(() => {
    void fetchThreads();
  }, [fetchThreads]);

  if (loadState === 'loading') {
    return <div className="text-sm p-4" style={{ color: 'var(--text-muted)' }}>Loading threads…</div>;
  }
  if (loadState === 'error') {
    return (
      <div className="text-sm text-red-600 p-4">
        Could not load threads. <button onClick={() => void fetchThreads()} className="underline">Retry</button>
      </div>
    );
  }
  if (loadState === 'empty') {
    return (
      <div className="rounded-2xl p-6 text-sm" style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)', color: 'var(--text-muted)' }}>
        No people threads yet. Threads appear once you have meetings with the same person.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {threads.map((t) => {
        const key = t.person_email || t.person_name || 'unknown';
        const isExpanded = expanded === key;
        const displayName = t.person_name || t.person_email || 'Unknown';

        // Header content shared between Link (when node_id present) and
        // accordion-button (when only name/email — rare edge case).
        const headerContent = (
          <div className="flex w-full items-center justify-between px-4 py-3">
            <div className="flex flex-col">
              <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                {displayName}
              </span>
              {t.person_email && t.person_name && (
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  {t.person_email}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--text-muted)' }}>
              <span>{t.meeting_count} meeting{t.meeting_count === 1 ? '' : 's'}</span>
              <span>·</span>
              <span>Last: {formatDate(t.last_met_at)}</span>
              <span className="ml-1">
                {t.person_node_id ? '→' : isExpanded ? '▾' : '▸'}
              </span>
            </div>
          </div>
        );

        return (
          <div
            key={key}
            className="rounded-2xl transition-colors hover:bg-black/[0.02]"
            style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
          >
            {t.person_node_id ? (
              <Link
                href={`/dashboard/people/${t.person_node_id}`}
                className="block"
                style={{ color: 'inherit', textDecoration: 'none' }}
                aria-label={`Open profile for ${displayName}`}
              >
                {headerContent}
              </Link>
            ) : (
              <>
                <button
                  type="button"
                  aria-expanded={isExpanded}
                  aria-label={`${isExpanded ? 'Collapse' : 'Expand'} thread for ${displayName}`}
                  onClick={() => setExpanded(isExpanded ? null : key)}
                  className="block w-full text-left"
                >
                  {headerContent}
                </button>
                {isExpanded && (
                  <div className="border-t border-black/[0.06] px-4 py-2">
                    <ul className="space-y-1">
                      {t.meetings.map((m) => (
                        <li key={m.id}>
                          <Link
                            href={`/dashboard/meetings/${m.id}`}
                            className="flex items-center justify-between rounded-lg px-2 py-1.5 text-sm hover:bg-black/[0.03]"
                          >
                            <span style={{ color: 'var(--text-primary)' }}>
                              {m.title || 'Untitled meeting'}
                            </span>
                            <span style={{ color: 'var(--text-muted)' }} className="text-xs">
                              {formatDate(m.meeting_start || m.created_at)}
                            </span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                    {t.meeting_count > t.meetings.length && (
                      <p className="px-2 py-1.5 text-xs" style={{ color: 'var(--text-muted)' }}>
                        + {t.meeting_count - t.meetings.length} earlier meeting{(t.meeting_count - t.meetings.length) === 1 ? '' : 's'} — open the full meeting list to see all.
                      </p>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
