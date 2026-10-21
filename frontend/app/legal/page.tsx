import Link from 'next/link';
import type { Metadata } from 'next';
import { Wordmark } from '@/components/brand/Wordmark';

export const metadata: Metadata = {
  title: 'Legal — PersonaOn',
  description: "PersonaOn's policies and terms.",
};

const documents = [
  {
    href: '/legal/terms',
    title: 'Terms of Use',
    lastUpdated: 'April 30, 2026',
    description: 'Your agreement with PersonaOn for using the platform and AI Personas.',
  },
  {
    href: '/legal/terms-creator',
    title: 'Creator Terms of Use',
    lastUpdated: 'April 30, 2026',
    description: 'Additional terms that apply when you build, deploy, or monetize a Persona.',
  },
  {
    href: '/legal/privacy',
    title: 'Privacy Policy',
    lastUpdated: 'April 30, 2026',
    description: 'How we collect, use, disclose, and retain personal information.',
  },
  {
    href: '/legal/biometric-consent',
    title: 'Biometric Consent',
    lastUpdated: 'April 30, 2026',
    description: 'Express consent for collection of voiceprints and facial geometry used to build a Persona.',
  },
];

export default function LegalIndexPage() {
  return (
    <div className="min-h-screen" style={{ backgroundColor: 'var(--bg-base)' }}>
      {/* Top nav */}
      <header
        className="sticky top-0 z-10 backdrop-blur-md"
        style={{
          backgroundColor: 'rgba(250, 250, 247, 0.88)',
          borderBottom: '1px solid var(--border-subtle)',
        }}
      >
        <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-4 md:px-8">
          <Wordmark href="/" size="sm" />
        </div>
      </header>

      {/* Page */}
      <main className="mx-auto max-w-3xl px-6 py-16 md:px-8 md:py-20">
        <h1
          className="text-5xl font-bold tracking-tight md:text-6xl"
          style={{
            color: 'var(--text-primary)',
            fontFamily: "'Playfair Display', Georgia, serif",
          }}
        >
          Legal
        </h1>
        <p
          className="mt-4 text-lg leading-7"
          style={{ color: 'var(--text-secondary)' }}
        >
          Here you&apos;ll find all our policies and terms.
        </p>

        <div className="mt-12 space-y-3">
          {documents.map((doc) => (
            <Link
              key={doc.href}
              href={doc.href}
              className="group flex items-start justify-between gap-6 rounded-2xl p-6 transition-all md:p-7"
              style={{
                backgroundColor: 'var(--bg-elevated)',
                border: '1px solid var(--border-subtle)',
                boxShadow: 'var(--shadow-sm)',
              }}
            >
              <div className="min-w-0 flex-1">
                <h2
                  className="text-xl font-bold tracking-tight md:text-2xl"
                  style={{ color: 'var(--text-primary)' }}
                >
                  {doc.title}
                </h2>
                <p
                  className="mt-2 text-sm leading-6"
                  style={{ color: 'var(--text-secondary)' }}
                >
                  {doc.description}
                </p>
                <p
                  className="mt-3 text-xs"
                  style={{ color: 'var(--text-tertiary)' }}
                >
                  Last updated {doc.lastUpdated}
                </p>
              </div>
              <span
                className="mt-1 shrink-0 transition-all group-hover:translate-x-1"
                aria-hidden="true"
                style={{ color: 'var(--text-link)' }}
              >
                →
              </span>
            </Link>
          ))}
        </div>

        <p
          className="mt-12 text-sm"
          style={{ color: 'var(--text-secondary)' }}
        >
          Questions about any of these documents? Email{' '}
          <a
            href="mailto:admin@personaon.com"
            className="hover:opacity-70"
            style={{ color: 'var(--text-link)' }}
          >
            admin@personaon.com
          </a>
          .
        </p>
      </main>
    </div>
  );
}
