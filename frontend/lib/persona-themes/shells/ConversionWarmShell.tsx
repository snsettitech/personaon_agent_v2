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

/** "Sainath Setti" → "Sainath" for the warm "Talk to {first}" headline. */
function firstName(name: string): string {
  const first = name.trim().split(/\s+/)[0];
  return first || name;
}

// The accent var the adapter injects on a wrapper above this shell. The hex
// fallback (conversion-warm's default orange) keeps the shell self-contained.
const ACCENT = 'var(--pon-accent, #e0653b)';
// Soft tints derived from the accent — color-mix degrades gracefully to the
// literal value in browsers without support (still on-brand).
const ACCENT_SOFT = 'color-mix(in srgb, var(--pon-accent, #e0653b) 12%, #ffffff)';
const ACCENT_WASH = 'color-mix(in srgb, var(--pon-accent, #e0653b) 22%, #ffffff)';

// Warm, soft, slightly rounded system stack — no external webfonts.
const WARM_SANS =
  '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif';

// ---------------------------------------------------------------------------
// Conversion-warm shell — the chat-first, booking-led layout. A warm, centered
// stage with minimal identity; the opaque `interaction` console IS the hero and
// carries chat + Book + voice + suggestion chips internally. One light
// credibility strip (expertise chips) appears under the console, and is hidden
// entirely when there's no expertise. Degrades gracefully to identity + console.
// ---------------------------------------------------------------------------

export function ConversionWarmShell({
  profile,
  interaction,
  visibility,
  mainStyle,
  slots,
}: ThemeShellProps) {
  const displayName = profile.name;
  const initials = getInitials(displayName) || 'P';

  // Credibility strip: expertise only, hide-empty (same visibility key Classic
  // uses for expertise). Never render a placeholder when there's nothing.
  const showCredibility =
    Boolean(visibility.areas_of_expertise) && profile.expertise.length > 0;

  // Owner-approved, crawlable Q&A — empty until the reviewed data pass wires it.
  const publicFaq = readPublicFaq(profile);
  const showFaq = publicFaq.length > 0;

  return (
    <div
      className="relative flex min-h-screen flex-col bg-[#ebe6e1] text-[#241f1c]"
      style={{ fontFamily: WARM_SANS }}
    >
      {slots?.topbar}

      {/* ─── Centered warm stage ──────────────────────────────────────────── */}
      <main
        className="relative z-10 flex-1 overflow-y-auto"
        style={{
          // Soft radial glow derived from the accent, fading into a warm paper base.
          backgroundImage: `radial-gradient(120% 80% at 50% 0%, ${ACCENT_SOFT}, #faf6f2 46%, #fffdfb)`,
          ...mainStyle,
        }}
      >
        <motion.div
          className="mx-auto flex w-full max-w-[600px] flex-col items-center px-5 pt-14 pb-10 sm:pt-20"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: 'easeOut' }}
        >
          {/* Avatar — small, accent-tinted, rounded */}
          <div
            className="flex h-[60px] w-[60px] flex-none items-center justify-center overflow-hidden rounded-[20px] text-xl font-bold"
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

          {/* Identity — name + one-line headline */}
          <div className="mt-3.5 flex flex-wrap items-center justify-center gap-2">
            <h1 className="text-center text-[23px] font-bold tracking-[-0.02em]">
              Talk to {firstName(displayName)}
            </h1>
            {profile.verified && (
              <span
                className="rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em]"
                style={{ backgroundColor: ACCENT_SOFT, color: ACCENT }}
              >
                Verified
              </span>
            )}
          </div>
          {profile.headline && (
            <p className="mt-1 max-w-[440px] text-center text-[14.5px] leading-relaxed text-[#7a6f68]">
              {profile.headline}
            </p>
          )}

          {/* ── Interactive console (opaque slot) — THE centerpiece ──
              Contains chat input + Book + voice + suggestion chips internally;
              the shell adds none of its own. Rendered exactly once. */}
          <div className="mt-5 w-full">{interaction}</div>

          {/* ── Credibility strip — one light expertise row, hidden when empty ── */}
          {showCredibility && (
            <div
              className="mt-6 w-full border-t pt-4"
              style={{ borderColor: 'rgba(60,40,30,0.10)' }}
            >
              <p className="mb-2.5 text-center text-[10.5px] font-bold uppercase tracking-[0.16em] text-[#a59a92]">
                A bit of background
              </p>
              <div className="flex flex-wrap justify-center gap-1.5">
                {profile.expertise.map((skill) => (
                  <span
                    key={skill}
                    className="rounded-full border bg-white px-3 py-1.5 text-[12.5px] font-semibold text-[#5a4f48]"
                    style={{ borderColor: 'rgba(60,40,30,0.10)' }}
                  >
                    {skill}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* ── Questions {firstName} answers — owner-approved, crawlable Q&A ──
              Server-rendered below the console (not inside it) so crawlers /
              answer engines read the answers in the raw HTML. */}
          {showFaq && (
            <div
              className="mt-6 w-full border-t pt-5"
              style={{ borderColor: 'rgba(60,40,30,0.10)' }}
            >
              <p className="mb-3.5 text-center text-[10.5px] font-bold uppercase tracking-[0.16em] text-[#a59a92]">
                Questions {firstName(displayName)} answers
              </p>
              <div className="space-y-4 text-left">
                {publicFaq.map((faq, i) => (
                  <div key={i}>
                    <h3 className="text-[14px] font-bold text-[#2f2a26]">
                      {faq.question}
                    </h3>
                    <p className="mt-1 text-[13.5px] leading-relaxed text-[#7a6f68]">
                      {faq.answer}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </motion.div>
      </main>

      {/* ─── Branding footer (frontend-coupled, injected by the adapter) ───── */}
      {slots?.branding}
    </div>
  );
}
