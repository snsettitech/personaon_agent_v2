'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import './globals.css';
import { reportRenderError } from '@/lib/analytics/reportError';

interface GlobalErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

/**
 * Top-level App Router error boundary (Next.js `global-error.tsx` convention).
 *
 * Only mounts when an error escapes every other boundary, including the
 * root layout itself — which is why it must define its own <html>/<body>
 * and import globals.css directly instead of relying on app/layout.tsx.
 *
 * Reports to PostHog via reportRenderError() so render-time crashes are
 * captured alongside the window-level errors PostHogProvider's
 * capture_exceptions already catches automatically.
 */
export default function GlobalError({ error, reset }: GlobalErrorProps) {
  useEffect(() => {
    reportRenderError(error, { digest: error.digest, boundary: 'global-error' });
  }, [error]);

  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="antialiased">
        <div
          className="min-h-screen flex flex-col"
          style={{ backgroundColor: 'var(--fog)' }}
        >
          <header className="px-6 py-6 md:px-10">
            <span
              style={{
                fontFamily: "'Geist', sans-serif",
                fontWeight: 600,
                fontSize: 18,
                letterSpacing: '-0.01em',
                color: 'var(--ink)',
              }}
            >
              PersonaOn
            </span>
          </header>

          <main className="flex flex-1 items-center justify-center px-6 py-20">
            <div className="mx-auto max-w-[640px] text-center">
              <p
                className="mx-auto inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.2em]"
                style={{
                  borderColor: 'rgba(29,29,31,0.10)',
                  color: 'var(--fg-2)',
                  background: 'rgba(255,255,255,0.6)',
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              >
                error &middot; something broke
              </p>

              <h1
                className="mx-auto mt-7"
                style={{
                  fontFamily: "'Geist', sans-serif",
                  fontWeight: 600,
                  fontSize: 'clamp(48px, 8vw, 100px)',
                  lineHeight: 0.98,
                  letterSpacing: '-0.045em',
                  color: 'var(--ink)',
                }}
              >
                This screen broke
                <br />
                <span style={{ color: 'var(--fg-3)' }}>on our end.</span>
              </h1>

              <p
                className="mx-auto mt-7 max-w-[460px]"
                style={{
                  color: 'var(--fg-2)',
                  fontFamily: "'Geist', sans-serif",
                  fontSize: 'clamp(17px, 1.5vw, 20px)',
                  lineHeight: 1.5,
                  letterSpacing: '-0.005em',
                }}
              >
                Your page and the persona behind it are untouched — this was
                just a glitch loading this screen. Reload to try again, or
                head back home while we look into it.
              </p>

              <div className="mt-10 flex flex-wrap justify-center gap-3">
                <button
                  type="button"
                  onClick={() => reset()}
                  className="inline-flex items-center gap-2 rounded-full px-7 transition-opacity hover:opacity-90"
                  style={{
                    height: 50,
                    background: 'var(--ink)',
                    color: '#FFFFFF',
                    fontSize: 15,
                    fontFamily: "'Geist', sans-serif",
                    letterSpacing: '-0.01em',
                    fontWeight: 500,
                    border: 'none',
                    cursor: 'pointer',
                  }}
                >
                  Reload page
                </button>
                <Link
                  href="/"
                  className="inline-flex items-center gap-2 rounded-full border px-7 transition-opacity hover:opacity-80"
                  style={{
                    height: 50,
                    borderColor: 'rgba(29,29,31,0.18)',
                    color: 'var(--ink)',
                    fontSize: 15,
                    fontFamily: "'Geist', sans-serif",
                    letterSpacing: '-0.01em',
                    fontWeight: 500,
                  }}
                >
                  Take me home
                </Link>
              </div>
            </div>
          </main>

          <footer
            className="px-6 py-8 text-center text-[11px] uppercase tracking-[0.18em] md:px-10"
            style={{
              color: 'var(--fg-3)',
              fontFamily: "'JetBrains Mono', monospace",
              borderTop: '1px solid rgba(29,29,31,0.06)',
            }}
          >
            &copy; {new Date().getFullYear()} PersonaOn
          </footer>
        </div>
      </body>
    </html>
  );
}
