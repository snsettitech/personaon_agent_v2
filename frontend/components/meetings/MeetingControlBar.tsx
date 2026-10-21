'use client';

import React, { useCallback, useRef, useState } from 'react';
import Link from 'next/link';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MeetingControlBarProps {
  twinId: string;
  meetingId: string;
  isMuted: boolean;
  onMuteToggle: (muted: boolean) => void;
  onLeave: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MeetingControlBar({
  twinId,
  meetingId,
  isMuted,
  onMuteToggle,
  onLeave,
}: MeetingControlBarProps): React.JSX.Element {
  const [saving, setSaving] = useState(false);
  const [showLeaveConfirm, setShowLeaveConfirm] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleMuteToggle = useCallback(() => {
    if (saving) return;

    // Debounce 500ms
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }

    const next = !isMuted;

    // Optimistic update
    onMuteToggle(next);
    setSaving(true);

    debounceRef.current = setTimeout(async () => {
      try {
        const apiBase = resolveApiBaseUrl();
        const res = await authFetchStandalone(
          `${apiBase}/v2/meetings/${twinId}/${meetingId}/mute`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ muted: next }),
          },
        );

        if (!res.ok) {
          // Rollback
          onMuteToggle(!next);
        }
      } catch {
        // Rollback on network error
        onMuteToggle(!next);
      } finally {
        setSaving(false);
      }
    }, 500);
  }, [isMuted, saving, twinId, meetingId, onMuteToggle]);

  const handleLeaveConfirm = useCallback(() => {
    setShowLeaveConfirm(false);
    onLeave();
  }, [onLeave]);

  return (
    <div
      className="fixed bottom-0 left-0 right-0 flex items-center justify-center gap-4 px-4"
      style={{
        backgroundColor: 'var(--bg-card)',
        borderTop: '1px solid var(--border-subtle)',
        height: '72px',
        zIndex: 50,
      }}
    >
      {/* Mute button */}
      <div className="flex flex-col items-center gap-1">
        <button
          type="button"
          onClick={handleMuteToggle}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              handleMuteToggle();
            }
          }}
          className="flex items-center justify-center rounded-full transition-colors cursor-pointer focus:outline-none focus:ring-2 focus:ring-offset-2"
          style={{
            width: '48px',
            height: '48px',
            backgroundColor: isMuted ? 'var(--bg-surface)' : 'var(--accent-red)',
            border: isMuted ? '1px solid var(--border-default)' : 'none',
            color: isMuted ? 'var(--text-secondary)' : '#FFFFFF',
            '--tw-ring-color': 'var(--primary-500)',
          } as React.CSSProperties}
          aria-label={isMuted ? 'Unmute persona' : 'Mute persona'}
        >
          {isMuted ? (
            /* Mic-off icon */
            <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M19 19L5 5m14 0v4a2 2 0 01-2 2h-1m-4 4v2m-4-6a4 4 0 004 4m4-4a4 4 0 00-4-4m0 0V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4"
              />
              <line x1="3" y1="3" x2="21" y2="21" strokeWidth={2} strokeLinecap="round" />
            </svg>
          ) : (
            /* Mic icon */
            <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z"
              />
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M19 10v2a7 7 0 01-14 0v-2M12 19v4M8 23h8"
              />
            </svg>
          )}
        </button>
        <span className="text-xs font-bold" style={{ color: 'var(--text-secondary)' }}>
          {isMuted ? 'Unmute persona' : 'Mute persona'}
        </span>
      </div>

      {/* Leave button */}
      <div className="flex items-center">
        {showLeaveConfirm ? (
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold" style={{ color: 'var(--text-secondary)' }}>
              End persona participation?
            </span>
            <button
              type="button"
              onClick={handleLeaveConfirm}
              className="rounded-xl px-3 py-1.5 text-sm font-bold cursor-pointer"
              style={{
                backgroundColor: 'var(--accent-red)',
                color: '#FFFFFF',
              }}
            >
              Confirm
            </button>
            <button
              type="button"
              onClick={() => setShowLeaveConfirm(false)}
              className="rounded-xl px-3 py-1.5 text-sm cursor-pointer"
              style={{ color: 'var(--text-secondary)' }}
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setShowLeaveConfirm(true)}
            className="rounded-xl px-4 py-2 text-sm font-bold cursor-pointer transition-colors"
            style={{
              backgroundColor: 'transparent',
              border: '1px solid var(--accent-red)',
              color: 'var(--accent-red)',
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--accent-red-light)';
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'transparent';
            }}
          >
            Leave Meeting
          </button>
        )}
      </div>

      {/* Back button */}
      <Link
        href={`/dashboard/meetings/${meetingId}`}
        className="rounded-xl px-4 py-2 text-sm"
        style={{
          backgroundColor: 'transparent',
          border: '1px solid var(--border-default)',
          color: 'var(--text-secondary)',
          textDecoration: 'none',
        }}
      >
        Back to Meeting
      </Link>
    </div>
  );
}
