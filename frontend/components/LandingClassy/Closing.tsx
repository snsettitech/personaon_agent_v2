'use client';

import Link from 'next/link';
import { analytics } from '@/lib/analytics/events';

export default function Closing() {
  const onPrimary = () => {
    analytics.landingCtaClicked({ cta_type: 'create_persona', position: 'closing' });
  };

  return (
    <section
      id="claim"
      className="relative"
      style={{ background: 'var(--fog)' }}
    >
      <div className="mx-auto max-w-[1100px] px-6 py-32 text-center md:py-40">
        <h2
          className="mx-auto max-w-[1000px]"
          style={{
            fontFamily: "'Geist', sans-serif",
            fontWeight: 600,
            fontSize: 'clamp(40px, 6vw, 80px)',
            lineHeight: 0.98,
            letterSpacing: '-0.035em',
            color: 'var(--ink)',
          }}
        >
          They&rsquo;ll Google you anyway.
          <br />
          <span
            style={{
              color: 'var(--fg-3)',
              fontFamily: "'Newsreader', Georgia, serif",
              fontStyle: 'italic',
              fontWeight: 400,
            }}
          >
            Give them a page that answers.
          </span>
        </h2>

        <p
          className="mx-auto mt-6 max-w-[560px]"
          style={{
            color: 'var(--fg-2)',
            fontFamily: "'Geist', sans-serif",
            fontSize: 17,
            lineHeight: 1.55,
            letterSpacing: '-0.005em',
          }}
        >
          Your story is already out there, flattened into a resume. PersonaOn
          makes it a living page &mdash; answering, booking, and working while
          you sleep.
        </p>

        <div className="mt-10 flex flex-wrap items-center justify-center gap-x-7 gap-y-3">
          <Link
            href="/auth/signup"
            onClick={onPrimary}
            className="inline-flex items-center gap-2 rounded-full transition-all hover:-translate-y-px"
            style={{
              height: 52,
              padding: '0 30px',
              background: 'var(--ink)',
              color: '#FFFFFF',
              fontSize: 16,
              fontFamily: "'Geist', sans-serif",
              letterSpacing: '-0.005em',
              fontWeight: 500,
              boxShadow: '0 6px 20px rgba(29,29,31,.18)',
            }}
          >
            Start free
            <span
              aria-hidden
              style={{ fontFamily: "'JetBrains Mono', monospace" }}
            >
              &rarr;
            </span>
          </Link>
        </div>

        <p
          className="mt-5 text-[12.5px]"
          style={{
            color: 'var(--fg-3)',
            fontFamily: "'Geist', sans-serif",
            letterSpacing: '-0.005em',
          }}
        >
          No credit card &middot; Live in under 3 minutes
        </p>
      </div>
    </section>
  );
}
