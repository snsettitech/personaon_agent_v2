'use client';

import React, { useCallback, useState } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TwinAttendanceToggleProps {
  twinId: string;
  meetingId: string;
  initialAttend: boolean;
  disabled?: boolean;
  disabledReason?: string;
}

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function TwinAttendanceToggle({
  twinId,
  meetingId,
  initialAttend,
  disabled = false,
  disabledReason,
}: TwinAttendanceToggleProps): React.JSX.Element {
  const [attend, setAttend] = useState(initialAttend);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');

  const handleToggle = useCallback(async () => {
    if (disabled) return;

    const prev = attend;
    const next = !attend;

    // Optimistic update
    setAttend(next);
    setSaveStatus('saving');

    try {
      const apiBase = resolveApiBaseUrl();
      const res = await authFetchStandalone(
        `${apiBase}/v2/meetings/${twinId}/${meetingId}/toggle-attendance`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ attend: next }),
        },
      );

      if (!res.ok) {
        throw new Error('save-failed');
      }

      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 2000);
    } catch {
      // Rollback on failure
      setAttend(prev);
      setSaveStatus('error');
    }
  }, [attend, disabled, twinId, meetingId]);

  return (
    <div
      className="flex items-center gap-2"
      onClick={(e) => e.preventDefault()}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
        }
      }}
    >
      {/* Label */}
      <span
        className="text-xs font-bold whitespace-nowrap"
        style={{ color: 'var(--text-secondary)' }}
      >
        Send your persona
      </span>

      {/* Toggle */}
      <div className="relative">
        <button
          type="button"
          role="switch"
          aria-checked={attend}
          aria-label={`Send your persona${disabled && disabledReason ? ` (${disabledReason})` : ''}`}
          disabled={disabled}
          onClick={() => { void handleToggle(); }}
          className={`w-12 h-6 rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 ${
            disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'
          }`}
          style={{
            backgroundColor: attend ? 'var(--primary-500)' : 'var(--bg-elevated)',
            border: attend ? 'none' : '1px solid var(--border-default)',
            // Focus ring color
            '--tw-ring-color': 'var(--primary-500)',
          } as React.CSSProperties}
          title={disabled && disabledReason ? disabledReason : undefined}
        >
          <div
            className={`w-5 h-5 bg-white rounded-full shadow-sm transition-transform ${
              attend ? 'translate-x-6' : 'translate-x-0.5'
            }`}
          />
        </button>
      </div>

      {/* Save status */}
      {saveStatus !== 'idle' && (
        <span
          className="text-[10px] font-bold whitespace-nowrap"
          style={{
            color: saveStatus === 'error' ? 'var(--accent-red)' : 'var(--text-muted)',
          }}
        >
          {saveStatus === 'saving' && 'Saving...'}
          {saveStatus === 'saved' && 'Saved'}
          {saveStatus === 'error' && 'Failed to save'}
        </span>
      )}
    </div>
  );
}
