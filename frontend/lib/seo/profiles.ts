import "server-only";

import { resolveApiBaseUrl } from "@/lib/api";

/**
 * Server-only data access for SEO surfaces (sitemap today; SSR persona page in
 * T0-4). The `server-only` import makes accidental client-component usage a
 * build error. Relies on `resolveApiBaseUrl()` (SSR-safe).
 */

export interface PublicProfileHandle {
  handle: string;
  lastModified: string;
}

interface HandlePageResponse {
  items?: Array<{ handle: string; last_modified: string; is_indexable: boolean }>;
  next_offset: number | null;
}

const PAGE_SIZE = 1000;

// Single-sitemap hard cap (sitemaps.org: 50k URLs / 50MB per file). When the
// public-persona count approaches this, switch app/sitemap.ts to
// generateSitemaps() sharding — see docs/architecture/track0-seo-rollout-plan.md.
const MAX_HANDLES = 50_000;

/**
 * Fetch every index-eligible public persona handle for the sitemap, paging
 * through the backend `GET /handles/public` (index-eligible only by default).
 *
 * Errors are swallowed (returns what was collected so far) so a transient
 * backend blip degrades the sitemap to marketing-only rather than 500-ing it.
 */
export async function getAllPublicProfileHandles(): Promise<PublicProfileHandle[]> {
  const base = resolveApiBaseUrl();
  const handles: PublicProfileHandle[] = [];
  let offset = 0;

  while (handles.length < MAX_HANDLES) {
    try {
      const res = await fetch(
        `${base}/handles/public?offset=${offset}&limit=${PAGE_SIZE}`,
        { next: { revalidate: 3600 } },
      );
      if (!res.ok) {
        console.error(`[sitemap] /handles/public offset=${offset} -> ${res.status}`);
        break;
      }
      const data = (await res.json()) as HandlePageResponse;
      for (const item of data.items ?? []) {
        // Defense-in-depth: the endpoint already returns index-eligible only,
        // but never let a non-indexable handle reach the sitemap.
        if (!item.is_indexable) continue;
        handles.push({ handle: item.handle, lastModified: item.last_modified });
      }
      if (data.next_offset == null) break;
      offset = data.next_offset;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "unknown error";
      console.error(`[sitemap] /handles/public offset=${offset} failed: ${msg}`);
      break;
    }
  }

  return handles;
}

/** A single owner-approved public FAQ entry (AEO Q&A pairs). */
export interface PublicFaqEntry {
  question: string;
  answer: string;
}

export interface PublicProfileResult {
  twinId: string;
  handle: string;
  shareToken: string | null;
  isIndexable: boolean;
  lastModified: string;
  profile: Record<string, unknown>;
  /**
   * Owner-approved FAQ pairs surfaced on public AEO surfaces (persona page,
   * per-persona llms.txt). Optional + defaults to [] — absent/empty for every
   * persona until an owner explicitly curates it. NEVER derived from response
   * seeds or any redacted-answer source (see extractPublicFaq).
   */
  public_faq?: PublicFaqEntry[];
}

/**
 * Defensively pull the owner-approved `public_faq` out of the redacted profile
 * pack. Reads ONLY from explicit owner-approved locations:
 *   1. `profile.public_faq`
 *   2. `profile.settings.public_profile.public_faq`
 * and NEVER from `public_response_seeds` / `response_seeds` or any other
 * redacted-answer field — auto-seeding from those would un-redact content the
 * owner never approved for FAQ display. Each entry must have a non-empty string
 * `question` AND `answer`; anything malformed is dropped. Returns [] when absent.
 */
function extractPublicFaq(profile: Record<string, unknown>): PublicFaqEntry[] {
  const settings = profile.settings as Record<string, unknown> | undefined;
  const publicProfile = settings?.public_profile as
    | Record<string, unknown>
    | undefined;
  const candidates: unknown[] = [profile.public_faq, publicProfile?.public_faq];

  for (const candidate of candidates) {
    if (!Array.isArray(candidate)) continue;
    const entries = candidate
      .map((item): PublicFaqEntry | null => {
        if (!item || typeof item !== "object") return null;
        const record = item as Record<string, unknown>;
        const question =
          typeof record.question === "string" ? record.question.trim() : "";
        const answer =
          typeof record.answer === "string" ? record.answer.trim() : "";
        if (!question || !answer) return null;
        return { question, answer };
      })
      .filter((entry): entry is PublicFaqEntry => entry !== null);
    if (entries.length > 0) return entries;
  }
  return [];
}

interface HandleProfileResponse {
  twin_id: string;
  handle: string;
  share_token: string | null;
  is_indexable: boolean;
  last_modified: string;
  profile: Record<string, unknown>;
}

/**
 * Fetch the SSR-ready redacted profile pack for a single public handle via the
 * backend `GET /handles/{handle}/profile`. This is the server-side data source
 * for the persona page (app/p/[handle]/page.tsx) so crawlers receive fully
 * rendered HTML and structured data instead of a client-only shell.
 *
 * Returns `null` on 404, non-ok, or thrown error (transient backend blip
 * degrades to a 404 rather than a 500). Real errors are logged.
 */
export async function getProfile(
  handle: string,
): Promise<PublicProfileResult | null> {
  const base = resolveApiBaseUrl();

  try {
    const res = await fetch(
      `${base}/handles/${encodeURIComponent(handle)}/profile`,
      { next: { revalidate: 3600, tags: [`profile:${handle}`] } },
    );
    if (res.status === 404) return null;
    if (!res.ok) {
      console.error(`[profile] /handles/${handle}/profile -> ${res.status}`);
      return null;
    }
    const data = (await res.json()) as HandleProfileResponse;
    const profile = data.profile ?? {};
    return {
      twinId: data.twin_id,
      handle: data.handle,
      shareToken: data.share_token ?? null,
      isIndexable: data.is_indexable,
      lastModified: data.last_modified,
      profile,
      public_faq: extractPublicFaq(profile),
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : "unknown error";
    console.error(`[profile] /handles/${handle}/profile failed: ${msg}`);
    return null;
  }
}
