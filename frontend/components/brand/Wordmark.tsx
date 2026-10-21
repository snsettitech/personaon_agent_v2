import Link from 'next/link';

// PersonaOn wordmark — single canonical source of truth.
// Renders the official PersonaOn lockup (pictorial mark + "PersonaOn")
// from the brand kit SVGs in /public/brand. Carrying it here means every
// consumer (nav, footer, legal, dashboard, auth) shares one rendering of
// the real logo instead of each component reinventing it inline.
//
// Light surfaces  -> /brand/wordmark.svg        (gradient "On", dark text)
// Dark/ink panels -> /brand/wordmark-white.svg  (white text variant)
// Source-of-truth kit (all variants, SVG + PNG): /public/brand/kit.

type WordmarkSize = 'sm' | 'md' | 'lg';

interface WordmarkProps {
  /** sm = 18px (compact nav), md = 26px (default, hero), lg = 40px (display) */
  size?: WordmarkSize;
  /** Use on dark/ink backgrounds — swaps to the white-text lockup */
  onInk?: boolean;
  /** Wrap in a Next.js Link to a destination — the standard logo-as-home-link */
  href?: string;
  /** Optional extra classes for layout (margin, alignment) */
  className?: string;
}

// Rendered lockup HEIGHT in px. The lockup aspect ratio is ~5.2:1
// (cropped viewBox 313.4 × 60.3 from the official brand export).
const SIZE_PX: Record<WordmarkSize, number> = {
  sm: 18,
  md: 26,
  lg: 40,
};

const LOCKUP_ASPECT = 5.2;

export function Wordmark({ size = 'md', onInk = false, href, className = '' }: WordmarkProps) {
  const h = SIZE_PX[size];

  const img = (
    // eslint-disable-next-line @next/next/no-img-element -- brand SVG, no optimization needed
    <img
      src={onInk ? '/brand/wordmark-white.svg' : '/brand/wordmark.svg'}
      alt="PersonaOn"
      width={Math.round(h * LOCKUP_ASPECT)}
      height={h}
      style={{ height: h, width: 'auto', display: 'block' }}
      className={className}
    />
  );

  if (href) {
    return (
      <Link
        href={href}
        aria-label="PersonaOn — home"
        style={{ display: 'inline-flex', lineHeight: 0, textDecoration: 'none' }}
      >
        {img}
      </Link>
    );
  }

  return img;
}

// Standalone pulse-dot — a status/utility mark (not the logo). Kept as-is
// for status badges, loading states, and "online" indicators, anywhere a
// small brand-coloured signal belongs without the full lockup.
interface PulseProps {
  size?: number;
  ring?: boolean;
  className?: string;
}

export function PulseDot({ size = 8, ring = true, className = '' }: PulseProps) {
  return (
    <span
      aria-hidden="true"
      className={className}
      style={{
        display: 'inline-block',
        width: size,
        height: size,
        borderRadius: '50%',
        background: 'var(--signal)',
        boxShadow: ring ? `0 0 0 ${Math.round(size / 2)}px rgba(0, 102, 204, 0.18)` : undefined,
      }}
    />
  );
}
