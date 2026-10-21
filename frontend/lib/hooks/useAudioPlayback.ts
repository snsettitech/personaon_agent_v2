'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { resolveApiBaseUrl } from '@/lib/api';

interface AudioState {
  isPlaying: boolean;
  isLoading: boolean;
  error: string | null;
}

// Global audio controller to prevent multiple simultaneous playbacks
let globalAudio: HTMLAudioElement | null = null;
let globalAudioUrl: string | null = null;

function cleanupGlobalAudio() {
  if (globalAudio) {
    globalAudio.pause();
    globalAudio.currentTime = 0;
    globalAudio = null;
  }
  if (globalAudioUrl) {
    URL.revokeObjectURL(globalAudioUrl);
    globalAudioUrl = null;
  }
}

export function useAudioPlayback(twinId?: string) {
  const [audioState, setAudioState] = useState<AudioState>({
    isPlaying: false,
    isLoading: false,
    error: null,
  });
  
  const currentTextRef = useRef<string | null>(null);
  const apiBaseUrl = resolveApiBaseUrl();

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      // Only cleanup if this instance started the current audio
      if (currentTextRef.current) {
        cleanupGlobalAudio();
      }
    };
  }, []);

  const stopAudio = useCallback(() => {
    cleanupGlobalAudio();
    currentTextRef.current = null;
    setAudioState({ isPlaying: false, isLoading: false, error: null });
  }, []);

  const playText = useCallback(async (text: string) => {
    // Stop any currently playing audio globally
    stopAudio();
    
    if (!twinId) {
      setAudioState({ isPlaying: false, isLoading: false, error: 'Twin ID not available' });
      return;
    }

    // Prevent double-clicks
    if (audioState.isLoading) return;

    currentTextRef.current = text;
    setAudioState({ isPlaying: false, isLoading: true, error: null });

    try {
      const response = await fetch(`${apiBaseUrl}/audio/tts/${twinId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Failed to generate audio (${response.status})`);
      }

      const audioBlob = await response.blob();
      const audioUrl = URL.createObjectURL(audioBlob);
      
      // Store globally for cleanup
      globalAudioUrl = audioUrl;
      
      const audio = new Audio(audioUrl);
      globalAudio = audio;
      
      audio.onended = () => {
        // Only update state if this is still the current audio
        if (currentTextRef.current === text) {
          setAudioState({ isPlaying: false, isLoading: false, error: null });
          currentTextRef.current = null;
        }
        URL.revokeObjectURL(audioUrl);
        if (globalAudioUrl === audioUrl) {
          globalAudioUrl = null;
        }
      };
      
      audio.onerror = () => {
        if (currentTextRef.current === text) {
          setAudioState({ isPlaying: false, isLoading: false, error: 'Failed to play audio' });
          currentTextRef.current = null;
        }
        URL.revokeObjectURL(audioUrl);
        if (globalAudioUrl === audioUrl) {
          globalAudioUrl = null;
        }
      };

      await audio.play();
      setAudioState({ isPlaying: true, isLoading: false, error: null });
      
    } catch (err) {
      // Only update error if this request is still current
      if (currentTextRef.current === text) {
        setAudioState({
          isPlaying: false,
          isLoading: false,
          error: err instanceof Error ? err.message : 'Failed to play audio',
        });
        currentTextRef.current = null;
      }
    }
  }, [twinId, apiBaseUrl, stopAudio, audioState.isLoading]);

  const togglePlayback = useCallback(async (text: string) => {
    // If already playing this text, stop it
    if (audioState.isPlaying && currentTextRef.current === text) {
      stopAudio();
    } else {
      await playText(text);
    }
  }, [audioState.isPlaying, stopAudio, playText]);

  return {
    ...audioState,
    playText,
    stopAudio,
    togglePlayback,
  };
}
