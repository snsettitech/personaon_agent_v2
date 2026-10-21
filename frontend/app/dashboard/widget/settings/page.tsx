'use client';

import React, { useState, useEffect, useRef } from 'react';
import Link from 'next/link';
import { useTwin } from '@/lib/context/TwinContext';
import { PersonaCard } from '@/components/share/PersonaCard';
import { useSharePersona } from '@/lib/share/useSharePersona';
import { analytics } from '@/lib/analytics/events';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { API_ENDPOINTS } from '@/lib/constants';

const DEFAULT_WELCOME = 'Hi! How can I help you?';
const DEFAULT_LEAD_PROMPT = 'Leave your name and email to start chatting';

const VALUE_FRAME_OPTIONS = [
  { value: 'opportunity', label: 'Opportunity' },
  { value: 'lead', label: 'Lead' },
  { value: 'inquiry', label: 'Inquiry' },
  { value: 'collaboration', label: 'Collaboration' },
  { value: 'interest', label: 'Interest' },
] as const;

function ToggleSwitch({ checked, onChange, id, ariaLabel }: { checked: boolean; onChange: (v: boolean) => void; id: string; ariaLabel?: string }) {
  return (
    <button
      type="button"
      id={id}
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0D9488] ${checked ? 'bg-[#0F766E]' : 'bg-[#D6D3D1]'}`}
    >
      <span className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${checked ? 'translate-x-5' : 'translate-x-0'}`} />
    </button>
  );
}

interface WidgetUi {
  position?: 'bottom-right' | 'bottom-left';
  bubble_color?: string;
  welcome_message?: string;
  lead_capture_enabled?: boolean;
  lead_capture_prompt?: string;
  value_frame?: string;
  booking_url?: string;
}

export default function WidgetSettingsPage() {
  const { activeTwin, refreshTwins } = useTwin();
  const persona = useSharePersona();
  const [saving, setSaving] = useState(false);
  const [savedTick, setSavedTick] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Read initial values from twin.settings.widget_ui
  const widgetUi = ((activeTwin?.settings as Record<string, unknown> | undefined)?.widget_ui ?? {}) as WidgetUi;

  const [position, setPosition] = useState<'bottom-right' | 'bottom-left'>(widgetUi.position ?? 'bottom-right');
  const [bubbleColor, setBubbleColor] = useState(widgetUi.bubble_color ?? '#0F766E');
  const [welcomeMessage, setWelcomeMessage] = useState(widgetUi.welcome_message ?? DEFAULT_WELCOME);
  const [leadCaptureEnabled, setLeadCaptureEnabled] = useState(!!widgetUi.lead_capture_enabled);
  const [leadCapturePrompt, setLeadCapturePrompt] = useState(widgetUi.lead_capture_prompt ?? DEFAULT_LEAD_PROMPT);
  const [valueFrame, setValueFrame] = useState(widgetUi.value_frame ?? 'lead');
  const [bookingUrl, setBookingUrl] = useState(widgetUi.booking_url ?? '');

  const savedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (savedTimerRef.current) clearTimeout(savedTimerRef.current); }, []);
  useEffect(() => { analytics.shareStudioOpened('settings'); }, []);

  // Re-sync form when twin loads (context may hydrate after first render)
  useEffect(() => {
    if (!activeTwin) return;
    const ui = ((activeTwin.settings as Record<string, unknown> | undefined)?.widget_ui ?? {}) as WidgetUi;
    setPosition(ui.position ?? 'bottom-right');
    setBubbleColor(ui.bubble_color ?? '#0F766E');
    setWelcomeMessage(ui.welcome_message ?? DEFAULT_WELCOME);
    setLeadCaptureEnabled(!!ui.lead_capture_enabled);
    setLeadCapturePrompt(ui.lead_capture_prompt ?? DEFAULT_LEAD_PROMPT);
    setValueFrame(ui.value_frame ?? 'lead');
    setBookingUrl(ui.booking_url ?? '');
  }, [activeTwin?.id]); // only re-sync when twin changes, not on every settings mutation

  const handleSave = async () => {
    if (!activeTwin?.id) return;
    setSaving(true);
    setError(null);
    if (bookingUrl.trim() && !/^https?:\/\//i.test(bookingUrl.trim())) {
      setError('Booking URL must start with https://');
      setSaving(false);
      return;
    }
    const widgetUiPatch: WidgetUi = {
      position,
      bubble_color: bubbleColor,
      welcome_message: welcomeMessage,
      lead_capture_enabled: leadCaptureEnabled,
      lead_capture_prompt: leadCapturePrompt,
      value_frame: valueFrame,
      booking_url: bookingUrl.trim() || undefined,
    };
    try {
      const res = await authFetchStandalone(API_ENDPOINTS.TWIN_DETAIL(activeTwin.id), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings: { widget_ui: widgetUiPatch } }),
      });
      if (!res.ok) throw new Error(`Save failed: ${res.status}`);
      if (savedTimerRef.current) clearTimeout(savedTimerRef.current);
      setSavedTick(true);
      refreshTwins();
      savedTimerRef.current = setTimeout(() => setSavedTick(false), 2000);
    } catch (err) {
      console.error('[WidgetSettings] save failed', err);
      setError('Failed to save settings. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  if (!activeTwin) {
    return <div className="p-8 text-center text-[#57534E]">Create a persona first.</div>;
  }

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-[#A8A29E]">
        <Link href="/dashboard/widget" className="hover:text-[#0F766E] transition-colors">Share Studio</Link>
        <span aria-hidden="true">→</span>
        <span className="text-[#1C1917] font-medium">Widget Settings</span>
      </div>

      <div>
        <h1 className="text-2xl font-black tracking-tight text-[#1C1917]">Widget Settings</h1>
        <p className="text-[#57534E] mt-1">
          Customise how your chat widget looks and whether it captures visitor info.
        </p>
      </div>

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm" role="alert">{error}</div>
      )}

      {/* Lead capture */}
      <div className="bg-white rounded-2xl border border-[#E7E5E4] shadow-sm p-6 space-y-4">
        <div>
          <h2 className="text-base font-bold text-[#1C1917]">Lead capture</h2>
          <p className="text-sm text-[#57534E] mt-0.5">
            Ask website visitors for their name and email before chatting — turn traffic into warm leads.
          </p>
        </div>

        <div className="flex items-center justify-between">
          <div>
            <span className="text-sm font-medium text-[#1C1917]">Ask visitors for name and email</span>
            <p className="text-xs text-[#57534E] mt-0.5">Visitors see a short form before chat opens.</p>
          </div>
          <ToggleSwitch id="lead-capture-toggle" checked={leadCaptureEnabled} onChange={setLeadCaptureEnabled} ariaLabel="Ask visitors for name and email" />
        </div>

        {leadCaptureEnabled && (
          <div className="space-y-4 pt-1 border-t border-[#F5F0EB]">
            <div>
              <label className="block text-sm font-medium text-[#57534E] mb-2">What should we ask?</label>
              <input
                type="text"
                value={leadCapturePrompt}
                onChange={(e) => setLeadCapturePrompt(e.target.value)}
                placeholder={DEFAULT_LEAD_PROMPT}
                maxLength={120}
                className="w-full px-4 py-2 border border-[#D6D3D1] rounded-xl text-[#1C1917] placeholder-[#A8A29E] focus:outline-none focus:ring-2 focus:ring-[#0D9488]"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-[#57534E] mb-2">Frame these visitors as</label>
              <select
                value={valueFrame}
                onChange={(e) => setValueFrame(e.target.value)}
                className="w-full px-4 py-2 border border-[#D6D3D1] rounded-xl text-[#1C1917] bg-white focus:outline-none focus:ring-2 focus:ring-[#0D9488]"
              >
                {VALUE_FRAME_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
              <p className="text-xs text-[#A8A29E] mt-1">Used to label captured contacts in your Leads inbox.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-[#57534E] mb-2">
                Booking URL <span className="text-[#A8A29E] font-normal">(optional)</span>
              </label>
              <input
                type="url"
                value={bookingUrl}
                onChange={(e) => setBookingUrl(e.target.value)}
                placeholder="https://cal.com/yourname"
                className="w-full px-4 py-2 border border-[#D6D3D1] rounded-xl text-[#1C1917] placeholder-[#A8A29E] focus:outline-none focus:ring-2 focus:ring-[#0D9488]"
              />
              <p className="text-xs text-[#A8A29E] mt-1">Shown to warm leads in the conversation as a booking prompt.</p>
            </div>
          </div>
        )}

        <Link href="/dashboard/widget/leads" className="text-sm font-semibold text-[#0F766E] hover:underline inline-block">
          View captured leads →
        </Link>
      </div>

      {/* Look & feel */}
      <div className="bg-white rounded-2xl border border-[#E7E5E4] shadow-sm p-6 space-y-5">
        <h2 className="text-base font-bold text-[#1C1917]">Look &amp; feel</h2>

        <div>
          <label className="block text-sm font-medium text-[#57534E] mb-2">Welcome message</label>
          <input
            type="text"
            value={welcomeMessage}
            onChange={(e) => setWelcomeMessage(e.target.value)}
            placeholder={DEFAULT_WELCOME}
            maxLength={200}
            className="w-full px-4 py-2 border border-[#D6D3D1] rounded-xl text-[#1C1917] placeholder-[#A8A29E] focus:outline-none focus:ring-2 focus:ring-[#0D9488]"
          />
        </div>

        <div className="grid sm:grid-cols-2 gap-5">
          <div>
            <label className="block text-sm font-medium text-[#57534E] mb-2">Chat button position</label>
            <div className="flex gap-2">
              {(['bottom-right', 'bottom-left'] as const).map((p) => (
                <button
                  type="button"
                  key={p}
                  onClick={() => setPosition(p)}
                  className={`flex-1 py-2 px-3 rounded-xl border-2 text-sm font-medium transition-all cursor-pointer ${
                    position === p
                      ? 'border-[#0F766E] bg-teal-50 text-[#0F766E]'
                      : 'border-[#E7E5E4] text-[#57534E] hover:border-[#D6D3D1]'
                  }`}
                >
                  {p === 'bottom-right' ? '→ Bottom right' : '← Bottom left'}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-[#57534E] mb-2">Button colour</label>
            <div className="flex items-center gap-3">
              <input
                type="color"
                value={bubbleColor}
                onChange={(e) => setBubbleColor(e.target.value)}
                className="w-10 h-10 rounded-lg cursor-pointer border border-[#E7E5E4]"
                aria-label="Chat bubble colour"
              />
              <code className="text-sm font-mono text-[#57534E]">{bubbleColor}</code>
            </div>
          </div>
        </div>
      </div>

      {/* Sticky save */}
      <div className="sticky bottom-4 flex justify-end">
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className={`px-6 py-3 rounded-xl text-sm font-semibold text-white shadow-lg transition-all cursor-pointer disabled:opacity-50 ${
            savedTick ? 'bg-emerald-500' : 'bg-[#0F766E] hover:bg-[#0D9488]'
          }`}
        >
          {saving ? 'Saving…' : savedTick ? '✓ Saved' : 'Save settings'}
        </button>
      </div>

      {persona && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-[#57534E]">Your AI persona</p>
          <PersonaCard persona={persona} size="sm" showUrl />
        </div>
      )}
    </div>
  );
}
