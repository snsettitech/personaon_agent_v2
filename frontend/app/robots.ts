import type { MetadataRoute } from "next";

import { SITE_URL } from "@/lib/seo/constants";

/**
 * robots.txt — allow crawl of public surfaces, disallow authed/app, API,
 * token-bearing share URLs, and the embed widget. Points crawlers at the
 * sitemap index (added in T0-3).
 *
 * AEO note: AI answer-engine crawlers (GPTBot, ClaudeBot, OAI-SearchBot,
 * PerplexityBot, Google-Extended, CCBot) are already permitted via the `*`
 * wildcard; we ALSO name them explicitly below so crawl intent is unambiguous
 * (some fetchers only honor a rule that names their exact user-agent). The
 * per-persona machine-readable summaries at `/p/{handle}/llms.txt` live under
 * the allowed `/` root and are intentionally crawlable — nothing disallows them.
 *
 * Note: Disallow only stops crawling, not indexing of already-known URLs.
 * Thin/unpublished persona pages are additionally `noindex`-gated via page
 * metadata (T0-4), which is the reliable exclusion mechanism.
 */

// Shared disallow list — kept identical for the wildcard rule and the explicit
// AI-crawler rules so no agent gets a broader (or narrower) crawl surface.
const DISALLOW: string[] = [
  "/dashboard",
  "/onboarding",
  "/admin",
  "/api/",
  // NOTE: /auth/ is intentionally crawlable so Google can see the
  // `X-Robots-Tag: noindex` header (next.config) and deindex those
  // pages. Disallowing here would keep already-indexed auth URLs in
  // the index (blocked pages can't be re-crawled to drop them).
  "/share/", // token-bearing share pages
  "/m/", // per-meeting recap share links (already noindex)
  "/widget", // embeddable chat widget
];

// AI answer-engine / training crawlers we explicitly welcome. Allowing them
// mirrors the `*` wildcard — this is intent-signalling, not a new grant.
const AI_CRAWLERS: string[] = [
  "GPTBot", // OpenAI crawl (training + answers)
  "OAI-SearchBot", // ChatGPT search
  "ClaudeBot", // Anthropic
  "PerplexityBot", // Perplexity
  "Google-Extended", // Gemini / Vertex grounding opt-in
  "CCBot", // Common Crawl (feeds many LLMs)
];

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: DISALLOW,
      },
      {
        userAgent: AI_CRAWLERS,
        allow: "/",
        disallow: DISALLOW,
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
