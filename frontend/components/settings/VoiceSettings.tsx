'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { Mic } from 'lucide-react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';
import { useTwin } from '@/lib/context/TwinContext';
import VoiceCloneSection from './VoiceCloneSection';

interface VoiceSettingsProps {
  twinId: string;
  twinName?: string;
}

const MEETING_VOICES = [
  { value: 'Puck', label: 'Puck', description: 'Bright and upbeat' },
  { value: 'Charon', label: 'Charon', description: 'Steady and grounded' },
  { value: 'Kore', label: 'Kore', description: 'Balanced default' },
  { value: 'Fenrir', label: 'Fenrir', description: 'Direct and confident' },
  { value: 'Aoede', label: 'Aoede', description: 'Warm and expressive' },
  { value: 'Leda', label: 'Leda', description: 'Clear and calm' },
  { value: 'Orus', label: 'Orus', description: 'Polished and composed' },
  { value: 'Zephyr', label: 'Zephyr', description: 'Light and conversational' },
] as const;

type SaveState = 'idle' | 'saving' | 'saved' | 'error';

export default function VoiceSettings({ twinId, twinName }: VoiceSettingsProps) {
  const apiBase = resolveApiBaseUrl();
  const { activeTwin, refreshTwins } = useTwin();
  const [selectedVoice, setSelectedVoice] = useState<string>('Kore');
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [saveError, setSaveError] = useState<string | null>(null);

  const currentSettings = useMemo(() => {
    if (!activeTwin || activeTwin.id !== twinId) return {};
    return (activeTwin.settings || {}) as Record<string, unknown>;
  }, [activeTwin, twinId]);

  useEffect(() => {
    const currentVoice = typeof currentSettings.gemini_voice === 'string'
      ? currentSettings.gemini_voice
      : 'Kore';
    setSelectedVoice(currentVoice);
  }, [currentSettings]);

  const saveMeetingVoice = async () => {
    setSaveState('saving');
    setSaveError(null);

    try {
      const nextSettings = {
        ...currentSettings,
        gemini_voice: selectedVoice,
      };

      const response = await authFetchStandalone(`${apiBase}/twins/${twinId}`, {
        method: 'PATCH',
        body: JSON.stringify({ settings: nextSettings }),
      });

      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || 'Failed to save meeting voice');
      }

      await refreshTwins();
      setSaveState('saved');
      window.setTimeout(() => setSaveState('idle'), 1500);
    } catch (error) {
      setSaveState('error');
      setSaveError(error instanceof Error ? error.message : 'Failed to save meeting voice');
    }
  };

  const selectedVoiceDetails = MEETING_VOICES.find((voice) => voice.value === selectedVoice) ?? MEETING_VOICES[2];

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold" style={{ color: 'var(--text-primary)' }}>Voice</h3>
        <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>
          Manage the cloned voice used for chat audio and live calls. Meeting bot voice is separate.
        </p>
      </div>

      <VoiceCloneSection twinId={twinId} twinName={twinName} />

      <div
        className="rounded-3xl p-6"
        style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
      >
        <div className="flex items-start gap-4">
          <div
            className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl"
            style={{ backgroundColor: 'var(--accent-trust-light)', color: 'var(--accent-trust-dark)' }}
          >
            <Mic className="h-6 w-6" strokeWidth={1.5} aria-hidden="true" />
          </div>

          <div className="flex-1">
            <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>Meeting Bot Voice</h3>
            <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary)' }}>
              Used only when your persona joins meetings and speaks on your behalf.
            </p>

            <div className="mt-4 max-w-xl">
              <div>
                <label className="mb-2 block text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>
                  Voice
                </label>
                <select
                  value={selectedVoice}
                  onChange={(event) => setSelectedVoice(event.target.value)}
                  className="w-full rounded-xl px-4 py-3 text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--primary-500)]"
                  style={{
                    border: '1px solid var(--border-subtle)',
                    backgroundColor: 'var(--bg-elevated)',
                    color: 'var(--text-primary)',
                  }}
                >
                  {MEETING_VOICES.map((voice) => (
                    <option key={voice.value} value={voice.value}>
                      {voice.label} - {voice.description}
                    </option>
                  ))}
                </select>
                <p className="mt-2 text-xs" style={{ color: 'var(--text-muted)' }}>
                  Current selection: {selectedVoiceDetails.label}. {selectedVoiceDetails.description}.
                </p>
              </div>
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={saveMeetingVoice}
                disabled={saveState === 'saving'}
                className="inline-flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60 cursor-pointer"
                style={{ background: 'linear-gradient(135deg, var(--brand-primary), var(--brand-secondary))' }}
              >
                {saveState === 'saving' ? 'Saving...' : 'Save Meeting Bot Voice'}
              </button>

              {saveState === 'saved' && (
                <span className="text-sm" style={{ color: 'var(--accent-emerald)' }}>
                  Saved
                </span>
              )}
            </div>

            {saveError && (
              <p className="mt-2 text-sm text-red-600">{saveError}</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
