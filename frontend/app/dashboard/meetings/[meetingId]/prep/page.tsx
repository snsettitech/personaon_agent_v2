'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';
import { useTwin } from '@/lib/context/TwinContext';
import { useMeetingsV2 } from '@/lib/features/meetingsV2';

interface MeetingPrepData {
  id: string;
  title: string | null;
  meeting_start: string | null;
  user_goal: string | null;
  user_context: string | null;
}

type SaveState = 'idle' | 'saving' | 'saved' | 'error';

export default function MeetingPrepPage(): React.JSX.Element {
  const params = useParams();
  const router = useRouter();
  const meetingId = String(params?.meetingId ?? '');
  const { activeTwin } = useTwin();
  const apiBaseUrl = resolveApiBaseUrl();

  // Preserve twin in nav back to the recap so the recap page doesn't
  // dead-end on "Missing persona parameter".
  const twinQs = activeTwin?.id ? `?twin=${activeTwin.id}` : '';
  const backHref = `/dashboard/meetings/${meetingId}${twinQs}`;
  const meetingsV2 = useMeetingsV2();

  // Phase B: prep is now the Notes tab on the unified meeting page; send v2 users there.
  useEffect(() => {
    if (meetingsV2 && meetingId) {
      router.replace(`/dashboard/meetings/${meetingId}?view=notes${activeTwin?.id ? `&twin=${activeTwin.id}` : ''}`);
    }
  }, [meetingsV2, meetingId, activeTwin?.id, router]);

  const [meeting, setMeeting] = useState<MeetingPrepData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [userGoal, setUserGoal] = useState('');
  const [userContext, setUserContext] = useState('');
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [saveError, setSaveError] = useState<string | null>(null);

  const savedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (savedTimerRef.current) clearTimeout(savedTimerRef.current);
    };
  }, []);

  // Load existing meeting
  useEffect(() => {
    if (!activeTwin?.id || !meetingId) return;
    let cancelled = false;
    void (async () => {
      try {
        const res = await authFetchStandalone(
          `${apiBaseUrl}/v2/meetings/${activeTwin.id}/${meetingId}`,
        );
        if (cancelled) return;
        if (!res.ok) {
          setLoadError(res.status === 404 ? 'Meeting not found' : 'Could not load meeting');
          return;
        }
        const payload = await res.json();
        const data: MeetingPrepData = payload?.data ?? payload;
        setMeeting(data);
        setUserGoal(data.user_goal ?? '');
        setUserContext(data.user_context ?? '');
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : 'Unknown error');
        }
      }
    })();
    return () => { cancelled = true; };
  }, [activeTwin?.id, meetingId, apiBaseUrl]);

  // Save on blur — debounced via direct calls (the user explicitly blurs)
  // eslint-disable-next-line react-hooks/preserve-manual-memoization
  const save = useCallback(async (goal: string, context: string) => {
    if (!activeTwin?.id || !meetingId) return;
    setSaveState('saving');
    setSaveError(null);
    try {
      const res = await authFetchStandalone(
        `${apiBaseUrl}/v2/meetings/${activeTwin.id}/${meetingId}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            user_goal: goal.trim() || null,
            user_context: context.trim() || null,
          }),
        },
      );
      if (!res.ok) {
        setSaveState('error');
        setSaveError(res.status === 404 ? 'Meeting not found' : 'Could not save');
        return;
      }
      setSaveState('saved');
      if (savedTimerRef.current) clearTimeout(savedTimerRef.current);
      savedTimerRef.current = setTimeout(() => {
        setSaveState('idle');
        savedTimerRef.current = null;
      }, 1500);
    } catch (err) {
      setSaveState('error');
      setSaveError(err instanceof Error ? err.message : 'Unknown error');
    }
  }, [activeTwin?.id, meetingId, apiBaseUrl]);

  if (loadError) {
    return (
      <div className="p-6 text-sm text-red-600">{loadError}</div>
    );
  }
  if (!meeting) {
    return <div className="p-6 text-sm" style={{ color: 'var(--text-muted)' }}>Loading…</div>;
  }

  const handleSaveClick = async () => {
    await save(userGoal, userContext);
  };

  const handleSaveAndBack = async () => {
    await save(userGoal, userContext);
    // Brief delay so the user sees "✓ Saved" before nav
    setTimeout(() => router.push(backHref), 400);
  };

  return (
    <div className="mx-auto max-w-2xl space-y-6 p-6">
      <div>
        <Link
          href={backHref}
          className="text-xs hover:underline"
          style={{ color: 'var(--text-muted)' }}
        >
          ← Back to meeting
        </Link>
        <h1 className="mt-2 text-2xl font-bold tracking-tight" style={{ color: 'var(--text-primary)' }}>
          Prep
        </h1>
        <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary)' }}>
          {meeting.title ?? 'Untitled meeting'}
        </p>
      </div>

      <div className="space-y-1">
        <label htmlFor="user_goal" className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
          What&apos;s your goal for this meeting?
        </label>
        <input
          id="user_goal"
          type="text"
          value={userGoal}
          maxLength={500}
          onChange={(e) => setUserGoal(e.target.value)}
          onBlur={() => void save(userGoal, userContext)}
          placeholder="e.g. lock in tier 2 pricing"
          className="w-full rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2"
          style={{
            backgroundColor: 'var(--bg-surface)',
            border: '1px solid var(--border-default)',
            color: 'var(--text-primary)',
          }}
        />
        <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
          One line. Feeds the recap engine&apos;s intent-vs-outcome.
        </p>
      </div>

      <div className="space-y-1">
        <label htmlFor="user_context" className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
          Anything the AI should know going in?
        </label>
        <textarea
          id="user_context"
          rows={5}
          maxLength={5000}
          value={userContext}
          onChange={(e) => setUserContext(e.target.value)}
          onBlur={() => void save(userGoal, userContext)}
          placeholder="e.g. investor I met at Antler Day 4. Wants to lead seed. Last time we talked he asked about our retention numbers."
          className="w-full rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2"
          style={{
            backgroundColor: 'var(--bg-surface)',
            border: '1px solid var(--border-default)',
            color: 'var(--text-primary)',
          }}
        />
      </div>

      {/* Action bar with explicit Save buttons — fixes the "no way to save" UX gap.
          Field-blur still triggers an autosave for users who don't click. */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
        <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
          {saveState === 'saving' && 'Saving…'}
          {saveState === 'saved' && '✓ Saved'}
          {saveState === 'error' && (saveError ?? 'Could not save')}
          {saveState === 'idle' && 'Autosaves on blur'}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void handleSaveClick()}
            disabled={saveState === 'saving'}
            className="rounded-xl px-4 py-2 text-sm font-medium transition-opacity disabled:opacity-50"
            style={{
              backgroundColor: 'transparent',
              color: 'var(--ink)',
              border: '1px solid var(--fog-line-2)',
            }}
          >
            Save
          </button>
          <button
            type="button"
            onClick={() => void handleSaveAndBack()}
            disabled={saveState === 'saving'}
            className="rounded-xl px-4 py-2 text-sm font-medium transition-opacity disabled:opacity-50"
            style={{
              backgroundColor: 'var(--ink)',
              color: '#fff',
            }}
          >
            Save and back to meeting
          </button>
        </div>
      </div>
    </div>
  );
}
