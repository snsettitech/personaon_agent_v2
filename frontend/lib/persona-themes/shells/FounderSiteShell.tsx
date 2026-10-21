'use client';

import { motion } from 'framer-motion';

import type { ThemeShellProps } from '../types';
import { readPublicFaq } from './public-faq';

// ---------------------------------------------------------------------------
// Local helpers
// ---------------------------------------------------------------------------

function getInitials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
}

/** "linkedin" → "LinkedIn" for the dark status chips / social row. */
function platformLabel(platform: string): string {
  return platform.charAt(0).toUpperCase() + platform.slice(1);
}

// The accent var the adapter injects on a wrapper above this shell. The hex
// fallback (founder-site's default signal blue) keeps the shell self-contained.
const ACCENT = 'var(--pon-accent, #0066cc)';
// Soft tint of the accent — color-mix degrades gracefully to the literal value
// in browsers without support (still on-brand).
const ACCENT_SOFT = 'color-mix(in srgb, var(--pon-accent, #0066cc) 14%, #ffffff)';

// Near-black hero ink (matches mockup --ink) and the light section base.
const INK = '#1d1d1f';

// Geometric / grotesque sans — system stack, no external webfonts.
const GROTESK_SANS =
  '"Inter","Helvetica Neue",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif';

// ---------------------------------------------------------------------------
// Founder-site shell ("Status Hero" — mockup direction A). A bold, dark
// full-bleed hero leads with avatar + name + headline + status chips (real
// social links only — the shell has no capability flags, so it asserts none);
// the opaque `interaction` console sits in a
// light "glass" card that pulls up over the hero's bottom edge so it's reachable
// in the first viewport. Below, a light section carries the work-experience
// timeline + expertise — each hidden when empty. Degrades gracefully: with no
// experience/expertise the hero + console alone still read strong.
// ---------------------------------------------------------------------------

export function FounderSiteShell({
  profile,
  interaction,
  visibility,
  mainStyle,
  slots,
}: ThemeShellProps) {
  const displayName = profile.name;
  const initials = getInitials(displayName) || 'P';

  // Hide-empty gating — canonical visibility keys paired with their fields.
  const showSocial =
    Boolean(visibility.social_links) && profile.socialLinks.length > 0;
  const showExperience =
    Boolean(visibility.work_experience) && profile.workExperience.length > 0;
  const showExpertise =
    Boolean(visibility.areas_of_expertise) && profile.expertise.length > 0;
  const showLowerSection = showExperience || showExpertise;
  // Owner-approved, crawlable Q&A — empty until the reviewed data pass wires it.
  const publicFaq = readPublicFaq(profile);
  const showFaq = publicFaq.length > 0;

  return (
    <div
      className="relative flex min-h-screen flex-col bg-[#e9e9ec] text-[#1d1d1f]"
      style={{ fontFamily: GROTESK_SANS }}
    >
      {slots?.topbar}

      <main
        className="relative z-10 flex-1 overflow-y-auto"
        style={mainStyle}
      >
        {/* ─── Dark full-bleed hero ──────────────────────────────────────────
            Sized (not 100vh) so the glass console below overlaps its bottom and
            is partly visible in the initial viewport. */}
        <section
          className="relative px-5 pt-12 pb-24 sm:px-8 sm:pt-16 sm:pb-28"
          style={{ backgroundColor: INK, color: '#ffffff' }}
        >
          <motion.div
            className="mx-auto flex w-full max-w-[920px] flex-col items-start gap-5 sm:flex-row sm:gap-6"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease: 'easeOut' }}
          >
            {/* Avatar */}
            <div
              className="flex h-[72px] w-[72px] flex-none items-center justify-center overflow-hidden rounded-[22px] text-2xl font-bold"
              style={{
                backgroundImage:
                  'linear-gradient(135deg, color-mix(in srgb, var(--pon-accent, #0066cc) 50%, transparent), rgba(255,255,255,0.14))',
                color: '#dce9ff',
              }}
            >
              {profile.avatarUrl ? (
                <img
                  src={profile.avatarUrl}
                  alt={displayName}
                  className="h-full w-full object-cover"
                />
              ) : (
                initials
              )}
            </div>

            {/* Identity + status chips */}
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <h1 className="text-[30px] font-bold leading-[1.05] tracking-[-0.03em] sm:text-[34px]">
                  {displayName}
                </h1>
                {profile.verified && (
                  <span
                    className="rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em]"
                    style={{ backgroundColor: ACCENT_SOFT, color: INK }}
                  >
                    Verified
                  </span>
                )}
              </div>
              {profile.headline && (
                <p className="mt-2 max-w-[600px] text-[15px] leading-relaxed text-[#b9b9c2]">
                  {profile.headline}
                </p>
              )}

              {/* Status chips — real social links only. The shell has no voice/
                  capability flag, so it never asserts one; the console surfaces
                  voice when available. Renders nothing when there are no socials. */}
              {showSocial && (
                <div className="mt-3.5 flex flex-wrap gap-2">
                  {profile.socialLinks.map((link) => (
                    <a
                      key={link.platform}
                      href={link.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="rounded-full border px-3 py-1.5 text-[12px] font-semibold transition hover:opacity-90"
                      style={{
                        backgroundColor: 'rgba(255,255,255,0.08)',
                        borderColor: 'rgba(255,255,255,0.14)',
                        color: '#e9e9ee',
                      }}
                    >
                      {platformLabel(link.platform)}
                    </a>
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        </section>

        {/* ─── Glass console card — pulls up over the hero's bottom edge ───────
            Holds the opaque `interaction` console (chat + Book + voice + chips),
            rendered EXACTLY ONCE. The negative margin overlaps the hero so the
            console is reachable in the initial viewport. */}
        <div className="relative z-20 mx-auto -mt-16 w-full max-w-[920px] px-5 sm:px-8">
          <div
            className="rounded-[18px] border bg-white p-3 shadow-[0_14px_40px_rgba(15,23,42,0.18)] sm:p-4"
            style={{ borderColor: 'rgba(29,29,31,0.10)' }}
          >
            <div className="mb-3 flex items-center gap-2">
              <span style={{ color: ACCENT }} className="text-lg leading-none">
                ◗
              </span>
              <span
                className="text-[11px] font-bold uppercase tracking-[0.14em]"
                style={{ color: ACCENT }}
              >
                Ask my persona anything
              </span>
            </div>
            {interaction}
          </div>
        </div>

        {/* ─── Light section: experience timeline + expertise ─────────────────
            Whole section hidden when both are empty/hidden. */}
        {showLowerSection && (
          <section className="mx-auto w-full max-w-[920px] px-5 pt-10 pb-12 sm:px-8">
            <div className="flex flex-col gap-9 sm:flex-row sm:gap-10">
              {showExperience && (
                <div className="flex-[1.3]">
                  <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.16em] text-[#8e8e93]">
                    Experience
                  </p>
                  <ol className="relative space-y-4 pl-5">
                    {profile.workExperience.map((job, i) => (
                      <li
                        key={`${job.company ?? ''}-${job.role ?? ''}-${i}`}
                        className="relative"
                      >
                        <span
                          aria-hidden
                          className="absolute left-[-20px] top-[6px] h-2 w-2 rounded-full"
                          style={{ backgroundColor: ACCENT }}
                        />
                        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
                          <p className="text-[14px] font-semibold text-[#1d1d1f]">
                            {job.role}
                            {job.role && job.company ? (
                              <span className="font-normal text-[#6e6e73]"> · </span>
                            ) : null}
                            <span className="font-medium text-[#6e6e73]">
                              {job.company}
                            </span>
                          </p>
                          {job.period && (
                            <p className="text-[11.5px] font-medium text-[#8e8e93]">
                              {job.period}
                            </p>
                          )}
                        </div>
                        {job.description && (
                          <p className="mt-1 text-[13px] leading-6 text-[#6e6e73]">
                            {job.description}
                          </p>
                        )}
                      </li>
                    ))}
                  </ol>
                </div>
              )}

              {showExpertise && (
                <div className="flex-1">
                  <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.16em] text-[#8e8e93]">
                    Expertise
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {profile.expertise.map((skill) => (
                      <span
                        key={skill}
                        className="rounded-full border bg-[#f5f5f7] px-3 py-1.5 text-[12px] font-semibold text-[#3a3a3c]"
                        style={{ borderColor: 'rgba(29,29,31,0.10)' }}
                      >
                        {skill}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </section>
        )}

        {/* ─── Questions {name} answers — owner-approved, crawlable Q&A ────────
            Server-rendered below the console (not inside it) so crawlers /
            answer engines read the answers in the raw HTML. */}
        {showFaq && (
          <section className="mx-auto w-full max-w-[920px] px-5 pt-4 pb-12 sm:px-8">
            <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.16em] text-[#8e8e93]">
              Questions {displayName} answers
            </p>
            <div className="space-y-5">
              {publicFaq.map((faq, i) => (
                <div key={i}>
                  <h3 className="text-[15px] font-semibold text-[#1d1d1f]">
                    {faq.question}
                  </h3>
                  <p className="mt-1 text-[13px] leading-6 text-[#6e6e73]">
                    {faq.answer}
                  </p>
                </div>
              ))}
            </div>
          </section>
        )}
      </main>

      {/* ─── Branding footer (frontend-coupled, injected by the adapter) ───── */}
      {slots?.branding}
    </div>
  );
}
