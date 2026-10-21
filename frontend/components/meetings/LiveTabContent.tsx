'use client';

/**
 * Live tab — streams the meeting transcript IN the unified page (one-page
 * experience) instead of punting to a separate /live route. Status badge +
 * connection/error banners + the live transcript + an inline mute toggle and
 * a Join link. Connection lifecycle lives in useLiveTranscript.
 * See docs/product/meetings-spec-and-plan.md.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';
import LiveTranscript from '@/components/meetings/LiveTranscript';
import { useLiveTranscript, type TwinStatus } from '@/lib/hooks/useLiveTranscript';

interface LiveTabContentProps {
  twinId: string;
  meetingId: string;
  meetLink?: string | null;
  /** Only open the WebSocket when the meeting is actually live. */
  enabled?: boolean;
  /** When absent, no bot is in the call — show a clear state, don't connect. */
  recallBotId?: string | null;
}

const STATUS_LABEL: Record<TwinStatus, string> = {
  joining: 'Joining…',
  listening: 'Your persona is listening',
  thinking: 'Your persona is thinking',
  speaking: 'Your persona is speaking',
  muted: 'Your persona is muted',
  deferred: 'Deferred to you',
  left: 'Your persona left',
};

export default function LiveTabContent({
  twinId, meetingId, meetLink, enabled = true, recallBotId,
}: LiveTabContentProps): React.JSX.Element {
  const hasBot = Boolean(recallBotId);
  const { messages, twinStatus, isMuted, setMuted, connectionStatus, error } =
    useLiveTranscript(meetingId, enabled && hasBot);
  const [savingMute, setSavingMute] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Cancel a pending mute debounce on unmount (e.g. switching tabs mid-window)
  // so the timer can't fire setState on an unmounted component.
  useEffect(() => () => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
  }, []);

  // Mute toggle — optimistic, debounced, rolls back on failure (mirrors the
  // legacy MeetingControlBar contract so the backend sees the same calls).
  const toggleMute = useCallback(() => {
    if (savingMute || !twinId) return;
    const next = !isMuted;
    setMuted(next);
    setSavingMute(true);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await authFetchStandalone(
          `${resolveApiBaseUrl()}/v2/meetings/${twinId}/${meetingId}/mute`,
          { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ muted: next }) },
        );
        if (!res.ok) setMuted(!next);
      } catch {
        setMuted(!next);
      } finally {
        setSavingMute(false);
      }
    }, 500);
  }, [savingMute, isMuted, twinId, meetingId, setMuted]);

  const dotColor =
    connectionStatus === 'connected' ? 'var(--signal, #2bb673)'
      : connectionStatus === 'connecting' ? 'var(--text-muted, #888)'
        : 'var(--accent-red, #c0392b)';

  // No bot dispatched -> there is no live stream to show. Avoid a forever
  // "Waiting…" spinner and a mute button that would POST to a non-existent bot.
  if (!hasBot) {
    return (
      <div className="rounded-3xl p-6 text-center text-sm" style={{ backgroundColor: 'var(--fog-2, #f7f7f8)', color: 'var(--text-secondary, #666)' }}>
        Your persona hasn’t joined this meeting.
        {meetLink && (
          <div className="mt-3">
            <a href={meetLink} target="_blank" rel="noreferrer" className="inline-block rounded-xl px-4 py-2 text-sm font-semibold text-white" style={{ backgroundColor: 'var(--brand-primary, #0066cc)' }}>Join meeting</a>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Status + live indicator */}
      <div className="flex items-center justify-between rounded-2xl px-4 py-2.5" style={{ backgroundColor: 'var(--bg-card, #fff)', border: '1px solid var(--border-subtle, #eee)' }}>
        <span className="flex items-center gap-2 text-sm font-medium" style={{ color: 'var(--text-primary, #111)' }}>
          <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: dotColor }} />
          {STATUS_LABEL[twinStatus] ?? 'Live'}
        </span>
        <button
          type="button"
          onClick={toggleMute}
          disabled={savingMute}
          className="rounded-full px-3 py-1 text-xs font-semibold"
          style={{
            border: '1px solid var(--border-default, #ddd)',
            color: isMuted ? 'var(--accent-red, #c0392b)' : 'var(--text-secondary, #555)',
            opacity: savingMute ? 0.6 : 1,
          }}
        >
          {isMuted ? 'Unmute AI' : 'Mute AI'}
        </button>
      </div>

      {connectionStatus === 'disconnected' && !error && (
        <div className="rounded-xl px-4 py-2 text-center text-sm" style={{ backgroundColor: 'var(--fog, #f3f4f6)', color: 'var(--text-secondary, #555)' }}>
          Live connection lost. Reconnecting…
        </div>
      )}
      {error && (
        <div className="rounded-xl px-4 py-2 text-center text-sm" style={{ backgroundColor: '#FEE2E2', color: '#991b1b' }}>
          {error}
        </div>
      )}

      {/* The stream */}
      {messages.length > 0 ? (
        <LiveTranscript messages={messages} />
      ) : (
        <div className="rounded-3xl p-6 text-center text-sm" style={{ backgroundColor: 'var(--fog-2, #f7f7f8)', color: 'var(--text-secondary, #666)' }}>
          Waiting for the conversation to start… your persona is taking notes.
        </div>
      )}

      {meetLink && (
        <a href={meetLink} target="_blank" rel="noreferrer" className="inline-block rounded-xl px-4 py-2 text-sm font-semibold text-white" style={{ backgroundColor: 'var(--brand-primary, #0066cc)' }}>
          Join meeting
        </a>
      )}
    </div>
  );
}
