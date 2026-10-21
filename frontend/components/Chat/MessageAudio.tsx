'use client';

import React, { useCallback } from 'react';
import { resolveApiBaseUrl, getChatAuthToken } from '@/lib/api';

// ---------------------------------------------------------------------------
// Global audio controller — stops previous audio when new one starts
// ---------------------------------------------------------------------------

let activeAudio: HTMLAudioElement | null = null;
let activeObjectUrl: string | null = null;
let activeCleanupCallback: (() => void) | null = null;

function stopActiveAudio(): void {
  if (activeAudio) {
    activeAudio.pause();
    activeAudio.currentTime = 0;
    activeAudio = null;
  }
  if (activeObjectUrl) {
    URL.revokeObjectURL(activeObjectUrl);
    activeObjectUrl = null;
  }
  if (activeCleanupCallback) {
    activeCleanupCallback();
    activeCleanupCallback = null;
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface MessageAudioProps {
  text: string;
  twinId: string;
  /** If true, use public (unauthenticated) TTS endpoint */
  isPublic?: boolean;
}

export default function MessageAudio({ text, twinId, isPublic }: MessageAudioProps) {
  const [state, setState] = React.useState<'idle' | 'loading' | 'playing'>('idle');

  const handleClick = useCallback(async () => {
    // If already playing this instance, stop it
    if (state === 'playing') {
      stopActiveAudio();
      setState('idle');
      return;
    }

    // Stop any other playing audio first
    stopActiveAudio();

    if (state === 'loading') return;
    setState('loading');

    try {
      const apiBase = resolveApiBaseUrl();
      const endpoint = isPublic
        ? `${apiBase}/v2/voice/${twinId}/tts/public`
        : `${apiBase}/v2/voice/${twinId}/tts`;

      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (!isPublic) {
        const token = await getChatAuthToken();
        if (!token) { setState('idle'); return; }
        headers['Authorization'] = `Bearer ${token}`;
      }

      const response = await fetch(endpoint, {
        method: 'POST',
        headers,
        body: JSON.stringify({ text }),
      });

      if (!response.ok) {
        throw new Error(`TTS failed (${response.status})`);
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);

      // Register as active
      activeAudio = audio;
      activeObjectUrl = url;
      activeCleanupCallback = () => setState('idle');

      audio.onended = () => {
        if (activeAudio === audio) {
          activeAudio = null;
          activeCleanupCallback = null;
        }
        URL.revokeObjectURL(url);
        if (activeObjectUrl === url) activeObjectUrl = null;
        setState('idle');
      };

      audio.onerror = () => {
        if (activeAudio === audio) {
          activeAudio = null;
          activeCleanupCallback = null;
        }
        URL.revokeObjectURL(url);
        if (activeObjectUrl === url) activeObjectUrl = null;
        setState('idle');
      };

      await audio.play();
      setState('playing');
    } catch {
      setState('idle');
    }
  }, [text, twinId, isPublic, state]);

  return (
    <button
      onClick={handleClick}
      disabled={state === 'loading'}
      aria-label={state === 'playing' ? 'Stop audio' : 'Listen to response'}
      title={state === 'playing' ? 'Stop' : 'Listen'}
      className={`inline-flex items-center justify-center w-7 h-7 rounded-full transition-all cursor-pointer ${
        state === 'playing'
          ? 'bg-[#eef5ff] text-[#0066cc]'
          : state === 'loading'
            ? 'bg-[#eef5ff] text-[#4f8fe8] animate-pulse'
            : 'text-slate-400 hover:text-[#0066cc] hover:bg-[#eef5ff]'
      }`}
    >
      {state === 'loading' ? (
        /* Spinner */
        <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      ) : state === 'playing' ? (
        /* Playing — waveform bars (CSS animated) */
        <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
          <rect x="1" y="5" width="2" height="6" rx="1" className="animate-voice-bar-1" />
          <rect x="5" y="3" width="2" height="10" rx="1" className="animate-voice-bar-2" />
          <rect x="9" y="4" width="2" height="8" rx="1" className="animate-voice-bar-3" />
          <rect x="13" y="5" width="2" height="6" rx="1" className="animate-voice-bar-1" />
        </svg>
      ) : (
        /* Idle — speaker icon */
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="2"
            d="M15.536 8.464a5 5 0 010 7.072M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z"
          />
        </svg>
      )}
    </button>
  );
}

/**
 * Programmatically trigger TTS playback for auto-play feature.
 * Returns a cleanup function to stop audio.
 */
export function autoPlayTTS(text: string, twinId: string, isPublic?: boolean): () => void {
  stopActiveAudio();

  const apiBase = resolveApiBaseUrl();
  const endpoint = isPublic
    ? `${apiBase}/v2/voice/${twinId}/tts/public`
    : `${apiBase}/v2/voice/${twinId}/tts`;

  const abortController = new AbortController();

  const tokenPromise = isPublic ? Promise.resolve(null) : getChatAuthToken();

  tokenPromise
    .then((token) => {
      if (!isPublic && !token) return undefined;
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;
      return fetch(endpoint, {
        method: 'POST',
        headers,
        body: JSON.stringify({ text }),
        signal: abortController.signal,
      });
    })
    .then((response) => {
      if (!response || !response.ok) return;
      return response.blob();
    })
    .then((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      activeAudio = audio;
      activeObjectUrl = url;
      activeCleanupCallback = null;
      audio.onended = () => {
        URL.revokeObjectURL(url);
        if (activeAudio === audio) activeAudio = null;
        if (activeObjectUrl === url) activeObjectUrl = null;
      };
      audio.onerror = () => {
        URL.revokeObjectURL(url);
        if (activeAudio === audio) activeAudio = null;
        if (activeObjectUrl === url) activeObjectUrl = null;
      };
      audio.play().catch(() => {});
    })
    .catch(() => {});

  return () => {
    abortController.abort();
    stopActiveAudio();
  };
}
