'use client';

import { useEffect, useState, type CSSProperties } from 'react';
import { ChevronDown, Lock } from 'lucide-react';

import { analytics } from '@/lib/analytics/events';
import type { DemoPreview } from '@/lib/experience/types';

import { DemoChat } from './DemoChat';
import { SignupWall } from './SignupWall';

const MONO = "'JetBrains Mono', monospace";
const SANS = "'Geist', sans-serif";
const SERIF = "'Instrument Serif', Georgia, serif";

// Collapsed teasers show 3 lines then fade out; "Show more" un-clamps to the
// full (still truncated) gist.
const CLAMP_STYLE: CSSProperties = {
  display: '-webkit-box',
  WebkitLineClamp: 3,
  WebkitBoxOrient: 'vertical',
  overflow: 'hidden',
  WebkitMaskImage: 'linear-gradient(180deg, #000 68%, transparent 100%)',
  maskImage: 'linear-gradient(180deg, #000 68%, transparent 100%)',
};

// A locked section shown as a PARTIAL reveal: the real gist stays legible, then
// fades out. "Show more" expands it a little further. Falls back to a blurred
// placeholder when a section has no teaser.
function LockedCard({ label, detail, teaser }: { label: string; detail: string; teaser?: string }) {
  const [expanded, setExpanded] = useState(false);
  const clamped = !expanded && Boolean(teaser);

  return (
    <div
      className="relative flex flex-col p-4"
      style={{ borderRadius: 18, border: '1px solid rgba(29,29,31,0.08)', background: 'var(--fog-2)', minHeight: 118 }}
    >
      <p className="text-[10px] uppercase tracking-[0.16em]" style={{ color: 'var(--fg-3)', fontFamily: MONO }}>
        {label}
      </p>

      {teaser ? (
        <p
          className="mt-2 text-[13px] leading-snug"
          style={{ color: 'var(--fg)', fontFamily: SANS, ...(clamped ? CLAMP_STYLE : null) }}
        >
          {teaser}
        </p>
      ) : (
        <div className="mt-2 space-y-1.5 blur-[3px]" aria-hidden>
          <div className="h-2.5 w-5/6 rounded" style={{ background: 'rgba(29,29,31,0.12)' }} />
          <div className="h-2.5 w-2/3 rounded" style={{ background: 'rgba(29,29,31,0.12)' }} />
        </div>
      )}

      <div className="mt-auto flex items-center justify-between gap-2 pt-3">
        <div className="flex items-center gap-1.5">
          <Lock size={12} style={{ color: 'var(--fg-3)' }} />
          <span className="text-[11px]" style={{ color: 'var(--fg-2)', fontFamily: SANS, fontWeight: 500 }}>
            {detail}
          </span>
        </div>
        {teaser && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            className="flex shrink-0 items-center gap-0.5 text-[11px] transition-opacity hover:opacity-70"
            style={{ color: 'var(--ink)', fontFamily: SANS, fontWeight: 500 }}
          >
            {expanded ? 'Show less' : 'Show more'}
            <ChevronDown size={13} style={{ transform: expanded ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }} />
          </button>
        )}
      </div>
    </div>
  );
}

export function PersonaReveal({ preview, token }: { preview: DemoPreview; token: string }) {
  useEffect(() => {
    analytics.experienceRevealViewed();
  }, []);

  const { locked } = preview;
  const t = preview.teasers ?? {};
  const lockedCards: { label: string; detail: string; teaser?: string }[] = [];
  if (locked.hasBio) lockedCards.push({ label: 'Full bio', detail: 'Unlock your full story', teaser: t.bio });
  if (locked.workExperience > 0)
    lockedCards.push({ label: 'Work history', detail: `${locked.workExperience} roles`, teaser: t.work });
  if (locked.achievements > 0)
    lockedCards.push({ label: 'Achievements', detail: `${locked.achievements} highlights`, teaser: t.achievement });
  if (locked.education > 0)
    lockedCards.push({ label: 'Education', detail: `${locked.education} entries`, teaser: t.education });
  if (locked.contributions > 0)
    lockedCards.push({ label: 'Contributions', detail: `${locked.contributions} items`, teaser: t.contribution });
  if (locked.hasVoice) lockedCards.push({ label: 'Voice & style', detail: 'How your twin sounds', teaser: t.voice });

  return (
    <div className="space-y-6">
      <div>
        <div className="flex flex-wrap items-center gap-2.5">
          <h2 className="text-[32px]" style={{ color: 'var(--ink)', fontFamily: SERIF, lineHeight: 1.05 }}>
            {preview.name}
          </h2>
          <span
            className="rounded-full px-2.5 py-1 text-[10px] uppercase tracking-[0.16em]"
            style={{ border: '1px solid rgba(29,29,31,0.12)', background: 'var(--fog-2)', color: 'var(--fg-2)', fontFamily: MONO }}
          >
            Demo preview
          </span>
        </div>
        {preview.headline && (
          <p className="mt-1.5 text-[15px]" style={{ color: 'var(--fg-2)', fontFamily: SANS }}>
            {preview.headline}
          </p>
        )}
        <p className="mt-2 text-[14px]" style={{ color: 'var(--fg-2)', fontFamily: SANS }}>
          {preview.knowsTeaser}
        </p>
      </div>

      <div className="p-5" style={{ borderRadius: 20, border: '1px solid rgba(29,29,31,0.08)', background: 'var(--fog-2)' }}>
        <p className="text-[10px] uppercase tracking-[0.2em]" style={{ color: 'var(--fg-3)', fontFamily: MONO }}>
          A taste of your twin
        </p>
        {preview.expertisePreview.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {preview.expertisePreview.map((tag) => (
              <span key={tag} className="rounded-full px-3 py-1 text-[13px]" style={{ background: 'var(--fog-3)', color: 'var(--fg)', fontFamily: SANS }}>
                {tag}
              </span>
            ))}
            {locked.expertise > 0 && (
              <span className="select-none rounded-full px-3 py-1 text-[13px] blur-[3px]" style={{ background: 'var(--fog-3)', color: 'var(--fg-3)', fontFamily: SANS }}>
                +{locked.expertise} more
              </span>
            )}
          </div>
        )}
        {preview.sampleQA.answer && (
          <div className="mt-4 p-4" style={{ borderRadius: 16, background: 'var(--fog-3)' }}>
            <p className="text-[13.5px]" style={{ color: 'var(--fg)', fontFamily: SANS, fontWeight: 600 }}>
              {preview.sampleQA.question}
            </p>
            <p className="mt-1.5 text-[13.5px] leading-relaxed" style={{ color: 'var(--fg-2)', fontFamily: SANS }}>
              {preview.sampleQA.answer}
            </p>
          </div>
        )}
      </div>

      <DemoChat token={token} suggestedQuestions={preview.suggestedQuestions} chatLimit={preview.chatLimit} />

      {lockedCards.length > 0 && (
        <div>
          <p className="mb-3 text-[10px] uppercase tracking-[0.2em]" style={{ color: 'var(--fg-3)', fontFamily: MONO }}>
            The rest of your persona
          </p>
          <div className="grid grid-cols-2 items-start gap-3 sm:grid-cols-3">
            {lockedCards.map((c) => (
              <LockedCard key={c.label} label={c.label} detail={c.detail} teaser={c.teaser} />
            ))}
          </div>
        </div>
      )}

      <SignupWall context="reveal" />
    </div>
  );
}
