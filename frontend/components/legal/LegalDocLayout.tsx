import Link from 'next/link';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Wordmark } from '@/components/brand/Wordmark';

export type LegalSlug = 'terms' | 'terms-creator' | 'privacy' | 'biometric-consent';

interface LegalDocLayoutProps {
  title: string;
  lastUpdated: string;
  slug: LegalSlug;
  markdown: string;
}

const ALL_DOCS: { slug: LegalSlug; title: string }[] = [
  { slug: 'terms', title: 'Terms of Use' },
  { slug: 'terms-creator', title: 'Creator Terms of Use' },
  { slug: 'privacy', title: 'Privacy Policy' },
  { slug: 'biometric-consent', title: 'Biometric Consent' },
];

// The markdown documents include their own H1 title and "Last updated" line
// at the top. We strip those before rendering so the page header (rendered
// by this component) is the canonical source of title + date.
function stripHeader(markdown: string): string {
  const lines = markdown.split('\n');
  let cursor = 0;
  while (cursor < lines.length && lines[cursor].trim() === '') cursor++;
  if (cursor < lines.length && lines[cursor].startsWith('# ')) cursor++;
  while (cursor < lines.length && lines[cursor].trim() === '') cursor++;
  if (cursor < lines.length && /^\*\*Last updated/i.test(lines[cursor])) cursor++;
  while (cursor < lines.length && lines[cursor].trim() === '') cursor++;
  return lines.slice(cursor).join('\n');
}

export function LegalDocLayout({ title, lastUpdated, slug, markdown }: LegalDocLayoutProps) {
  const body = stripHeader(markdown);
  const otherDocs = ALL_DOCS.filter((d) => d.slug !== slug);

  return (
    <div className="min-h-screen" style={{ backgroundColor: 'var(--bg-base)' }}>
      {/* Top nav — matches the Landing/Footer wordmark pattern (dot + name in Plus Jakarta Sans bold) */}
      <header
        className="sticky top-0 z-10 backdrop-blur-md"
        style={{
          backgroundColor: 'rgba(250, 250, 247, 0.88)',
          borderBottom: '1px solid var(--border-subtle)',
        }}
      >
        <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-4 md:px-8">
          <Wordmark href="/" size="sm" />
          <Link
            href="/legal"
            className="text-sm transition-colors hover:opacity-70"
            style={{ color: 'var(--text-secondary)' }}
          >
            ← All legal documents
          </Link>
        </div>
      </header>

      {/* Document */}
      <main className="mx-auto max-w-3xl px-6 py-12 md:px-8 md:py-16">
        <div
          className="mb-10 pb-8"
          style={{ borderBottom: '1px solid var(--border-subtle)' }}
        >
          <h1
            className="text-4xl font-bold tracking-tight md:text-5xl"
            style={{
              color: 'var(--text-primary)',
              fontFamily: "'Playfair Display', Georgia, serif",
            }}
          >
            {title}
          </h1>
          <p className="mt-3 text-sm" style={{ color: 'var(--text-secondary)' }}>
            Last updated {lastUpdated}
          </p>
        </div>

        <article
          className="prose prose-stone max-w-none
            prose-headings:font-bold
            prose-h2:mt-12 prose-h2:text-2xl prose-h2:pt-10
            prose-h3:mt-8 prose-h3:text-xl
            prose-p:leading-7
            prose-li:leading-7
            prose-strong:font-semibold"
          style={
            {
              ['--tw-prose-body' as string]: 'var(--text-primary)',
              ['--tw-prose-headings' as string]: 'var(--text-primary)',
              ['--tw-prose-lead' as string]: 'var(--text-secondary)',
              ['--tw-prose-links' as string]: 'var(--text-link)',
              ['--tw-prose-bold' as string]: 'var(--text-primary)',
              ['--tw-prose-bullets' as string]: 'var(--text-tertiary)',
              ['--tw-prose-counters' as string]: 'var(--text-tertiary)',
              ['--tw-prose-quotes' as string]: 'var(--text-secondary)',
              ['--tw-prose-quote-borders' as string]: 'var(--text-link)',
              ['--tw-prose-hr' as string]: 'var(--border-subtle)',
              ['--tw-prose-th-borders' as string]: 'var(--border-default)',
              ['--tw-prose-td-borders' as string]: 'var(--border-subtle)',
              ['--tw-prose-code' as string]: 'var(--text-primary)',
            } as React.CSSProperties
          }
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown>
        </article>

        {/* Cross-links to other legal docs */}
        <div
          className="mt-16 pt-8"
          style={{ borderTop: '1px solid var(--border-subtle)' }}
        >
          <p
            className="text-sm font-semibold mb-4"
            style={{ color: 'var(--text-secondary)' }}
          >
            Other legal documents
          </p>
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
            {otherDocs.map((doc) => (
              <Link
                key={doc.slug}
                href={`/legal/${doc.slug}`}
                className="transition-colors hover:opacity-70"
                style={{ color: 'var(--text-link)' }}
              >
                {doc.title}
              </Link>
            ))}
          </div>
          <p
            className="mt-6 text-xs"
            style={{ color: 'var(--text-tertiary)' }}
          >
            Questions? Contact us at{' '}
            <a
              href="mailto:admin@personaon.com"
              className="hover:opacity-70"
              style={{ color: 'var(--text-link)' }}
            >
              admin@personaon.com
            </a>
          </p>
        </div>
      </main>
    </div>
  );
}
