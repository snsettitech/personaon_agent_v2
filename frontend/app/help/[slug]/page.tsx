import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { ArrowRight, CheckCircle2, CircleDot, Sparkles } from 'lucide-react';

import { HelpArticleTracker, HelpCtaLink } from '@/components/help/HelpAnalytics';
import { getHelpArticle, HELP_ARTICLES } from '@/lib/help/content';

type PageProps = {
  params: Promise<{ slug: string }>;
};

export function generateStaticParams() {
  return HELP_ARTICLES.map((article) => ({ slug: article.slug }));
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const article = getHelpArticle(slug);
  if (!article) {
    return { title: 'Help Article' };
  }
  return {
    title: `${article.title} | PersonaOn Help`,
    description: article.description,
  };
}

export default async function HelpArticlePage({ params }: PageProps) {
  const { slug } = await params;
  const article = getHelpArticle(slug);
  if (!article) notFound();

  return (
    <main className="min-h-screen bg-[var(--fog)]">
      <HelpArticleTracker slug={article.slug} />
      <section className="mx-auto max-w-6xl px-5 py-10 md:py-14">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <Link
            href="/help"
            className="inline-flex items-center gap-2 text-sm font-medium text-[var(--fg-2)] hover:text-[var(--fg)]"
          >
            <ArrowRight className="h-4 w-4 rotate-180" />
            Help
          </Link>
          <HelpCtaLink
            slug={article.slug}
            href={article.cta.href}
            className="inline-flex h-10 items-center gap-2 rounded-full bg-[var(--signal)] px-4 text-sm font-semibold text-white transition hover:bg-[var(--signal-hot)]"
          >
            {article.cta.label}
          </HelpCtaLink>
        </div>

        <header className="mt-10 grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-end">
          <div>
            <p className="text-sm font-semibold uppercase tracking-wider text-[var(--signal)]">
              {article.audience}
            </p>
            <h1 className="mt-4 text-4xl font-semibold tracking-normal text-[var(--fg)] md:text-6xl">
              {article.title}
            </h1>
            <p className="mt-5 max-w-3xl text-lg leading-8 text-[var(--fg-2)]">
              {article.description}
            </p>
          </div>

          <div className="rounded-2xl border border-[var(--fog-line)] bg-white p-5 shadow-sm">
            <div className="flex items-start gap-3">
              <div className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--primary-50)] text-[var(--signal)]">
                <Sparkles className="h-4 w-4" />
              </div>
              <div>
                <p className="text-sm font-semibold text-[var(--fg)]">Target outcome</p>
                <p className="mt-1 text-sm leading-6 text-[var(--fg-2)]">{article.outcome}</p>
              </div>
            </div>
          </div>
        </header>

        <div className="mt-12 grid gap-8 lg:grid-cols-[minmax(0,1fr)_340px]">
          <article className="space-y-6">
            {article.sections.map((section) => (
              <section
                key={section.heading}
                className="rounded-2xl border border-[var(--fog-line)] bg-white p-6 shadow-sm"
              >
                <h2 className="text-2xl font-semibold text-[var(--fg)]">{section.heading}</h2>
                <p className="mt-3 text-base leading-7 text-[var(--fg-2)]">{section.body}</p>
                {section.bullets && (
                  <ul className="mt-5 space-y-3">
                    {section.bullets.map((bullet) => (
                      <li key={bullet} className="flex gap-3 text-sm leading-6 text-[var(--fg-2)]">
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--ok)]" />
                        <span>{bullet}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            ))}
          </article>

          <aside className="space-y-4 lg:sticky lg:top-6 lg:self-start">
            <div className="rounded-2xl border border-[var(--fog-line)] bg-white p-5 shadow-sm">
              <h2 className="text-base font-semibold text-[var(--fg)]">Use Cases</h2>
              <div className="mt-4 space-y-4">
                {article.useCases.map((useCase) => (
                  <div key={useCase.title} className="border-t border-[var(--fog-line)] pt-4 first:border-t-0 first:pt-0">
                    <div className="flex items-start gap-2">
                      <CircleDot className="mt-0.5 h-4 w-4 shrink-0 text-[var(--signal)]" />
                      <h3 className="text-sm font-semibold text-[var(--fg)]">{useCase.title}</h3>
                    </div>
                    <p className="mt-2 text-sm leading-6 text-[var(--fg-2)]">{useCase.persona}</p>
                    <p className="mt-2 text-sm leading-6 text-[var(--fg-2)]">
                      <span className="font-semibold text-[var(--fg)]">Trigger:</span> {useCase.trigger}
                    </p>
                    <p className="mt-1 text-sm leading-6 text-[var(--fg-2)]">
                      <span className="font-semibold text-[var(--fg)]">Action:</span> {useCase.action}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-2xl border border-[var(--fog-line)] bg-[var(--ink)] p-5 text-white shadow-sm">
              <p className="text-sm font-semibold">Next step</p>
              <p className="mt-2 text-sm leading-6 text-white/70">
                Apply this guide inside your workspace, then review the next chat or lead that comes in.
              </p>
              <HelpCtaLink
                slug={article.slug}
                href={article.cta.href}
                className="mt-4 inline-flex h-10 items-center gap-2 rounded-full bg-white px-4 text-sm font-semibold text-[var(--ink)] transition hover:bg-white/90"
              >
                {article.cta.label}
              </HelpCtaLink>
            </div>
          </aside>
        </div>
      </section>
    </main>
  );
}
