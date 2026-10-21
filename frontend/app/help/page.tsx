import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowRight, BookOpen, CheckCircle2 } from 'lucide-react';

import { HELP_ARTICLES } from '@/lib/help/content';

export const metadata: Metadata = {
  title: 'PersonaOn Help',
  description: 'Practical guides for building, improving, publishing, and maintaining a PersonaOn persona.',
};

export default function HelpIndexPage() {
  return (
    <main className="min-h-screen bg-[var(--fog)]">
      <section className="mx-auto max-w-6xl px-5 py-12 md:py-16">
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-2 text-sm font-medium text-[var(--fg-2)] hover:text-[var(--fg)]"
        >
          <ArrowRight className="h-4 w-4 rotate-180" />
          Dashboard
        </Link>

        <div className="mt-10 max-w-3xl">
          <div className="mb-5 inline-flex h-10 w-10 items-center justify-center rounded-xl bg-white text-[var(--signal)] shadow-sm">
            <BookOpen className="h-5 w-5" />
          </div>
          <h1 className="text-4xl font-semibold tracking-normal text-[var(--fg)] md:text-6xl">
            PersonaOn Help
          </h1>
          <p className="mt-5 text-lg leading-8 text-[var(--fg-2)]">
            Short operating guides for making your persona useful, keeping it current,
            and using chat activity as an improvement loop.
          </p>
        </div>

        <div className="mt-10 grid gap-4 md:grid-cols-2">
          {HELP_ARTICLES.map((article) => (
            <Link
              key={article.slug}
              href={`/help/${article.slug}`}
              className="group block rounded-2xl border border-[var(--fog-line)] bg-white p-6 shadow-sm transition hover:-translate-y-0.5 hover:border-[var(--border-accent)] hover:shadow-[var(--shadow-card)]"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-[var(--signal)]">
                    {article.audience}
                  </p>
                  <h2 className="mt-3 text-xl font-semibold text-[var(--fg)]">
                    {article.title}
                  </h2>
                </div>
                <ArrowRight className="mt-1 h-5 w-5 shrink-0 text-[var(--fg-3)] transition group-hover:translate-x-1 group-hover:text-[var(--signal)]" />
              </div>
              <p className="mt-3 text-sm leading-6 text-[var(--fg-2)]">
                {article.description}
              </p>
              <div className="mt-5 flex items-start gap-2 text-sm text-[var(--fg-2)]">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--ok)]" />
                <span>{article.outcome}</span>
              </div>
            </Link>
          ))}
        </div>
      </section>
    </main>
  );
}
