'use client';

import React, { useState, useRef, useEffect } from 'react';
import Link from 'next/link';
import { PersonaCard } from '@/components/share/PersonaCard';
import { getEmailSignatureHtml } from '@/lib/share/utils';
import { useSharePersona } from '@/lib/share/useSharePersona';
import { analytics } from '@/lib/analytics/events';

type Platform = 'gmail' | 'outlook' | 'apple';

const PLATFORM_LABELS: Record<Platform, string> = {
  gmail: 'Gmail',
  outlook: 'Outlook',
  apple: 'Apple Mail',
};

const PLATFORM_STEPS: Record<Platform, string[]> = {
  gmail: [
    'Click the copy button below',
    'Open Gmail → Settings (gear icon) → See all settings',
    'Go to the "General" tab → scroll to "Signature"',
    'Click into the signature text area and paste (Cmd+V / Ctrl+V)',
    'Scroll down and click "Save Changes"',
  ],
  outlook: [
    'Click the copy button below',
    'Open Outlook → File → Options → Mail → Signatures…',
    'Click "New", give it a name, then click in the Edit area',
    'Paste (Cmd+V / Ctrl+V)',
    'Set it as default for new messages and click OK',
  ],
  apple: [
    'Click the copy button below',
    'Open Apple Mail → Mail menu → Settings → Signatures',
    'Click + to create a new signature',
    'Uncheck "Always match my default message font" if shown',
    'Paste (Cmd+V) into the signature body',
  ],
};

const PLATFORM_TIPS: Record<Platform, string> = {
  gmail: 'Tip: If the formatting looks off after pasting, try pasting in the web version of Gmail (not a desktop app).',
  outlook: 'Tip: Make sure to use Outlook for Windows or Mac, not Outlook Web Access (OWA) — OWA does not support rich HTML signatures.',
  apple: 'Tip: The signature will appear in rich HTML when recipients view it in HTML-capable email clients.',
};


export default function EmailSignaturePage() {
  const persona = useSharePersona();
  const [platform, setPlatform] = useState<Platform>('gmail');
  const [copied, setCopied] = useState(false);
  const [copiedFallback, setCopiedFallback] = useState(false);
  const [flashRing, setFlashRing] = useState(false);
  const [showFallbackWarning, setShowFallbackWarning] = useState(false);

  const copiedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const warningTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (copiedTimerRef.current) clearTimeout(copiedTimerRef.current);
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    if (warningTimerRef.current) clearTimeout(warningTimerRef.current);
  }, []);

  useEffect(() => { analytics.shareStudioOpened('email-signature'); }, []);

  if (!persona) {
    return (
      <div className="p-8 text-center text-[#57534E]">
        Complete your profile to generate your email signature.
      </div>
    );
  }

  const signatureHtml = getEmailSignatureHtml(persona, platform);

  const copySignature = async () => {
    try {
      const blob = new Blob([signatureHtml], { type: 'text/html' });
      const richItem = new ClipboardItem({ 'text/html': blob });
      await navigator.clipboard.write([richItem]);
      setCopied(true);
      analytics.shareActionCopied('email-signature', 'signature');
      setFlashRing(true);
      flashTimerRef.current = setTimeout(() => setFlashRing(false), 600);
      copiedTimerRef.current = setTimeout(() => setCopied(false), 2500);
    } catch {
      try {
        await navigator.clipboard.writeText(signatureHtml);
        setCopiedFallback(true);
        setShowFallbackWarning(true);
        copiedTimerRef.current = setTimeout(() => setCopiedFallback(false), 2500);
        warningTimerRef.current = setTimeout(() => setShowFallbackWarning(false), 8000);
      } catch {
        // Both clipboard methods failed
      }
    }
  };

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-[#A8A29E]">
        <Link href="/dashboard/widget" className="hover:text-[#0F766E] transition-colors">Share Studio</Link>
        <span aria-hidden="true">→</span>
        <span className="text-[#1C1917] font-medium">Email Signature</span>
      </div>

      <div>
        <h1 className="text-2xl font-black tracking-tight text-[#1C1917]">Email Signature</h1>
        <p className="text-[#57534E] mt-1">
          Add your AI to every email. Every person you email becomes a potential conversation with your AI.
        </p>
      </div>

      {/* Platform tabs */}
      <div className="flex gap-1 bg-[#F5F0EB] p-1 rounded-xl w-fit">
        {(Object.keys(PLATFORM_LABELS) as Platform[]).map((p) => (
          <button
            type="button"
            key={p}
            onClick={() => setPlatform(p)}
            className={`px-4 py-1.5 text-sm font-semibold rounded-lg transition-all cursor-pointer ${
              platform === p ? 'bg-white text-[#1C1917] shadow-sm' : 'text-[#57534E] hover:text-[#1C1917]'
            }`}
          >
            {PLATFORM_LABELS[p]}
          </button>
        ))}
      </div>

      {showFallbackWarning && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-sm text-amber-800">
          ⚠ Your browser copied the raw HTML code, not the formatted signature. For best results, open this page in <strong>Chrome</strong> and copy again — it will paste correctly into Gmail.
        </div>
      )}

      {/* Live preview */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[#57534E]">Preview — this is what people will see</h2>
          <button
            onClick={copySignature}
            className={`px-4 py-2 text-sm font-semibold rounded-xl transition-all duration-200 cursor-pointer ${
              copied
                ? 'bg-emerald-500 text-white scale-105'
                : copiedFallback
                ? 'bg-emerald-400 text-white'
                : 'bg-[#0F766E] hover:bg-[#0D9488] text-white'
            }`}
          >
            {copied ? '✓ Copied to clipboard!' : copiedFallback ? '✓ HTML copied' : 'Copy signature'}
          </button>
        </div>

        {/* Safe: signatureHtml is generated by getEmailSignatureHtml which escapes all user fields via escHtml() */}
        <div
          className={`bg-white rounded-2xl border border-[#E7E5E4] p-6 transition-all duration-300 ${flashRing ? 'ring-2 ring-[#0F766E] ring-offset-2' : ''}`}
          dangerouslySetInnerHTML={{ __html: signatureHtml }}
        />

        <p className="text-xs text-[#A8A29E]">
          This preview is accurate. The signature will look the same in email clients that support HTML.
        </p>
      </div>

      {/* Step-by-step instructions */}
      <div className="bg-[#F8FAFC] rounded-2xl border border-[#E7E5E4] p-6 space-y-4">
        <h2 className="text-base font-bold text-[#1C1917]">
          How to add it to {PLATFORM_LABELS[platform]}
        </h2>
        <ol className="space-y-3">
          {PLATFORM_STEPS[platform].map((step, i) => (
            <li key={i} className="flex items-start gap-3">
              <span className="shrink-0 w-6 h-6 rounded-full bg-[#0F766E] text-white text-xs font-bold flex items-center justify-center mt-0.5">
                {i + 1}
              </span>
              <span className="text-sm text-[#374151] leading-relaxed">{step}</span>
            </li>
          ))}
        </ol>
        <p className="text-xs text-[#A8A29E]">{PLATFORM_TIPS[platform]}</p>
      </div>

      {/* Persona card reminder */}
      <div className="space-y-2">
        <p className="text-xs font-medium text-[#57534E]">Your AI persona</p>
        <PersonaCard persona={persona} size="sm" showUrl />
      </div>
    </div>
  );
}
