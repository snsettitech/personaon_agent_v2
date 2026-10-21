'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { motion, useReducedMotion, AnimatePresence, type Variants } from 'framer-motion';
import { useTwin } from '@/lib/context/TwinContext';
import { API_ENDPOINTS } from '@/lib/constants';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { useToast } from '@/components/ui';
import { resolveApiBaseUrl } from '@/lib/api';
import { getSupabaseClient } from '@/lib/supabase/client';
import { formatPersonaDisplayName } from '@/lib/branding/personaName';
import { ExtractionReviewCard } from '@/components/persona/ExtractionReviewCard';
import { headlineTextError, meaningfulTextError } from '@/lib/validation/textQuality';

type WorkExperienceDraft = {
  company: string;
  role: string;
  startYear: string;
  endYear: string;
  isCurrent: boolean;
  description: string;
};

type EducationDraft = {
  institution: string;
  degree: string;
  field: string;
  startYear: string;
  endYear: string;
  description: string;
};

type ProfileDraft = {
  displayName: string;
  organization: string;
  role: string;
  headline: string;
  bio: string;
  careerContext: string;
  pinnedQuestions: string[];
  socialLinks: string[];
  profileVideoEnabled: boolean;
  avatarUrl: string;
  mindLabel: string;
  areasOfExpertise: string[];
  keyAchievements: string[];
  contributions: string[];
  personalityTraits: string[];
  speakingStyle: string;
  workExperience: WorkExperienceDraft[];
  education: EducationDraft[];
  nationality: string;
  birthYear: string;
  deathYear: string;
};

type ProfileInsightsResponse = {
  profile_pack?: PersonaProfilePack | null;
  metrics?: Record<string, unknown> | null;
  question_suggestions?: string[];
  question_capacity_estimate?: number;
  question_capacity_prompt?: string;
  name_deep_research?: {
    run_id?: string;
    status?: string;
  } | null;
  extraction_review?: { work_experience_issues?: string[] } | null;
};

type PersonaProfilePack = {
  name?: string;
  occupation?: string;
  headline?: string;
  bio?: string;
  short_description?: string;
  avatar_url?: string;
  image_url?: string;
  birth_year?: number | null;
  death_year?: number | null;
  nationality?: string;
  verified_profile?: boolean;
  verified_claims_count?: number;
  areas_of_expertise?: string[];
  personality_traits?: string[];
  key_achievements?: string[];
  contributions?: string[];
  speaking_style?: string;
  social_links?: Record<string, string>;
  pinned_questions?: string[];
  education?: Array<{ institution?: string; degree?: string; field?: string; description?: string; start_year?: number | null; end_year?: number | null }>;
  work_experience?: Array<{ company?: string; role?: string; description?: string; start_year?: number | null; end_year?: number | null; is_current?: boolean }>;
};

const DEFAULT_PINNED_QUESTIONS = [
  'What inspired you to start this project?',
  'What should people know about your style and approach?',
  'What are the best ways to connect with you?',
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function normalizeStringArray(
  value: unknown,
  fallback: string[] = [],
  max = Number.POSITIVE_INFINITY
): string[] {
  if (!Array.isArray(value)) return [...fallback];
  const cleaned = value
    .map((item) => (typeof item === 'string' ? item.trim() : ''))
    .filter((item) => item.length > 0);
  const next = cleaned.slice(0, max);
  return next.length > 0 ? next : [...fallback];
}

function normalizeYear(value: unknown): string {
  if (typeof value === 'number' && Number.isFinite(value)) return String(Math.trunc(value));
  if (typeof value === 'string') {
    const match = value.match(/\d{4}/);
    return match ? match[0] : '';
  }
  return '';
}

function normalizeWorkExperience(value: unknown, max = 8): WorkExperienceDraft[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((entry) => {
      if (!isRecord(entry)) return null;
      const role = typeof entry.role === 'string' ? entry.role.trim() : '';
      const company = typeof entry.company === 'string' ? entry.company.trim() : '';
      const description = typeof entry.description === 'string' ? entry.description.trim() : '';
      const startYear = normalizeYear(entry.start_year);
      const endYear = normalizeYear(entry.end_year);
      const isCurrent = entry.is_current === true || (!endYear && Boolean(startYear || role || company));
      if (!role && !company && !description) return null;
      return { role, company, description, startYear, endYear, isCurrent };
    })
    .filter((entry): entry is WorkExperienceDraft => Boolean(entry))
    .slice(0, max);
}

function normalizeEducation(value: unknown, max = 8): EducationDraft[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((entry) => {
      if (!isRecord(entry)) return null;
      const institution = typeof entry.institution === 'string' ? entry.institution.trim() : '';
      const degree = typeof entry.degree === 'string' ? entry.degree.trim() : '';
      const field = typeof entry.field === 'string' ? entry.field.trim() : '';
      const description = typeof entry.description === 'string' ? entry.description.trim() : '';
      const startYear = normalizeYear(entry.start_year);
      const endYear = normalizeYear(entry.end_year);
      if (!institution && !degree && !field && !description) return null;
      return { institution, degree, field, description, startYear, endYear };
    })
    .filter((entry): entry is EducationDraft => Boolean(entry))
    .slice(0, max);
}

function yearToNumber(value: string): number | null {
  const cleaned = value.trim();
  if (!/^\d{4}$/.test(cleaned)) return null;
  return Number(cleaned);
}

function normalizeSocialLinkArray(value: unknown, max = 8): string[] {
  if (isRecord(value)) {
    return normalizeStringArray(Object.values(value), [], max);
  }
  return normalizeStringArray(value, [], max);
}

function inferSocialLinkLabel(url: string, index: number): string {
  try {
    const parsed = new URL(url.startsWith('http') ? url : `https://${url}`);
    const host = parsed.hostname.toLowerCase();
    if (host.includes('linkedin.com')) return 'linkedin';
    if (host.includes('instagram.com')) return 'instagram';
    if (host.includes('youtube.com') || host.includes('youtu.be')) return 'youtube';
    if (host.includes('x.com') || host.includes('twitter.com')) return 'twitter';
    if (host.includes('github.com')) return 'github';
    if (host.includes('wikipedia.org')) return 'wikipedia';
    return index === 0 ? 'website' : `link${index + 1}`;
  } catch {
    return index === 0 ? 'website' : `link${index + 1}`;
  }
}

function socialLinksToRecord(links: string[]): Record<string, string> {
  return links.reduce<Record<string, string>>((accumulator, link, index) => {
    const cleaned = link.trim();
    if (!cleaned) return accumulator;
    const normalized = cleaned.startsWith('http') ? cleaned : `https://${cleaned}`;
    const baseLabel = inferSocialLinkLabel(normalized, index);
    let label = baseLabel;
    let suffix = 2;
    while (accumulator[label] && accumulator[label] !== normalized) {
      label = `${baseLabel}_${suffix}`;
      suffix += 1;
    }
    accumulator[label] = normalized;
    return accumulator;
  }, {});
}

function firstName(fullName: string): string {
  const parts = fullName.trim().split(/\s+/);
  return parts[0] || 'Creator';
}

function initials(fullName: string): string {
  const letters = fullName
    .trim()
    .split(/\s+/)
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2);
  return letters.join('').toUpperCase() || 'DT';
}

function profileLifeLine(profile: PersonaProfilePack | null): string {
  if (!profile) return '';
  const years =
    profile.birth_year || profile.death_year
      ? `${profile.birth_year || ''}${profile.birth_year || profile.death_year ? ' - ' : ''}${profile.death_year || 'Present'}`
      : '';
  if (profile.nationality && years) return `${profile.nationality} • ${years}`;
  return profile.nationality || years;
}

function IconPlus() {
  return (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4" />
    </svg>
  );
}

function IconClose() {
  return (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
    </svg>
  );
}

function IconLock() {
  return (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm3-10V7a3 3 0 016 0v4H9z" />
    </svg>
  );
}

function IconChat() {
  return (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
    </svg>
  );
}

function IconExternalLink() {
  return (
    <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
    </svg>
  );
}

function IconPencil() {
  return (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
    </svg>
  );
}

type PersonaScoreCategory = {
  label: string;
  score: number;
  max: number;
};

type PersonaScoreResponse = {
  total_score: number;
  total_max: number;
  categories: PersonaScoreCategory[];
  label: string;
};

function PersonaScoreRing({ twinId }: { twinId: string }) {
  const [data, setData] = useState<PersonaScoreResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function fetchScore() {
      try {
        const base = resolveApiBaseUrl();
        const res = await authFetchStandalone(`${base}/v2/twins/${twinId}/score`);
        if (!res.ok) throw new Error(`Score API ${res.status}`);
        const json = await res.json();
        if (!cancelled) setData(json as PersonaScoreResponse);
      } catch (err) {
        console.error('[PersonaScoreRing] Failed to load score:', err);
        if (!cancelled) setError(true);
      }
    }

    void fetchScore();
    return () => { cancelled = true; };
  }, [twinId]);

  if (error || !data || !Array.isArray(data.categories)) return null;

  const pct = data.total_max > 0 ? Math.round((data.total_score / data.total_max) * 100) : 0;
  const circumference = 2 * Math.PI * 22;

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative flex h-14 w-14 items-center justify-center">
        <svg className="h-14 w-14 -rotate-90" viewBox="0 0 48 48">
	          <circle cx="24" cy="24" r="22" fill="none" stroke="#E5E5EA" strokeWidth="4" />
	          <circle
	            cx="24" cy="24" r="22" fill="none"
	            stroke="#0066cc" strokeWidth="4" strokeLinecap="round"
            strokeDasharray={`${(pct / 100) * circumference} ${circumference}`}
          />
        </svg>
        <span className="absolute text-xs font-bold" style={{ color: 'var(--text-primary)' }}>{pct}%</span>
      </div>
      <span
        className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
        style={{ backgroundColor: 'var(--bg-elevated)', color: 'var(--text-secondary)' }}
      >
	        <span className="inline-block h-1.5 w-1.5 rounded-full bg-[#0066cc]" />
        {data.label}
      </span>
    </div>
  );
}

function ProfilePageContent() {
  const { activeTwin, user, refreshTwins, isLoading, twins, setActiveTwin } = useTwin();
  const { showToast } = useToast();
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedTwinId = searchParams.get('twinId');
  const [canonicalProfileId, setCanonicalProfileId] = useState<string | null>(null);
  const [profileInsights, setProfileInsights] = useState<ProfileInsightsResponse | null>(null);
  const [showAllSuggestions, setShowAllSuggestions] = useState(false);

  useEffect(() => {
    void refreshTwins();
  }, [refreshTwins]);

  useEffect(() => {
    let cancelled = false;

    async function resolveCanonicalProfile() {
      try {
        const response = await authFetchStandalone('/profile');
        if (!response.ok) {
          if (response.status === 404 && !cancelled) {
            setCanonicalProfileId(null);
          }
          return;
        }
        const payload = await response.json();
        if (!cancelled) {
          setCanonicalProfileId(typeof payload?.id === 'string' ? payload.id : null);
        }
      } catch (error) {
        console.error('[Profile] Failed to resolve canonical profile:', error);
      }
    }

    void resolveCanonicalProfile();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!requestedTwinId) return;
    if (canonicalProfileId && requestedTwinId !== canonicalProfileId) return;
    if (activeTwin?.id === requestedTwinId) return;
    const exists = twins.some((t) => t.id === requestedTwinId);
    if (!exists) return;
    setActiveTwin(requestedTwinId);
  }, [requestedTwinId, canonicalProfileId, activeTwin?.id, twins, setActiveTwin]);

  useEffect(() => {
    if (!canonicalProfileId) return;
    if (activeTwin?.id === canonicalProfileId) return;
    const exists = twins.some((t) => t.id === canonicalProfileId);
    if (!exists) return;
    setActiveTwin(canonicalProfileId);
  }, [canonicalProfileId, activeTwin?.id, twins, setActiveTwin]);

  const effectiveTwin = useMemo(() => {
    if (!canonicalProfileId) return activeTwin;
    return twins.find((t) => t.id === canonicalProfileId) || activeTwin;
  }, [canonicalProfileId, twins, activeTwin]);

  useEffect(() => {
    let cancelled = false;

    async function loadProfileInsights() {
      if (!effectiveTwin?.id) {
        setProfileInsights(null);
        return;
      }

      try {
        const response = await authFetchStandalone(API_ENDPOINTS.TWIN_PROFILE_INSIGHTS(effectiveTwin.id));
        if (!response.ok) {
          throw new Error(`Failed to load profile insights (${response.status})`);
        }
        const payload = await response.json();
        if (!cancelled) {
          setProfileInsights(payload as ProfileInsightsResponse);
        }
      } catch (error) {
        console.error('[Profile] Failed to load profile insights:', error);
        if (!cancelled) {
          setProfileInsights(null);
        }
      }
    }

    void loadProfileInsights();
    return () => {
      cancelled = true;
    };
  }, [effectiveTwin?.id]);

  const handleExtractionReviewDismissed = useCallback(() => {
    setProfileInsights((prev) => (prev ? { ...prev, extraction_review: null } : prev));
  }, []);

  // ── LinkedIn verification state ───────────────────────────────────────────
  const isLinkedInVerified = useMemo(() => {
    const settings = isRecord(effectiveTwin?.settings) ? effectiveTwin.settings : {};
    return settings.identity_verified === true || Boolean(isRecord(settings.public_profile) ? (settings.public_profile as Record<string, unknown>).verified_profile : false);
  }, [effectiveTwin?.settings]);

  const [verifyingLinkedIn, setVerifyingLinkedIn] = useState(false);
  const [linkedInVerifyDone, setLinkedInVerifyDone] = useState(false);
  const verifyOnReturnFiredRef = useRef(false);

  const handleConnectLinkedIn = useCallback(async () => {
    if (!effectiveTwin?.id) return;
    setVerifyingLinkedIn(true);
    try {
      const supabase = getSupabaseClient();
      const verifyRes = await authFetchStandalone(`/v2/twins/${effectiveTwin.id}/verify-linkedin`, { method: 'POST', body: '{}' });
      if (verifyRes.ok) {
        setLinkedInVerifyDone(true);
        showToast('Identity verified with LinkedIn.', 'success');
        void refreshTwins();
        return;
      }
      const { error } = await supabase.auth.signInWithOAuth({
        provider: 'linkedin_oidc',
        options: { redirectTo: `${window.location.origin}/auth/callback?redirect=/dashboard/profile&action=verify_twin&twin_id=${effectiveTwin.id}` },
      });
      if (error) showToast('LinkedIn connection failed. Please try again.', 'error');
    } catch {
      showToast('Could not connect LinkedIn. Please try again.', 'error');
    } finally {
      setVerifyingLinkedIn(false);
    }
  }, [effectiveTwin?.id, showToast, refreshTwins]);

  // After returning from LinkedIn OAuth, auto-call verify endpoint
  useEffect(() => {
    if (verifyOnReturnFiredRef.current) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get('action') !== 'verify_twin' || !params.get('twin_id') || !effectiveTwin?.id) return;
    verifyOnReturnFiredRef.current = true;
    window.history.replaceState({}, '', window.location.pathname);
    void (async () => {
      try {
        const res = await authFetchStandalone(`/v2/twins/${effectiveTwin.id}/verify-linkedin`, { method: 'POST', body: '{}' });
        if (res.ok) {
          setLinkedInVerifyDone(true);
          showToast('Identity verified with LinkedIn.', 'success');
          void refreshTwins();
        } else {
          showToast('LinkedIn verification failed. Please try again.', 'error');
        }
      } catch {
        showToast('LinkedIn verification failed. Please try again.', 'error');
      }
    })();
  }, [effectiveTwin?.id, showToast, refreshTwins]);

	  const derivedProfile = useMemo<ProfileDraft>(() => {
	    const settings = isRecord(effectiveTwin?.settings) ? effectiveTwin.settings : {};
	    const profile = isRecord(settings.public_profile) ? settings.public_profile : {};
	    const pp = isRecord(settings.persona_profile) ? settings.persona_profile : {};
	    const pack = profileInsights?.profile_pack;
	    const tagline = typeof settings.tagline === 'string' ? settings.tagline : '';
	    const publicIntro = typeof settings.public_intro === 'string' ? settings.public_intro : '';
    const displayName = formatPersonaDisplayName(
      (typeof profile.display_name === 'string' && profile.display_name.trim()) ||
      (typeof pp.name === 'string' && pp.name.trim()) ||
      effectiveTwin?.name ||
      user?.full_name ||
      'Persona'
    );

    const organization =
      (typeof profile.organization === 'string' && profile.organization.trim()) || '';
    const role =
      (typeof profile.role === 'string' && profile.role.trim()) ||
      (typeof pp.occupation === 'string' && pp.occupation.trim()) ||
      '';
    const headline =
      (typeof profile.headline === 'string' && profile.headline.trim()) ||
      tagline ||
      (typeof pp.short_description === 'string' && pp.short_description.trim()) ||
      '';
    const bio =
      (typeof profile.bio === 'string' && profile.bio.trim()) ||
      publicIntro ||
      (typeof pp.short_description === 'string' && pp.short_description.trim()) ||
      'Add a short bio so visitors know what this persona can help with.';
    const pinnedQuestions = normalizeStringArray(profile.pinned_questions, DEFAULT_PINNED_QUESTIONS, 5);
    const socialLinks = normalizeSocialLinkArray(
      profile.social_links || pp.social_links, 8);
    const profileVideoEnabled =
      typeof profile.profile_video_enabled === 'boolean' ? profile.profile_video_enabled : true;
    const avatarUrl =
      (typeof profile.avatar_url === 'string' && profile.avatar_url.trim()) ||
      (typeof pp.image_url === 'string' && pp.image_url.trim()) ||
      user?.avatar_url ||
      '';

    const mindLabel =
      (typeof profile.mind_label === 'string' && profile.mind_label.trim()) || 'Persona';

	    const careerContext =
	      (typeof profile.career_context === 'string' && profile.career_context.trim()) || '';
	    const areasOfExpertise = normalizeStringArray(
	      profile.areas_of_expertise || pp.areas_of_expertise || pack?.areas_of_expertise,
	      [],
	      8
	    );
	    const keyAchievements = normalizeStringArray(
	      profile.key_achievements || pp.key_achievements || pp.achievements || pack?.key_achievements,
	      [],
	      8
	    );
	    const contributions = normalizeStringArray(
	      profile.contributions || pp.contributions || pack?.contributions,
	      [],
	      8
	    );
	    const personalityTraits = normalizeStringArray(
	      profile.personality_traits || pp.personality_traits || pack?.personality_traits,
	      [],
	      8
	    );
	    const speakingStyle =
	      (typeof profile.speaking_style === 'string' && profile.speaking_style.trim()) ||
	      (typeof pp.speaking_style === 'string' && pp.speaking_style.trim()) ||
	      pack?.speaking_style ||
	      '';
	    const workExperience = normalizeWorkExperience(
	      profile.work_experience || pp.work_experience || pack?.work_experience
	    );
	    const education = normalizeEducation(
	      profile.education || pp.education || pack?.education
	    );

	    return {
	      displayName,
      organization,
      role,
      headline,
      bio,
      careerContext,
      pinnedQuestions,
      socialLinks,
	      profileVideoEnabled,
	      avatarUrl,
	      mindLabel,
	      areasOfExpertise,
	      keyAchievements,
	      contributions,
	      personalityTraits,
	      speakingStyle,
	      workExperience,
	      education,
	      nationality:
	        (typeof profile.nationality === 'string' && profile.nationality.trim()) ||
	        (typeof pack?.nationality === 'string' && pack.nationality.trim()) ||
	        '',
	      birthYear:
	        profile.birth_year != null
	          ? String(profile.birth_year)
	          : pack?.birth_year != null
	            ? String(pack.birth_year)
	            : '',
	      deathYear:
	        profile.death_year != null
	          ? String(profile.death_year)
	          : pack?.death_year != null
	            ? String(pack.death_year)
	            : '',
	    };
	  }, [effectiveTwin?.name, effectiveTwin?.settings, profileInsights?.profile_pack, user?.avatar_url, user?.full_name]);

	  const [draft, setDraft] = useState<ProfileDraft>(derivedProfile);
	  const [isEditing, setIsEditing] = useState(false);
	  const [isSaving, setIsSaving] = useState(false);

	  const previewProfile = useMemo<PersonaProfilePack>(() => {
	    const pack = profileInsights?.profile_pack;
	    const packSocial = Object.fromEntries(
	      draft.socialLinks
	        .filter((link) => link.trim())
	        .map((link, index) => [`link${index + 1}`, link.trim()])
	    );

	    return {
	      name: draft.displayName || pack?.name,
	      occupation:
	        [draft.role, draft.organization].filter(Boolean).join(' at ') ||
	        pack?.occupation ||
	        draft.headline,
	      headline: draft.headline || pack?.headline,
	      bio: draft.bio || pack?.bio,
	      short_description: draft.bio || draft.headline || pack?.short_description || pack?.bio,
	      avatar_url: draft.avatarUrl || pack?.avatar_url || pack?.image_url,
	      birth_year:
	        draft.birthYear.trim() !== ''
	          ? Number.parseInt(draft.birthYear, 10) || pack?.birth_year
	          : pack?.birth_year,
	      death_year:
	        draft.deathYear.trim() !== ''
	          ? Number.parseInt(draft.deathYear, 10) || pack?.death_year
	          : pack?.death_year,
	      nationality: draft.nationality.trim() || pack?.nationality,
	      verified_profile: Boolean(pack?.verified_profile),
	      verified_claims_count: pack?.verified_claims_count,
	      areas_of_expertise: draft.areasOfExpertise,
	      personality_traits: draft.personalityTraits,
	      key_achievements: draft.keyAchievements,
	      contributions: draft.contributions,
	      speaking_style: draft.speakingStyle,
	      social_links: packSocial,
	      pinned_questions: draft.pinnedQuestions,
	      education: draft.education.map((entry) => ({
	        institution: entry.institution,
	        degree: entry.degree,
	        field: entry.field,
	        description: entry.description,
	        start_year: yearToNumber(entry.startYear),
	        end_year: yearToNumber(entry.endYear),
	      })),
	      work_experience: draft.workExperience.map((entry) => ({
	        company: entry.company,
	        role: entry.role,
	        description: entry.description,
	        start_year: yearToNumber(entry.startYear),
	        end_year: entry.isCurrent ? null : yearToNumber(entry.endYear),
	        is_current: entry.isCurrent,
	      })),
	    };
	  }, [draft, profileInsights?.profile_pack]);

  const previewLifeLine = useMemo(() => profileLifeLine(previewProfile), [previewProfile]);
  const previewSocialLinks = useMemo(() => Object.entries(previewProfile.social_links || {}), [previewProfile]);

	  useEffect(() => {
    setDraft(derivedProfile);
    setIsEditing(false);
  }, [derivedProfile]);

  const handleAddQuestion = () => {
    setDraft((prev) => {
      if (prev.pinnedQuestions.length >= 5) return prev;
      return { ...prev, pinnedQuestions: [...prev.pinnedQuestions, ''] };
    });
  };

  const handleUpdateQuestion = (idx: number, value: string) => {
    setDraft((prev) => ({
      ...prev,
      pinnedQuestions: prev.pinnedQuestions.map((item, itemIdx) => (itemIdx === idx ? value : item)),
    }));
  };

  const handleRemoveQuestion = (idx: number) => {
    setDraft((prev) => ({
      ...prev,
      pinnedQuestions: prev.pinnedQuestions.filter((_, itemIdx) => itemIdx !== idx),
    }));
  };

  const handleAddLink = () => {
    setDraft((prev) => ({ ...prev, socialLinks: [...prev.socialLinks, ''] }));
  };

  const handleUpdateLink = (idx: number, value: string) => {
    setDraft((prev) => ({
      ...prev,
      socialLinks: prev.socialLinks.map((item, itemIdx) => (itemIdx === idx ? value : item)),
    }));
  };

	  const handleRemoveLink = (idx: number) => {
	    setDraft((prev) => ({
	      ...prev,
	      socialLinks: prev.socialLinks.filter((_, itemIdx) => itemIdx !== idx),
	    }));
	  };

	  const updateStringList = (
	    key: 'areasOfExpertise' | 'keyAchievements' | 'contributions' | 'personalityTraits',
	    idx: number,
	    value: string
	  ) => {
	    setDraft((prev) => ({
	      ...prev,
	      [key]: prev[key].map((item, itemIdx) => (itemIdx === idx ? value : item)),
	    }));
	  };

	  const addStringListItem = (
	    key: 'areasOfExpertise' | 'keyAchievements' | 'contributions' | 'personalityTraits'
	  ) => {
	    setDraft((prev) => ({ ...prev, [key]: [...prev[key], ''] }));
	    setIsEditing(true);
	  };

	  const removeStringListItem = (
	    key: 'areasOfExpertise' | 'keyAchievements' | 'contributions' | 'personalityTraits',
	    idx: number
	  ) => {
	    setDraft((prev) => ({ ...prev, [key]: prev[key].filter((_, itemIdx) => itemIdx !== idx) }));
	  };

	  const addWorkExperience = () => {
	    setDraft((prev) => ({
	      ...prev,
	      workExperience: [
	        ...prev.workExperience,
	        { company: '', role: '', startYear: '', endYear: '', isCurrent: true, description: '' },
	      ],
	    }));
	    setIsEditing(true);
	  };

	  const updateWorkExperience = <K extends keyof WorkExperienceDraft>(
	    idx: number,
	    key: K,
	    value: WorkExperienceDraft[K]
	  ) => {
	    setDraft((prev) => ({
	      ...prev,
	      workExperience: prev.workExperience.map((entry, itemIdx) => (
	        itemIdx === idx ? { ...entry, [key]: value } : entry
	      )),
	    }));
	  };

	  const removeWorkExperience = (idx: number) => {
	    setDraft((prev) => ({
	      ...prev,
	      workExperience: prev.workExperience.filter((_, itemIdx) => itemIdx !== idx),
	    }));
	  };

	  const addEducation = () => {
	    setDraft((prev) => ({
	      ...prev,
	      education: [
	        ...prev.education,
	        { institution: '', degree: '', field: '', startYear: '', endYear: '', description: '' },
	      ],
	    }));
	    setIsEditing(true);
	  };

	  const updateEducation = <K extends keyof EducationDraft>(
	    idx: number,
	    key: K,
	    value: EducationDraft[K]
	  ) => {
	    setDraft((prev) => ({
	      ...prev,
	      education: prev.education.map((entry, itemIdx) => (
	        itemIdx === idx ? { ...entry, [key]: value } : entry
	      )),
	    }));
	  };

	  const removeEducation = (idx: number) => {
	    setDraft((prev) => ({
	      ...prev,
	      education: prev.education.filter((_, itemIdx) => itemIdx !== idx),
	    }));
	  };

  const handleOpenChat = (seedQuestion?: string) => {
    if (!effectiveTwin?.id) {
      showToast('No profile is selected yet.', 'info');
      return;
    }
    const twinStatus = String(effectiveTwin?.status || '').toLowerCase();
    const canChatByStatus =
      twinStatus === 'active' || twinStatus === 'persona_built' || twinStatus === 'live';
    const canChatByLegacyFlag = !twinStatus && Boolean(effectiveTwin?.is_active);
    const canChat = canChatByStatus || canChatByLegacyFlag;
    if (!canChat) {
      showToast('Profile is still building. Chat unlocks when setup is complete.', 'info');
      return;
    }

    const params = new URLSearchParams();
    params.set('source', 'profile');
    params.set('twinId', effectiveTwin.id);
    if (seedQuestion && seedQuestion.trim()) {
      params.set('q', seedQuestion.trim());
    }
    router.push(`/dashboard/chat?${params.toString()}`);
  };

  const handleSave = async () => {
    if (!effectiveTwin) return;

    // Reject "nill"-style garbage bio/headline before saving. Mirrors the
    // server-side check in modules/text_quality.py (and patch_twin, which
    // enforces this on the raw settings dict too) — this is a fail-fast UX
    // nicety, not the sole guard, since this form PATCHes /v2/twins/{id}
    // directly with a raw settings object.
    //
    // An exactly-empty field (never set) is left alone — only a non-empty
    // value that fails the meaningfulness bar (too short, single word,
    // all-whitespace, or repeated-character filler) is rejected, so personas
    // that have simply never had a bio/headline aren't blocked from saving
    // unrelated changes.
    const headlineError = draft.headline.length > 0 ? headlineTextError(draft.headline) : undefined;
    const bioError = draft.bio.length > 0 ? meaningfulTextError(draft.bio) : undefined;
    if (headlineError || bioError) {
      showToast(bioError || headlineError || 'Please fix the highlighted fields.', 'error');
      return;
    }

    const cleanedPinned = draft.pinnedQuestions
      .map((item) => item.trim())
      .filter((item) => item.length > 0)
      .slice(0, 5);

	    const cleanedSocial = draft.socialLinks
	      .map((item) => item.trim())
	      .filter((item) => item.length > 0);
	    const cleanedExpertise = draft.areasOfExpertise.map((item) => item.trim()).filter(Boolean).slice(0, 8);
	    const cleanedAchievements = draft.keyAchievements.map((item) => item.trim()).filter(Boolean).slice(0, 8);
	    const cleanedContributions = draft.contributions.map((item) => item.trim()).filter(Boolean).slice(0, 8);
	    const cleanedTraits = draft.personalityTraits.map((item) => item.trim()).filter(Boolean).slice(0, 8);
	    const cleanedWork = draft.workExperience
	      .map((entry) => ({
	        company: entry.company.trim(),
	        role: entry.role.trim(),
	        description: entry.description.trim(),
	        start_year: yearToNumber(entry.startYear),
	        end_year: entry.isCurrent ? null : yearToNumber(entry.endYear),
	        is_current: entry.isCurrent,
	      }))
	      .filter((entry) => entry.company || entry.role || entry.description)
	      .slice(0, 8);
	    const cleanedEducation = draft.education
	      .map((entry) => ({
	        institution: entry.institution.trim(),
	        degree: entry.degree.trim(),
	        field: entry.field.trim(),
	        description: entry.description.trim(),
	        start_year: yearToNumber(entry.startYear),
	        end_year: yearToNumber(entry.endYear),
	      }))
	      .filter((entry) => entry.institution || entry.degree || entry.field || entry.description)
	      .slice(0, 8);
	    const cleanedSocialRecord = socialLinksToRecord(cleanedSocial);
	    const occupation = [draft.role.trim(), draft.organization.trim()].filter(Boolean).join(' at ');

	    const currentSettings = isRecord(effectiveTwin.settings) ? effectiveTwin.settings : {};
	    const currentProfile = isRecord(currentSettings.public_profile) ? currentSettings.public_profile : {};
	    const currentPersonaProfile = isRecord(currentSettings.persona_profile) ? currentSettings.persona_profile : {};

	    const cleanedNationality = draft.nationality.trim();
	    const parsedBirthYear = draft.birthYear.trim() === '' ? null : Number.parseInt(draft.birthYear, 10);
	    const parsedDeathYear = draft.deathYear.trim() === '' ? null : Number.parseInt(draft.deathYear, 10);
	    const cleanedBirthYear = typeof parsedBirthYear === 'number' && Number.isFinite(parsedBirthYear) ? parsedBirthYear : null;
	    const cleanedDeathYear = typeof parsedDeathYear === 'number' && Number.isFinite(parsedDeathYear) ? parsedDeathYear : null;

	    const nextSettings = {
	      ...currentSettings,
	      public_profile: {
	        ...currentProfile,
        display_name: draft.displayName.trim(),
        organization: draft.organization.trim(),
        role: draft.role.trim(),
	        headline: draft.headline.trim(),
	        bio: draft.bio.trim(),
	        career_context: draft.careerContext.trim(),
	        pinned_questions: cleanedPinned,
	        social_links: cleanedSocialRecord,
	        profile_video_enabled: draft.profileVideoEnabled,
	        avatar_url: draft.avatarUrl.trim(),
	        mind_label: draft.mindLabel.trim() || 'Persona',
	        areas_of_expertise: cleanedExpertise,
	        key_achievements: cleanedAchievements,
	        contributions: cleanedContributions,
	        personality_traits: cleanedTraits,
	        speaking_style: draft.speakingStyle.trim(),
	        work_experience: cleanedWork,
	        education: cleanedEducation,
	        nationality: cleanedNationality,
	        birth_year: cleanedBirthYear,
	        death_year: cleanedDeathYear,
	      },
	      persona_profile: {
	        ...currentPersonaProfile,
	        name: draft.displayName.trim(),
	        display_name: draft.displayName.trim(),
	        organization: draft.organization.trim(),
	        occupation: occupation || draft.headline.trim(),
	        headline: draft.headline.trim(),
	        bio: draft.bio.trim(),
	        short_description: draft.bio.trim() || draft.headline.trim(),
	        image_url: draft.avatarUrl.trim(),
	        social_links: cleanedSocialRecord,
	        areas_of_expertise: cleanedExpertise,
	        key_achievements: cleanedAchievements,
	        achievements: cleanedAchievements,
	        contributions: cleanedContributions,
	        personality_traits: cleanedTraits,
	        speaking_style: draft.speakingStyle.trim(),
	        work_experience: cleanedWork,
	        education: cleanedEducation,
	        nationality: cleanedNationality,
	        birth_year: cleanedBirthYear,
	        death_year: cleanedDeathYear,
	      },
	    };

    setIsSaving(true);
    try {
      const response = await authFetchStandalone(API_ENDPOINTS.TWIN_DETAIL(effectiveTwin.id), {
        method: 'PATCH',
        body: JSON.stringify({ settings: nextSettings }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(errorText || 'Failed to save profile settings');
      }

      await refreshTwins();
      setIsEditing(false);
      showToast('Profile updated', 'success');
    } catch (error) {
      console.error('[Profile] Failed to save settings:', error);
      showToast('Failed to save profile', 'error');
    } finally {
      setIsSaving(false);
    }
  };

  // Keep hook order stable across loading, empty, and loaded states.
  const shouldReduceMotion = useReducedMotion();

  if (isLoading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-t-transparent" style={{ borderColor: 'var(--primary-500)', borderTopColor: 'transparent' }} />
      </div>
    );
  }

  if (!effectiveTwin) {
    return (
      <div className="rounded-2xl border bg-white p-8" style={{ borderColor: 'var(--border-subtle)' }}>
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>No persona selected</h2>
        <p className="mt-2 text-sm" style={{ color: 'var(--text-secondary)' }}>Select a persona to customize your profile.</p>
      </div>
    );
  }

  const suggestionList = profileInsights?.question_suggestions ?? [];
  const visibleSuggestions = showAllSuggestions ? suggestionList : suggestionList.slice(0, 6);

	  // Shared input style for edit mode
	  const inputCls = 'w-full rounded-xl border px-4 py-2.5 text-sm focus:outline-none focus:ring-2 transition'
	    + ' bg-white focus:ring-[#0066cc]/20 focus:border-[#0066cc]';
  const inputStyle = { borderColor: 'var(--border-subtle)', color: 'var(--text-primary)' };

  const fadeUp: Variants = {
    hidden: { opacity: 0, y: shouldReduceMotion ? 0 : 16 },
    visible: (i: number) => ({
      opacity: 1,
      y: 0,
      transition: { duration: 0.35, ease: 'easeOut' as const, delay: i * 0.06 },
    }),
  };

  const card: Variants = {
    hidden: { opacity: 0, y: shouldReduceMotion ? 0 : 12 },
    visible: { opacity: 1, y: 0, transition: { duration: 0.3, ease: 'easeOut' as const } },
  };

  const signalSections = [
    {
      key: 'areasOfExpertise' as const,
      label: 'Expertise',
      placeholder: 'AI product strategy',
      values: draft.areasOfExpertise,
    },
    {
      key: 'keyAchievements' as const,
      label: 'Achievements',
      placeholder: 'Launched a product used by...',
      values: draft.keyAchievements,
    },
    {
      key: 'contributions' as const,
      label: 'Contributions',
      placeholder: 'Published essays on...',
      values: draft.contributions,
    },
    {
      key: 'personalityTraits' as const,
      label: 'Personality',
      placeholder: 'Clear, direct, warm',
      values: draft.personalityTraits,
    },
  ];

  return (
    <div className="min-h-screen bg-[#f5f5f7] pb-28 pt-4">
      <div className="mx-auto max-w-6xl px-4 md:px-6">
        {effectiveTwin?.id && profileInsights?.extraction_review?.work_experience_issues?.length ? (
          <ExtractionReviewCard
            issues={profileInsights.extraction_review.work_experience_issues}
            twinId={effectiveTwin.id}
            onDismissed={handleExtractionReviewDismissed}
          />
        ) : null}
        <motion.section
          className="overflow-hidden rounded-[2rem] border border-black/10 bg-white shadow-[0_28px_90px_rgba(15,23,42,0.08)]"
          initial="hidden"
          animate="visible"
          custom={0}
          variants={fadeUp}
        >
          <div className="relative p-6 md:p-8">
            <div className="pointer-events-none absolute inset-x-0 top-0 h-52 bg-[radial-gradient(circle_at_50%_0%,rgba(0,102,204,0.11),transparent_62%)]" />
            <div className="relative z-10 flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
              <div className="flex flex-col gap-5 md:flex-row md:items-start">
                <div className="relative h-28 w-28 shrink-0 overflow-hidden rounded-[2rem] bg-[linear-gradient(135deg,rgba(0,102,204,0.18),rgba(255,255,255,0.96))] text-[#0b3d91] shadow-[0_22px_70px_rgba(15,23,42,0.22)] ring-1 ring-[#0066cc]/12">
                  {draft.avatarUrl ? (
                    <img src={draft.avatarUrl} alt={draft.displayName} className="h-full w-full object-cover" />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center text-3xl font-semibold">
                      {initials(draft.displayName)}
                    </div>
                  )}
                  {(isLinkedInVerified || linkedInVerifyDone) && (
                    <span className="absolute bottom-2 right-2 flex h-7 w-7 items-center justify-center rounded-full border-2 border-white bg-[#0066cc] shadow" title="LinkedIn verified">
                      <svg className="h-3.5 w-3.5 text-white" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                    </span>
                  )}
                </div>

                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold uppercase tracking-[0.24em] text-[#0066cc]">Persona Profile Builder</p>
                  {isEditing ? (
                    <div className="mt-4 grid gap-3 md:grid-cols-2">
                      <input value={draft.displayName} onChange={(e) => setDraft((prev) => ({ ...prev, displayName: e.target.value }))} className={inputCls} style={inputStyle} placeholder="Display name" />
                      <input value={draft.avatarUrl} onChange={(e) => setDraft((prev) => ({ ...prev, avatarUrl: e.target.value }))} className={inputCls} style={inputStyle} placeholder="Avatar URL" />
                      <input value={draft.role} onChange={(e) => setDraft((prev) => ({ ...prev, role: e.target.value }))} className={inputCls} style={inputStyle} placeholder="Role" />
                      <input value={draft.organization} onChange={(e) => setDraft((prev) => ({ ...prev, organization: e.target.value }))} className={inputCls} style={inputStyle} placeholder="Organization" />
                      <input value={draft.headline} onChange={(e) => setDraft((prev) => ({ ...prev, headline: e.target.value }))} className={`${inputCls} md:col-span-2`} style={inputStyle} placeholder="Headline" />
                      <input value={draft.nationality} onChange={(e) => setDraft((prev) => ({ ...prev, nationality: e.target.value }))} className={inputCls} style={inputStyle} placeholder="Nationality (e.g. Indian-American)" />
                      <div className="grid grid-cols-2 gap-2">
                        <input
                          value={draft.birthYear}
                          onChange={(e) => setDraft((prev) => ({ ...prev, birthYear: e.target.value.replace(/\D/g, '').slice(0, 4) }))}
                          inputMode="numeric"
                          maxLength={4}
                          className={inputCls}
                          style={inputStyle}
                          placeholder="Birth year"
                        />
                        <input
                          value={draft.deathYear}
                          onChange={(e) => setDraft((prev) => ({ ...prev, deathYear: e.target.value.replace(/\D/g, '').slice(0, 4) }))}
                          inputMode="numeric"
                          maxLength={4}
                          className={inputCls}
                          style={inputStyle}
                          placeholder="Death year (leave blank if living)"
                        />
                      </div>
                    </div>
                  ) : (
                    <>
                      <h1 className="mt-4 text-4xl font-semibold tracking-[-0.045em] text-[#111111] md:text-6xl">
                        {draft.displayName}
                      </h1>
                      <p className="mt-3 text-base text-[#6e6e73] md:text-lg">
                        {[draft.role, draft.organization].filter(Boolean).join(' at ') || draft.headline || 'Add role and organization so people know who this persona represents.'}
                      </p>
                      {draft.headline && (
                        <p className="mt-4 max-w-2xl text-xl leading-8 tracking-[-0.02em] text-[#1d1d1f]">
                          {draft.headline}
                        </p>
                      )}
                      {previewLifeLine && <p className="mt-2 text-sm text-[#8e8e93]">{previewLifeLine}</p>}
                    </>
                  )}
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                {!isLinkedInVerified && !linkedInVerifyDone && (
                  <button
                    onClick={handleConnectLinkedIn}
                    disabled={verifyingLinkedIn}
                    className="inline-flex cursor-pointer items-center gap-2 rounded-full border border-black/10 bg-white px-4 py-2 text-sm font-semibold text-[#1d1d1f] shadow-sm transition hover:border-[#0066cc]/30 hover:text-[#0066cc] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {verifyingLinkedIn ? 'Connecting...' : 'Verify with LinkedIn'}
                  </button>
                )}
                {isEditing ? (
                  <>
                    <button
                      onClick={() => { setDraft(derivedProfile); setIsEditing(false); }}
                      className="cursor-pointer rounded-full border border-black/10 bg-white px-5 py-2 text-sm font-semibold text-[#6e6e73] transition hover:text-[#111111]"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleSave}
                      disabled={isSaving}
                      className="cursor-pointer rounded-full bg-[#0066cc] px-5 py-2 text-sm font-semibold text-white shadow-[0_12px_28px_rgba(0,102,204,0.24)] transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {isSaving ? 'Saving...' : 'Save profile'}
                    </button>
                  </>
                ) : (
                  <button
                    onClick={() => setIsEditing(true)}
                    className="inline-flex cursor-pointer items-center gap-2 rounded-full bg-[#0066cc] px-5 py-2 text-sm font-semibold text-white shadow-[0_12px_28px_rgba(0,102,204,0.24)] transition hover:brightness-105"
                  >
                    <IconPencil />
                    Edit profile
                  </button>
                )}
              </div>
            </div>
          </div>
        </motion.section>

        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="space-y-6">
            <motion.section className="rounded-[2rem] border border-black/10 bg-white p-6 shadow-sm" initial="hidden" animate="visible" custom={1} variants={card}>
              <h2 className="mb-5 text-2xl font-semibold tracking-[-0.03em] text-[#111111]">About</h2>
              {isEditing ? (
                <div className="grid gap-4">
                  <textarea rows={6} value={draft.bio} onChange={(e) => setDraft((prev) => ({ ...prev, bio: e.target.value }))} className="w-full resize-y rounded-2xl border border-black/10 bg-white px-4 py-3 text-sm leading-7 text-[#111111] focus:border-[#0066cc] focus:outline-none focus:ring-2 focus:ring-[#0066cc]/20" placeholder="Public bio" />
                  <textarea rows={4} value={draft.careerContext} onChange={(e) => setDraft((prev) => ({ ...prev, careerContext: e.target.value }))} className="w-full resize-y rounded-2xl border border-black/10 bg-[#f5f5f7] px-4 py-3 text-sm leading-7 text-[#111111] focus:border-[#0066cc] focus:outline-none focus:ring-2 focus:ring-[#0066cc]/20" placeholder="Career story or background notes" />
                </div>
              ) : (
                <div className="space-y-4 text-[15px] leading-7 text-[#1d1d1f]">
                  <p>{draft.bio || 'Add a bio so people know what your persona can answer and how it should represent you.'}</p>
                  {draft.careerContext && <p className="rounded-2xl bg-[#f5f5f7] p-4 text-[#6e6e73]">{draft.careerContext}</p>}
                </div>
              )}
            </motion.section>

            <motion.section className="rounded-[2rem] border border-black/10 bg-white p-6 shadow-sm" initial="hidden" animate="visible" custom={2} variants={card}>
              <div className="mb-5 flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-2xl font-semibold tracking-[-0.03em] text-[#111111]">Experience</h2>
                </div>
                {isEditing && <button onClick={addWorkExperience} className="inline-flex cursor-pointer items-center gap-2 rounded-full bg-[#0066cc] px-4 py-2 text-sm font-semibold text-white"><IconPlus /> Add</button>}
              </div>
              <div className="space-y-4">
                {draft.workExperience.length === 0 && !isEditing && <p className="rounded-2xl bg-[#f5f5f7] p-4 text-sm text-[#6e6e73]">Add experience so the persona can answer questions about your roles and work history.</p>}
                {draft.workExperience.map((entry, idx) => (
                  <div key={`work-${idx}`} className="rounded-2xl border border-black/10 bg-[#f5f5f7] p-4">
                    {isEditing ? (
                      <div className="grid gap-3 md:grid-cols-2">
                        <input value={entry.role} onChange={(e) => updateWorkExperience(idx, 'role', e.target.value)} className={inputCls} style={inputStyle} placeholder="Role or title" />
                        <input value={entry.company} onChange={(e) => updateWorkExperience(idx, 'company', e.target.value)} className={inputCls} style={inputStyle} placeholder="Company" />
                        <input value={entry.startYear} onChange={(e) => updateWorkExperience(idx, 'startYear', e.target.value)} className={inputCls} style={inputStyle} placeholder="Start year" />
                        <input value={entry.endYear} onChange={(e) => updateWorkExperience(idx, 'endYear', e.target.value)} disabled={entry.isCurrent} className={inputCls} style={inputStyle} placeholder="End year" />
                        <label className="flex items-center gap-2 text-sm text-[#6e6e73]"><input type="checkbox" checked={entry.isCurrent} onChange={(e) => updateWorkExperience(idx, 'isCurrent', e.target.checked)} /> Current role</label>
                        <button onClick={() => removeWorkExperience(idx)} className="justify-self-start rounded-full border border-black/10 bg-white px-3 py-1.5 text-xs font-semibold text-[#6e6e73] hover:text-red-600">Remove</button>
                        <textarea value={entry.description} onChange={(e) => updateWorkExperience(idx, 'description', e.target.value)} className="md:col-span-2 w-full resize-y rounded-xl border border-black/10 bg-white px-4 py-3 text-sm leading-6 focus:border-[#0066cc] focus:outline-none focus:ring-2 focus:ring-[#0066cc]/20" rows={3} placeholder="Role notes" />
                      </div>
                    ) : (
                      <div>
                        <p className="text-base font-semibold text-[#111111]">{entry.role || 'Role'}</p>
                        <p className="mt-1 text-sm text-[#6e6e73]">{[entry.company, [entry.startYear, entry.isCurrent ? 'Present' : entry.endYear].filter(Boolean).join(' - ')].filter(Boolean).join(' | ')}</p>
                        {entry.description && <p className="mt-3 text-sm leading-6 text-[#1d1d1f]">{entry.description}</p>}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </motion.section>

            <motion.section className="rounded-[2rem] border border-black/10 bg-white p-6 shadow-sm" initial="hidden" animate="visible" custom={3} variants={card}>
              <div className="mb-5 flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-2xl font-semibold tracking-[-0.03em] text-[#111111]">Education</h2>
                </div>
                {isEditing && <button onClick={addEducation} className="inline-flex cursor-pointer items-center gap-2 rounded-full bg-[#0066cc] px-4 py-2 text-sm font-semibold text-white"><IconPlus /> Add</button>}
              </div>
              <div className="space-y-4">
                {draft.education.length === 0 && !isEditing && <p className="rounded-2xl bg-[#f5f5f7] p-4 text-sm text-[#6e6e73]">Add education if it helps the persona explain your background accurately.</p>}
                {draft.education.map((entry, idx) => (
                  <div key={`education-${idx}`} className="rounded-2xl border border-black/10 bg-[#f5f5f7] p-4">
                    {isEditing ? (
                      <div className="grid gap-3 md:grid-cols-2">
                        <input value={entry.institution} onChange={(e) => updateEducation(idx, 'institution', e.target.value)} className={inputCls} style={inputStyle} placeholder="Institution" />
                        <input value={entry.degree} onChange={(e) => updateEducation(idx, 'degree', e.target.value)} className={inputCls} style={inputStyle} placeholder="Degree" />
                        <input value={entry.field} onChange={(e) => updateEducation(idx, 'field', e.target.value)} className={inputCls} style={inputStyle} placeholder="Field of study" />
                        <div className="grid grid-cols-2 gap-2"><input value={entry.startYear} onChange={(e) => updateEducation(idx, 'startYear', e.target.value)} className={inputCls} style={inputStyle} placeholder="Start" /><input value={entry.endYear} onChange={(e) => updateEducation(idx, 'endYear', e.target.value)} className={inputCls} style={inputStyle} placeholder="End" /></div>
                        <button onClick={() => removeEducation(idx)} className="justify-self-start rounded-full border border-black/10 bg-white px-3 py-1.5 text-xs font-semibold text-[#6e6e73] hover:text-red-600">Remove</button>
                        <textarea value={entry.description} onChange={(e) => updateEducation(idx, 'description', e.target.value)} className="md:col-span-2 w-full resize-y rounded-xl border border-black/10 bg-white px-4 py-3 text-sm leading-6 focus:border-[#0066cc] focus:outline-none focus:ring-2 focus:ring-[#0066cc]/20" rows={3} placeholder="Education notes" />
                      </div>
                    ) : (
                      <div>
                        <p className="text-base font-semibold text-[#111111]">{entry.degree || entry.field || 'Education'}</p>
                        <p className="mt-1 text-sm text-[#6e6e73]">{[entry.institution, [entry.startYear, entry.endYear].filter(Boolean).join(' - ')].filter(Boolean).join(' | ')}</p>
                        {entry.description && <p className="mt-3 text-sm leading-6 text-[#1d1d1f]">{entry.description}</p>}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </motion.section>

            <motion.section className="rounded-[2rem] border border-black/10 bg-white p-6 shadow-sm" initial="hidden" animate="visible" custom={4} variants={card}>
              <h2 className="text-2xl font-semibold tracking-[-0.03em] text-[#111111]">Expertise</h2>
              <div className="mt-5 grid gap-4 md:grid-cols-2">
                {signalSections.map((section) => (
                  <div key={section.key} className="rounded-2xl border border-black/10 bg-[#f5f5f7] p-4">
                    <div className="mb-3 flex items-start justify-between gap-2">
                      <div>
                        <p className="font-semibold text-[#111111]">{section.label}</p>
                      </div>
                      {isEditing && <button onClick={() => addStringListItem(section.key)} className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-[#0066cc] shadow-sm">Add</button>}
                    </div>
                    {isEditing ? (
                      <div className="space-y-2">
                        {section.values.map((item, idx) => (
                          <div key={`${section.key}-${idx}`} className="flex gap-2">
                            <input value={item} onChange={(e) => updateStringList(section.key, idx, e.target.value)} className={inputCls} style={inputStyle} placeholder={section.placeholder} />
                            <button onClick={() => removeStringListItem(section.key, idx)} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-black/10 bg-white text-[#6e6e73] hover:text-red-600"><IconClose /></button>
                          </div>
                        ))}
                        {section.values.length === 0 && <p className="text-sm text-[#8e8e93]">No entries yet.</p>}
                      </div>
                    ) : (
                      <div className="flex flex-wrap gap-2">
                        {section.values.length > 0 ? section.values.map((item) => <span key={item} className="rounded-full border border-black/10 bg-white px-3 py-1 text-xs font-semibold text-[#1d1d1f]">{item}</span>) : <span className="text-sm text-[#8e8e93]">Add this to improve answer quality.</span>}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </motion.section>
          </div>

          <aside className="space-y-6 lg:sticky lg:top-6 lg:self-start">
            <motion.section className="rounded-[2rem] border border-black/10 bg-white p-6 shadow-sm" initial="hidden" animate="visible" custom={1} variants={fadeUp}>
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[#0066cc]">Readiness</p>
              <div className="mt-4 flex justify-center">{effectiveTwin?.id && <PersonaScoreRing twinId={effectiveTwin.id} />}</div>
              <div className="mt-5 space-y-2 text-sm text-[#6e6e73]">
                <p>
                  Status:{' '}
                  <span
                    className="rounded-full bg-[#0f7a2a] px-2.5 py-1 text-xs font-semibold capitalize shadow-[0_8px_18px_rgba(15,122,42,0.18)]"
                    style={{ color: '#ffffff' }}
                  >
                    {String(effectiveTwin?.status || 'Draft').replace(/_/g, ' ')}
                  </span>
                </p>
              </div>
            </motion.section>

            <motion.section className="rounded-[2rem] border border-black/10 bg-white p-6 shadow-sm" initial="hidden" animate="visible" custom={2} variants={fadeUp}>
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[#0066cc]">Ask me about</p>
                </div>
                {isEditing && <span className="text-xs font-semibold text-[#8e8e93]">Max 5</span>}
              </div>
              {isEditing ? (
                <div className="space-y-2">
                  {draft.pinnedQuestions.map((question, idx) => (
                    <div key={`question-edit-${idx}`} className="flex gap-2">
                      <input type="text" value={question} onChange={(e) => handleUpdateQuestion(idx, e.target.value)} className={inputCls} style={inputStyle} placeholder="Question visitors should ask" />
                      <button onClick={() => handleRemoveQuestion(idx)} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-black/10 bg-white text-[#6e6e73] hover:text-red-600"><IconClose /></button>
                    </div>
                  ))}
                  <button onClick={handleAddQuestion} disabled={draft.pinnedQuestions.length >= 5} className="inline-flex cursor-pointer items-center gap-2 rounded-full border border-black/10 bg-[#f5f5f7] px-3 py-1.5 text-xs font-semibold text-[#0066cc] disabled:cursor-not-allowed disabled:opacity-40"><IconPlus /> Add question</button>
                </div>
              ) : (
                <div className="space-y-2">
                  {draft.pinnedQuestions.map((question, idx) => (
                    <button key={`question-view-${idx}`} onClick={() => handleOpenChat(question)} className="block w-full cursor-pointer rounded-2xl bg-[#f5f5f7] px-4 py-3 text-left text-sm leading-6 text-[#111111] transition hover:bg-[#ebebef]">
                      <span className="mr-2 text-xs font-semibold text-[#0066cc]">{String(idx + 1).padStart(2, '0')}</span>{question}
                    </button>
                  ))}
                </div>
              )}
            </motion.section>

            <motion.section className="rounded-[2rem] border border-black/10 bg-white p-6 shadow-sm" initial="hidden" animate="visible" custom={3} variants={fadeUp}>
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[#0066cc]">Voice & Style</p>
              {isEditing ? (
                <textarea value={draft.speakingStyle} onChange={(e) => setDraft((prev) => ({ ...prev, speakingStyle: e.target.value }))} rows={4} className="mt-4 w-full resize-y rounded-2xl border border-black/10 bg-[#f5f5f7] px-4 py-3 text-sm leading-6 text-[#111111] focus:border-[#0066cc] focus:outline-none focus:ring-2 focus:ring-[#0066cc]/20" placeholder="Direct, thoughtful, practical, concise..." />
              ) : (
                <p className="mt-4 rounded-2xl bg-[#f5f5f7] p-4 text-sm italic leading-6 text-[#1d1d1f]">{draft.speakingStyle || 'Add speaking style so answers feel more like you.'}</p>
              )}
            </motion.section>

            <motion.section className="rounded-[2rem] border border-black/10 bg-white p-6 shadow-sm" initial="hidden" animate="visible" custom={4} variants={fadeUp}>
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[#0066cc]">Links</p>
              {isEditing ? (
                <div className="mt-4 space-y-2">
                  {draft.socialLinks.map((link, idx) => (
                    <div key={`social-${idx}`} className="flex gap-2">
                      <input type="text" value={link} onChange={(e) => handleUpdateLink(idx, e.target.value)} placeholder="domain.com/handle" className={inputCls} style={inputStyle} />
                      <button onClick={() => handleRemoveLink(idx)} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-black/10 bg-white text-[#6e6e73] hover:text-red-600"><IconClose /></button>
                    </div>
                  ))}
                  <button onClick={handleAddLink} className="inline-flex cursor-pointer items-center gap-2 rounded-full border border-black/10 bg-[#f5f5f7] px-3 py-1.5 text-xs font-semibold text-[#0066cc]"><IconPlus /> Add link</button>
                </div>
              ) : (
                <div className="mt-4 flex flex-wrap gap-2">
                  {previewSocialLinks.length > 0 ? previewSocialLinks.map(([label, url], idx) => (
                    <a key={`sidebar-${idx}-${label}-${url}`} href={url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 rounded-full border border-black/10 bg-[#f5f5f7] px-3 py-1.5 text-xs font-semibold capitalize text-[#1d1d1f] transition hover:text-[#0066cc]">
                      {label}<IconExternalLink />
                    </a>
                  )) : <p className="text-sm text-[#8e8e93]">No public links yet.</p>}
                </div>
              )}
            </motion.section>

            {suggestionList.length > 0 && (
              <motion.section className="rounded-[2rem] border border-black/10 bg-white p-6 shadow-sm" initial="hidden" animate="visible" custom={5} variants={fadeUp}>
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[#0066cc]">Try asking your persona:</p>
                <div className="mt-4 flex flex-wrap gap-2">
                  {visibleSuggestions.map((question, idx) => (
                    <button key={`suggestion-${idx}`} onClick={() => handleOpenChat(question)} className="cursor-pointer rounded-full border border-black/10 bg-[#f5f5f7] px-3 py-1.5 text-xs font-semibold text-[#1d1d1f] transition hover:text-[#0066cc]">{question}</button>
                  ))}
                </div>
                {suggestionList.length > 6 && (
                  <button onClick={() => setShowAllSuggestions((v) => !v)} className="mt-3 cursor-pointer text-xs font-semibold text-[#0066cc] hover:underline">
                    {showAllSuggestions ? 'Show less' : `Show ${suggestionList.length - 6} more`}
                  </button>
                )}
              </motion.section>
            )}
          </aside>
        </div>
      </div>

      <motion.div
        className="fixed bottom-0 left-0 right-0 z-30 px-4 py-3 md:px-6"
        style={{ backgroundColor: 'rgba(245,245,247,0.88)', backdropFilter: 'blur(16px)', borderTop: '1px solid rgba(0,0,0,0.08)' }}
        initial={{ y: 60, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ delay: 0.25, duration: 0.35, ease: 'easeOut' }}
      >
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3">
          <span className="truncate text-sm font-medium text-[#6e6e73]">
            {isEditing ? 'Editing persona profile' : `${firstName(draft.displayName)}'s Persona`}
          </span>
          <div className="flex items-center gap-2">
            {isEditing && (
              <button onClick={handleSave} disabled={isSaving} className="cursor-pointer rounded-full bg-[#0066cc] px-5 py-2 text-sm font-semibold text-white shadow-[0_12px_28px_rgba(0,102,204,0.24)] transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-60">
                {isSaving ? 'Saving...' : 'Save'}
              </button>
            )}
            <button onClick={() => handleOpenChat()} className="inline-flex cursor-pointer items-center gap-2 rounded-full border border-black/10 bg-white px-5 py-2 text-sm font-semibold text-[#0066cc] shadow-sm transition hover:bg-[#f5f5f7]">
              <IconChat />
              Chat preview
            </button>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
function ProfilePageFallback() {
  return (
    <div className="flex h-[60vh] items-center justify-center">
      <div className="h-10 w-10 animate-spin rounded-full border-4 border-t-transparent" style={{ borderColor: 'var(--primary-500)', borderTopColor: 'transparent' }} />
    </div>
  );
}

export default function ProfilePage() {
  return (
    <Suspense fallback={<ProfilePageFallback />}>
      <ProfilePageContent />
    </Suspense>
  );
}
