import posthog from 'posthog-js';

const POSTHOG_KEY = process.env.NEXT_PUBLIC_POSTHOG_KEY;
// Mirrors PostHogProvider.tsx's host selection (kept in sync manually —
// this file must stay import-independent of PostHogProvider so it also
// works when a render crash happens before PostHogProvider ever mounts).
const POSTHOG_HOST = process.env.NEXT_PUBLIC_POSTHOG_HOST
  ?? (process.env.NODE_ENV === 'production' ? '/ingest' : 'https://us.i.posthog.com');

/**
 * Reports a React render-time error (caught by an error boundary) to PostHog.
 *
 * Error boundaries such as app/global-error.tsx can fire before
 * PostHogProvider has ever mounted — e.g. a crash inside the root layout's
 * own render tree, before its children (including PostHogProvider) run.
 * In that case the shared `posthog` singleton is still un-initialized, and
 * calling `captureException` on it silently no-ops. This guards that case
 * with a minimal defensive init (just enough to deliver the exception)
 * instead of quietly dropping the report.
 */
export function reportRenderError(error: unknown, context?: Record<string, unknown>): void {
  if (typeof window === 'undefined' || !POSTHOG_KEY) return;

  try {
    if (!posthog.__loaded) {
      // Kept in sync with PostHogProvider.tsx's real init call (manually —
      // this file must stay import-independent of PostHogProvider). This
      // fallback should currently be unreachable in practice, since
      // PostHogProvider.tsx runs its init at module-evaluation time, before
      // any error boundary that imports this file could render. But if a
      // future refactor moves that init into the component body/a useEffect,
      // this fallback becomes live — so its privacy/capture settings must
      // not be weaker than the real init, or a real crash would produce an
      // unmasked recording/capture window until PostHogProvider re-inits.
      posthog.init(POSTHOG_KEY, {
        api_host: POSTHOG_HOST,
        person_profiles: 'identified_only',
        capture_pageview: false,
        autocapture: false,
        session_recording: {
          maskAllInputs: true,
        },
        capture_exceptions: true,
        rageclick: true,
      });
    }

    posthog.captureException(error, context);
  } catch (reportingError) {
    // Never let telemetry failure mask the original render error.
    console.error('[reportRenderError] Failed to report exception to PostHog:', reportingError);
  }
}
