'use client';

import React, { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { useTwin } from '@/lib/context/TwinContext';
import { CopyButton } from '@/components/share/CopyButton';
import { PersonaCard } from '@/components/share/PersonaCard';
import { getWebsiteSnippet } from '@/lib/share/utils';
import { listWidgetKeys, createWidgetKey, updateWidgetConfig, PlanUpgradeRequiredError, type WidgetApiKey } from '@/lib/widget/api';
import { useSharePersona } from '@/lib/share/useSharePersona';
import { analytics } from '@/lib/analytics/events';

type Platform = 'wordpress' | 'wix' | 'squarespace' | 'webflow' | 'shopify' | 'custom';

interface PlatformInfo {
  label: string;
  icon: string;
  steps: string[];
  note?: string;
}

const PLATFORMS: Record<Platform, PlatformInfo> = {
  wordpress: {
    label: 'WordPress',
    icon: '🔵',
    steps: [
      'Copy the code snippet below',
      'Log in to your WordPress dashboard',
      "Go to Appearance → Theme Editor (or use the Block Editor)",
      "Open your theme's footer.php file",
      'Paste the snippet just before the closing </body> tag',
      'Click Update File',
    ],
    note: "Using Elementor or Divi? Insert a \"HTML\" widget in the footer section and paste there instead.",
  },
  wix: {
    label: 'Wix',
    icon: '⚡',
    steps: [
      'Copy the code snippet below',
      'Open your Wix Editor',
      'Click "Add" → "Embed" → "Custom Code"',
      'Choose "Body – end" as the placement',
      'Paste the snippet and click Apply',
      'Publish your site',
    ],
    note: 'You need a Wix Premium plan to add custom code. Free Wix sites do not support this.',
  },
  squarespace: {
    label: 'Squarespace',
    icon: '⬛',
    steps: [
      'Copy the code snippet below',
      'Open your Squarespace dashboard',
      'Go to Settings → Advanced → Code Injection',
      'Paste the snippet into the "Footer" field',
      'Click Save',
    ],
    note: 'Code injection requires a Squarespace Personal plan or higher.',
  },
  webflow: {
    label: 'Webflow',
    icon: '🟦',
    steps: [
      'Copy the code snippet below',
      'Open your Webflow Designer',
      'Click the gear icon (Site Settings) → Custom Code tab',
      'Paste the snippet into "Footer Code"',
      'Click Save Changes, then Publish',
    ],
  },
  shopify: {
    label: 'Shopify',
    icon: '🟢',
    steps: [
      'Copy the code snippet below',
      'From your Shopify admin, go to Online Store → Themes',
      'Click Actions → Edit code on your active theme',
      'Open the "theme.liquid" file',
      'Paste just before the closing </body> tag',
      'Click Save',
    ],
  },
  custom: {
    label: 'Other / Custom HTML',
    icon: '💻',
    steps: [
      'Copy the code snippet below',
      'Open your website\'s HTML file in a text editor',
      'Find the closing </body> tag (near the bottom of the file)',
      'Paste the snippet just above it',
      'Save and upload the file',
    ],
    note: "The snippet works in any website that lets you add HTML — including static sites, custom CMS platforms, and frameworks like React or Vue (add it to your root HTML file or index.html).",
  },
};


export default function WebsitePage() {
  const { activeTwin } = useTwin();
  const persona = useSharePersona();
  const [selectedPlatform, setSelectedPlatform] = useState<Platform | null>(null);
  const [keys, setKeys] = useState<WidgetApiKey[]>([]);
  const [creating, setCreating] = useState(false);
  const [keyError, setKeyError] = useState<string | null>(null);
  const [rawKey, setRawKey] = useState<string | null>(null);

  const twinId = activeTwin?.id;
  const activeKey = keys.find((k) => k.is_active);

  const loadKeys = useCallback(async () => {
    if (!twinId) return;
    try {
      const data = await listWidgetKeys(twinId);
      setKeys(data);
    } catch (err) {
      console.error('[WebsitePage] loadKeys failed', err);
    }
  }, [twinId]);

  useEffect(() => { void loadKeys(); }, [loadKeys]);
  useEffect(() => { analytics.shareStudioOpened('website'); }, []);

  const handleCreateKey = async () => {
    if (!twinId) return;
    setCreating(true);
    setKeyError(null);
    try {
      const result = await createWidgetKey(twinId, 'Website Widget');
      setRawKey(result.key);
      // Propagate saved widget_ui settings into this key's widget_config
      const widgetUi = ((activeTwin?.settings as Record<string, unknown> | undefined)?.widget_ui ?? {}) as Record<string, unknown>;
      if (Object.keys(widgetUi).length > 0) {
        try {
          await updateWidgetConfig(result.id, widgetUi as import('@/lib/widget/api').WidgetConfig);
        } catch {
          // Non-fatal — widget still works with defaults
        }
      }
      await loadKeys();
    } catch (err) {
      console.error('[WebsitePage] createWidgetKey failed', err);
      if (err instanceof PlanUpgradeRequiredError) {
        setKeyError('Your plan doesn\'t include website embedding. Upgrade to Pro to add the chat widget to your site.');
      } else {
        setKeyError('Something went wrong generating your code. Please try again.');
      }
    } finally {
      setCreating(false);
    }
  };

  if (!persona) {
    return <div className="p-8 text-center text-[#57534E]">Complete your profile first.</div>;
  }

  const snippet = rawKey ? getWebsiteSnippet(rawKey) : null;
  const platform = selectedPlatform ? PLATFORMS[selectedPlatform] : null;

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-[#A8A29E]">
        <Link href="/dashboard/widget" className="hover:text-[#0F766E] transition-colors">Share Studio</Link>
        <span aria-hidden="true">→</span>
        <span className="text-[#1C1917] font-medium">Website</span>
      </div>

      <div>
        <h1 className="text-2xl font-black tracking-tight text-[#1C1917]">Add to Your Website</h1>
        <p className="text-[#57534E] mt-1">
          A floating chat button on your website means visitors can talk to your AI anytime — even when you&apos;re not there.
        </p>
      </div>

      {/* Step 1: pick platform */}
      <div className="bg-white rounded-2xl border border-[#E7E5E4] p-5 space-y-4">
        <div>
          <h2 className="text-base font-bold text-[#1C1917]">Step 1 — What&apos;s your website built on?</h2>
          <p className="text-sm text-[#57534E] mt-1">Pick your platform and we&apos;ll show you exactly what to do.</p>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {(Object.entries(PLATFORMS) as [Platform, PlatformInfo][]).map(([key, info]) => (
            <button
              type="button"
              key={key}
              onClick={() => setSelectedPlatform(key)}
              className={`flex items-center gap-2 px-3 py-2.5 rounded-xl border-2 text-sm font-medium transition-all cursor-pointer ${
                selectedPlatform === key
                  ? 'border-[#0F766E] bg-teal-50 text-[#0F766E]'
                  : 'border-[#E7E5E4] text-[#57534E] hover:border-[#D6D3D1]'
              }`}
            >
              <span aria-hidden="true">{info.icon}</span>
              <span>{info.label}</span>
            </button>
          ))}
        </div>
      </div>

      {selectedPlatform && (
        <>
          {/* Step 2: get code */}
          <div className="bg-white rounded-2xl border border-[#E7E5E4] p-5 space-y-4">
            <h2 className="text-base font-bold text-[#1C1917]">Step 2 — Get your website code</h2>

            {rawKey ? (
              <div className="space-y-3">
                <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-3 text-sm text-emerald-800 font-semibold">
                  ✓ Key generated! Copy your code now — the full key is only shown once for security.
                </div>
                <div className="flex items-start gap-3">
                  <pre className="flex-1 p-3 bg-[#1C1917] text-[#A8D5D1] rounded-xl text-xs font-mono whitespace-pre-wrap break-all">
                    {snippet}
                  </pre>
                  <CopyButton
                    text={snippet ?? ''}
                    label="Copy"
                    copiedLabel="Copied!"
                    size="sm"
                    className="shrink-0 mt-1"
                  />
                </div>
              </div>
            ) : activeKey ? (
              <div className="space-y-3">
                <p className="text-sm text-[#57534E]">
                  You already have an active key. For security, the full key is only shown once at creation.
                </p>
                <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-sm text-amber-800">
                  ⚠ To add a new website, generate a new key — then copy the snippet immediately.
                </div>
                <button
                  type="button"
                  onClick={handleCreateKey}
                  disabled={creating}
                  className="px-5 py-2.5 text-sm font-semibold bg-[#0F766E] hover:bg-[#0D9488] text-white rounded-xl transition-colors disabled:opacity-50 cursor-pointer"
                >
                  {creating ? 'Generating…' : 'Generate a new key'}
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-sm text-[#57534E]">First, generate a code for your website.</p>
                {keyError && (
                  keyError.includes('Upgrade') || keyError.includes('plan') ? (
                    <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-sm text-amber-800">
                      {keyError}{' '}
                      <Link href="/dashboard/billing" className="font-semibold underline">View plans →</Link>
                    </div>
                  ) : (
                    <p className="text-sm text-red-600">{keyError}</p>
                  )
                )}
                <button
                  type="button"
                  onClick={handleCreateKey}
                  disabled={creating}
                  className="px-5 py-2.5 text-sm font-semibold bg-[#0F766E] hover:bg-[#0D9488] text-white rounded-xl transition-colors disabled:opacity-50 cursor-pointer"
                >
                  {creating ? 'Generating…' : 'Generate my website code'}
                </button>
              </div>
            )}
          </div>

          {/* Step 3: platform instructions */}
          {(activeKey ?? rawKey) && platform && (
            <div className="bg-[#F8FAFC] rounded-2xl border border-[#E7E5E4] p-5 space-y-4">
              <h2 className="text-base font-bold text-[#1C1917]">
                Step 3 — Add it to {platform.label}
              </h2>
              <ol className="space-y-3">
                {platform.steps.map((step, i) => (
                  <li key={i} className="flex items-start gap-3">
                    <span className="shrink-0 w-6 h-6 rounded-full bg-[#0F766E] text-white text-xs font-bold flex items-center justify-center mt-0.5">
                      {i + 1}
                    </span>
                    <span className="text-sm text-[#374151] leading-relaxed">{step}</span>
                  </li>
                ))}
              </ol>
              {platform.note && (
                <div className="bg-amber-50 rounded-xl px-4 py-3 text-sm text-amber-800">
                  💡 {platform.note}
                </div>
              )}
            </div>
          )}

          {/* Lead capture upsell */}
          <div className="bg-gradient-to-r from-[#F0FDF9] to-[#ECFDF5] rounded-2xl border border-[#BBF7D0] p-5 flex items-start gap-4">
            <div className="text-2xl" aria-hidden="true">📬</div>
            <div className="space-y-1">
              <div className="text-sm font-bold text-[#1C1917]">Capture visitor emails automatically</div>
              <div className="text-sm text-[#57534E]">
                Your AI can ask visitors for their name and email before they start chatting — turning website traffic into warm leads.
              </div>
              <Link href="/dashboard/widget/settings" className="text-sm font-semibold text-[#0F766E] hover:underline">
                Turn on lead capture →
              </Link>
            </div>
          </div>
        </>
      )}

      <div className="space-y-2">
        <p className="text-xs font-medium text-[#57534E]">Your AI persona</p>
        <PersonaCard persona={persona} size="sm" showUrl />
      </div>
    </div>
  );
}
