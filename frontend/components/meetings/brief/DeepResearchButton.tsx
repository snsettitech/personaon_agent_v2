'use client';

import React, { useEffect, useRef, useState } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';
import type { BriefContract } from '@/lib/types/brief';

/**
 * W9d — "Run deep research" CTA + polling.
 *
 * Triggers ``POST /v2/meetings/{twin}/{meeting}/brief/deep`` and then polls
 * ``GET /brief?deep=1`` every 5s until ``deep_generated_at`` appears on
 * the brief. After completion, calls ``onDeepBriefReady(brief)`` so the
 * parent can re-render with the richer data.
 *
 * Visible states:
 *   - ``idle`` — button visible (only when not freshly deep + flag implied
 *     via 503 detection)
 *   - ``running`` — disabled button with "Researching…" + spinner
 *   - ``error`` — inline message + retry option (auto-clears on next idle)
 *   - cached — parent already has ``deep_generated_at`` so this component
 *     either hides or renders a small "Deep research from {time}" line
 *
 * Polling has a hard timeout (~150s = 30 attempts × 5s) so a wedged job
 * doesn't poll forever. Past the timeout we surface a "still working —
 * check back later" message rather than a hard error.
 */

interface DeepResearchButtonProps {
  twinId: string;
  meetingId: string;
  brief: BriefContract;
  onDeepBriefReady: (brief: BriefContract) => void;
}

type ButtonState = 'idle' | 'running' | 'error' | 'unavailable';

// AUDIT FIX (W9d MEDIUM): discriminated union for the POST response
// status so a backend typo like 'cache' falls through to a no-op
// instead of silently triggering a polling loop.
type DeepTriggerStatus = 'cached' | 'queued';

const POLL_INTERVAL_MS = 5_000;
// AUDIT FIX (W9d MEDIUM): extend ceiling to 45 attempts (~225s) so the
// worst-case backend latency (90s) plus queue time (~60s) doesn't strand
// users at "still working" 30s before completion.
const POLL_MAX_ATTEMPTS = 45;

export function DeepResearchButton({
  twinId,
  meetingId,
  brief,
  onDeepBriefReady,
}: DeepResearchButtonProps): React.JSX.Element | null {
  const [state, setState] = useState<ButtonState>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const apiBaseUrl = resolveApiBaseUrl();

  // AUDIT FIX (W9d HIGH): clean up any in-flight poll ONLY on unmount.
  // Brief-change cleanup lives in the second effect below — keeping both
  // here would be redundant.
  useEffect(() => {
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, []);

  // When the brief gets a fresh deep_generated_at (parent fetched the
  // updated brief), stop any in-flight poll. This is a real edge case,
  // not just defense: the page may re-fetch via its own useEffect if
  // the user navigates back/forward, and we'd be left polling for a
  // brief that's already been served.
  useEffect(() => {
    if (brief.deep_generated_at && pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
      setState('idle');
    }
  }, [brief.deep_generated_at]);

  if (state === 'unavailable') return null;

  // If we already have a deep brief, render the footer indicator only.
  if (brief.deep_generated_at) {
    return <DeepBriefBadge generatedAt={brief.deep_generated_at} />;
  }

  async function startPolling(): Promise<void> {
    let attempts = 0;
    pollingRef.current = setInterval(async () => {
      attempts += 1;
      if (attempts > POLL_MAX_ATTEMPTS) {
        if (pollingRef.current) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
        setState('error');
        setErrorMessage(
          "Still working — check back in a minute and refresh the page.",
        );
        return;
      }
      try {
        const res = await authFetchStandalone(
          `${apiBaseUrl}/v2/meetings/${twinId}/${meetingId}/brief?deep=1`,
        );
        if (!res.ok) return; // transient — keep polling
        const payload = (await res.json()) as { data?: BriefContract };
        const polled = payload?.data;
        if (polled?.deep_generated_at) {
          if (pollingRef.current) {
            clearInterval(pollingRef.current);
            pollingRef.current = null;
          }
          setState('idle');
          onDeepBriefReady(polled);
        }
      } catch {
        // Transient — keep polling. We won't surface every blip.
      }
    }, POLL_INTERVAL_MS);
  }

  async function handleClick(): Promise<void> {
    // AUDIT FIX (W9d HIGH): synchronous re-entry guard. Without this, a
    // pointer-up between the `setState('running')` call and the next
    // React render could fire a second `onClick` (the disabled prop
    // doesn't take effect until the next paint). Backend has an
    // idempotency key but defending here saves a round-trip.
    if (state === 'running') return;
    setState('running');
    setErrorMessage(null);
    try {
      const res = await authFetchStandalone(
        `${apiBaseUrl}/v2/meetings/${twinId}/${meetingId}/brief/deep`,
        { method: 'POST' },
      );
      if (res.status === 503) {
        // Feature flag off — hide the button rather than show an error
        setState('unavailable');
        return;
      }
      if (res.status === 429) {
        // Rate-limited (W9d audit fix in backend). Show the server-supplied
        // message if present, else generic.
        let msg = 'Daily deep research limit reached. Try again tomorrow.';
        try {
          const body = await res.json();
          if (body && typeof body.detail === 'string') msg = body.detail;
        } catch {
          // fall through
        }
        setState('error');
        setErrorMessage(msg);
        return;
      }
      if (!res.ok) {
        // AUDIT FIX (W9d MEDIUM): a 404 on the deep endpoint for a
        // meeting whose brief just rendered isn't "meeting missing" —
        // it means the route isn't mounted or the feature isn't
        // available. Same UX as 503 (hide the button) rather than
        // confusing the user.
        if (res.status === 404) {
          setState('unavailable');
          return;
        }
        setState('error');
        setErrorMessage('Could not start deep research. Try again later.');
        return;
      }
      const payload = (await res.json()) as {
        status?: DeepTriggerStatus;
        data?: BriefContract;
      };
      if (payload?.status === 'cached' && payload.data) {
        // Server already has a fresh deep brief; skip polling.
        setState('idle');
        onDeepBriefReady(payload.data);
        return;
      }
      if (payload?.status === 'queued') {
        await startPolling();
        return;
      }
      // Unknown / missing status — don't silently start a polling loop.
      setState('error');
      setErrorMessage('Unexpected response. Try again.');
    } catch (err) {
      setState('error');
      setErrorMessage(
        err instanceof Error ? err.message : 'Network error',
      );
    }
  }

  const isRunning = state === 'running';
  // AUDIT FIX (W9d HIGH a11y): link the error region to the button so
  // screen-reader users get the error context when they re-focus the
  // button to retry. Static id is fine — only one instance per page.
  const errorId = 'deep-research-error';
  const hasError = state === 'error' && !!errorMessage;

  return (
    <div className="mt-4 flex flex-col items-center gap-2">
      <button
        type="button"
        onClick={handleClick}
        disabled={isRunning}
        aria-busy={isRunning}
        aria-describedby={hasError ? errorId : undefined}
        className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full text-sm min-h-[44px] transition-colors disabled:cursor-not-allowed disabled:opacity-70"
        style={{
          background: 'transparent',
          border: '1px solid var(--border-default)',
          color: 'var(--text-primary)',
        }}
      >
        {isRunning ? (
          <>
            <Spinner />
            {/* aria-live="polite" so screen readers announce the
                state change when state flips to running */}
            <span aria-live="polite">Researching… (~30-45s)</span>
          </>
        ) : (
          <>
            <span aria-hidden className="font-mono text-xs">
              ⚡
            </span>
            {hasError ? 'Try deep research again' : 'Run deep research'}
          </>
        )}
      </button>
      {hasError && (
        <div
          id={errorId}
          className="text-xs text-center"
          style={{ color: 'var(--text-secondary)' }}
          role="alert"
        >
          {errorMessage}
        </div>
      )}
    </div>
  );
}

function Spinner(): React.JSX.Element {
  return (
    <span
      aria-hidden
      className="inline-block w-3.5 h-3.5 rounded-full animate-spin"
      style={{
        border: '2px solid var(--border-default)',
        borderTopColor: 'var(--text-primary)',
      }}
    />
  );
}

function DeepBriefBadge({
  generatedAt,
}: {
  generatedAt: string;
}): React.JSX.Element {
  const relative = formatRelative(generatedAt);
  return (
    <div
      className="mt-2 text-center font-mono text-[11px]"
      style={{ color: 'var(--text-secondary)' }}
    >
      Deep research {relative}
    </div>
  );
}

function formatRelative(iso: string): string {
  const ts = new Date(iso);
  if (Number.isNaN(ts.getTime())) return 'recently';
  const diffMs = Date.now() - ts.getTime();
  // AUDIT FIX (W9d MEDIUM): clamp to 0 so client clock skew (timestamp
  // in the future) doesn't render "-3 min ago".
  const mins = Math.max(0, Math.round(diffMs / 60_000));
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return ts.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  });
}
