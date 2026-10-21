'use client';

// ===========================================================================
// SiteShell — the `site` theme. Renders the persona page in the premium
// editorial style of the standalone personaon-sites app (warm paper, Fraunces
// display serif, generous spacing, card hover lifts), but as a pure-
// presentational shell conforming to the ThemeShellProps contract.
//
// TOKEN SCOPING: every editorial color/font lives as a `--site-*` CSS custom
// property defined ONLY on this shell's `.persona-theme-site` root wrapper (see
// `siteTokens` below). The shell and its primitives consume those vars via
// Tailwind arbitrary-value utilities (`bg-[var(--site-paper)]`, …). Nothing
// leaks: no global Tailwind color utilities, no edits to globals.css, and the
// vars are inherited only by descendants of this wrapper. `--site-accent` is
// wired to the adapter-provided `--pon-accent` so the 6-swatch accent picker
// keeps working.
//
// The opaque `interaction` console is rendered EXACTLY ONCE, inline, inside an
// anchored card. The shell adds no chat/voice of its own; "Ask my persona"
// affordances scroll that anchor into view (see primitives `AskButton`).
// ===========================================================================

import type { CSSProperties } from 'react';
import {
  ArrowRight,
  ArrowUpRight,
  BadgeCheck,
  ExternalLink,
  MessageCircle,
  Send,
} from 'lucide-react';

import type { ThemeShellProps } from '../types';
import { readPublicFaq } from './public-faq';
import {
  AskButton,
  Badge,
  Card,
  CardBody,
  PERSONA_CONSOLE_ANCHOR,
  PersonaAvatar,
  Reveal,
  SectionHeading,
  cx,
  scrollToPersonaConsole,
} from './site/primitives';

// ---------------------------------------------------------------------------
// Local helpers
// ---------------------------------------------------------------------------

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return 'P';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function platformLabel(platform: string): string {
  return platform.charAt(0).toUpperCase() + platform.slice(1);
}

/** First sentence of the bio — used as the hero statement. */
function firstSentence(text: string): string {
  const t = text.trim();
  if (!t) return '';
  const m = t.match(/^(.+?[.!?])(\s|$)/);
  return (m ? m[1] : t).trim();
}

/**
 * Derive a one-word category label for an achievement statement using only
 * generic, persona-neutral signal words (ported verbatim from the standalone
 * `achievementLabel` in personaon-sites/lib/personaon.ts), so it reads
 * correctly for ANY profile.
 */
function achievementLabel(text: string): string {
  const t = text.toLowerCase();
  if (/\b(found(ed|er)|co-?found|launch|started|bootstrap)\b/.test(t)) return 'Founder';
  if (/\b(venture|vc|invest(or|ing|ed)?|portfolio|incubat|accelerat)\b/.test(t)) return 'Venture';
  if (/\b(fortune|enterprise|fmcg|d2c|clients?|customers?|brands?|scal(e|ed|ing))\b/.test(t)) return 'Scale';
  if (/\b(promot(ed|ion)|senior|recogni[sz]ed|award-?winning)\b/.test(t)) return 'Growth';
  if (/\b(director|elected|president|chair|council|head of|board|led|leading|managed)\b/.test(t)) return 'Leadership';
  if (/\b(fellow(ship)?|scholarship|award|honou?r|published|research|dean|valedictorian)\b/.test(t)) return 'Honor';
  return 'Highlight';
}

// --- featured media embed helpers (ported from ClassicShell) ----------------

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

function extractInstagramShortcode(
  url: string,
): { shortcode: string; embedType: string } | null {
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
// Scoped editorial tokens — applied ONLY on the `.persona-theme-site` root.
// Values mirror personaon-sites/app/globals.css @theme. `--site-accent` reads
// the adapter-injected `--pon-accent` (fallback = terracotta, the standalone's
// accent). All consumers reference these via Tailwind arbitrary-value classes.
// ---------------------------------------------------------------------------

const siteTokens: CSSProperties = {
  ['--site-paper' as string]: '#f7f4ed',
  ['--site-paper-2' as string]: '#fffdf8',
  ['--site-ink' as string]: '#1b1a18',
  ['--site-ink-2' as string]: '#34312c',
  ['--site-muted' as string]: '#6f6a61',
  ['--site-muted-2' as string]: '#9b958a',
  ['--site-line' as string]: 'rgba(27, 26, 24, 0.12)',
  ['--site-line-2' as string]: 'rgba(27, 26, 24, 0.07)',
  ['--site-accent' as string]: 'var(--pon-accent, #b4502a)',
  ['--site-accent-2' as string]: 'var(--pon-accent, #8c3c1f)',
  ['--site-accent-soft' as string]:
    'color-mix(in srgb, var(--pon-accent, #b4502a) 10%, transparent)',
  ['--site-ok' as string]: '#15803d',
  ['--site-serif' as string]:
    'Fraunces, Georgia, "Times New Roman", serif',
  ['--site-shadow' as string]: '0 14px 40px rgba(27, 26, 24, 0.1)',
};

const CONTENT = 'mx-auto max-w-[1080px] px-7';

// ---------------------------------------------------------------------------

export function SiteShell({
  profile,
  interaction,
  visibility,
  mainStyle,
  slots,
}: ThemeShellProps) {
  const displayName = profile.name;
  const initials = getInitials(displayName);
  const statement = firstSentence(profile.bio);
  // Remainder of the bio after the lead sentence — shown below the statement so
  // a multi-sentence bio never repeats its first sentence in the hero.
  const bioTrimmed = profile.bio.trim();
  const bioRest = bioTrimmed.startsWith(statement)
    ? bioTrimmed.slice(statement.length).trim()
    : '';

  // Hide-empty gating — canonical visibility keys paired with their fields
  // (same keys ClassicShell honors).
  const showSocial =
    Boolean(visibility.social_links) && profile.socialLinks.length > 0;
  const showHighlights =
    Boolean(visibility.key_achievements) && profile.achievements.length > 0;
  const showTraits =
    Boolean(visibility.personality_traits) && profile.traits.length > 0;
  const showExpertise =
    Boolean(visibility.areas_of_expertise) && profile.expertise.length > 0;
  const showExperience =
    Boolean(visibility.work_experience) && profile.workExperience.length > 0;
  const showEducation =
    Boolean(visibility.education) && profile.education.length > 0;
  const showContributions =
    Boolean(visibility.contributions) && profile.contributions.length > 0;
  const showFeatured =
    Boolean(visibility.featured_content) && profile.featured.length > 0;
  // Owner-approved, crawlable Q&A — empty until the reviewed data pass wires it.
  const publicFaq = readPublicFaq(profile);
  const showFaq = publicFaq.length > 0;

  const teaserQuestion =
    profile.pinnedQuestions[0] ?? 'What are you working on these days?';

  return (
    <div
      className="persona-theme-site relative flex min-h-screen flex-col bg-[var(--site-paper)] font-[family-name:var(--site-serif)] text-[var(--site-ink)]"
      style={siteTokens}
    >
      {slots?.topbar}

      <main
        className="relative z-10 flex-1 overflow-y-auto"
        style={mainStyle}
      >
        {/* ── HERO ───────────────────────────────────────────────────────── */}
        <section className={cx(CONTENT, 'py-16 sm:py-24')}>
          <div className="grid items-center gap-12 lg:grid-cols-[1.4fr_0.9fr]">
            <Reveal>
              {profile.headline && (
                <p className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--site-accent)]">
                  {profile.headline}
                </p>
              )}

              <h1 className="mt-4 font-[family-name:var(--site-serif)] text-[clamp(40px,6vw,64px)] font-semibold leading-[1.0] tracking-tight text-[var(--site-ink)]">
                {displayName}
              </h1>

              {profile.verified && (
                <span className="mt-4 inline-flex items-center gap-1.5 rounded-full bg-[var(--site-accent-soft)] px-3 py-1.5 text-xs font-semibold text-[var(--site-accent-2)]">
                  <BadgeCheck className="size-3.5" aria-hidden="true" />
                  Verified profile
                </span>
              )}

              {statement && (
                <p className="mt-6 max-w-xl text-lg leading-relaxed text-[var(--site-ink-2)]">
                  {statement}
                </p>
              )}

              {bioRest && (
                <p className="mt-4 max-w-xl text-[15px] leading-relaxed text-[var(--site-muted)]">
                  {bioRest}
                </p>
              )}

              {profile.lifeLine && (
                <p className="mt-3 text-sm text-[var(--site-muted-2)]">
                  {profile.lifeLine}
                </p>
              )}

              {showSocial && (
                <div className="mt-6 flex flex-wrap items-center gap-2.5">
                  {profile.socialLinks.map((link) => (
                    <a
                      key={link.platform}
                      href={link.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-full border border-[var(--site-line)] bg-[var(--site-paper-2)] px-3.5 py-2 text-[13px] font-medium text-[var(--site-ink-2)] transition-all duration-200 hover:-translate-y-px hover:border-[var(--site-accent)] hover:text-[var(--site-accent)] [&_svg]:size-3.5 [&_svg]:shrink-0"
                    >
                      <ExternalLink aria-hidden="true" />
                      {platformLabel(link.platform)}
                    </a>
                  ))}
                </div>
              )}

              <div className="mt-8 flex flex-wrap items-center gap-3">
                <AskButton variant="primary">
                  <MessageCircle aria-hidden="true" />
                  Ask my persona
                </AskButton>
              </div>

              {/* Pre-chat voice / cloned-voice notice — injected by adapter */}
              {slots?.heroAside}
            </Reveal>

            <Reveal delay={120}>
              {/* Teaser card — a click-to-focus affordance for the console. */}
              <button
                type="button"
                onClick={scrollToPersonaConsole}
                className="block w-full cursor-pointer text-left"
                aria-label="Ask my persona"
              >
                <Card className="w-full hover:-translate-y-1 hover:border-[var(--site-accent)] hover:shadow-[var(--site-shadow)]">
                  <CardBody className="flex flex-col gap-4">
                    <div className="flex items-center gap-3">
                      <PersonaAvatar
                        src={profile.avatarUrl}
                        alt={displayName}
                        initials={initials}
                        className="size-10 shrink-0 rounded-xl object-cover"
                        monogramClassName="flex size-10 shrink-0 items-center justify-center rounded-xl bg-[var(--site-accent)] font-[family-name:var(--site-serif)] text-sm font-semibold text-[var(--site-paper-2)]"
                      />
                      <div className="min-w-0">
                        <div className="text-sm font-semibold text-[var(--site-ink)]">
                          Ask my persona
                        </div>
                        <div className="flex items-center gap-1.5 text-xs text-[var(--site-muted)]">
                          <span
                            className="size-1.5 rounded-full bg-[var(--site-ok)]"
                            aria-hidden="true"
                          />
                          Online · answers from my real work
                        </div>
                      </div>
                    </div>

                    <div className="self-start rounded-2xl rounded-tl-sm bg-[var(--site-accent-soft)] px-4 py-2.5 text-sm leading-snug text-[var(--site-accent-2)]">
                      {teaserQuestion}
                    </div>

                    <div className="flex items-center justify-between gap-3 rounded-full border border-[var(--site-line)] bg-[var(--site-paper)] px-4 py-2.5">
                      <span className="truncate text-sm text-[var(--site-muted-2)]">
                        Ask me anything…
                      </span>
                      <span
                        className="flex size-7 shrink-0 items-center justify-center rounded-full bg-[var(--site-ink)] text-[var(--site-paper-2)]"
                        aria-hidden="true"
                      >
                        <Send className="size-3.5" />
                      </span>
                    </div>
                  </CardBody>
                </Card>
              </button>
            </Reveal>
          </div>
        </section>

        {/* ── PERSONA CONSOLE (opaque `interaction`, rendered EXACTLY ONCE) ── */}
        <section className={cx(CONTENT, 'pb-4')}>
          <div id={PERSONA_CONSOLE_ANCHOR} className="scroll-mt-6">
            <Card className="overflow-hidden">
              <div className="flex items-center gap-2 border-b border-[var(--site-line-2)] px-5 py-3.5">
                <span className="text-[17px] leading-none text-[var(--site-accent)]">
                  ◗
                </span>
                <span className="text-[11px] font-bold uppercase tracking-[0.14em] text-[var(--site-accent)]">
                  Chat with my persona
                </span>
              </div>
              <CardBody>{interaction}</CardBody>
            </Card>
          </div>
        </section>

        {/* ── HIGHLIGHTS (achievements + derived one-word label) ─────────── */}
        {showHighlights && (
          <section className={cx(CONTENT, 'py-16 sm:py-20')}>
            <Reveal>
              <SectionHeading kicker="Highlights" title="What I've done" />
            </Reveal>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {profile.achievements.map((ach, i) => (
                <Reveal key={`${ach}-${i}`} delay={i * 60}>
                  <Card className="h-full hover:-translate-y-1 hover:border-[var(--site-line)] hover:shadow-[var(--site-shadow)]">
                    <CardBody className="flex h-full flex-col">
                      <Badge variant="tag">{achievementLabel(ach)}</Badge>
                      <p className="mt-3 text-[15px] leading-relaxed text-[var(--site-ink-2)]">
                        {ach}
                      </p>
                    </CardBody>
                  </Card>
                </Reveal>
              ))}
            </div>
          </section>
        )}

        {/* ── TRAITS ─────────────────────────────────────────────────────── */}
        {showTraits && (
          <section className="border-y border-[var(--site-line-2)] bg-[var(--site-paper-2)]">
            <div className={cx(CONTENT, 'py-16 text-center sm:py-20')}>
              <Reveal>
                <p className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--site-muted-2)]">
                  How people describe working with me
                </p>
                <div className="mx-auto mt-6 flex max-w-2xl flex-wrap justify-center gap-2.5">
                  {profile.traits.map((trait, i) => (
                    <Badge key={`${trait}-${i}`} variant="default">
                      {trait}
                    </Badge>
                  ))}
                </div>
              </Reveal>
            </div>
          </section>
        )}

        {/* ── EXPERTISE ──────────────────────────────────────────────────── */}
        {showExpertise && (
          <section className={cx(CONTENT, 'py-16 sm:py-20')}>
            <Reveal>
              <SectionHeading kicker="Focus areas" title="What I work on" />
            </Reveal>
            <div className="flex flex-wrap gap-2.5">
              {profile.expertise.map((skill, i) => (
                <Badge key={`${skill}-${i}`} variant="soft">
                  {skill}
                </Badge>
              ))}
            </div>
          </section>
        )}

        {/* ── EXPERIENCE ─────────────────────────────────────────────────── */}
        {showExperience && (
          <section className="border-y border-[var(--site-line-2)] bg-[var(--site-paper-2)]">
            <div className={cx(CONTENT, 'py-16 sm:py-20')}>
              <Reveal>
                <SectionHeading kicker="Background" title="Experience" />
              </Reveal>
              <ul className="flex flex-col divide-y divide-[var(--site-line-2)] border-t border-[var(--site-line-2)]">
                {profile.workExperience.map((job, i) => (
                  <Reveal key={`${job.company ?? ''}-${job.role ?? ''}-${i}`} delay={i * 50}>
                    <li className="grid gap-2 py-6 sm:grid-cols-[1fr_auto]">
                      <div>
                        <h3 className="font-[family-name:var(--site-serif)] text-xl font-semibold leading-snug tracking-tight text-[var(--site-ink)]">
                          {job.role ? job.role : job.company}
                          {job.role && job.company ? (
                            <span className="text-base font-normal text-[var(--site-muted)]">
                              {' · '}
                              {job.company}
                            </span>
                          ) : null}
                        </h3>
                        {job.description && (
                          <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-[var(--site-ink-2)]">
                            {job.description}
                          </p>
                        )}
                      </div>
                      {job.period && (
                        <span className="text-sm tabular-nums text-[var(--site-muted-2)] sm:text-right">
                          {job.period}
                        </span>
                      )}
                    </li>
                  </Reveal>
                ))}
              </ul>
            </div>
          </section>
        )}

        {/* ── EDUCATION ──────────────────────────────────────────────────── */}
        {showEducation && (
          <section className={cx(CONTENT, 'py-16 sm:py-20')}>
            <Reveal>
              <SectionHeading kicker="Education" title="Where I studied" />
            </Reveal>
            <ul className="flex flex-col divide-y divide-[var(--site-line-2)] border-t border-[var(--site-line-2)]">
              {profile.education.map((edu, i) => {
                const degreeLine = [edu.degree, edu.field].filter(Boolean).join(', ');
                return (
                  <li
                    key={`${edu.institution ?? ''}-${i}`}
                    className="grid gap-1 py-5 sm:grid-cols-[1fr_auto] sm:items-baseline"
                  >
                    <div>
                      <h3 className="text-base font-semibold text-[var(--site-ink)]">
                        {edu.institution}
                      </h3>
                      {degreeLine && (
                        <p className="mt-1 text-[15px] leading-snug text-[var(--site-ink-2)]">
                          {degreeLine}
                        </p>
                      )}
                    </div>
                    {edu.period && (
                      <span className="text-sm tabular-nums text-[var(--site-muted-2)] sm:text-right">
                        {edu.period}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        {/* ── CONTRIBUTIONS ──────────────────────────────────────────────── */}
        {showContributions && (
          <section className={cx(CONTENT, 'py-16 sm:py-20')}>
            <Reveal>
              <SectionHeading kicker="Contributions" title="What I've given back" />
            </Reveal>
            <div className="flex flex-wrap gap-2.5">
              {profile.contributions.map((c, i) => (
                <Badge key={`${c}-${i}`} variant="default">
                  {c}
                </Badge>
              ))}
            </div>
          </section>
        )}

        {/* ── FEATURED (media embeds — ported from ClassicShell, restyled) ── */}
        {showFeatured && (
          <section className="border-y border-[var(--site-line-2)] bg-[var(--site-paper-2)]">
            <div className={cx(CONTENT, 'py-16 sm:py-20')}>
              <Reveal>
                <SectionHeading kicker="Featured" title="Selected work" />
              </Reveal>
              <div className="grid gap-4 sm:grid-cols-2">
                {profile.featured.map((item) => {
                  if (item.type === 'youtube') {
                    const videoId = extractYouTubeId(item.url);
                    if (!videoId || !/^[\w-]{11}$/.test(videoId)) return null;
                    return (
                      <div
                        key={`${item.type}-${item.url}`}
                        className="h-[320px] overflow-hidden rounded-2xl border border-[var(--site-line)] bg-[var(--site-paper)] shadow-[var(--site-shadow)]"
                      >
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
                  if (item.type === 'instagram') {
                    const instaData = extractInstagramShortcode(item.url);
                    if (instaData && /^[\w-]{1,40}$/.test(instaData.shortcode)) {
                      const embedSrc = `https://www.instagram.com/${instaData.embedType}/${instaData.shortcode}/embed/`;
                      return (
                        <div
                          key={`${item.type}-${item.url}`}
                          className="h-[320px] overflow-hidden rounded-2xl border border-[var(--site-line)] bg-[var(--site-paper)] shadow-[var(--site-shadow)]"
                        >
                          <iframe
                            src={embedSrc}
                            title={item.title || 'Instagram post'}
                            scrolling="no"
                            className="h-full w-full"
                            style={{ border: 'none' }}
                          />
                        </div>
                      );
                    }
                  }
                  // Generic link card.
                  const safeUrl = /^https?:\/\//i.test(item.url)
                    ? item.url
                    : `https://${item.url}`;
                  let domain = '';
                  try {
                    domain = new URL(safeUrl).hostname.replace('www.', '');
                  } catch {
                    domain = item.url;
                  }
                  return (
                    <a
                      key={`${item.type}-${item.url}`}
                      href={safeUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex h-[320px] items-center gap-4 rounded-2xl border border-[var(--site-line)] bg-[var(--site-paper)] p-5 shadow-[var(--site-shadow)] transition-all duration-200 hover:-translate-y-1 hover:border-[var(--site-accent)]"
                    >
                      <span
                        className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[var(--site-accent-soft)] text-[var(--site-accent-2)] [&_svg]:size-5"
                        aria-hidden="true"
                      >
                        <ExternalLink />
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-semibold text-[var(--site-ink)]">
                          {item.title || domain}
                        </span>
                        <span className="mt-0.5 block truncate text-xs text-[var(--site-muted)]">
                          {domain}
                        </span>
                      </span>
                      <ArrowUpRight
                        className="ml-auto size-4 shrink-0 text-[var(--site-muted-2)]"
                        aria-hidden="true"
                      />
                    </a>
                  );
                })}
              </div>
            </div>
          </section>
        )}

        {/* ── Q&A — owner-approved, crawlable answers ─────────────────────
            Server-rendered as raw <h3>/<p> so answer engines read it directly,
            never behind the persona console. */}
        {showFaq && (
          <section className={cx(CONTENT, 'py-16 sm:py-20')}>
            <Reveal>
              <SectionHeading
                kicker="Q&A"
                title={`Questions ${displayName} answers`}
              />
            </Reveal>
            <div className="mx-auto flex max-w-3xl flex-col gap-4">
              {publicFaq.map((faq, i) => (
                <Reveal key={`${faq.question}-${i}`} delay={i * 50}>
                  <Card className="hover:-translate-y-0.5 hover:border-[var(--site-line)] hover:shadow-[var(--site-shadow)]">
                    <CardBody>
                      <h3 className="font-[family-name:var(--site-serif)] text-lg font-semibold leading-snug tracking-tight text-[var(--site-ink)]">
                        {faq.question}
                      </h3>
                      <p className="mt-2 text-[15px] leading-relaxed text-[var(--site-ink-2)]">
                        {faq.answer}
                      </p>
                    </CardBody>
                  </Card>
                </Reveal>
              ))}
            </div>
          </section>
        )}

        {/* ── CTA BAND (ported from standalone) ──────────────────────────── */}
        <section className={cx(CONTENT, 'py-16 sm:py-24')}>
          <Reveal>
            <div className="rounded-2xl bg-[var(--site-ink)] p-8 text-[var(--site-paper-2)] shadow-[var(--site-shadow)] sm:p-10">
              <div className="flex flex-col items-start justify-between gap-7 lg:flex-row lg:items-center">
                <div className="max-w-xl">
                  <h2 className="font-[family-name:var(--site-serif)] text-[clamp(26px,3.4vw,36px)] font-semibold leading-[1.1] tracking-tight">
                    Want to work together?
                  </h2>
                  <p className="mt-3 text-[15px] leading-relaxed text-[var(--site-paper-2)]/70">
                    Ask my persona anything — it answers from my real work,
                    anytime.
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <AskButton variant="accent">
                    <MessageCircle aria-hidden="true" />
                    Ask my persona
                  </AskButton>
                </div>
              </div>

              <div className="mt-8 border-t border-[var(--site-paper-2)]/15 pt-6">
                <a
                  href="https://personaon.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-sm text-sm font-semibold text-[var(--site-paper-2)]/70 transition-colors hover:text-[var(--site-paper-2)]"
                >
                  <span aria-hidden="true">⚡</span>
                  Built with PersonaOn — build your own
                  <ArrowRight className="size-4" aria-hidden="true" />
                </a>
              </div>
            </div>
          </Reveal>
        </section>
      </main>

      {/* ── Branding footer (frontend-coupled, injected by the adapter) ──── */}
      {slots?.branding}
    </div>
  );
}
