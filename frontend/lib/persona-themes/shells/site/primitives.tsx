'use client';

// ===========================================================================
// Site-shell primitives — ports of the standalone personaon-sites editorial
// components (Card / Badge / Reveal / SectionHeading / PersonaAvatar /
// AskButton), restyled to read the SCOPED `--site-*` CSS custom properties that
// SiteShell defines on its `.persona-theme-site` root. These are fresh files in
// the frontend; nothing is imported from the standalone app.
//
// Token contract (all set by SiteShell's root wrapper, never global):
//   --site-paper, --site-paper-2, --site-ink, --site-ink-2, --site-muted,
//   --site-muted-2, --site-line, --site-line-2, --site-accent (= --pon-accent),
//   --site-accent-2, --site-accent-soft, --site-ok, --site-serif, --site-shadow
// ===========================================================================

import { useEffect, useRef, useState } from 'react';

/** Tiny class joiner — no external clsx/cva dependency in this frontend. */
export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}

// ---------------------------------------------------------------------------
// Card / CardBody — warm paper-2 surface, hairline border, large radius.
// ---------------------------------------------------------------------------

export function Card({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cx(
        'rounded-2xl border border-[var(--site-line)] bg-[var(--site-paper-2)] transition-all duration-200',
        className,
      )}
      {...props}
    />
  );
}

export function CardBody({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cx('p-5 sm:p-6', className)} {...props} />;
}

// ---------------------------------------------------------------------------
// Badge — default (bordered pill), soft (accent-tinted), tag (uppercase accent
// micro-label). Ported from the standalone badge variants.
// ---------------------------------------------------------------------------

type BadgeVariant = 'default' | 'soft' | 'tag';

const BADGE_STYLES: Record<BadgeVariant, string> = {
  default:
    'inline-flex items-center rounded-full border border-[var(--site-line)] bg-[var(--site-paper-2)] px-3.5 py-2 text-[13px] font-medium text-[var(--site-ink-2)]',
  soft:
    'inline-flex items-center rounded-full bg-[var(--site-accent-soft)] px-3.5 py-2 text-[13px] font-semibold text-[var(--site-accent-2)]',
  tag: 'inline-flex items-center text-[11px] font-bold uppercase tracking-[0.06em] text-[var(--site-accent)]',
};

export function Badge({
  className,
  variant = 'default',
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { variant?: BadgeVariant }) {
  return <span className={cx(BADGE_STYLES[variant], className)} {...props} />;
}

// ---------------------------------------------------------------------------
// Reveal — fade-up on scroll, hardened so content is NEVER stuck hidden.
// Ported verbatim in behavior from the standalone; uses inline styles instead
// of the standalone's global `.reveal` CSS class so it stays self-contained.
// ---------------------------------------------------------------------------

export function Reveal({
  children,
  className,
  delay = 0,
}: {
  children: React.ReactNode;
  className?: string;
  delay?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [seen, setSeen] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    // Respect reduced-motion: reveal immediately, no observer.
    if (
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    ) {
      setSeen(true);
      return;
    }

    const rect = el.getBoundingClientRect();
    if (rect.top < window.innerHeight && rect.bottom > 0) {
      setSeen(true);
      return;
    }

    const fallback = window.setTimeout(() => setSeen(true), 1800);
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setSeen(true);
          window.clearTimeout(fallback);
          io.disconnect();
        }
      },
      { threshold: 0, rootMargin: '0px 0px -8% 0px' },
    );
    io.observe(el);

    return () => {
      io.disconnect();
      window.clearTimeout(fallback);
    };
  }, []);

  return (
    <div
      ref={ref}
      className={cx('transition-all duration-[600ms] ease-out', className)}
      style={{
        opacity: seen ? 1 : 0,
        transform: seen ? 'none' : 'translateY(16px)',
        transitionDelay: delay ? `${delay}ms` : undefined,
      }}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SectionHeading — accent kicker + big Fraunces title. Ported from standalone.
// ---------------------------------------------------------------------------

export function SectionHeading({
  kicker,
  title,
  children,
}: {
  kicker: string;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="mb-9 flex flex-wrap items-end justify-between gap-5">
      <div>
        <div className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--site-accent)]">
          {kicker}
        </div>
        <h2 className="mt-2.5 font-[family-name:var(--site-serif)] text-[clamp(28px,4vw,38px)] font-semibold leading-[1.08] tracking-tight text-[var(--site-ink)]">
          {title}
        </h2>
      </div>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// PersonaAvatar — image with graceful monogram fallback. Ported from standalone
// (onError swap requires a client component).
// ---------------------------------------------------------------------------

interface PersonaAvatarProps {
  src?: string;
  alt: string;
  initials: string;
  className?: string;
  monogramClassName?: string;
}

export function PersonaAvatar({
  src,
  alt,
  initials,
  className,
  monogramClassName,
}: PersonaAvatarProps) {
  const [failed, setFailed] = useState(false);
  const url = (src ?? '').trim();
  const showImage = url.length > 0 && !failed;

  if (showImage) {
    return (
      <img src={url} alt={alt} className={className} onError={() => setFailed(true)} />
    );
  }

  return (
    <span role="img" aria-label={alt} className={monogramClassName}>
      {initials}
    </span>
  );
}

// ---------------------------------------------------------------------------
// AskButton — the editorial CTA. The standalone dispatches a window event to its
// own chat overlay; here the persona console is the OPAQUE `interaction` node
// rendered inline by SiteShell. So this affordance scrolls the console anchor
// into view (and focuses it) — a contract-safe action that never inspects the
// console. `onActivate` lets the hero pass extra behavior if needed.
// ---------------------------------------------------------------------------

export const PERSONA_CONSOLE_ANCHOR = 'site-persona-console';

type AskButtonVariant = 'primary' | 'accent' | 'ghost';

const ASK_BASE =
  'inline-flex h-11 items-center justify-center gap-2 whitespace-nowrap rounded-full px-5 text-sm font-semibold transition-all duration-200 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--site-accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--site-paper)] [&_svg]:size-4 [&_svg]:shrink-0';

const ASK_VARIANTS: Record<AskButtonVariant, string> = {
  primary:
    'border border-[var(--site-ink)] bg-[var(--site-ink)] text-[var(--site-paper-2)] hover:-translate-y-px hover:border-[var(--site-accent)] hover:bg-[var(--site-accent)]',
  accent:
    'bg-[var(--site-accent-soft)] text-[var(--site-accent-2)] hover:-translate-y-px hover:bg-[var(--site-accent)] hover:text-[var(--site-paper-2)]',
  ghost:
    'border border-[var(--site-line)] bg-[var(--site-paper-2)] text-[var(--site-ink-2)] hover:-translate-y-px hover:border-[var(--site-accent)] hover:text-[var(--site-accent)]',
};

export function scrollToPersonaConsole(): void {
  if (typeof document === 'undefined') return;
  const el = document.getElementById(PERSONA_CONSOLE_ANCHOR);
  if (!el) return;
  el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  // Move focus to the first focusable control inside the console without
  // inspecting its structure (querySelector on standard focusable tags only).
  const focusable = el.querySelector<HTMLElement>(
    'input, textarea, button, [contenteditable="true"]',
  );
  focusable?.focus({ preventScroll: true });
}

interface AskButtonProps {
  children: React.ReactNode;
  className?: string;
  variant?: AskButtonVariant;
}

export function AskButton({ children, className, variant = 'accent' }: AskButtonProps) {
  return (
    <button
      type="button"
      onClick={scrollToPersonaConsole}
      className={cx(ASK_BASE, ASK_VARIANTS[variant], className)}
    >
      {children}
    </button>
  );
}
