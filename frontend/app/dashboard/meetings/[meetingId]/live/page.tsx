'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useSearchParams, useRouter } from 'next/navigation';
import { resolveApiBaseUrl } from '@/lib/api';
import { authFetchStandalone, getAuthToken } from '@/lib/hooks/useAuthFetch';
import LiveTranscript from '@/components/meetings/LiveTranscript';
import MeetingControlBar from '@/components/meetings/MeetingControlBar';
import type { TranscriptMessage } from '@/components/meetings/LiveTranscript';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TwinStatus = 'joining' | 'listening' | 'thinking' | 'speaking' | 'muted' | 'deferred' | 'left';

interface WsTranscriptEvent {
  type: 'transcript';
  speaker: string;
  text: string;
  timestamp: string;
}

interface WsTwinResponseEvent {
  type: 'twin_response';
  question: string;
  response: string;
  confidence: number;
  sources: Array<{ text: string; source_id?: string }>;
  is_deferral: boolean;
}

interface WsTwinStatusEvent {
  type: 'twin_status';
  status: TwinStatus;
}

interface WsErrorEvent {
  type: 'error';
  message: string;
}

type WsEvent = WsTranscriptEvent | WsTwinResponseEvent | WsTwinStatusEvent | WsErrorEvent;

// ---------------------------------------------------------------------------
// Status badge config
// ---------------------------------------------------------------------------

const STATUS_BADGE_CONFIG: Record<string, { label: string; bg: string; color: string }> = {
  joining:   { label: 'Joining...',     bg: 'var(--primary-50)',          color: 'var(--primary-700)' },
  listening: { label: 'Persona Active', bg: 'var(--accent-emerald-light)', color: 'var(--accent-emerald)' },
  thinking:  { label: 'Persona Active', bg: 'var(--accent-emerald-light)', color: 'var(--accent-emerald)' },
  speaking:  { label: 'Persona Speaking', bg: 'var(--primary-50)',        color: 'var(--primary-500)' },
  muted:     { label: 'Persona Muted',  bg: 'var(--accent-red-light)',    color: 'var(--accent-red)' },
  deferred:  { label: 'Deferred',       bg: 'var(--accent-trust-light)',  color: 'var(--accent-trust-dark)' },
  left:      { label: 'Persona Left',   bg: 'var(--bg-surface)',          color: 'var(--text-muted)' },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return [h, m, s].map((v) => String(v).padStart(2, '0')).join(':');
}

function buildWsUrl(apiBase: string, meetingId: string): string {
  const wsBase = apiBase.replace(/^http/, 'ws');
  return `${wsBase}/ws/meeting/${meetingId}/live`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function LiveMeetingPage(): React.JSX.Element {
  const params = useParams();
  const searchParams = useSearchParams();
  const router = useRouter();

  const meetingId = params['meetingId'] as string;
  const twinId = searchParams.get('twin') ?? '';

  const [messages, setMessages] = useState<TranscriptMessage[]>([]);
  const [twinStatus, setTwinStatus] = useState<TwinStatus>('joining');
  const [isMuted, setIsMuted] = useState(false);
  const [meetingTitle, setMeetingTitle] = useState('Meeting');
  // Defaults to "now" so the timer runs immediately, then is corrected to the
  // real meeting_start once loadMeeting resolves — otherwise the elapsed clock
  // counts from when the page was opened, not when the meeting began.
  const [startTime, setStartTime] = useState<Date>(() => new Date());
  const [elapsed, setElapsed] = useState(0);
  const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting');
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const messageIdRef = useRef(0);
  const connectWsRef = useRef<() => void>(() => undefined);
  // Guards the async token fetch: if the component unmounts before the socket
  // is created, we must not open a leaked WebSocket.
  const activeRef = useRef(false);

  // Duration timer
  useEffect(() => {
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTime.getTime()) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [startTime]);

  // Fetch meeting title + status. If the meeting is no longer live (completed,
  // failed, or cancelled), redirect to the detail page immediately — the WS
  // endpoint would just refuse the connection and trigger an infinite
  // "Reconnecting..." loop.
  useEffect(() => {
    if (!twinId || !meetingId) return;
    const apiBase = resolveApiBaseUrl();

    async function loadMeeting() {
      try {
        const res = await authFetchStandalone(`${apiBase}/v2/meetings/${twinId}/${meetingId}`);
        if (res.ok) {
          const body = await res.json() as { data: { title: string | null; status: string; meeting_start?: string | null } };
          if (body.data.title) {
            setMeetingTitle(body.data.title);
          }
          if (body.data.meeting_start) {
            const ms = new Date(body.data.meeting_start);
            if (!Number.isNaN(ms.getTime())) {
              setStartTime(ms);
            }
          }
          const terminalStatuses = ['completed', 'failed', 'cancelled'];
          if (terminalStatuses.includes(body.data.status)) {
            router.replace(`/dashboard/meetings/${meetingId}`);
            return;
          }
        }
      } catch {
        // Non-fatal — keep default title
      }
    }

    void loadMeeting();
  }, [twinId, meetingId, router]);

  // WebSocket connection
  const connectWs = useCallback(() => {
    if (!meetingId) return;

    setConnectionStatus('connecting');

    // The backend live WS (meeting_voice.py:meeting_live_ws) closes with 4001 when
    // the `token` query param is missing. This page historically opened the socket
    // with no token, so auth failed instantly and the user saw a permanent
    // "connection lost / may have ended" — even while the meeting was live. Fetch
    // the Supabase JWT first and append it as ?token=.
    void (async () => {
      const token = await getAuthToken();
      if (!activeRef.current) return; // unmounted during the await
      if (!token) {
        setError('You are signed out — reload to resume the live transcript.');
        setConnectionStatus('disconnected');
        return;
      }

      const apiBase = resolveApiBaseUrl();
      const url = `${buildWsUrl(apiBase, meetingId)}?token=${encodeURIComponent(token)}`;

      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
      setConnectionStatus('connected');
      setError(null);
      reconnectAttemptRef.current = 0;

      // Keepalive ping every 30s
      pingTimerRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }));
        }
      }, 30000);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string) as WsEvent;

        switch (data.type) {
          case 'transcript': {
            const id = String(++messageIdRef.current);
            setMessages((prev) => [
              ...prev,
              {
                id,
                speaker: data.speaker,
                text: data.text,
                timestamp: data.timestamp,
                isTwin: false,
              },
            ]);
            break;
          }
          case 'twin_response': {
            const id = String(++messageIdRef.current);
            setMessages((prev) => [
              ...prev,
              {
                id,
                speaker: 'Persona',
                text: data.is_deferral ? data.response : data.response,
                timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                isTwin: true,
                confidence: data.confidence,
                isDeferral: data.is_deferral,
              },
            ]);
            break;
          }
          case 'twin_status': {
            setTwinStatus(data.status as TwinStatus);
            if (data.status === 'muted') {
              setIsMuted(true);
            } else if (data.status === 'listening' || data.status === 'speaking') {
              setIsMuted(false);
            }
            break;
          }
          case 'error': {
            setError(data.message);
            break;
          }
        }
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = (event) => {
      setConnectionStatus('disconnected');
      if (pingTimerRef.current) {
        clearInterval(pingTimerRef.current);
        pingTimerRef.current = null;
      }
      // Unmounting (or deps changed): don't schedule a reconnect or set state on
      // an unmounted component. The cleanup effect already closed the socket.
      if (!activeRef.current) return;

      // Server-initiated close codes that mean "do not reconnect":
      //   1000 normal closure, 1008 policy violation (auth/ownership),
      //   4000-4999 application-defined (we reserve these for "meeting ended").
      const terminalCode = event.code === 1000 || event.code === 1008 || (event.code >= 4000 && event.code <= 4999);

      // Cap reconnect attempts so a dead meeting doesn't loop forever. After
      // MAX_RECONNECT_ATTEMPTS the banner stays on "disconnected" without
      // scheduling another try — the user sees a stable state, not churn.
      const MAX_RECONNECT_ATTEMPTS = 5;
      if (terminalCode || reconnectAttemptRef.current >= MAX_RECONNECT_ATTEMPTS) {
        setError('Live connection lost. This meeting may have ended — reload to see the final transcript.');
        return;
      }

      // Exponential backoff reconnect: 1s, 2s, 4s, max 10s
      const delay = Math.min(1000 * Math.pow(2, reconnectAttemptRef.current), 10000);
      reconnectAttemptRef.current += 1;

      reconnectTimerRef.current = setTimeout(() => {
        connectWsRef.current();
      }, delay);
    };

    ws.onerror = () => {
      // onclose will fire after onerror, reconnect handled there
    };
    })();
  }, [meetingId]);

  useEffect(() => {
    connectWsRef.current = connectWs;
  }, [connectWs]);

  useEffect(() => {
    activeRef.current = true;
    connectWs();

    return () => {
      activeRef.current = false;
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      if (pingTimerRef.current) {
        clearInterval(pingTimerRef.current);
      }
    };
  }, [connectWs]);

  // Mute handler
  const handleMuteToggle = useCallback((muted: boolean) => {
    setIsMuted(muted);
    if (muted) {
      setTwinStatus('muted');
    } else {
      setTwinStatus('listening');
    }
  }, []);

  // Leave handler
  const handleLeave = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'leave' }));
    }
    router.push(`/dashboard/meetings/${meetingId}?twin=${twinId}`);
  }, [meetingId, twinId, router]);

  const badge = STATUS_BADGE_CONFIG[twinStatus] ?? STATUS_BADGE_CONFIG['joining'];

  return (
    <div
      className="flex flex-col"
      style={{ height: 'calc(100vh - 72px)', backgroundColor: 'var(--bg-base)' }}
    >
      {/* Status bar */}
      <div
        className="sticky top-0 flex items-center justify-between px-4 shrink-0"
        style={{
          backgroundColor: 'var(--bg-card)',
          borderBottom: '1px solid var(--border-subtle)',
          height: '56px',
          zIndex: 40,
        }}
      >
        <div className="flex items-center gap-3 min-w-0">
          <h1
            className="text-sm font-bold truncate"
            style={{ color: 'var(--text-primary)' }}
          >
            {meetingTitle}
          </h1>
          <span className="text-sm shrink-0" style={{ color: 'var(--text-secondary)' }}>
            {formatDuration(elapsed)}
          </span>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {/* Twin status badge */}
          <span
            className="inline-block rounded-full px-2.5 py-0.5 text-xs font-bold uppercase"
            style={{ backgroundColor: badge.bg, color: badge.color }}
          >
            {badge.label}
          </span>
        </div>
      </div>

      {/* Connection banner */}
      {connectionStatus === 'disconnected' && (
        <div
          className="px-4 py-2 text-sm text-center"
          style={{ backgroundColor: 'var(--accent-trust-light)', color: 'var(--accent-trust-dark)' }}
        >
          Live connection lost. Reconnecting...
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div
          className="px-4 py-2 text-sm text-center"
          style={{ backgroundColor: '#FEE2E2', color: '#991b1b' }}
        >
          {error}
        </div>
      )}

      {/* Live transcript */}
      <LiveTranscript messages={messages} />

      {/* Control bar (fixed bottom) */}
      <MeetingControlBar
        twinId={twinId}
        meetingId={meetingId}
        isMuted={isMuted}
        onMuteToggle={handleMuteToggle}
        onLeave={handleLeave}
      />

      {/* Spacer for fixed control bar */}
      <div className="shrink-0" style={{ height: '72px' }} />
    </div>
  );
}
