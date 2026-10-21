'use client';

import React, { useEffect } from 'react';
import Link from 'next/link';
import { useTwin } from '@/lib/context/TwinContext';
import { PersonaCard } from '@/components/share/PersonaCard';
import { CopyButton } from '@/components/share/CopyButton';
import { QRCodeDisplay } from '@/components/share/QRCodeDisplay';
import { getShareUrl } from '@/lib/share/utils';
import { useSharePersona } from '@/lib/share/useSharePersona';
import { analytics } from '@/lib/analytics/events';

interface SurfaceCard {
  href: string;
  icon: string;
  title: string;
  description: string;
  cta: string;
  badge?: string;
}

const SURFACES: SurfaceCard[] = [
  {
    href: '/dashboard/widget/email-signature',
    icon: '✉️',
    title: 'Email Signature',
    description: 'Add your AI to every email you send — one click to add in Gmail, Outlook, or Apple Mail.',
    cta: 'Get signature →',
    badge: 'Most popular',
  },
  {
    href: '/dashboard/widget/linkedin',
    icon: '💼',
    title: 'LinkedIn',
    description: 'Post about your AI or add a link to your profile so connections can chat with you anytime.',
    cta: 'Share on LinkedIn →',
  },
  {
    href: '/dashboard/widget/social',
    icon: '📱',
    title: 'Instagram & X',
    description: 'Put your AI in your bio link or share it as a tweet — takes 30 seconds.',
    cta: 'Share on social →',
  },
  {
    href: '/dashboard/widget/website',
    icon: '🌐',
    title: 'Your Website',
    description: "Add a floating chat button to your site. Tell us what platform you use and we'll walk you through it.",
    cta: 'Add to website →',
  },
  {
    href: '/dashboard/widget/qr',
    icon: '⬛',
    title: 'QR Code & Print',
    description: 'Download a QR code for business cards, slide decks, event badges, and anywhere people can\'t click.',
    cta: 'Get QR code →',
  },
  {
    href: '/dashboard/widget/settings',
    icon: '⚙️',
    title: 'Widget Settings',
    description: 'Choose your chat bubble color, position, and whether to ask visitors for their contact info.',
    cta: 'Edit settings →',
  },
];


export default function ShareStudioPage() {
  const { activeTwin } = useTwin();
  const persona = useSharePersona();

  useEffect(() => { analytics.shareActionClicked('hub', 'share_studio_opened'); }, []);

  if (!activeTwin) {
    return (
      <div className="p-8 text-center text-[#57534E]">
        <p>Create a persona first to start sharing.</p>
      </div>
    );
  }

  const shareUrl = persona?.handle ? getShareUrl(persona.handle) : '';
  const isPublished = Boolean(
    (activeTwin.settings as Record<string, unknown> | undefined)?.is_public
  );

  return (
    <div className="space-y-8 max-w-4xl">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-black tracking-tight text-[#1C1917]">Share Studio</h1>
        <p className="text-[#57534E] mt-1">
          Share your AI persona everywhere — pick where you want it to appear.
        </p>
      </div>

      {/* Hero: persona card + QR side by side */}
      <div className="bg-gradient-to-br from-[#F0FDF9] to-[#ECFDF5] rounded-3xl border border-[#BBF7D0] p-6 flex flex-col sm:flex-row gap-6 items-start">
        {/* Left: persona card + copy link */}
        <div className="flex-1 min-w-0 space-y-4">
          {persona && <PersonaCard persona={persona} size="md" showUrl={false} />}

          {shareUrl ? (
            <div className="bg-white rounded-2xl border border-[#E7E5E4] p-4 space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-xs font-medium text-[#57534E] mb-1">Your share link</div>
                  <div className="text-sm font-mono text-[#1C1917] truncate">{shareUrl}</div>
                </div>
                <CopyButton text={shareUrl} label="Copy link" copiedLabel="Copied!" size="sm" />
              </div>
              {!isPublished && (
                <div className="text-xs text-amber-700 bg-amber-50 rounded-xl px-3 py-2">
                  ⚠ Your persona is currently private. Go to{' '}
                  <Link href="/dashboard/share" className="font-semibold underline">Share</Link>{' '}
                  to make it public before sharing.
                </div>
              )}
            </div>
          ) : (
            <div className="bg-white rounded-2xl border border-[#E7E5E4] p-4 text-sm text-[#57534E]">
              Complete your profile in{' '}
              <Link href="/dashboard/profile" className="text-[#0F766E] font-semibold underline">Profile</Link>{' '}
              to get your share link.
            </div>
          )}
        </div>

        {/* Right: QR code (always visible) */}
        {shareUrl && (
          <div className="flex flex-col items-center gap-2 shrink-0">
            <div className="text-xs font-medium text-[#57534E] text-center mb-1">QR code</div>
            <div className="p-3 bg-white rounded-2xl border border-[#E7E5E4] shadow-sm">
              <QRCodeDisplay url={shareUrl} size={120} personaName={persona?.name} showDownload={false} />
            </div>
            <Link
              href="/dashboard/widget/qr"
              className="text-xs text-[#0F766E] font-semibold hover:underline"
            >
              Download full size →
            </Link>
          </div>
        )}
      </div>

      {/* Surface cards grid */}
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-widest text-[#A8A29E] mb-4">
          Where do you want to share?
        </h2>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {SURFACES.map((surface) => (
            <Link
              key={surface.href}
              href={surface.href}
              className="group relative bg-white rounded-2xl border border-[#E7E5E4] p-5 hover:border-[#0F766E] hover:shadow-md transition-all duration-200"
            >
              {surface.badge && (
                <span className="absolute top-3 right-3 text-[10px] font-bold uppercase tracking-wider text-[#0F766E] bg-[#F0FDF4] px-2 py-0.5 rounded-full">
                  {surface.badge}
                </span>
              )}
              <div className="text-2xl mb-3" aria-hidden="true">{surface.icon}</div>
              <div className="text-base font-bold text-[#1C1917] mb-1">{surface.title}</div>
              <div className="text-sm text-[#57534E] mb-4 leading-relaxed">{surface.description}</div>
              <div className="text-sm font-semibold text-[#0F766E] group-hover:translate-x-1 transition-transform duration-150">
                {surface.cta}
              </div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
