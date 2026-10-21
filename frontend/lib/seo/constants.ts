/**
 * Canonical SEO constants — single source of truth for the site origin and
 * brand entity. Imported by robots.ts, sitemap.ts, layout metadata, and
 * per-page structured data so the canonical host never drifts.
 *
 * In production NEXT_PUBLIC_FRONTEND_URL = https://personaon.com (non-www).
 * The non-www fallback matches the prod canonical; both www and root resolve
 * to the same Cloud Run service, so we standardize on non-www to avoid
 * duplicate-content dilution.
 */
export const SITE_URL = (
  process.env.NEXT_PUBLIC_FRONTEND_URL || "https://personaon.com"
).replace(/\/+$/, "");

export const SITE_NAME = "PersonaOn";

export const SITE_DESCRIPTION =
  "Your professional persona, maintained by an agent. A public page that " +
  "chats with visitors, captures leads, and stays current — in your voice, " +
  "never synthetic.";

/**
 * Official, verified PersonaOn profiles for schema.org `sameAs` (entity
 * disambiguation in the Knowledge Graph + AI engines).
 *
 * These are the confirmed owner brand profiles — genuinely PersonaOn-owned and
 * provided by the owner. A wrong/guessed `sameAs` actively harms Knowledge-Graph
 * disambiguation, so only owner-verified brand URLs belong here.
 */
export const SOCIAL_LINKS: string[] = [
  "https://www.linkedin.com/company/personaon",
  "https://www.reddit.com/user/persona-on",
  "https://x.com/personaon_ai",
  "https://www.instagram.com/personaon.ai",
];
