'use client';

import posthog from 'posthog-js';
import { PostHogProvider as PHProvider, usePostHog } from 'posthog-js/react';
import { Suspense, useEffect } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';

const POSTHOG_KEY = process.env.NEXT_PUBLIC_POSTHOG_KEY;
// In production, use /ingest reverse proxy to bypass ad blockers.
// In dev, hit PostHog directly (rewrites may not proxy correctly on localhost).
const POSTHOG_HOST = process.env.NEXT_PUBLIC_POSTHOG_HOST
  ?? (process.env.NODE_ENV === 'production' ? '/ingest' : 'https://us.i.posthog.com');
const SAFE_PAGEVIEW_QUERY_PARAMS = new Set([
  'utm_source',
  'utm_medium',
  'utm_campaign',
  'utm_content',
  'utm_term',
  'ref',
  'source',
]);

function buildSafePageviewUrl(pathname: string, rawSearch: string): string {
  if (!rawSearch) return pathname;
  const source = new URLSearchParams(rawSearch);
  const safe = new URLSearchParams();
  source.forEach((value, key) => {
    if (SAFE_PAGEVIEW_QUERY_PARAMS.has(key)) {
      safe.set(key, value.slice(0, 160));
    }
  });
  const query = safe.toString();
  return query ? `${pathname}?${query}` : pathname;
}

// Initialize PostHog once on the client
if (typeof window !== 'undefined' && POSTHOG_KEY) {
  posthog.init(POSTHOG_KEY, {
    api_host: POSTHOG_HOST,
    ui_host: 'https://us.posthog.com',
    person_profiles: 'identified_only',

    // Pageview: manual capture for SPA route changes
    capture_pageview: false,
    capture_pageleave: true,

    // Autocapture: clicks, inputs, form submissions
    autocapture: true,

    // Session replay
    session_recording: {
      maskAllInputs: true,
      maskInputFn: (text) => {
        // Keep replay useful for layout while avoiding captured form contents.
        return '*'.repeat(text.length);
      },
    },

    // Heatmaps
    enable_heatmaps: true,

    // Error tracking — autocapture uncaught exceptions
    capture_exceptions: true,

    // Performance — capture web vitals
    capture_performance: true,

    // Dead clicks and rage clicks (part of autocapture)
    rageclick: true,

    loaded: (ph) => {
      if (process.env.NODE_ENV === 'development') {
        ph.debug();
      }
    },
  });
}

/**
 * Captures page views on Next.js App Router route changes.
 */
function PostHogPageView() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const ph = usePostHog();

  useEffect(() => {
    if (pathname && ph) {
      const url = buildSafePageviewUrl(pathname, searchParams?.toString() ?? '');
      ph.capture('$pageview', { $current_url: url });
    }
  }, [pathname, searchParams, ph]);

  return null;
}

interface PostHogProviderProps {
  children: React.ReactNode;
}

export function PostHogProvider({ children }: PostHogProviderProps) {
  if (!POSTHOG_KEY) {
    return <>{children}</>;
  }

  return (
    <PHProvider client={posthog}>
      <Suspense fallback={null}>
        <PostHogPageView />
      </Suspense>
      {children}
    </PHProvider>
  );
}
