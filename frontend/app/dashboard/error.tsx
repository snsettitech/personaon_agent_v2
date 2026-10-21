'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { Card, CardContent } from '@/components/ui';
import { reportRenderError } from '@/lib/analytics/reportError';

interface DashboardErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

/**
 * Segment-level error boundary for /dashboard.
 *
 * Narrower than app/global-error.tsx: it renders inside dashboard/layout.tsx
 * (DashboardShell + sidebar stay mounted), so a crash in one dashboard
 * screen doesn't blank the whole app — the user keeps their nav and can
 * click elsewhere without a hard reload.
 */
export default function DashboardError({ error, reset }: DashboardErrorProps) {
  useEffect(() => {
    reportRenderError(error, { digest: error.digest, boundary: 'dashboard-error' });
  }, [error]);

  return (
    <div className="flex flex-1 items-center justify-center px-6 py-20">
      <Card className="max-w-[480px] text-center">
        <CardContent className="py-10">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
            dashboard error
          </p>
          <h1 className="mt-4 text-2xl font-semibold text-slate-900">
            This screen hit a snag.
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-slate-500">
            Nothing on your persona was lost — just this view failed to
            load. Try again, or head back to your dashboard home.
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <button
              type="button"
              onClick={() => reset()}
              className="rounded-2xl bg-slate-950 px-6 py-3 text-sm font-semibold text-white transition hover:bg-slate-800"
            >
              Try again
            </button>
            <Link
              href="/dashboard"
              className="rounded-2xl border border-black/10 px-6 py-3 text-sm font-semibold text-slate-900 transition hover:bg-black/5"
            >
              Back to dashboard
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
