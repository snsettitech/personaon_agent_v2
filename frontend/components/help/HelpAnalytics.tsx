'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import type { ReactNode } from 'react';
import { useEffect } from 'react';

import { analytics } from '@/lib/analytics/events';

export function HelpArticleTracker({ slug }: { slug: string }) {
  const searchParams = useSearchParams();
  const source = searchParams.get('source') ?? searchParams.get('utm_source') ?? undefined;

  useEffect(() => {
    analytics.helpArticleViewed({ slug, source });
  }, [slug, source]);

  return null;
}

export function HelpCtaLink({
  slug,
  href,
  children,
  className,
}: {
  slug: string;
  href: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Link
      href={href}
      className={className}
      onClick={() => analytics.helpCtaClicked({ slug, cta: String(children), target: href })}
    >
      {children}
    </Link>
  );
}
