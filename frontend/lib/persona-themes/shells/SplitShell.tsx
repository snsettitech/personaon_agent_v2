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

/** "linkedin" → "LinkedIn" for the rail's social link row. */
function platformLabel(platform: string): string {
  return platform.charAt(0).toUpperCase() + platform.slice(1);
}

// The accent var the adapter injects on a wrapper above this shell. The hex
// fallback (split's default signal blue) keeps the shell self-contained.
const ACCENT = 'var(--pon-accent, #0066cc)';
// Soft tint of the accent — color-mix degrades gracefully to the literal value
// in browsers without support (still on-brand).
const ACCENT_WASH = 'color-mix(in srgb, var(--pon-accent, #0066cc) 18%, #ffffff)';

// Neutral light rail base (matches mockup --fog) and hairline divider color.
const RAIL_BG = '#f5f5f7';
const LINE = 'rgba(29,29,31,0.10)';

// Neutral system sans — no external webfonts.
const NEUTRAL_SANS =
  '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif';

// ---------------------------------------------------------------------------
// Split Sidebar shell (mockup direction C). Desktop: a fixed/sticky LEFT
// identity rail (calm neutral panel) holds avatar + name + headline + social
// links + the opaque `interaction` console (chat + Book + voice live inside it),
// while a RIGHT column scrolls through work-experience → expertise → education.
// Mobile: stacks — the rail (identity + console) sits on top so the console is in
// the first viewport, content below. Each right-column section is hidden when
// empty/hidden; with a thin profile the rail alone still reads strong. The
// console is rendered EXACTLY ONCE and positioned via responsive CSS.
// ---------------------------------------------------------------------------

export function SplitShell({
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
  const showEducation =
    Boolean(visibility.education) && profile.education.length > 0;
  // Owner-approved, crawlable Q&A — empty until the reviewed data pass wires it.
  const publicFaq = readPublicFaq(profile);
  const showFaq = publicFaq.length > 0;
  const showRightColumn = showExperience || showExpertise || showEducation || showFaq;

  return (
    <div
      className="relative flex min-h-screen flex-col text-[#1d1d1f]"
      style={{ backgroundColor: '#ffffff', fontFamily: NEUTRAL_SANS }}
    >
      {slots?.topbar}

      <main
        className="relative z-10 flex flex-1 flex-col overflow-y-auto lg:flex-row lg:overflow-visible"
        style={mainStyle}
      >
        {/* ─── LEFT identity rail ──────────────────────────────────────────────
            Mobile: a full-width block stacked on top (so the console is in the
            first viewport). Desktop (lg+): a fixed-width neutral panel pinned to
            the top of the viewport via `sticky` while the right column scrolls. */}
        <aside
          className="w-full flex-none border-b px-6 py-7 lg:w-[320px] lg:self-start lg:border-b-0 lg:border-r lg:px-6 lg:py-8 lg:sticky lg:top-0 lg:max-h-screen lg:overflow-y-auto"
          style={{ backgroundColor: RAIL_BG, borderColor: LINE }}
        >
          <motion.div
            className="mx-auto w-full max-w-[520px] lg:max-w-none"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease: 'easeOut' }}
          >
            {/* Avatar */}
            <div
              className="flex h-[62px] w-[62px] flex-none items-center justify-center overflow-hidden rounded-[20px] text-xl font-bold"
              style={{
                backgroundImage: `linear-gradient(135deg, ${ACCENT_WASH}, rgba(255,255,255,0.96))`,
                color: ACCENT,
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

            {/* Identity — name + verified + headline */}
            <div className="mt-3.5 flex flex-wrap items-center gap-x-2 gap-y-1.5">
              <h1 className="text-[23px] font-bold leading-[1.1] tracking-[-0.02em]">
                {displayName}
              </h1>
              {profile.verified && (
                <span
                  className="rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em]"
                  style={{ backgroundColor: ACCENT_WASH, color: ACCENT }}
                >
                  Verified
                </span>
              )}
            </div>
            {profile.headline && (
              <p className="mt-1.5 text-[13.5px] leading-relaxed text-[#6e6e73]">
                {profile.headline}
              </p>
            )}

            {/* Social links — hidden when empty */}
            {showSocial && (
              <div className="mt-3 flex flex-wrap gap-2">
                {profile.socialLinks.map((link) => (
                  <a
                    key={link.platform}
                    href={link.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="rounded-full border bg-white px-3 py-1.5 text-[12px] font-semibold text-[#3a3a3c] transition hover:opacity-90"
                    style={{ borderColor: LINE }}
                  >
                    {platformLabel(link.platform)}
                  </a>
                ))}
              </div>
            )}

            {/* ── Interactive console (opaque slot) — rendered EXACTLY ONCE ──
                Holds chat + Book + voice + suggestion chips internally; the shell
                adds none of its own. Always present so the rail never looks empty
                even on a thin profile. */}
            <div className="mt-5">
              <div className="mb-2.5 flex items-center gap-2">
                <span style={{ color: ACCENT }} className="text-base leading-none">
                  ◗
                </span>
                <span
                  className="text-[10px] font-bold uppercase tracking-[0.14em]"
                  style={{ color: ACCENT }}
                >
                  Talk to my persona
                </span>
              </div>
              {interaction}
            </div>

            {/* Branding footer — rail bottom (frontend-coupled, adapter-injected) */}
            {slots?.branding}
          </motion.div>
        </aside>

        {/* ─── RIGHT scrolling content column ──────────────────────────────────
            Work-experience → expertise → education. Each section is hidden when
            empty/hidden; the whole column collapses to nothing on a thin profile
            (the rail stands alone). No placeholders, ever. */}
        {showRightColumn && (
          <div className="min-w-0 flex-1 px-6 py-8 sm:px-8 lg:px-10">
            <div className="mx-auto w-full max-w-[680px] lg:mx-0">
              {showExperience && (
                <section className="mb-9">
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
                </section>
              )}

              {showExpertise && (
                <section className="mb-9">
                  <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.16em] text-[#8e8e93]">
                    Expertise
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {profile.expertise.map((skill) => (
                      <span
                        key={skill}
                        className="rounded-full border px-3 py-1.5 text-[12px] font-semibold text-[#3a3a3c]"
                        style={{ backgroundColor: RAIL_BG, borderColor: LINE }}
                      >
                        {skill}
                      </span>
                    ))}
                  </div>
                </section>
              )}

              {showEducation && (
                <section className="mb-9">
                  <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.16em] text-[#8e8e93]">
                    Education
                  </p>
                  <ul className="space-y-3">
                    {profile.education.map((edu, i) => (
                      <li key={`${edu.institution ?? ''}-${i}`}>
                        <p className="text-[14px] font-semibold text-[#1d1d1f]">
                          {edu.institution}
                        </p>
                        <p className="text-[13px] text-[#6e6e73]">
                          {[edu.degree, edu.field].filter(Boolean).join(', ')}
                          {edu.period && (
                            <span className="text-[#8e8e93]"> · {edu.period}</span>
                          )}
                        </p>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {/* ── Questions {name} answers — owner-approved, crawlable Q&A ──
                  Server-rendered in the content column so answer engines read
                  it raw (not behind the persona console). */}
              {showFaq && (
                <section className="mb-9">
                  <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.16em] text-[#8e8e93]">
                    Questions {displayName} answers
                  </p>
                  <div className="space-y-5">
                    {publicFaq.map((faq, i) => (
                      <div key={i}>
                        <h3 className="text-[14px] font-semibold text-[#1d1d1f]">
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
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
