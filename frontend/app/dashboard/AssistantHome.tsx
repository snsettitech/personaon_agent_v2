'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { BarChart3, Calendar, Mail, PencilLine } from 'lucide-react';
import AssistantChat, { type AssistantSuggestion } from './AssistantChat';
import { useTwin, useCanChat } from '@/lib/context/TwinContext';
import { useHomeStatus } from '@/lib/hooks/useHomeStatus';
import { HomeStatusCards } from './HomeStatusCards';

const SUBTITLE =
  "I'm your chief of staff — I keep your persona sharp, tell you how it's landing, and handle the follow-ups.";

/** Initials from a display name, e.g. "Sainath Setti" -> "SS". */
function initialsFrom(name: string): string {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join('') || 'P'
  );
}

/**
 * Home v1 — Assistant Home (see plans/home-v1-assistant.md).
 *
 * The whole Home IS the chief-of-staff chat (ChatGPT-style). The empty state is
 * the hero — the owner's mark (avatar, else initials), heading, the composer as
 * the focal point, contextual chips (Improve / Respond / Show / Meet, with live
 * counts), then the "what's happening" cards. Once a conversation starts,
 * AssistantChat switches to the message view with a sticky composer.
 *
 * Renders inside DashboardShell's scrolling <main>. No fake data: the chat only
 * mounts on a real chat-ready twin, and each status card hides when empty.
 */
export default function AssistantHome() {
  const { activeTwin, isLoading } = useTwin();
  const canChat = useCanChat(activeTwin);
  const homeStatus = useHomeStatus(activeTwin?.id);
  const router = useRouter();

  const nudgeKey = activeTwin ? `nudge_capture_dismissed_${activeTwin.id}` : null;
  const [nudgeDismissed, setNudgeDismissed] = useState(true);

  useEffect(() => {
    if (!nudgeKey) return;
    try {
      setNudgeDismissed(localStorage.getItem(nudgeKey) === '1');
    } catch {
      setNudgeDismissed(false);
    }
  }, [nudgeKey]);

  const captureEnabledForCleanup = Boolean(
    ((activeTwin?.settings as Record<string, unknown> | undefined)?.widget_ui as Record<string, unknown> | undefined)?.lead_capture_enabled
  );
  useEffect(() => {
    if (!nudgeKey || !captureEnabledForCleanup) return;
    try { localStorage.removeItem(nudgeKey); } catch { /* ignore */ }
  }, [nudgeKey, captureEnabledForCleanup]);

  function dismissNudge() {
    setNudgeDismissed(true);
    if (nudgeKey) {
      try { localStorage.setItem(nudgeKey, '1'); } catch { /* ignore */ }
    }
  }

  if (isLoading) {
    return <p className="py-16 text-center text-sm text-neutral-400">Loading your workspace…</p>;
  }
  if (!activeTwin) {
    return (
      <p className="py-16 text-center text-sm text-neutral-500">
        Create your persona to start talking with your chief of staff.
      </p>
    );
  }
  if (!canChat) {
    return (
      <p className="py-16 text-center text-sm text-neutral-500">
        Your persona is still being set up. Finish onboarding to start.
      </p>
    );
  }

  const { readiness, pending } = homeStatus;
  const waiting = pending
    ? (pending.to_review || 0) + (pending.follow_ups || 0) + (pending.visitor_questions || 0)
    : 0;

  // The hero mark represents the owner's persona: avatar if set, else initials.
  const settings = (activeTwin.settings ?? {}) as Record<string, unknown>;
  const widgetUi = (settings.widget_ui ?? {}) as Record<string, unknown>;
  const captureEnabled = Boolean(widgetUi.lead_capture_enabled);
  const showNudge = !captureEnabled && !nudgeDismissed;
  const publicProfile = (settings.public_profile ?? {}) as Record<string, unknown>;
  const markImageUrl =
    (publicProfile.avatar_url as string | undefined) ||
    (publicProfile.image_url as string | undefined) ||
    undefined;
  const markInitials = initialsFrom(activeTwin.name);

  const suggestions: AssistantSuggestion[] = [
    {
      key: 'improve',
      icon: PencilLine,
      label: 'Improve',
      hint: readiness ? `${readiness.score}/${readiness.max}` : undefined,
      prompt: 'What should I add to make my persona answer better?',
    },
    {
      key: 'respond',
      icon: Mail,
      label: 'Respond',
      hint: waiting > 0 ? `${waiting} waiting` : undefined,
      prompt: 'Who is waiting on a reply from me, and can you help me draft one?',
    },
    {
      key: 'show',
      icon: BarChart3,
      label: 'Show',
      hint: homeStatus.conversationCount ? `${homeStatus.conversationCount} recent` : undefined,
      prompt: 'How has my persona been landing lately?',
    },
    {
      key: 'meet',
      icon: Calendar,
      label: 'Meet',
      onClick: () => router.push('/dashboard/meetings'),
    },
  ];

  return (
    <AssistantChat
      key={activeTwin.id}
      twinId={activeTwin.id}
      subtitle={SUBTITLE}
      suggestions={suggestions}
      markImageUrl={markImageUrl}
      markInitials={markInitials}
      belowSuggestions={
        <>
          {showNudge && (
            <div className="flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm">
              <span className="mt-0.5 text-amber-500 shrink-0" aria-hidden="true">⚠</span>
              <div className="flex-1 min-w-0">
                <p className="font-semibold text-amber-900">You&apos;re missing every lead that visits you</p>
                <p className="text-amber-800 mt-0.5 text-xs">Lead capture is off — visitors chat and disappear with no way to reconnect.</p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Link
                  href="/dashboard/widget/settings"
                  className="text-xs font-semibold text-amber-900 underline underline-offset-2 hover:text-amber-700"
                >
                  Enable capture
                </Link>
                <button
                  type="button"
                  onClick={dismissNudge}
                  aria-label="Dismiss"
                  className="text-amber-400 hover:text-amber-600 transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>
          )}
          <HomeStatusCards status={homeStatus} />
        </>
      }
    />
  );
}
