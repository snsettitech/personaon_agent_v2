'use client';

import Link from 'next/link';

import { analytics } from '@/lib/analytics/events';
import type { SignupWallContext } from '@/lib/analytics/experienceEvents';

const SANS = "'Geist', sans-serif";

export function SignupWall({
  title,
  subtitle,
  context,
}: {
  title?: string;
  subtitle?: string;
  context: SignupWallContext;
}) {
  return (
    <div
      className="text-center"
      style={{
        borderRadius: 24,
        border: '1px solid rgba(29,29,31,0.10)',
        background: 'linear-gradient(180deg, var(--fog-2) 0%, var(--fog-3) 100%)',
        padding: 24,
      }}
    >
      <p className="text-[18px]" style={{ color: 'var(--ink)', fontFamily: "'Instrument Serif', Georgia, serif" }}>
        {title ?? 'Sign up to unlock your full persona'}
      </p>
      <p className="mx-auto mt-1.5 max-w-[420px] text-[14px]" style={{ color: 'var(--fg-2)', fontFamily: SANS }}>
        {subtitle ?? 'See everything your twin knows, keep chatting, and claim your page — free.'}
      </p>
      <Link
        href="/auth/signup"
        onClick={() => analytics.experienceSignupWallClicked({ context })}
        className="mt-4 inline-flex items-center gap-1 rounded-full px-6 transition-opacity hover:opacity-90"
        style={{ height: 44, background: 'var(--ink)', color: '#fff', fontFamily: SANS, fontSize: 14, fontWeight: 500 }}
      >
        Create my PersonaOn
        <span aria-hidden>&rsaquo;</span>
      </Link>
    </div>
  );
}
