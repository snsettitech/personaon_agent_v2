'use client';

/**
 * Phase B (slice 4) — the Notes/prep, editable inline on the unified meeting page
 * (no separate /prep route). Autosaves on blur via PATCH, mirroring the prep page.
 * See docs/product/meetings-spec-and-plan.md.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';

interface NotesTabContentProps {
  twinId: string;
  meetingId: string;
  initialGoal: string;
  initialContext: string;
}

type SaveState = 'idle' | 'saving' | 'saved' | 'error';

export default function NotesTabContent({
  twinId, meetingId, initialGoal, initialContext,
}: NotesTabContentProps): React.JSX.Element {
  const apiBaseUrl = resolveApiBaseUrl();
  const [goal, setGoal] = useState(initialGoal);
  const [context, setContext] = useState(initialContext);
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const save = useCallback(async () => {
    if (!twinId || !meetingId) return;
    setSaveState('saving');
    try {
      const res = await authFetchStandalone(`${apiBaseUrl}/v2/meetings/${twinId}/${meetingId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_goal: goal.trim() || null,
          user_context: context.trim() || null,
        }),
      });
      if (!res.ok) { setSaveState('error'); return; }
      setSaveState('saved');
      if (savedTimer.current) clearTimeout(savedTimer.current);
      savedTimer.current = setTimeout(() => setSaveState('idle'), 2000);
    } catch {
      setSaveState('error');
    }
  }, [apiBaseUrl, twinId, meetingId, goal, context]);

  // Clear the "Saved" timer on unmount (e.g. switching tabs) — avoids setState-on-unmounted.
  useEffect(() => () => {
    if (savedTimer.current) clearTimeout(savedTimer.current);
  }, []);

  const inputStyle = { borderColor: 'var(--border-default, #ddd)', color: 'var(--text-primary, #111)' } as const;
  const labelStyle = { color: 'var(--text-muted, #888)' } as const;

  return (
    <div className="rounded-3xl p-5 space-y-4" style={{ backgroundColor: 'var(--bg-card, #fff)', border: '1px solid var(--border-subtle, #eee)' }}>
      <div>
        <label className="text-xs font-semibold uppercase tracking-wide" style={labelStyle}>Goal</label>
        <input
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onBlur={() => void save()}
          maxLength={500}
          placeholder="e.g. lock in tier-2 pricing"
          className="mt-1 w-full rounded-xl border px-3 py-2 text-sm"
          style={inputStyle}
        />
      </div>
      <div>
        <label className="text-xs font-semibold uppercase tracking-wide" style={labelStyle}>Notes &amp; context</label>
        <textarea
          value={context}
          onChange={(e) => setContext(e.target.value)}
          onBlur={() => void save()}
          maxLength={5000}
          rows={6}
          placeholder="Anything you want to remember or cover…"
          className="mt-1 w-full rounded-xl border px-3 py-2 text-sm"
          style={inputStyle}
        />
      </div>
      <p className="text-xs" style={labelStyle}>
        {saveState === 'saving' ? 'Saving…'
          : saveState === 'saved' ? '✓ Saved'
            : saveState === 'error' ? 'Could not save — try again'
              : 'Autosaves when you click away'}
      </p>
    </div>
  );
}
