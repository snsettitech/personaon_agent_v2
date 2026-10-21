'use client';

import { useCallback, useEffect, useState } from 'react';

import { useToast } from '@/components/ui';
import { PUBLIC_SITE_URL } from '@/lib/constants';
import { isRuntimeFeatureEnabled } from '@/lib/features/runtimeFlags';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import {
  ACCENT_HEX,
  ACCENT_IDS,
  DEFAULT_ACCENT_FOR,
  isAccent,
  isThemeId,
  type AccentId,
  type ThemeId,
} from '@/lib/persona-themes';

interface ThemeOption {
  id: ThemeId;
  name: string;
  description: string;
  badge?: string;
}

// Owner-facing labels. Order mirrors THEME_IDS but `site` is featured first.
const THEME_OPTIONS: readonly ThemeOption[] = [
  { id: 'site', name: 'Site', description: 'A full premium website', badge: 'New' },
  { id: 'classic', name: 'Classic', description: 'Clean card layout (default)' },
  { id: 'editorial', name: 'Editorial', description: 'Broadsheet portfolio' },
  { id: 'founder-site', name: 'Founder', description: 'Bold personal site' },
  { id: 'conversion-warm', name: 'Conversion', description: 'Warm landing page' },
  { id: 'split', name: 'Split', description: 'Sidebar layout' },
];

const accentLabel = (accent: AccentId): string => accent.charAt(0).toUpperCase() + accent.slice(1);

export function ThemePicker() {
  const { showToast } = useToast();
  const themesLive = isRuntimeFeatureEnabled('personaThemes');

  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [handle, setHandle] = useState<string>('');

  // Baseline = last saved server state; selected = pending local choice.
  const [savedTheme, setSavedTheme] = useState<ThemeId>('classic');
  const [savedAccent, setSavedAccent] = useState<AccentId | null>(null);
  const [selectedTheme, setSelectedTheme] = useState<ThemeId>('classic');
  const [selectedAccent, setSelectedAccent] = useState<AccentId | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setIsLoading(true);
      setLoadError(false);
      try {
        const res = await authFetchStandalone('/profile');
        if (!res.ok) throw new Error(`Request failed (${res.status})`);
        const data: unknown = await res.json();
        if (cancelled) return;
        const obj = data && typeof data === 'object' ? (data as Record<string, unknown>) : {};
        const theme: ThemeId = isThemeId(obj.theme_id) ? obj.theme_id : 'classic';
        const accent: AccentId | null = isAccent(obj.accent) ? obj.accent : null;
        setHandle(typeof obj.handle === 'string' ? obj.handle : '');
        setSavedTheme(theme);
        setSavedAccent(accent);
        setSelectedTheme(theme);
        setSelectedAccent(accent);
      } catch (error) {
        if (cancelled) return;
        console.error('[ThemePicker] Failed to load profile:', error);
        setLoadError(true);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const hasUnsavedChanges = selectedTheme !== savedTheme || selectedAccent !== savedAccent;
  // Classic renders wrapper-free, so accent has no effect there.
  const accentApplies = selectedTheme !== 'classic';
  const effectiveAccent: AccentId = selectedAccent ?? DEFAULT_ACCENT_FOR[selectedTheme];

  const previewUrl = handle
    ? `${PUBLIC_SITE_URL.replace(/\/$/, '')}/p/${encodeURIComponent(handle)}?theme=${selectedTheme}`
    : '';

  const handleSave = useCallback(async () => {
    if (isSaving) return;  // always saveable; the status indicator conveys saved/unsaved
    setIsSaving(true);
    try {
      const res = await authFetchStandalone('/profile', {
        method: 'PATCH',
        body: JSON.stringify({ theme_id: selectedTheme, accent: selectedAccent ?? null }),
      });
      if (!res.ok) throw new Error(`Request failed (${res.status})`);
      setSavedTheme(selectedTheme);
      setSavedAccent(selectedAccent);
      showToast('Layout saved.', 'success');
    } catch (error) {
      console.error('[ThemePicker] Failed to save layout:', error);
      showToast("Couldn't save your layout. Please try again.", 'error');
    } finally {
      setIsSaving(false);
    }
  }, [isSaving, selectedAccent, selectedTheme, showToast]);

  if (isLoading) {
    return (
      <div className="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
        <p className="text-sm text-slate-500">Loading layout options…</p>
      </div>
    );
  }

  return (
    <div className="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Layout</h2>
          <p className="mt-1 text-sm text-slate-500">
            Choose how your public persona page looks. Preview before you publish.
          </p>
        </div>
      </div>

      {loadError && (
        <p className="mt-4 text-sm text-rose-600">
          Couldn&apos;t load your current layout. You can still pick one and save it.
        </p>
      )}

      {!themesLive && (
        <p className="mt-4 rounded-2xl bg-slate-50 px-4 py-3 text-xs leading-5 text-slate-500">
          Layouts are rolling out — your selection is saved and your preview works; your live page
          will switch over once layouts are enabled.
        </p>
      )}

      {/* Theme grid */}
      <fieldset className="mt-5">
        <legend className="sr-only">Public page layout</legend>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {THEME_OPTIONS.map((option) => {
            const isSelected = option.id === selectedTheme;
            return (
              <button
                key={option.id}
                type="button"
                onClick={() => setSelectedTheme(option.id)}
                aria-pressed={isSelected}
                className={`flex flex-col rounded-2xl border p-4 text-left transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0066cc] focus-visible:ring-offset-2 ${
                  isSelected
                    ? 'border-[#0066cc] bg-[rgba(0,102,204,0.06)] shadow-sm'
                    : 'border-slate-200 bg-white hover:border-slate-300'
                }`}
              >
                <span className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-slate-900">{option.name}</span>
                  {option.badge && (
                    <span className="rounded-full bg-[#0066cc] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white">
                      {option.badge}
                    </span>
                  )}
                  {isSelected && (
                    <span className="ml-auto text-xs font-semibold text-[#0066cc]">Selected</span>
                  )}
                </span>
                <span className="mt-1 text-xs leading-5 text-slate-500">{option.description}</span>
              </button>
            );
          })}
        </div>
      </fieldset>

      {/* Accent swatches (hidden for Classic — it renders wrapper-free) */}
      {accentApplies && (
        <fieldset className="mt-6">
          <legend className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
            Accent
          </legend>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {ACCENT_IDS.map((accent) => {
              const isSelected = selectedAccent === accent;
              const isFallback = selectedAccent === null && accent === effectiveAccent;
              return (
                <button
                  key={accent}
                  type="button"
                  onClick={() => setSelectedAccent(accent)}
                  aria-pressed={isSelected}
                  aria-label={`${accentLabel(accent)}${isFallback ? ' (default for this layout)' : ''}`}
                  title={accentLabel(accent)}
                  className={`h-8 w-8 rounded-full border-2 transition-transform focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0066cc] focus-visible:ring-offset-2 ${
                    isSelected || isFallback
                      ? 'border-slate-900 scale-110'
                      : 'border-transparent hover:scale-105'
                  }`}
                  style={{ backgroundColor: ACCENT_HEX[accent] }}
                />
              );
            })}
            {selectedAccent !== null && (
              <button
                type="button"
                onClick={() => setSelectedAccent(null)}
                className="ml-1 rounded-full px-2 py-1 text-xs font-medium text-slate-500 underline-offset-2 hover:text-slate-700 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0066cc]"
              >
                Use default
              </button>
            )}
          </div>
          {selectedAccent === null && (
            <p className="mt-2 text-xs text-slate-400">
              Using the default accent ({accentLabel(effectiveAccent)}) for this layout.
            </p>
          )}
        </fieldset>
      )}

      {/* Actions */}
      <div className="mt-6 flex flex-wrap items-center gap-3">
        {/* Inline bg/color on purpose: a global glass `button` rule in globals.css
            overrides Tailwind `bg-slate-950`, which made the enabled (white-text)
            button render white-on-white = invisible. Inline styles win (same trick
            the accent swatches use). Always clickable so it never looks grayed/broken. */}
        <button
          type="button"
          onClick={() => void handleSave()}
          disabled={isSaving}
          style={{ backgroundColor: '#0f172a', color: '#ffffff' }}
          className="rounded-2xl px-5 py-2.5 text-sm font-semibold transition-opacity hover:opacity-90 disabled:opacity-60 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0066cc] focus-visible:ring-offset-2"
        >
          {isSaving ? 'Saving…' : 'Save & Publish'}
        </button>
        {previewUrl ? (
          <a
            href={previewUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-2xl border border-slate-200 bg-white px-5 py-2.5 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0066cc] focus-visible:ring-offset-2"
          >
            Preview
          </a>
        ) : (
          <span
            aria-disabled="true"
            className="cursor-not-allowed rounded-2xl border border-slate-200 bg-slate-50 px-5 py-2.5 text-sm font-semibold text-slate-400"
            title="Set a handle to preview your page"
          >
            Preview
          </span>
        )}

        {/* Save status — keep the "Save & Publish" action always visible and label
            the state separately, so the button never masquerades as a dead "Saved"
            pill (which read as "there is no save button"). */}
        <span
          className="ml-auto inline-flex items-center gap-1.5 text-xs font-medium"
          role="status"
          aria-live="polite"
        >
          {hasUnsavedChanges ? (
            <>
              <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden="true" />
              <span className="text-amber-600">Unsaved changes</span>
            </>
          ) : (
            <>
              <span className="text-emerald-600" aria-hidden="true">✓</span>
              <span className="text-slate-500">All changes saved</span>
            </>
          )}
        </span>
      </div>
    </div>
  );
}
