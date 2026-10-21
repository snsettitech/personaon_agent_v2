'use client';

import React, { useEffect } from 'react';
import Link from 'next/link';
import { PersonaCard } from '@/components/share/PersonaCard';
import { CopyButton } from '@/components/share/CopyButton';
import { getShareUrl, getXIntentUrl } from '@/lib/share/utils';
import { useSharePersona } from '@/lib/share/useSharePersona';
import { analytics } from '@/lib/analytics/events';


interface SocialSectionProps {
  icon: string;
  title: string;
  steps: string[];
  copyText: string;
  copyLabel: string;
  cta?: { label: string; href: string; onClick?: () => void };
  tip?: string;
  onCopied?: () => void;
}

function SocialSection({ icon, title, steps, copyText, copyLabel, cta, tip, onCopied }: SocialSectionProps) {
  return (
    <div className="bg-white rounded-2xl border border-[#E7E5E4] p-5 space-y-4">
      <div className="flex items-center gap-3">
        <span className="text-2xl" aria-hidden="true">{icon}</span>
        <h2 className="text-base font-bold text-[#1C1917]">{title}</h2>
      </div>

      <div className="flex items-center gap-3 bg-[#F5F0EB] rounded-xl p-3">
        <span className="text-xs font-mono text-[#1C1917] flex-1 truncate">{copyText}</span>
        <CopyButton text={copyText} label={copyLabel} copiedLabel="Copied!" size="sm" variant="secondary" onCopied={onCopied} />
      </div>

      <ol className="space-y-2">
        {steps.map((step, i) => (
          <li key={i} className="flex items-start gap-3">
            <span className="shrink-0 w-5 h-5 rounded-full bg-[#F5F0EB] text-[#57534E] text-xs font-bold flex items-center justify-center mt-0.5">
              {i + 1}
            </span>
            <span className="text-sm text-[#374151] leading-relaxed">{step}</span>
          </li>
        ))}
      </ol>

      {cta && (
        <a
          href={cta.href}
          target="_blank"
          rel="noopener noreferrer"
          onClick={cta.onClick}
          className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-semibold bg-[#1C1917] hover:bg-[#374151] text-white rounded-xl transition-colors"
        >
          {cta.label} ↗
        </a>
      )}

      {tip && <p className="text-xs text-[#A8A29E]">{tip}</p>}
    </div>
  );
}

export default function SocialPage() {
  const persona = useSharePersona();

  useEffect(() => { analytics.shareStudioOpened('social'); }, []);

  if (!persona) {
    return <div className="p-8 text-center text-[#57534E]">Complete your profile to share on social.</div>;
  }

  const shareUrl = getShareUrl(persona.handle);
  const xIntentUrl = getXIntentUrl(persona);
  const xCopyText = `I built an AI version of myself — ask it anything.\n\n${shareUrl}`;

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex items-center gap-2 text-sm text-[#A8A29E]">
        <Link href="/dashboard/widget" className="hover:text-[#0F766E] transition-colors">Share Studio</Link>
        <span aria-hidden="true">→</span>
        <span className="text-[#1C1917] font-medium">Instagram &amp; X</span>
      </div>

      <div>
        <h1 className="text-2xl font-black tracking-tight text-[#1C1917]">Instagram, TikTok &amp; X</h1>
        <p className="text-[#57534E] mt-1">Get your AI in your social bio in under a minute.</p>
      </div>

      <SocialSection
        icon="📸"
        title="Instagram — Bio Link"
        copyText={shareUrl}
        copyLabel="Copy link"
        onCopied={() => analytics.shareActionCopied('social', 'link')}
        steps={[
          'Copy the link above',
          'Open Instagram → tap your profile photo → Edit Profile',
          'Tap "Website" (or "Add link" if you have multiple links)',
          'Paste the link and tap Done',
        ]}
        tip="Instagram only allows one bio link. If you already use Linktree or bio.link, just add your AI link there instead."
      />

      <SocialSection
        icon="🎵"
        title="TikTok — Bio Link"
        copyText={shareUrl}
        copyLabel="Copy link"
        onCopied={() => analytics.shareActionCopied('social', 'link')}
        steps={[
          'Copy the link above',
          'Open TikTok → tap Profile → tap Edit Profile',
          'Tap "Website" and paste the link',
          'Tap Save',
        ]}
        tip="You need 1,000 followers for a clickable TikTok bio link. Under that, add the URL as text in your bio anyway — some visitors will type it."
      />

      <SocialSection
        icon="𝕏"
        title="X (Twitter) — Share a Tweet"
        copyText={xCopyText}
        copyLabel="Copy tweet"
        onCopied={() => analytics.shareActionCopied('social', 'post')}
        cta={{ label: 'Post on X', href: xIntentUrl, onClick: () => analytics.shareActionClicked('social', 'post_on_x') }}
        steps={[
          'Click "Post on X" to open a pre-filled tweet',
          'Review and edit the text if you like',
          'Click Tweet / Post',
        ]}
        tip={'Adding "AI" or "persona" in the post text improves discoverability because people search these terms.'}
      />

      <div className="space-y-2">
        <p className="text-xs font-medium text-[#57534E]">Your AI persona</p>
        <PersonaCard persona={persona} size="sm" showUrl />
      </div>
    </div>
  );
}
