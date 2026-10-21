import type { PortfolioProfile } from '../types';

// ---------------------------------------------------------------------------
// Public FAQ — the owner-approved, crawlable Q&A contract shared with the
// backend. A persona profile MAY carry `public_faq: { question, answer }[]`.
//
// SAFETY (non-negotiable): `public_faq` is a NEW, owner-approved field that is
// EMPTY by default. It is read ONLY from the explicit field the owner populated
// — never derived from `response_seeds` / `public_response_seeds` or any other
// redacted source. Seeding is a separate, later, reviewed pass. Until that pass
// runs, `readPublicFaq` returns `[]` and every shell renders nothing, so this
// change can never un-redact existing content.
//
// The field is intentionally NOT part of the typed `PortfolioProfile` yet (that
// type lives outside this shells/ package). The render half therefore reads it
// through a narrow cast and validates every entry defensively.
// ---------------------------------------------------------------------------

export interface PublicFaqEntry {
  question: string;
  answer: string;
}

/**
 * Read owner-approved public FAQ pairs off the presentation profile, defensively.
 * Returns `[]` for anything malformed or absent — never throws, never fetches.
 * Entries with a non-string / blank question or answer are dropped.
 */
export function readPublicFaq(profile: PortfolioProfile): PublicFaqEntry[] {
  const raw = (profile as PortfolioProfile & { public_faq?: unknown }).public_faq;
  if (!Array.isArray(raw)) return [];

  const out: PublicFaqEntry[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const q = (item as { question?: unknown }).question;
    const a = (item as { answer?: unknown }).answer;
    if (typeof q !== 'string' || typeof a !== 'string') continue;
    const question = q.trim();
    const answer = a.trim();
    if (question && answer) out.push({ question, answer });
  }
  return out;
}
