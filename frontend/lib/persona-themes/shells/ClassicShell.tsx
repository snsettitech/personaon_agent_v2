'use client';

import { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';

import type { ThemeShellProps } from '../types';
import { readPublicFaq } from './public-faq';

// ---------------------------------------------------------------------------
// Local helpers (moved verbatim from the legacy ProfileExperience chrome)
// ---------------------------------------------------------------------------

function getInitials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
}

function extractYouTubeId(url: string): string | null {
  const patterns = [
    /[?&]v=([^&#]+)/,
    /youtu\.be\/([^?&#]+)/,
    /\/embed\/([^?&#]+)/,
    /\/shorts\/([^?&#]+)/,
  ];
  for (const p of patterns) {
    const m = url.match(p);
    if (m?.[1]) return m[1];
  }
  return null;
}

function extractInstagramShortcode(url: string): { shortcode: string; embedType: string } | null {
  const patterns: Array<[RegExp, string]> = [
    [/instagram\.com\/p\/([^/?#]+)/, 'p'],
    [/instagram\.com\/reel\/([^/?#]+)/, 'reel'],
    [/instagram\.com\/tv\/([^/?#]+)/, 'tv'],
  ];
  for (const [pattern, embedType] of patterns) {
    const m = url.match(pattern);
    if (m?.[1]) return { shortcode: m[1], embedType };
  }
  return null;
}

// ---------------------------------------------------------------------------
// Classic shell — today's persona-page chrome. The interactive surface
// arrives via `interaction` (opaque); frontend-coupled widgets (topbar,
// branding footer, pre-chat voice) arrive via `slots`. Only this shell does the
// hero→chat collapse (`active`); other layouts ignore it.
//
// Accent-token parity (execution-board 0.3): Classic reads the owner's
// `--pon-accent` design token like every other shell, falling back to the
// legacy hardcoded blue (#0066cc) when the token is absent — so pages that
// never set an accent render byte-identical to before this fix.
//
// Browser-safety fallback (review fix): the four tint tokens below rely on
// color-mix(), which is unsupported on pre-Safari 16.2 / pre-Chrome 111 /
// pre-Firefox 113 (still present on some embedded webviews). On those
// browsers a bare `var(--classic-accent-*)` reference makes the *consuming*
// declaration invalid at computed-value time and renders nothing. To keep
// Classic guaranteed-renderable in any browser, CLASSIC_ACCENT_STYLE_TAG
// below defines static rgba(#0066cc, …) fallback rules first, then upgrades
// them to the dynamic color-mix()-derived tokens inside an `@supports`
// feature query only when the browser can evaluate color-mix().
// ---------------------------------------------------------------------------

const CLASSIC_ACCENT_VARS: React.CSSProperties = {
  ['--classic-accent' as string]: 'var(--pon-accent, #0066cc)',
  ['--classic-accent-soft' as string]: 'color-mix(in srgb, var(--pon-accent, #0066cc) 10%, transparent)',
  ['--classic-accent-wash' as string]: 'color-mix(in srgb, var(--pon-accent, #0066cc) 18%, transparent)',
  ['--classic-accent-ring' as string]: 'color-mix(in srgb, var(--pon-accent, #0066cc) 12%, transparent)',
  ['--classic-accent-dot' as string]: 'color-mix(in srgb, var(--pon-accent, #0066cc) 80%, transparent)',
};

// Scoped to `.personaon-classic-shell` so these rules never leak to other
// shells. Fallback values match the legacy static #0066cc constants this
// shell used before accent-token parity was introduced.
const CLASSIC_ACCENT_STYLE_TAG = `
  .personaon-classic-shell .classic-accent-glow {
    background: rgba(0, 102, 204, 0.10);
  }
  .personaon-classic-shell .classic-avatar-frame {
    background: linear-gradient(135deg, rgba(0, 102, 204, 0.18), rgba(255, 255, 255, 0.96));
    box-shadow: 0 18px 40px rgba(0, 102, 204, 0.12), 0 0 0 1px rgba(0, 102, 204, 0.12);
  }
  .personaon-classic-shell .classic-timeline-dot {
    background-color: rgba(0, 102, 204, 0.8);
  }
  @supports (color: color-mix(in srgb, red 50%, blue)) {
    .personaon-classic-shell .classic-accent-glow {
      background: radial-gradient(circle at 50% 0%, var(--classic-accent-soft), transparent 60%);
    }
    .personaon-classic-shell .classic-avatar-frame {
      background: linear-gradient(135deg, var(--classic-accent-wash), rgba(255, 255, 255, 0.96));
      box-shadow: 0 18px 40px var(--classic-accent-ring), 0 0 0 1px var(--classic-accent-ring);
    }
    .personaon-classic-shell .classic-timeline-dot {
      background-color: var(--classic-accent-dot);
    }
  }
`;

export function ClassicShell({
  profile,
  interaction,
  visibility,
  active = false,
  mainStyle,
  slots,
}: ThemeShellProps) {
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [shareCopied, setShareCopied] = useState(false);
  const [shareQrVisible, setShareQrVisible] = useState(false);
  const [instaLightbox, setInstaLightbox] = useState<{ src: string; title: string } | null>(null);

  const displayName = profile.name;
  const headline = profile.headline;
  const avatarSrc = profile.avatarUrl;
  const initials = getInitials(displayName) || 'P';

  const hasAbout =
    (visibility.areas_of_expertise && profile.expertise.length > 0) ||
    (visibility.key_achievements && profile.achievements.length > 0) ||
    (visibility.personality_traits && profile.traits.length > 0) ||
    (visibility.contributions && profile.contributions.length > 0) ||
    (visibility.education && profile.education.length > 0);

  // Owner-approved, crawlable Q&A — empty until the reviewed data pass wires it.
  const publicFaq = readPublicFaq(profile);

  return (
    <div
      className="personaon-classic-shell relative h-screen flex flex-col overflow-hidden bg-[#f5f5f7]"
      style={CLASSIC_ACCENT_VARS}
    >
      {/* Browser-safety fallback for the color-mix()-derived accent tints — see
          CLASSIC_ACCENT_STYLE_TAG comment above for why this can't be inline style. */}
      <style>{CLASSIC_ACCENT_STYLE_TAG}</style>

      {/* Accent radial gradient at top — reads --pon-accent via --classic-accent-soft,
          with a static rgba(#0066cc) fallback for browsers without color-mix() support. */}
      <div className="classic-accent-glow pointer-events-none absolute inset-x-0 top-0 h-72" />

      {slots?.topbar}

      {/* ─── Main content ─────────────────────────────────────────────────── */}
      <main className="relative z-10 flex-1 flex flex-col overflow-hidden" style={mainStyle}>

        {/* ── Initial hero state ── */}
        <AnimatePresence mode="wait">
        {!active && (
          <motion.div
            key="hero"
            className="flex-1 overflow-y-auto"
            exit={{ opacity: 0, y: -16, transition: { duration: 0.22, ease: 'easeIn' } }}
          >
            <motion.div
              className="mx-auto w-full max-w-[880px] px-4 pt-20 pb-6 sm:pt-24 md:px-6"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.35, ease: 'easeOut' }}
            >
              {/* Share modal */}
              {shareModalOpen && (
                <div
                  className="fixed inset-0 z-50 flex items-end justify-center sm:items-center p-4"
                  onClick={(e) => { if (e.target === e.currentTarget) { setShareModalOpen(false); setShareQrVisible(false); } }}
                >
                  {/* Backdrop */}
                  <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" />

                  {/* Panel */}
                  <div className="relative w-full max-w-md rounded-[28px] border border-black/8 bg-white/95 p-6 shadow-[0_24px_80px_rgba(15,23,42,0.20)] backdrop-blur-xl">
                    {/* Header */}
                    <div className="flex items-center justify-between mb-5">
                      <h2 className="text-base font-semibold text-[#111111]">Share this profile</h2>
                      <button
                        onClick={() => { setShareModalOpen(false); setShareQrVisible(false); }}
                        className="flex h-7 w-7 items-center justify-center rounded-full bg-black/6 text-[#6e6e73] hover:bg-black/10 transition"
                        aria-label="Close"
                      >
                        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
                      </button>
                    </div>

                    {/* URL row */}
                    <div className="break-all rounded-2xl border border-black/8 bg-[#f5f5f7] px-4 py-3 font-mono text-xs text-[#3a3a3c] mb-3">
                      {window.location.href}
                    </div>

                    {/* Action buttons */}
                    <div className="flex gap-2">
                      <button
                        onClick={() => {
                          navigator.clipboard.writeText(window.location.href).catch(() => {});
                          setShareCopied(true);
                          setTimeout(() => setShareCopied(false), 2000);
                        }}
                        className={`flex-1 rounded-2xl py-3 text-sm font-semibold transition-colors ${
                          shareCopied ? 'bg-emerald-500 text-white' : 'bg-[#1d1d1f] text-white hover:bg-black'
                        }`}
                      >
                        {shareCopied ? 'Copied!' : 'Copy Link'}
                      </button>
                      <button
                        onClick={() => setShareQrVisible((v) => !v)}
                        className="rounded-2xl border border-black/10 bg-white px-4 py-3 text-sm font-semibold text-[#1d1d1f] hover:bg-[#f5f5f7] transition"
                      >
                        QR
                      </button>
                    </div>

                    {/* QR code */}
                    {shareQrVisible && (
                      <div className="mt-4 rounded-[20px] border border-black/8 bg-[#f5f5f7] p-5 flex flex-col items-center">
                        <div className="rounded-2xl border border-black/8 bg-white p-2">
                          <img
                            src={`https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(window.location.href)}`}
                            alt="QR Code"
                            className="h-44 w-44"
                          />
                        </div>
                        <p className="mt-3 text-xs text-[#6e6e73]">Scan to open this profile</p>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* ── Main profile card (mirrors share page preview) ── */}
              <div className="relative rounded-[32px] border border-black/8 bg-white/80 p-6 shadow-[0_10px_40px_rgba(15,23,42,0.07)] backdrop-blur-xl mb-5 md:p-8">
                {/* Share button — top-right of the card */}
                <button
                  onClick={() => setShareModalOpen(true)}
                  aria-label="Share this profile"
                  className="absolute top-4 right-4 z-10 flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-full border border-black/10 bg-white/85 text-[#6e6e73] shadow-sm transition hover:bg-white hover:text-[#111111] backdrop-blur"
                >
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" /></svg>
                  <span className="hidden sm:inline">Share</span>
                </button>
                <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:gap-7">
                  {/* Avatar — gradient, text, and ring all derive from --classic-accent.
                      Background/shadow come from the classic-avatar-frame class (see
                      CLASSIC_ACCENT_STYLE_TAG) so pre-color-mix() browsers fall back to
                      the static rgba(#0066cc) rule instead of rendering nothing. */}
                  <div
                    className="classic-avatar-frame shrink-0 h-24 w-24 overflow-hidden rounded-[28px] self-start"
                    style={{
                      color: 'var(--classic-accent)',
                    }}
                  >
                    {avatarSrc
                      ? <img src={avatarSrc} alt={displayName} className="h-full w-full object-cover" />
                      : <div className="flex h-full w-full items-center justify-center text-2xl font-semibold">{initials}</div>}
                  </div>

                  {/* Name / headline / bio block */}
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2 mb-1">
                      <h1 className="text-3xl font-semibold tracking-[-0.03em] text-[#111111] md:text-4xl">{displayName}</h1>
                      {profile.verified && (
                        <span className="rounded-full bg-emerald-50 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-700">Verified</span>
                      )}
                    </div>
                    {headline && (
                      <p className="text-base text-[#6e6e73] mb-1">{headline}</p>
                    )}
                    {profile.lifeLine && (
                      <p className="text-sm text-[#8e8e93] mb-3">{profile.lifeLine}</p>
                    )}
                    {profile.bio && (
                      <p className="text-sm leading-relaxed text-[#3a3a3f]">{profile.bio}</p>
                    )}

                    {/* Social links */}
                    {visibility.social_links && profile.socialLinks.length > 0 && (
                      <div className="mt-4 flex flex-wrap gap-2">
                        {profile.socialLinks.map((link) => (
                          <a
                            key={link.platform}
                            href={link.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs font-semibold px-3 py-1.5 rounded-full border border-black/8 bg-[#f5f5f7] text-[var(--classic-accent)] transition hover:bg-white"
                          >
                            {link.platform.charAt(0).toUpperCase() + link.platform.slice(1)} ↗
                          </a>
                        ))}
                      </div>
                    )}

                    {/* Voice call (pre-chat) — frontend-coupled, injected by the adapter */}
                    {slots?.heroAside}
                  </div>
                </div>
              </div>


              {/* ── Featured content ── */}
              {visibility.featured_content && profile.featured.length > 0 && (
                <div className="mb-5">
                  <h3 className="mb-4 text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">Featured</h3>
                  <div className="grid gap-4 sm:grid-cols-2">
                    {profile.featured.map((item, i) => {
                      if (item.type === 'youtube') {
                        const videoId = extractYouTubeId(item.url);
                        if (!videoId) return null;
                        return (
                          <div key={i} className="overflow-hidden rounded-[20px] border border-slate-200 bg-white shadow-sm h-[320px]">
                            <iframe
                              src={`https://www.youtube.com/embed/${videoId}`}
                              title={item.title || 'YouTube video'}
                              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                              allowFullScreen
                              className="h-full w-full"
                            />
                          </div>
                        );
                      }
                      // Instagram — embedded iframe preview
                      if (item.type === 'instagram') {
                        const instaData = extractInstagramShortcode(item.url);
                        if (instaData) {
                          const embedSrc = `https://www.instagram.com/${instaData.embedType}/${instaData.shortcode}/embed/`;
                          const embedTitle = item.title || 'Instagram post';
                          return (
                            <div key={i} className="relative overflow-hidden rounded-[20px] border border-slate-200 bg-white shadow-sm h-[320px] group cursor-pointer">
                              <iframe
                                src={embedSrc}
                                title={embedTitle}
                                scrolling="no"
                                className="h-full w-full pointer-events-none"
                                style={{ border: 'none' }}
                              />
                              {/* Transparent click interceptor — captures clicks the iframe would swallow */}
                              <div
                                className="absolute inset-0"
                                onClick={() => setInstaLightbox({ src: embedSrc, title: embedTitle })}
                                aria-label="View full post"
                                role="button"
                              />
                            </div>
                          );
                        }
                      }
                      // Generic link card
                      const safeUrl = /^https?:\/\//i.test(item.url) ? item.url : `https://${item.url}`;
                      let domain = '';
                      try { domain = new URL(safeUrl).hostname.replace('www.', ''); } catch { domain = item.url; }
                      return (
                        <a
                          key={i}
                          href={safeUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex h-[320px] items-center gap-4 rounded-[20px] border border-slate-200 bg-white p-5 shadow-sm transition hover:border-slate-300 hover:shadow-md"
                        >
                          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-xl">
                            🔗
                          </div>
                          <div className="min-w-0">
                            <p className="truncate text-sm font-semibold text-[#111111]">
                              {item.title || domain}
                            </p>
                            <p className="truncate text-xs text-slate-500 mt-0.5">{domain}</p>
                          </div>
                          <svg className="ml-auto h-4 w-4 shrink-0 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" /></svg>
                        </a>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* ── EXPERIENCE: the heart of the portfolio — full-width timeline ── */}
              {visibility.work_experience && profile.workExperience.length > 0 && (
                <>
                  <h3 className="mb-4 text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">Experience</h3>
                  <section className="mb-5 rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
                    <ol className="space-y-6">
                      {profile.workExperience.map((job, i) => (
                        <li key={`${job.company ?? ''}-${job.role ?? ''}-${i}`} className="relative pl-6">
                          <span
                            aria-hidden
                            className="classic-timeline-dot absolute left-0 top-[7px] h-2.5 w-2.5 rounded-full"
                          />
                          {i < profile.workExperience.length - 1 && (
                            <span aria-hidden className="absolute left-[4px] top-[22px] bottom-[-18px] w-px bg-slate-200" />
                          )}
                          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
                            <p className="text-[15px] font-semibold text-slate-900">
                              {job.role}
                              {job.role && job.company ? <span className="font-normal text-slate-500"> · </span> : null}
                              <span className="font-medium text-slate-600">{job.company}</span>
                            </p>
                            {job.period && (
                              <p className="text-xs font-medium text-slate-400">{job.period}</p>
                            )}
                          </div>
                          {job.description && (
                            <p className="mt-1 text-sm leading-6 text-slate-600">{job.description}</p>
                          )}
                        </li>
                      ))}
                    </ol>
                  </section>
                </>
              )}

              {/* ── ABOUT section header ── */}
              {hasAbout && (
                <>
                  <h3 className="mb-4 text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">About</h3>
                  <div className="grid gap-6 sm:grid-cols-2 mb-5">
                    {visibility.education && profile.education.length > 0 && (
                      <section className="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
                        <h3 className="mb-4 text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">Education</h3>
                        <ul className="space-y-3">
                          {profile.education.map((edu, i) => (
                            <li key={`${edu.institution ?? ''}-${i}`}>
                              <p className="text-sm font-semibold text-slate-900">{edu.institution}</p>
                              <p className="text-sm text-slate-600">
                                {[edu.degree, edu.field].filter(Boolean).join(', ')}
                                {edu.period && (
                                  <span className="text-slate-400"> · {edu.period}</span>
                                )}
                              </p>
                            </li>
                          ))}
                        </ul>
                      </section>
                    )}
                    {visibility.areas_of_expertise && profile.expertise.length > 0 && (
                      <section className="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
                        <h3 className="mb-4 text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">Areas of Expertise</h3>
                        <div className="flex flex-wrap gap-2">
                          {profile.expertise.map((skill) => (
                            <span key={skill} className="rounded-full bg-slate-100 px-3 py-1.5 text-sm text-slate-700">
                              {skill}
                            </span>
                          ))}
                        </div>
                      </section>
                    )}

                    {visibility.key_achievements && profile.achievements.length > 0 && (
                      <section className="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
                        <h3 className="mb-4 text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">Key Achievements</h3>
                        <div className="flex flex-wrap gap-2">
                          {profile.achievements.slice(0, 6).map((ach, i) => (
                            <span key={i} className="rounded-full bg-slate-100 px-3 py-1.5 text-sm text-slate-700">
                              {ach}
                            </span>
                          ))}
                        </div>
                      </section>
                    )}

                    {visibility.personality_traits && profile.traits.length > 0 && (
                      <section className="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
                        <h3 className="mb-4 text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">Personality Traits</h3>
                        <div className="flex flex-wrap gap-2">
                          {profile.traits.map((trait) => (
                            <span key={trait} className="rounded-full bg-slate-100 px-3 py-1.5 text-sm text-slate-700">
                              {trait}
                            </span>
                          ))}
                        </div>
                      </section>
                    )}

                    {visibility.contributions && profile.contributions.length > 0 && (
                      <section className="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
                        <h3 className="mb-4 text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">Contributions</h3>
                        <div className="flex flex-wrap gap-2">
                          {profile.contributions.slice(0, 6).map((c, i) => (
                            <span key={i} className="rounded-full bg-slate-100 px-3 py-1.5 text-sm text-slate-700">
                              {c}
                            </span>
                          ))}
                        </div>
                      </section>
                    )}
                  </div>
                </>
              )}

              {/* ── Questions {name} answers — owner-approved, crawlable Q&A ──
                  Server-rendered in the initial hero HTML (not behind the chat
                  console) so crawlers / answer engines read the answers raw. */}
              {publicFaq.length > 0 && (
                <>
                  <h3 className="mb-4 text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">
                    Questions {displayName} answers
                  </h3>
                  <section className="mb-5 rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
                    <div className="space-y-6">
                      {publicFaq.map((faq, i) => (
                        <div
                          key={i}
                          className={i > 0 ? 'border-t border-slate-100 pt-6' : undefined}
                        >
                          <h3 className="text-[15px] font-semibold text-slate-900">{faq.question}</h3>
                          <p className="mt-1.5 text-sm leading-6 text-slate-600">{faq.answer}</p>
                        </div>
                      ))}
                    </div>
                  </section>
                </>
              )}
            </motion.div>
          </motion.div>
        )}
        </AnimatePresence>

        {/* ── Interactive console (opaque slot) ── */}
        {interaction}
      </main>

      {/* ─── Branding footer (frontend-coupled, injected by the adapter) ───── */}
      {slots?.branding}

      {/* ─── Instagram lightbox ───────────────────────────────────────────── */}
      {instaLightbox && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
          onClick={() => setInstaLightbox(null)}
        >
          <div
            className="relative w-full max-w-sm rounded-[28px] overflow-hidden shadow-[0_32px_80px_rgba(0,0,0,0.40)]"
            onClick={(e) => e.stopPropagation()}
          >
            <iframe
              src={instaLightbox.src}
              title={instaLightbox.title}
              scrolling="no"
              className="w-full"
              style={{ height: '620px', border: 'none', display: 'block' }}
            />
            <button
              onClick={() => setInstaLightbox(null)}
              aria-label="Close"
              className="absolute top-3 right-3 flex h-8 w-8 items-center justify-center rounded-full bg-black/60 text-white backdrop-blur hover:bg-black/80 transition"
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
