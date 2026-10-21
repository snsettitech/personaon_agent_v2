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

/** "linkedin" → "LinkedIn" for the social chip row. */
function platformLabel(platform: string): string {
  return platform.charAt(0).toUpperCase() + platform.slice(1);
}

// The accent var the adapter injects on a wrapper above this shell. The hex
// fallback (editorial's default slate) keeps the shell self-contained. Slate is
// quiet by design — editorial uses the accent sparingly (timeline dots, console
// title, link arrows), never as a fill.
const ACCENT = 'var(--pon-accent, #475569)';

// Serif display stack for headings (name + section labels) and system sans for
// body — both pinned via fontFamily, no external webfonts.
const SERIF =
  'Iowan Old Style, Charter, Georgia, "Times New Roman", serif';
const SANS =
  '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif';

// ---------------------------------------------------------------------------
// Editorial-portfolio shell (mockup direction B). Light, typographic,
// credibility-first: a big serif name + lede bio, then a 2-column body where the
// work-experience timeline is the magazine-like SPINE (left, prominent) with
// expertise + education below it, and the opaque `interaction` console lives in a
// calm STICKY panel on the right that stays in view as the spine scrolls.
//
// The console is rendered EXACTLY ONCE. On desktop it sits in the right column
// (visible in the first viewport, sticky). On mobile the grid collapses to one
// column and CSS `order` docks the console ABOVE the spine content (after the
// name/bio), so it's reachable in the first viewport without rendering twice.
//
// Hide-empty throughout: timeline / expertise / education each render only when
// non-empty AND visible. With a thin profile the serif name + bio + console
// alone still read well.
// ---------------------------------------------------------------------------

export function EditorialShell({
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
  const showSpine = showExperience || showExpertise || showEducation || showFaq;

  const sectionLabel =
    'text-[11px] font-bold uppercase tracking-[0.16em] text-[#8e8e93]';

  return (
    <div
      className="relative flex min-h-screen flex-col bg-white text-[#1d1d1f]"
      style={{ fontFamily: SANS }}
    >
      {slots?.topbar}

      <main className="relative z-10 flex-1 overflow-y-auto" style={mainStyle}>
        <motion.div
          className="mx-auto w-full max-w-[1040px] px-6 pt-12 pb-16 sm:px-10 sm:pt-16"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: 'easeOut' }}
        >
          {/* ─── Masthead: avatar + big serif name + lede bio + social chips ─── */}
          <header className="max-w-[680px]">
            <div
              className="mb-5 flex h-[58px] w-[58px] flex-none items-center justify-center overflow-hidden rounded-[20px] text-lg font-bold"
              style={{
                backgroundImage:
                  'linear-gradient(135deg, color-mix(in srgb, var(--pon-accent, #475569) 18%, #ffffff), rgba(255,255,255,0.96))',
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

            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <h1
                className="text-[40px] font-semibold leading-[1.03] tracking-[-0.02em] sm:text-[44px]"
                style={{ fontFamily: SERIF }}
              >
                {displayName}
              </h1>
              {profile.verified && (
                <span
                  className="rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em]"
                  style={{
                    backgroundColor:
                      'color-mix(in srgb, var(--pon-accent, #475569) 12%, #ffffff)',
                    color: ACCENT,
                  }}
                >
                  Verified
                </span>
              )}
            </div>

            {profile.headline && (
              <p className="mt-2.5 text-[16px] text-[#6e6e73]">
                {profile.headline}
              </p>
            )}
            {profile.bio && (
              <p className="mt-4 text-[16.5px] leading-relaxed text-[#3a3a3f]">
                {profile.bio}
              </p>
            )}

            {showSocial && (
              <div className="mt-5 flex flex-wrap gap-2">
                {profile.socialLinks.map((link) => (
                  <a
                    key={link.platform}
                    href={link.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="rounded-full border bg-[#f5f5f7] px-3 py-1.5 text-[12px] font-semibold text-[#3a3a3c] transition hover:bg-white"
                    style={{ borderColor: 'rgba(29,29,31,0.10)' }}
                  >
                    {platformLabel(link.platform)}{' '}
                    <span style={{ color: ACCENT }}>↗</span>
                  </a>
                ))}
              </div>
            )}
          </header>

          {/* ─── 2-column body ──────────────────────────────────────────────
              Desktop: spine (left, flex-[1.5]) + sticky console (right). Mobile:
              single column with `order` docking the console above the spine. */}
          <div className="mt-9 flex flex-col gap-9 lg:mt-12 lg:flex-row lg:gap-12">
            {/* SPINE — the magazine-like content column. Hidden entirely when a
                thin profile has nothing to show. */}
            {showSpine && (
              <div className="order-2 min-w-0 flex-[1.5] lg:order-1">
                {showExperience && (
                  <section className="border-t pt-7" style={{ borderColor: 'rgba(29,29,31,0.10)' }}>
                    <p className={`mb-5 ${sectionLabel}`}>Experience</p>
                    <ol className="relative space-y-7 pl-5">
                      {profile.workExperience.map((job, i) => (
                        <li
                          key={`${job.company ?? ''}-${job.role ?? ''}-${i}`}
                          className="relative"
                        >
                          <span
                            aria-hidden
                            className="absolute left-[-20px] top-[7px] h-2 w-2 rounded-full"
                            style={{ backgroundColor: ACCENT }}
                          />
                          {i < profile.workExperience.length - 1 && (
                            <span
                              aria-hidden
                              className="absolute left-[-17px] top-[19px] bottom-[-28px] w-px"
                              style={{ backgroundColor: 'rgba(29,29,31,0.10)' }}
                            />
                          )}
                          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
                            <p
                              className="text-[17px] font-semibold tracking-[-0.01em] text-[#1d1d1f]"
                              style={{ fontFamily: SERIF }}
                            >
                              {job.role}
                              {job.role && job.company ? (
                                <span className="font-normal text-[#6e6e73]"> · </span>
                              ) : null}
                              <span className="font-medium text-[#6e6e73]">
                                {job.company}
                              </span>
                            </p>
                            {job.period && (
                              <p className="text-[12px] font-medium text-[#8e8e93]">
                                {job.period}
                              </p>
                            )}
                          </div>
                          {job.description && (
                            <p className="mt-1.5 text-[14px] leading-7 text-[#52525b]">
                              {job.description}
                            </p>
                          )}
                        </li>
                      ))}
                    </ol>
                  </section>
                )}

                {showExpertise && (
                  <section className="mt-9 border-t pt-7" style={{ borderColor: 'rgba(29,29,31,0.10)' }}>
                    <p className={`mb-4 ${sectionLabel}`}>Expertise</p>
                    <div className="flex flex-wrap gap-2">
                      {profile.expertise.map((skill) => (
                        <span
                          key={skill}
                          className="rounded-full border bg-[#f5f5f7] px-3 py-1.5 text-[12.5px] font-semibold text-[#3a3a3c]"
                          style={{ borderColor: 'rgba(29,29,31,0.10)' }}
                        >
                          {skill}
                        </span>
                      ))}
                    </div>
                  </section>
                )}

                {showEducation && (
                  <section className="mt-9 border-t pt-7" style={{ borderColor: 'rgba(29,29,31,0.10)' }}>
                    <p className={`mb-4 ${sectionLabel}`}>Education</p>
                    <ul className="space-y-3.5">
                      {profile.education.map((edu, i) => (
                        <li key={`${edu.institution ?? ''}-${i}`}>
                          <p
                            className="text-[15px] font-semibold tracking-[-0.01em] text-[#1d1d1f]"
                            style={{ fontFamily: SERIF }}
                          >
                            {edu.institution}
                          </p>
                          <p className="text-[13.5px] text-[#6e6e73]">
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
                    Server-rendered in the spine so answer engines read it raw. */}
                {showFaq && (
                  <section
                    className={`${showExperience || showExpertise || showEducation ? 'mt-9 ' : ''}border-t pt-7`}
                    style={{ borderColor: 'rgba(29,29,31,0.10)' }}
                  >
                    <p className={`mb-5 ${sectionLabel}`}>Questions {displayName} answers</p>
                    <div className="space-y-6">
                      {publicFaq.map((faq, i) => (
                        <div key={i}>
                          <h3
                            className="text-[16px] font-semibold tracking-[-0.01em] text-[#1d1d1f]"
                            style={{ fontFamily: SERIF }}
                          >
                            {faq.question}
                          </h3>
                          <p className="mt-1.5 text-[14px] leading-7 text-[#52525b]">
                            {faq.answer}
                          </p>
                        </div>
                      ))}
                    </div>
                  </section>
                )}
              </div>
            )}

            {/* CONSOLE — opaque `interaction`, rendered EXACTLY ONCE. Right column
                on desktop (sticky, first-viewport), docked above the spine on
                mobile via `order-1`. The shell adds no chat/Book/voice of its own. */}
            <aside className="order-1 w-full flex-none lg:order-2 lg:w-[360px] lg:self-start">
              <div className="lg:sticky lg:top-6">
                <div
                  className="rounded-[18px] border bg-white p-4 shadow-[0_14px_40px_rgba(15,23,42,0.10)]"
                  style={{ borderColor: 'rgba(29,29,31,0.10)' }}
                >
                  <div className="mb-3 flex items-center gap-2">
                    <span style={{ color: ACCENT }} className="text-[17px] leading-none">
                      ◗
                    </span>
                    <span
                      className="text-[11px] font-bold uppercase tracking-[0.14em]"
                      style={{ color: ACCENT }}
                    >
                      Chat with my persona
                    </span>
                  </div>
                  {interaction}
                </div>
              </div>
            </aside>
          </div>
        </motion.div>
      </main>

      {/* ─── Branding footer (frontend-coupled, injected by the adapter) ───── */}
      {slots?.branding}
    </div>
  );
}
