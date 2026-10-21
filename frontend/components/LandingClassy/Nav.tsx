'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { Wordmark } from '@/components/brand/Wordmark';
import { analytics } from '@/lib/analytics/events';

const LINKS = [
  { label: 'How it works', href: '/#how' },
  { label: "Who it's for", href: '/#who' },
  { label: 'Real, not synthetic', href: '/#voice' },
  { label: 'Sign in', href: '/auth/login' },
];

export default function Nav() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  return (
    <>
      {/* Apple-style top promo strip */}
      <div
        className="fixed inset-x-0 top-0 z-[60] flex h-10 items-center justify-center px-6 text-[12.5px]"
        style={{
          background: 'var(--ink)',
          color: '#FFFFFF',
          fontFamily: "'Geist', sans-serif",
          letterSpacing: '-0.005em',
        }}
      >
        <span style={{ color: 'rgba(255,255,255,0.7)' }}>
          PersonaOn is now free.
        </span>
        <Link
          href="/auth/signup"
          onClick={() =>
            analytics.landingCtaClicked({ cta_type: 'create_persona', position: 'promo' })
          }
          className="ml-2 inline-flex items-center gap-1"
          style={{ color: '#FFFFFF', textDecoration: 'none' }}
        >
          Create yours
          <span aria-hidden>&rsaquo;</span>
        </Link>
      </div>

      <nav
        className="fixed inset-x-0 top-10 z-50 transition-all duration-300"
        style={{
          backgroundColor: scrolled ? 'rgba(245,245,247,0.82)' : 'rgba(245,245,247,0.55)',
          backdropFilter: 'saturate(180%) blur(20px)',
          WebkitBackdropFilter: 'saturate(180%) blur(20px)',
          borderBottom: scrolled ? '1px solid rgba(29,29,31,0.06)' : '1px solid transparent',
        }}
      >
        <div className="mx-auto flex h-12 max-w-[1024px] items-center justify-between px-6">
          <Wordmark href="/" size="sm" />

          <div className="hidden items-center gap-7 md:flex">
            {LINKS.map(({ label, href }) => (
              <Link
                key={label}
                href={href}
                className="text-[12.5px] transition-opacity hover:opacity-60"
                style={{
                  color: 'var(--fg)',
                  fontFamily: "'Geist', sans-serif",
                  letterSpacing: '-0.005em',
                }}
              >
                {label}
              </Link>
            ))}
            {/* Highlighted entry to the live "Experience" demo so it's reachable from
                the top of the page without scrolling. */}
            <Link
              href="/experience"
              onClick={() => analytics.landingCtaClicked({ cta_type: 'try_demo', position: 'nav' })}
              className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[12.5px] transition-opacity hover:opacity-80"
              style={{
                border: '1px solid rgba(29,29,31,0.14)',
                background: 'var(--fog-2)',
                color: 'var(--fg)',
                fontFamily: "'Geist', sans-serif",
                letterSpacing: '-0.005em',
              }}
            >
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: '#2BB673' }} aria-hidden />
              Try it free
            </Link>
          </div>

          <Link
            href="/auth/signup"
            onClick={() =>
              analytics.landingCtaClicked({ cta_type: 'create_persona', position: 'nav' })
            }
            className="text-[12.5px] transition-opacity hover:opacity-60"
            style={{
              color: 'var(--fg)',
              fontFamily: "'Geist', sans-serif",
              letterSpacing: '-0.005em',
            }}
          >
            Start free
          </Link>
        </div>
      </nav>
    </>
  );
}
