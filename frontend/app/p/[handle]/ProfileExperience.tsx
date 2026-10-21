'use client';

import Link from 'next/link';
import type React from 'react';
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Volume2 } from 'lucide-react';

import { resolveApiBaseUrl } from '@/lib/api';
import { ProfileDrawer } from '@/components/persona/ProfileDrawer';
import { analytics } from '@/lib/analytics/events';
import { storeReferral } from '@/lib/analytics/referral';
import { Wordmark } from '@/components/brand/Wordmark';
import VoiceCall from '@/components/Chat/VoiceCall';
import { renderTheme, isThemeId, isAccent, ACCENT_HEX, DEFAULT_ACCENT_FOR, type ThemeId } from '@/lib/persona-themes';

import { isRuntimeFeatureEnabled } from '@/lib/features/runtimeFlags';
import { PersonaConsole } from './console/PersonaConsole';
import { toPortfolioProfile, type RawPublicProfile } from './toPortfolioProfile';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PublicProfile {
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
  work_experience?: Array<{
    company?: string;
    role?: string;
    description?: string;
    start_year?: number;
    end_year?: number;
    period?: string;
  }>;
  education?: Array<{
    institution?: string;
    degree?: string;
    field?: string;
    start_year?: number;
    end_year?: number;
    period?: string;
  }>;
  social_links?: Record<string, string>;
  image_url?: string;
  avatar_url?: string;
  suggested_questions?: string[];
  featured_content?: FeaturedItem[];
  social_link_visibility?: Record<string, boolean>;
  voice_capabilities?: {
    tts?: boolean;
    live_call?: boolean;
    provider?: string;
    voice_name?: string;
  };
  booking?: {
    enabled?: boolean;
    connected?: boolean;
  };
}

type FeaturedItem = {
  type: 'youtube' | 'instagram' | 'link';
  url: string;
  title?: string;
  hidden?: boolean;
};

type SectionVisibility = {
  areas_of_expertise: boolean;
  key_achievements: boolean;
  personality_traits: boolean;
  contributions: boolean;
  featured_content: boolean;
  social_links: boolean;
  pinned_questions: boolean;
  work_experience: boolean;
  education: boolean;
};

// ---------------------------------------------------------------------------
// ConversionBar — acquisition surface (free tier only)
// ---------------------------------------------------------------------------

function ConversionBar({ personaName, handle }: { personaName: string; handle: string }) {
  return (
    <div className="fixed bottom-0 left-0 right-0 z-30 flex items-center justify-between gap-4 px-5 border-t border-black/8 bg-white/90 backdrop-blur-xl" style={{ height: '48px' }}>
      <p className="min-w-0 truncate text-xs font-medium text-[#6e6e73]">
        {personaName} is powered by PersonaOn
      </p>
      <Link
        href={`/auth/signup?ref=${encodeURIComponent(handle)}&utm_source=persona_page`}
        onClick={() => {
          storeReferral(handle, 'persona_page');
          analytics.personaPageCtaClicked({ handle, surface: 'conversion_bar' });
        }}
        className="shrink-0 text-xs font-semibold text-[#0066cc]"
      >
        Build yours free →
      </Link>
    </div>
  );
}

// Minimal "Powered by" footer (core/pro+ tiers).
function PoweredByFooter() {
  return (
    <div className="fixed bottom-0 left-0 right-0 flex items-center justify-center" style={{ height: '32px' }}>
      <p className="text-xs font-medium text-[#8e8e93]">Powered by PersonaOn</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Voice-call-unavailable notice (chat TTS works, live calls don't)
// ---------------------------------------------------------------------------

function VoiceCallUnavailableNotice({ voiceName }: { voiceName?: string | null }) {
  const label = voiceName?.trim() ? `Cloned voice: ${voiceName.trim()}` : 'Cloned voice ready';

  return (
    <div className="mt-4 inline-flex max-w-full items-start gap-2 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
      <Volume2 className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span>
        <span className="font-semibold">{label}</span>
        {' '}for chat audio. Live calls are not enabled for this persona yet.
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Top bar — Wordmark + auth CTAs. In chat mode the floating pill header owns
// the top edge on small screens, so the bar hides there (md+ keeps it).
// ---------------------------------------------------------------------------

function TopBar({ active }: { active: boolean }) {
  return (
    <div className={`pointer-events-none absolute inset-x-0 top-4 z-30 items-center justify-between px-4 sm:top-5 sm:px-6 lg:px-8 ${active ? 'hidden md:flex' : 'flex'}`}>
      <div className="pointer-events-auto">
        <Wordmark href="/" size="sm" />
      </div>
      <div className="flex items-center gap-3 sm:gap-4">
        <Link
          href="/auth/login"
          onClick={() =>
            analytics.landingCtaClicked({ cta_type: 'sign_in', position: 'public_persona_page' })
          }
          className="pointer-events-auto hidden text-sm font-medium text-[#1d1d1f]/70 transition-opacity hover:text-[#1d1d1f] hover:opacity-100 sm:inline"
        >
          Sign in
        </Link>
        <Link
          href="/auth/signup"
          onClick={() =>
            analytics.landingCtaClicked({ cta_type: 'create_persona', position: 'public_persona_page' })
          }
          aria-label="Create your persona"
          className="pointer-events-auto inline-flex items-center justify-center gap-1.5 rounded-full bg-[#1d1d1f] text-sm font-medium text-white shadow-sm transition-opacity hover:opacity-90 h-9 w-9 sm:h-auto sm:w-auto sm:px-4 sm:py-2"
        >
          <svg
            aria-hidden
            className="h-3.5 w-3.5"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 4v16m8-8H4"
            />
          </svg>
          <span className="hidden sm:inline">Create your persona</span>
        </Link>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Derived profile state — pure mapping from the redacted profile pack
// ---------------------------------------------------------------------------

interface DerivedProfileState {
  profile: PublicProfile;
  tier: 'free' | 'core';
  showBranding: boolean;
  hasVoice: boolean;
  hasLiveVoice: boolean;
  sectionVisibility: SectionVisibility;
  themeId: string | null;
  accentId: string | null;
}

/**
 * Pure derivation of UI state from the redacted profile pack. Shared by the
 * SSR seed (initial useState values) and the client-side fetch fallback so the
 * mapping logic lives in exactly one place.
 */
function deriveProfileState(profileData: Record<string, unknown>): DerivedProfileState {
  const settings = (profileData.settings ?? {}) as Record<string, unknown>;
  const extractedTier =
    (settings.subscription_tier as 'free' | 'core' | undefined) ?? 'free';
  // show_branding: free tier defaults to showing branding (null = show).
  // Paid tiers default to hiding branding (null = hide, explicit true = show).
  const rawShowBranding = settings.show_branding;
  const isPaidProfile = ['pro', 'business', 'believer'].includes(extractedTier);
  const showBranding = isPaidProfile
    ? rawShowBranding === true
    : rawShowBranding !== false;
  // Voice capabilities are channel-specific: chat TTS can work even when live calls are unavailable.
  const voiceCapabilities = (profileData.voice_capabilities ?? {}) as PublicProfile['voice_capabilities'];
  const hasVoice = Boolean(voiceCapabilities?.tts ?? profileData.has_voice);
  const hasLiveVoice = Boolean(voiceCapabilities?.live_call);
  // Read section visibility settings (default all true if not set)
  const rawVis = (settings.section_visibility as Partial<SectionVisibility> | undefined) ?? {};
  const sectionVisibility: SectionVisibility = {
    areas_of_expertise: rawVis.areas_of_expertise !== false,
    key_achievements: rawVis.key_achievements !== false,
    personality_traits: rawVis.personality_traits !== false,
    contributions: rawVis.contributions !== false,
    featured_content: rawVis.featured_content !== false,
    social_links: rawVis.social_links !== false,
    pinned_questions: rawVis.pinned_questions !== false,
    work_experience: rawVis.work_experience !== false,
    education: rawVis.education !== false,
  };
  // Layout theme (Phase 1 emits it past redaction at pack.settings.theme_id).
  const themeId = (settings.theme_id as string | undefined) ?? null;
  // Accent swatch (emitted past redaction at pack.settings.accent; null = use theme default).
  const accentId = (settings.accent as string | undefined) ?? null;
  // Merge persona_profile fields (includes suggested_questions) into the profile
  const baseProfile = (profileData.profile ?? profileData) as Record<string, unknown>;
  const personaProfile = (profileData.persona_profile ?? settings.persona_profile ?? {}) as Record<string, unknown>;
  const profile: PublicProfile = {
    ...(baseProfile as PublicProfile),
    suggested_questions: (baseProfile.suggested_questions
      || personaProfile.suggested_questions
      || baseProfile.pinned_questions
      || []) as string[],
    social_link_visibility: (profileData.social_link_visibility ?? {}) as Record<string, boolean>,
    booking: (profileData.booking ?? baseProfile.booking) as PublicProfile['booking'],
  };

  return { profile, tier: extractedTier, showBranding, hasVoice, hasLiveVoice, sectionVisibility, themeId, accentId };
}

// ---------------------------------------------------------------------------
// Main page — thin adapter: fetch → derive → map → renderTheme(theme, …)
// ---------------------------------------------------------------------------

interface ProfileExperienceProps {
  handle: string;
  initialTwinId: string | null;
  initialShareToken: string | null;
  initialData: Record<string, unknown> | null;
}

export function ProfileExperience(props: ProfileExperienceProps) {
  const { handle } = props;
  const apiBaseUrl = useMemo(() => resolveApiBaseUrl(), []);

  // Seed derived state from SSR data so the first (server) render shows real
  // content. When there's no SSR data, fall back to the existing client fetch.
  const [seeded] = useState(() =>
    props.initialData ? deriveProfileState(props.initialData) : null,
  );

  const searchParams = useSearchParams();
  const resumeConvId = searchParams.get('conv');

  const [twinId, setTwinId] = useState<string | null>(props.initialTwinId);
  const [shareToken, setShareToken] = useState<string | null>(props.initialShareToken);
  const [profile, setProfile] = useState<PublicProfile | null>(seeded?.profile ?? null);
  const [tier, setTier] = useState<'free' | 'core'>(seeded?.tier ?? 'free');
  // Chat-started flag, driven by PersonaConsole via onActivityChange. Owns the
  // Classic shell's hero→chat collapse + top-bar hide; chat state lives in the console.
  const [active, setActive] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [loading, setLoading] = useState(props.initialData ? false : true);
  const [error, setError] = useState<string | null>(null);
  const [hasVoice, setHasVoice] = useState(seeded?.hasVoice ?? false);
  const [hasLiveVoice, setHasLiveVoice] = useState(seeded?.hasLiveVoice ?? false);
  const [showBranding, setShowBranding] = useState(seeded?.showBranding ?? true);
  const [themeId, setThemeId] = useState<string | null>(seeded?.themeId ?? null);
  const [accentId, setAccentId] = useState<string | null>(seeded?.accentId ?? null);
  const [sectionVisibility, setSectionVisibility] = useState<SectionVisibility>(
    seeded?.sectionVisibility ?? {
      areas_of_expertise: true,
      key_achievements: true,
      personality_traits: true,
      contributions: true,
      featured_content: true,
      social_links: true,
      work_experience: true,
      education: true,
      pinned_questions: true,
    },
  );

  // Resolve handle → twin_id + share_token → profile.
  // SSR fallback only: when the server already seeded `initialData`, the page
  // is fully rendered and this client fetch is skipped entirely.
  useEffect(() => {
    if (props.initialData) return;
    if (!handle) return;

    const load = async () => {
      setLoading(true);
      setError(null);

      try {
        // Step 1: resolve handle
        const resolveRes = await fetch(`${apiBaseUrl}/handles/resolve?handle=${handle}`);
        if (!resolveRes.ok) {
          setError('not_found');
          setLoading(false);
          return;
        }
        const resolveData = (await resolveRes.json()) as { twin_id: string; share_token: string };
        const resolvedTwinId = resolveData.twin_id;
        const resolvedToken = resolveData.share_token;
        setTwinId(resolvedTwinId);
        setShareToken(resolvedToken);

        // Step 2: fetch profile
        const profileRes = await fetch(
          `${apiBaseUrl}/share/${resolvedTwinId}/${resolvedToken}/profile`
        );
        if (!profileRes.ok) {
          setError('profile_error');
          setLoading(false);
          return;
        }
        const profileData = await profileRes.json();
        const derived = deriveProfileState(profileData);
        setTier(derived.tier);
        setShowBranding(derived.showBranding);
        setHasVoice(derived.hasVoice);
        setHasLiveVoice(derived.hasLiveVoice);
        setSectionVisibility(derived.sectionVisibility);
        setThemeId(derived.themeId);
        setAccentId(derived.accentId);
        setProfile(derived.profile);
      } catch {
        setError('network_error');
      } finally {
        setLoading(false);
      }
    };

    void load();
  }, [handle, apiBaseUrl, props.initialData]);

  const portfolio = useMemo(
    () => toPortfolioProfile((profile ?? {}) as RawPublicProfile),
    [profile],
  );

  // ─── Loading state ───────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center bg-[#f5f5f7]">
        <div className="flex flex-col items-center gap-4">
          <div className="w-20 h-20 rounded-[1.5rem] animate-pulse bg-black/8" />
          <div className="h-5 w-36 rounded-full animate-pulse bg-black/8" />
          <div className="h-3.5 w-52 rounded-full animate-pulse bg-black/6" />
        </div>
      </div>
    );
  }

  // ─── Error / not found state ─────────────────────────────────────────────
  if (error) {
    const errorCopy =
      error === 'not_found'
        ? { title: "This persona doesn't exist.", body: 'Check the URL and try again.' }
        : error === 'profile_error'
          ? { title: "This persona isn't available right now.", body: 'Try again in a moment.' }
          : { title: "We couldn't reach PersonaOn.", body: 'Check your connection and try again.' };

    return (
      <div className="h-screen flex items-center justify-center p-4 bg-[#f5f5f7]">
        <div className="w-full max-w-md rounded-3xl p-10 text-center bg-white/90 shadow-[0_18px_55px_rgba(15,23,42,0.10)] border border-black/8 backdrop-blur-xl">
          <h1 className="text-2xl font-semibold tracking-tight text-[#111111]">
            {errorCopy.title}
          </h1>
          <p className="mt-2 text-sm text-[#6e6e73]">{errorCopy.body}</p>
        </div>
      </div>
    );
  }

  const displayName = profile?.name ?? '';
  const headline = profile?.occupation || profile?.headline || '';
  const avatarSrc = profile?.image_url || profile?.avatar_url;
  const voiceName = profile?.voice_capabilities?.voice_name ?? null;

  // Bottom padding accounts for ConversionBar (free) or minimal footer (core/pro+).
  const bottomPadding = !showBranding ? '0px' : tier === 'free' ? '56px' : '32px';

  // Honor a stored non-classic theme only when the flag is on (Phase 4 ships
  // the other shells). Until then every twin renders Classic. A `?theme=`
  // query param lets a published owner preview any layout (flag-gated).
  const themeOverride = searchParams.get('theme'); // published-page layout preview
  const effectiveTheme: ThemeId = isRuntimeFeatureEnabled('personaThemes')
    ? (isThemeId(themeOverride) ? themeOverride : (isThemeId(themeId) ? themeId : 'classic'))
    : 'classic';
  // Accent: stored swatch → hex, else the effective theme's default. Computed
  // for every theme — Classic's default accent is 'blue' (#0066cc), matching
  // its legacy hardcoded color, so a page that never picked an accent renders
  // byte-identical to before the accent-token parity fix (execution-board 0.3).
  // There is no `?accent=` preview param: accent preview requires saving the
  // selection. If one is ever added, it MUST be sanitized through isAccent()
  // (never passed raw to the --pon-accent var).
  const accentHex = ACCENT_HEX[isAccent(accentId) ? accentId : DEFAULT_ACCENT_FOR[effectiveTheme]];

  // The interaction console — opaque to the theme shell.
  const interaction = (
    <PersonaConsole
      twinId={twinId}
      shareToken={shareToken}
      apiBaseUrl={apiBaseUrl}
      personaName={displayName}
      headline={headline}
      avatarUrl={avatarSrc}
      hasVoice={hasVoice}
      hasLiveVoice={hasLiveVoice}
      voiceName={voiceName}
      booking={{
        enabled: Boolean(profile?.booking?.enabled),
        connected: Boolean(profile?.booking?.connected),
      }}
      suggestedQuestions={profile?.suggested_questions ?? []}
      pinnedQuestionsVisible={sectionVisibility.pinned_questions}
      showBranding={showBranding}
      handle={handle}
      initialConversationId={resumeConvId}
      onActivityChange={setActive}
      onOpenProfile={() => setDrawerOpen(true)}
    />
  );

  const themed = renderTheme(effectiveTheme, {
    profile: portfolio,
    interaction,
    visibility: sectionVisibility,
    active,
    mainStyle: { paddingBottom: bottomPadding },
    slots: {
      topbar: <TopBar active={active} />,
      branding: showBranding
        ? tier === 'free'
          ? <ConversionBar personaName={displayName} handle={handle} />
          : <PoweredByFooter />
        : null,
      heroAside: hasLiveVoice && twinId ? (
        <div className="mt-4">
          <VoiceCall
            twinId={twinId}
            twinName={displayName}
            avatarUrl={avatarSrc}
            voiceName={voiceName}
            isPublic
            shareToken={shareToken}
          />
        </div>
      ) : hasVoice ? (
        <VoiceCallUnavailableNotice voiceName={voiceName} />
      ) : null,
    },
  });

  return (
    <>
      {/* Profile drawer — chrome, opened by the console's "View profile" button. */}
      {profile && (
        <ProfileDrawer
          profile={profile}
          isOpen={drawerOpen}
          onClose={() => setDrawerOpen(false)}
        />
      )}

      {/* Every shell (including Classic) carries the accent via a --pon-accent
          CSS var on a thin wrapper — execution-board 0.3 accent-token parity fix. */}
      <div style={{ ['--pon-accent' as string]: accentHex } as React.CSSProperties}>{themed}</div>
    </>
  );
}
