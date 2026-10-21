import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // The /experience demo route extracts resume text server-side with these
  // CommonJS Node libs — keep them external so `output: 'standalone'` traces
  // them instead of bundling (which breaks their internal requires).
  serverExternalPackages: ['pdf-parse', 'mammoth'],
  async redirects() {
    return [
      { source: '/onboarding/v2', destination: '/onboarding', permanent: true },
      {
        // Force ONE canonical host: 301 www → non-www. Both hosts were serving
        // 200 with no redirect, so Google overrode our non-www canonical tag,
        // chose www.personaon.com, and deindexed the non-www homepage as a
        // "duplicate". A 301 is a directive (the canonical <link> is only a hint)
        // — this consolidates all signals to personaon.com and transfers the
        // www impressions over. Flagged by the SEO watchdog.
        source: '/:path*',
        has: [{ type: 'host', value: 'www.personaon.com' }],
        destination: 'https://personaon.com/:path*',
        permanent: true,
      },
    ];
  },
  async headers() {
    return [
      {
        // Auth pages (login/signup/etc.) are public and got indexed by Google.
        // X-Robots-Tag noindex deindexes them. They are intentionally NOT in
        // robots.txt disallow anymore — a blocked page can't be crawled, so
        // Google would never see this header and the URLs would stay indexed.
        source: '/auth/:path*',
        headers: [{ key: 'X-Robots-Tag', value: 'noindex, follow' }],
      },
    ];
  },
  // PostHog reverse proxy — routes analytics through our domain to bypass ad blockers.
  // Increases event capture rate by 10-30%.
  async rewrites() {
    return [
      {
        source: '/ingest/static/:path*',
        destination: 'https://us-assets.i.posthog.com/static/:path*',
      },
      {
        source: '/ingest/:path*',
        destination: 'https://us.i.posthog.com/:path*',
      },
      {
        source: '/ingest/decide',
        destination: 'https://us.i.posthog.com/decide',
      },
    ];
  },
  // Skip PostHog rewrites from middleware processing
  skipTrailingSlashRedirect: true,
  // IMPORTANT: No hardcoded fallback values.
  // In production: env vars injected at build time via Cloud Run / GitHub Actions.
  // In local dev: set in frontend/.env.local (see frontend/.env.example).
  // output: 'standalone' is required for the Cloud Run Dockerfile.
  output: 'standalone',
};

export default nextConfig;
