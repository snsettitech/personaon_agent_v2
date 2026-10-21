'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { motion } from 'framer-motion';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';

interface VoiceCloneSectionProps {
  twinId: string;
  twinName?: string;
}

function VoiceChannelStatus({
  label,
  detail,
  tone = 'ready',
}: {
  label: string;
  detail: string;
  tone?: 'ready' | 'separate';
}) {
  const isReady = tone === 'ready';

  return (
    <div
      className="rounded-2xl px-3 py-2.5"
      style={{
        backgroundColor: isReady ? 'var(--accent-emerald-light)' : 'var(--bg-elevated)',
        border: `1px solid ${isReady ? 'var(--accent-emerald)' : 'var(--border-subtle)'}`,
      }}
    >
      <div className="flex items-center gap-2">
        <span
          className="h-2 w-2 rounded-full"
          style={{ backgroundColor: isReady ? 'var(--accent-emerald)' : 'var(--text-muted)' }}
          aria-hidden="true"
        />
        <p className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>
          {label}
        </p>
      </div>
      <p className="mt-1 text-xs leading-5" style={{ color: 'var(--text-secondary)' }}>
        {detail}
      </p>
    </div>
  );
}

export default function VoiceCloneSection({ twinId, twinName }: VoiceCloneSectionProps) {
  const apiBase = resolveApiBaseUrl();
  const [voiceStatus, setVoiceStatus] = useState<{ cloned: boolean; voice_id?: string; voice_name?: string } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [recording, setRecording] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await authFetchStandalone(`${apiBase}/v2/voice/${twinId}/status`);
      if (res.ok) setVoiceStatus(await res.json() as { cloned: boolean; voice_id?: string; voice_name?: string });
    } catch { /* ignore */ }
  }, [apiBase, twinId]);

  useEffect(() => { void fetchStatus(); }, [fetchStatus]);

  useEffect(() => {
    return () => {
      previewAudioRef.current?.pause();
      previewAudioRef.current = null;
    };
  }, []);

  const uploadAudio = async (file: Blob, filename: string) => {
    setUploading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append('audio', file, filename);
      const res = await authFetchStandalone(`${apiBase}/v2/voice/${twinId}/clone`, { method: 'POST', body: formData });
      if (res.ok) {
        const data = await res.json() as { voice_id: string; voice_name: string };
        setVoiceStatus({ cloned: true, voice_id: data.voice_id, voice_name: data.voice_name });
      } else {
        const errData = await res.json().catch(() => ({ detail: 'Upload failed' })) as { detail: string };
        setError(errData.detail || 'Voice cloning failed');
      }
    } catch {
      setError('Network error during upload');
    } finally {
      setUploading(false);
    }
  };

  const playVoicePreview = async () => {
    if (!voiceStatus?.cloned) return;

    setPreviewing(true);
    setError(null);
    previewAudioRef.current?.pause();
    previewAudioRef.current = null;

    try {
      const res = await authFetchStandalone(`${apiBase}/v2/voice/${twinId}/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: 'Hi, this is a preview of my cloned voice. This is how I can sound when I answer people in chat.',
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({ detail: 'Voice preview failed' })) as { detail?: string };
        throw new Error(errData.detail || 'Voice preview failed');
      }

      const audioUrl = URL.createObjectURL(await res.blob());
      const audio = new Audio(audioUrl);
      previewAudioRef.current = audio;
      audio.onended = () => {
        URL.revokeObjectURL(audioUrl);
        if (previewAudioRef.current === audio) previewAudioRef.current = null;
        setPreviewing(false);
      };
      audio.onerror = () => {
        URL.revokeObjectURL(audioUrl);
        if (previewAudioRef.current === audio) previewAudioRef.current = null;
        setPreviewing(false);
        setError('Voice preview failed');
      };
      await audio.play();
    } catch (err) {
      setPreviewing(false);
      setError(err instanceof Error ? err.message : 'Voice preview failed');
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) void uploadAudio(file, file.name);
  };

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      mediaRecorderRef.current = mediaRecorder;
      chunksRef.current = [];
      mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      mediaRecorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        stream.getTracks().forEach(t => t.stop());
        void uploadAudio(blob, 'voice-recording.webm');
      };
      mediaRecorder.start();
      setRecording(true);
    } catch {
      setError('Microphone access denied');
    }
  };

  const stopRecording = () => { mediaRecorderRef.current?.stop(); setRecording(false); };
  const handleDelete = async () => {
    try {
      await authFetchStandalone(`${apiBase}/v2/voice/${twinId}/clone`, { method: 'DELETE' });
      setVoiceStatus({ cloned: false });
    } catch { /* ignore */ }
  };

  return (
    <div
      className="rounded-3xl p-6"
      style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
    >
      <div className="flex items-start gap-4">
        <div
          className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl"
          style={{ backgroundColor: 'var(--accent-trust-light)', color: 'var(--accent-trust-dark)' }}
        >
          <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 18.75a6 6 0 006-6v-1.5m-6 7.5a6 6 0 01-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 01-3-3V4.5a3 3 0 116 0v8.25a3 3 0 01-3 3z" />
          </svg>
        </div>
        <div className="flex-1">
          <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>Voice Cloning</h3>

          {voiceStatus?.cloned ? (
            <div className="mt-2">
              <div className="flex items-center gap-2">
                <span
                  className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium"
                  style={{ backgroundColor: 'var(--accent-emerald-light)', color: 'var(--accent-emerald)' }}
                >
                  <svg className="h-3 w-3" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clipRule="evenodd" />
                  </svg>
                  Voice ready
                </span>
                {voiceStatus.voice_name && (
                  <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{voiceStatus.voice_name}</span>
                )}
              </div>
              <p className="mt-2 text-sm" style={{ color: 'var(--text-secondary)' }}>
                Chat audio and live calls use this cloned voice. Meeting bot voice is configured separately.
              </p>
              <div className="mt-4 grid gap-2 sm:grid-cols-3">
                <VoiceChannelStatus
                  label="Chat audio"
                  detail="Assistant playback uses this clone."
                />
                <VoiceChannelStatus
                  label="Live calls"
                  detail="The Call button speaks with this clone."
                />
                <VoiceChannelStatus
                  label="Meeting bot"
                  detail="Uses the Gemini voice setting below."
                  tone="separate"
                />
              </div>
              <div className="mt-4 flex flex-wrap gap-3">
                <button
                  onClick={playVoicePreview}
                  disabled={previewing}
                  className="inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold text-white transition-colors disabled:opacity-60 cursor-pointer"
                  style={{ backgroundColor: 'var(--primary-600)' }}
                >
                  <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
                  {previewing ? 'Playing...' : 'Play voice preview'}
                </button>
                <button
                  onClick={handleDelete}
                  className="inline-flex items-center rounded-xl px-4 py-2.5 text-sm font-medium transition-colors cursor-pointer"
                  style={{ border: '1px solid var(--border-subtle)', color: 'var(--text-secondary)', backgroundColor: 'var(--bg-elevated)' }}
                >
                  Remove voice clone
                </button>
              </div>
            </div>
          ) : (
            <>
              <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary)' }}>
                Record or upload 30-60 seconds of your voice. Your persona will speak in your voice.
              </p>

              {recording ? (
                <div className="mt-4 space-y-4">
                  <div className="rounded-2xl p-4" style={{ backgroundColor: 'var(--accent-trust-light)', border: '1px solid var(--border-trust)' }}>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--accent-trust-dark)' }}>Read this aloud</span>
                      <span className="inline-flex items-center gap-1.5 text-sm font-mono font-bold text-red-600">
                        <span className="h-2 w-2 rounded-full bg-red-500 animate-pulse" />
                        Recording
                      </span>
                    </div>
                    <p className="text-sm leading-relaxed" style={{ color: 'var(--text-primary)' }}>
                      Hi, I am {twinName || 'a professional'} and this is how I naturally speak. I believe in building meaningful connections through authentic conversations. When someone asks me a question, I like to take a moment to think about it and give a thoughtful, genuine response. My approach is always to be direct, honest, and helpful.
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <button
                      onClick={stopRecording}
                      className="inline-flex items-center gap-2 rounded-xl bg-red-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-red-700 transition-colors cursor-pointer"
                    >
                      <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>
                      Stop &amp; Clone
                    </button>
                    <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Read naturally at your own pace</span>
                  </div>
                </div>
              ) : (
                <div className="mt-4 space-y-3">
                  <div className="flex flex-wrap gap-3">
                    <motion.button
                      onClick={startRecording}
                      disabled={uploading}
                      className="inline-flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-50 cursor-pointer"
                      style={{ background: 'linear-gradient(135deg, var(--brand-primary), var(--brand-secondary))' }}
                      whileHover={{ scale: 1.03 }}
                      whileTap={{ scale: 0.97 }}
                    >
                      <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" /></svg>
                      Record Voice
                    </motion.button>
                    <label className={`inline-flex cursor-pointer items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium transition-colors ${uploading ? 'opacity-50 pointer-events-none' : ''}`}
                      style={{ border: '1px solid var(--border-default)', color: 'var(--text-secondary)', backgroundColor: 'var(--bg-elevated)' }}
                    >
                      <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" /></svg>
                      Upload Audio
                      <input type="file" accept="audio/*" onChange={handleFileUpload} className="hidden" />
                    </label>
                  </div>
                  <p className="text-xs" style={{ color: 'var(--text-muted)' }}>A guided reading prompt will appear when you start recording.</p>
                </div>
              )}

              {uploading && (
                <div className="mt-3 flex items-center gap-2 text-sm" style={{ color: 'var(--brand-primary)' }}>
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-t-transparent" style={{ borderColor: 'var(--brand-primary)', borderTopColor: 'transparent' }} />
                  Cloning your voice…
                </div>
              )}
            </>
          )}

          {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
        </div>
      </div>
    </div>
  );
}
