import type { PortfolioProfile } from '@/lib/persona-themes';

/** The loosely-typed redacted profile pack fields the persona page reads.
 *  Mirrors the `PublicProfile` shape inline in ProfileExperience.tsx.
 *  Intentionally omits `voice_capabilities` and `booking` — those are passed
 *  straight to PersonaConsole, not through this presentation-only mapper. */
export interface RawPublicProfile {
  name?: string;
  occupation?: string;
  bio?: string;
  short_description?: string;
  headline?: string;
  areas_of_expertise?: string[];
  key_achievements?: string[];
  personality_traits?: string[];
  contributions?: string[];
  nationality?: string;
  birth_year?: number | null;
  death_year?: number | null;
  verified_profile?: boolean;
  work_experience?: Array<{ company?: string; role?: string; description?: string; start_year?: number; end_year?: number; period?: string }>;
  education?: Array<{ institution?: string; degree?: string; field?: string; start_year?: number; end_year?: number; period?: string }>;
  social_links?: Record<string, string>;
  social_link_visibility?: Record<string, boolean>;
  image_url?: string;
  avatar_url?: string;
  suggested_questions?: string[];
  featured_content?: Array<{ type: 'youtube' | 'instagram' | 'link'; url: string; title?: string; hidden?: boolean }>;
}

/** Coerce a stored URL to http(s) — blocks `javascript:` / `data:` schemes.
 *  The shells receive only pre-sanitized urls (PortfolioProfile contract). */
function safeHttpUrl(url: string): string {
  if (/^https?:\/\//i.test(url)) return url;
  if (/^(javascript|data|vbscript|blob|file):/i.test(url.trim())) return '';
  return `https://${url}`;
}

function periodLabel(entry: { start_year?: number; end_year?: number; period?: string }): string {
  if (entry.period?.trim()) return entry.period.trim();
  if (entry.start_year && entry.end_year) return `${entry.start_year} – ${entry.end_year}`;
  if (entry.start_year) return `${entry.start_year} – Present`;
  if (entry.end_year) return `${entry.end_year}`;
  return '';
}

function lifeLine(p: RawPublicProfile): string | undefined {
  const years =
    p.birth_year || p.death_year ? `${p.birth_year || ''} - ${p.death_year || 'Present'}` : '';
  if (p.nationality && years) return `${p.nationality} • ${years}`;
  return p.nationality || years || undefined;
}

/** Map the redacted public profile to the presentation-only PortfolioProfile the
 *  theme shells consume. ALL urls (social links + featured) are sanitized to
 *  http(s) here so shells receive trusted urls (spec §4.2) and never need to
 *  re-sanitize. */
export function toPortfolioProfile(raw: RawPublicProfile): PortfolioProfile {
  const socialLinks = Object.entries(raw.social_links ?? {})
    .filter(([platform]) => raw.social_link_visibility?.[platform] !== false)
    .map(([platform, url]) => ({ platform, url: safeHttpUrl(url) }))
    .filter((s) => s.url);

  return {
    name: raw.name ?? '',
    headline: raw.occupation || raw.headline || '',
    bio: raw.short_description || raw.bio || '',
    avatarUrl: raw.image_url || raw.avatar_url || undefined,
    verified: Boolean(raw.verified_profile),
    lifeLine: lifeLine(raw),
    socialLinks,
    expertise: raw.areas_of_expertise ?? [],
    achievements: raw.key_achievements ?? [],
    traits: raw.personality_traits ?? [],
    contributions: raw.contributions ?? [],
    workExperience: (raw.work_experience ?? []).map((j) => ({
      company: j.company, role: j.role, description: j.description, period: periodLabel(j),
    })),
    education: (raw.education ?? []).map((e) => ({
      institution: e.institution, degree: e.degree, field: e.field, period: periodLabel(e),
    })),
    featured: (raw.featured_content ?? []).filter((f) => !f.hidden).map((f) => ({
      type: f.type, url: safeHttpUrl(f.url), title: f.title,
    })).filter((f) => f.url),
    pinnedQuestions: raw.suggested_questions ?? [],
  };
}
