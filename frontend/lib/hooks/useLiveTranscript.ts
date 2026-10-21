'use client';

/**
 * useLiveTranscript — owns the live meeting WebSocket so any page can stream the
 * transcript. Extracted from the legacy /live page so the unified meeting page
 * can embed the live feed in-place (Littlefield-style one-page experience) rather
 * than navigating to a separate route.
 *
 * NOTE: unlike the legacy /live page, this hook appends the Supabase JWT as the
 * `?token=` query param. The backend WS (meeting_voice.py:685) closes with 4001
 * when the token is missing — the legacy page never sent one, so its live stream
 * always failed auth. This hook fixes that.
 *
 * Lifecycle: connects to `/ws/meeting/{id}/live?token=…`, keepalive ping every
 * 30s, capped exponential-backoff reconnect (max 5 attempts; terminal close codes
 * stop retrying), full cleanup on unmount. See docs/product/meetings-spec-and-plan.md.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { resolveApiBaseUrl } from '@/lib/api';
import { getAuthToken } from '@/lib/hooks/useAuthFetch';
import type { TranscriptMessage } from '@/components/meetings/LiveTranscript';

export type TwinStatus =
  | 'joining' | 'listening' | 'thinking' | 'speaking' | 'muted' | 'deferred' | 'left';

type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';

interface WsTranscriptEvent { type: 'transcript'; speaker: string; text: string; timestamp: string; }
interface WsTwinResponseEvent {
  type: 'twin_response';
  question: string;
  response: string;
  confidence: number;
  sources: Array<{ text: string; source_id?: string }>;
  is_deferral: boolean;
}
interface WsTwinStatusEvent { type: 'twin_status'; status: TwinStatus; }
interface WsErrorEvent { type: 'error'; message: string; }
type WsEvent = WsTranscriptEvent | WsTwinResponseEvent | WsTwinStatusEvent | WsErrorEvent;

function wsBase(apiBase: string): string {
  return apiBase.replace(/^http/, 'ws');
}

export interface UseLiveTranscript {
  messages: TranscriptMessage[];
  twinStatus: TwinStatus;
  isMuted: boolean;
  setMuted: (muted: boolean) => void;
  connectionStatus: ConnectionStatus;
  error: string | null;
}

/**
 * @param meetingId  the meeting to stream. When falsy the hook stays idle.
 * @param enabled    only connect when true (e.g. the meeting is live). Pass false
 *                   to keep the socket closed on non-live phases.
 */
export function useLiveTranscript(meetingId: string, enabled: boolean = true): UseLiveTranscript {
  const [messages, setMessages] = useState<TranscriptMessage[]>([]);
  const [twinStatus, setTwinStatus] = useState<TwinStatus>('joining');
  const [isMuted, setIsMuted] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('connecting');
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const messageIdRef = useRef(0);
  const connectWsRef = useRef<() => void>(() => undefined);
  // Guards the async token fetch: if the component unmounts (or deps change)
  // before the WebSocket is created, we must not open a leaked socket.
  const activeRef = useRef(false);

  const connectWs = useCallback(() => {
    if (!meetingId || !enabled) return;
    setConnectionStatus('connecting');

    void (async () => {
      const token = await getAuthToken();
      if (!activeRef.current) return; // unmounted during the await
      if (!token) {
        setError('You are signed out — reload to resume the live transcript.');
        setConnectionStatus('disconnected');
        return;
      }
      const url = `${wsBase(resolveApiBaseUrl())}/ws/meeting/${meetingId}/live?token=${encodeURIComponent(token)}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnectionStatus('connected');
        setError(null);
        reconnectAttemptRef.current = 0;
        pingTimerRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }));
        }, 30000);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data as string) as WsEvent;
          switch (data.type) {
            case 'transcript':
              setMessages((prev) => [...prev, {
                id: String(++messageIdRef.current),
                speaker: data.speaker, text: data.text, timestamp: data.timestamp, isTwin: false,
              }]);
              break;
            case 'twin_response':
              setMessages((prev) => [...prev, {
                id: String(++messageIdRef.current),
                speaker: 'Persona',
                text: data.response,
                timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                isTwin: true, confidence: data.confidence, isDeferral: data.is_deferral,
              }]);
              break;
            case 'twin_status':
              setTwinStatus(data.status);
              if (data.status === 'muted') setIsMuted(true);
              else if (data.status === 'listening' || data.status === 'speaking') setIsMuted(false);
              break;
            case 'error':
              setError(data.message);
              break;
          }
        } catch {
          // Ignore malformed frames.
        }
      };

      ws.onclose = (closeEvent) => {
        setConnectionStatus('disconnected');
        if (pingTimerRef.current) { clearInterval(pingTimerRef.current); pingTimerRef.current = null; }
        if (!activeRef.current) return; // unmounting — don't reconnect
        // Terminal close codes (1000 normal, 1008 auth/policy, 4000-4999 app "ended"
        // — includes 4001 "not authenticated") must NOT reconnect. Otherwise cap
        // attempts so a dead meeting can't loop forever.
        const terminal =
          closeEvent.code === 1000 || closeEvent.code === 1008 ||
          (closeEvent.code >= 4000 && closeEvent.code <= 4999);
        const MAX = 5;
        if (terminal || reconnectAttemptRef.current >= MAX) {
          setError('Live connection lost. This meeting may have ended — reload to see the final transcript.');
          return;
        }
        const delay = Math.min(1000 * Math.pow(2, reconnectAttemptRef.current), 10000);
        reconnectAttemptRef.current += 1;
        reconnectTimerRef.current = setTimeout(() => connectWsRef.current(), delay);
      };

      ws.onerror = () => {
        // onclose fires after onerror; reconnect handled there.
      };
    })();
  }, [meetingId, enabled]);

  useEffect(() => { connectWsRef.current = connectWs; }, [connectWs]);

  useEffect(() => {
    if (!meetingId || !enabled) return undefined;
    activeRef.current = true;
    connectWs();
    return () => {
      activeRef.current = false;
      if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (pingTimerRef.current) clearInterval(pingTimerRef.current);
      reconnectAttemptRef.current = 0;
    };
  }, [connectWs, meetingId, enabled]);

  return { messages, twinStatus, isMuted, setMuted: setIsMuted, connectionStatus, error };
}
