import type React from 'react';

/** The v1 layout set. Keep in sync with backend ALLOWED_THEME_IDS
 *  (backend/modules/public_profile_pack.py) and the picker in Phase 4. */
export const THEME_IDS = ['classic', 'founder-site', 'conversion-warm', 'editorial', 'split', 'site'] as const;
export type ThemeId = (typeof THEME_IDS)[number];

/** Narrow an untrusted value (e.g. a query param or stored field) to a ThemeId. */
export function isThemeId(value: unknown): value is ThemeId {
  return typeof value === 'string' && (THEME_IDS as readonly string[]).includes(value);
}

/** Curated public-page accent swatches. Keep in sync with backend ALLOWED_ACCENTS
 *  (backend/modules/public_profile_pack.py). */
export const ACCENT_IDS = ['blue', 'orange', 'forest', 'violet', 'slate', 'crimson'] as const;
export type AccentId = (typeof ACCENT_IDS)[number];

/** Narrow an untrusted value (e.g. a stored field) to an AccentId. */
export function isAccent(value: unknown): value is AccentId {
  return typeof value === 'string' && (ACCENT_IDS as readonly string[]).includes(value);
}

export const ACCENT_HEX: Record<AccentId, string> = {
  blue: '#0066cc', orange: '#e0653b', forest: '#2f7d5b',
  violet: '#6c5ce0', slate: '#475569', crimson: '#c0392b',
};

/** Each theme's default accent when the owner hasn't picked one. */
export const DEFAULT_ACCENT_FOR: Record<ThemeId, AccentId> = {
  classic: 'blue', 'founder-site': 'blue', 'conversion-warm': 'orange',
  editorial: 'slate', split: 'blue', site: 'orange',
};

/** Normalized, presentation-only profile. Shells consume ONLY this — never the
 *  raw redacted pack. `lifeLine` is a pre-computed display string (nationality •
 *  years) the Classic hero shows; absent for profiles without those fields. */
export interface PortfolioProfile {
  name: string;
  headline: string;
  bio: string;
  avatarUrl?: string;
  verified: boolean;
  lifeLine?: string;
  socialLinks: ReadonlyArray<{ platform: string; url: string }>; // pre-sanitized http(s)
  expertise: readonly string[];
  achievements: readonly string[];
  traits: readonly string[];
  contributions: readonly string[];
  workExperience: ReadonlyArray<{ company?: string; role?: string; description?: string; period: string }>;
  education: ReadonlyArray<{ institution?: string; degree?: string; field?: string; period: string }>;
  featured: ReadonlyArray<{ type: 'youtube' | 'instagram' | 'link'; url: string; title?: string }>;
  pinnedQuestions: readonly string[];
}

/** Props every theme shell receives. `interaction` is the OPAQUE console slot —
 *  shells render it but never inspect it. `active` (chat-started) is used only by
 *  the Classic shell for its hero→chat collapse; other layouts ignore it.
 *  `mainStyle` lets the adapter pass through the page's bottom padding (which
 *  depends on branding/tier owned by the adapter). */
export interface ThemeShellProps {
  profile: PortfolioProfile;
  interaction: React.ReactNode;
  visibility: Readonly<Record<string, boolean>>; // section_visibility; shells must honor hidden sections
  active?: boolean;
  mainStyle?: React.CSSProperties;
  slots?: {
    topbar?: React.ReactNode;
    branding?: React.ReactNode;
    heroAside?: React.ReactNode; // e.g. pre-chat VoiceCall / cloned-voice notice
  };
}
