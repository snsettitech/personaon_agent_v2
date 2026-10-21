import Link from 'next/link';
import { Wordmark } from '@/components/brand/Wordmark';

export default function NotFound(): React.JSX.Element {
  return (
    <div
      className="min-h-screen flex flex-col"
      style={{ backgroundColor: 'var(--fog)' }}
    >
      <header className="px-6 py-6 md:px-10">
        <Wordmark href="/" size="sm" />
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
            404 &middot; not found
          </p>

          <h1
            className="mx-auto mt-7"
            style={{
              fontFamily: "'Geist', sans-serif",
              fontWeight: 600,
              fontSize: 'clamp(56px, 9.5vw, 128px)',
              lineHeight: 0.96,
              letterSpacing: '-0.045em',
              color: 'var(--ink)',
            }}
          >
            This page
            <br />
            <span style={{ color: 'var(--fg-3)' }}>isn&rsquo;t home.</span>
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
            The link you followed is broken, or the page has moved. Let&rsquo;s
            get you back to something that works.
          </p>

          <div className="mt-10 flex justify-center">
            <Link
              href="/"
              className="inline-flex items-center gap-2 rounded-full px-7 transition-opacity hover:opacity-90"
              style={{
                height: 50,
                background: 'var(--ink)',
                color: '#FFFFFF',
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
  );
}
