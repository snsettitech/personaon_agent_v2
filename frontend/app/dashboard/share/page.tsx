'use client';

import Link from 'next/link';
import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTwin } from '@/lib/context/TwinContext';
import { formatPersonaDisplayName } from '@/lib/branding/personaName';
import { API_ENDPOINTS, PUBLIC_SITE_URL } from '@/lib/constants';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { ThemePicker } from '@/components/persona/ThemePicker';
import { PublishGateBanner } from '@/components/persona/PublishGateBanner';

type ShareLinkInfo = {
  share_token?: string | null;
  share_url?: string | null;
  public_share_enabled?: boolean;
};

type FeaturedItem = {
  type: 'youtube' | 'instagram' | 'link';
  url: string;
  title?: string;
  hidden?: boolean;
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
  areas_of_expertise?: string[];
  key_achievements?: string[];
  personality_traits?: string[];
  contributions?: string[];
  speaking_style?: string;
  social_links?: Record<string, string>;
  pinned_questions?: string[];
};

function detectFeaturedType(url: string): FeaturedItem['type'] {
  if (/youtube\.com\/|youtu\.be\//.test(url)) return 'youtube';
  if (/instagram\.com\//.test(url)) return 'instagram';
  return 'link';
}

function extractYouTubeId(url: string): string | null {
  const patterns = [
    /[?&]v=([^&#]+)/,
    /youtu\.be\/([^?&#]+)/,
    /\/embed\/([^?&#]+)/,
    /\/shorts\/([^?&#]+)/,
  ];
  for (const p of patterns) {
    const m = url.match(p);
    if (m?.[1]) return m[1];
  }
  return null;
}

type ProfileInsightsResponse = {
  profile_pack?: PersonaProfilePack | null;
};

type SectionVisibility = {
  areas_of_expertise: boolean;
  key_achievements: boolean;
  personality_traits: boolean;
  contributions: boolean;
  featured_content: boolean;
  social_links: boolean;
  pinned_questions: boolean;
};

type SocialLinkVisibility = Record<string, boolean>;

// Mirrors backend modules.share_links.PUBLIC_TWIN_STATUSES — 'active' is the
// only status the backend treats as publicly reachable (has_public_twin_status,
// is_publicly_accessible_twin_record). 'persona_built' means the build
// pipeline finished, not that the owner has published; keeping it in this set
// made the publish gate disappear the moment a persona finished building,
// before the owner ever clicked Publish.
const PUBLIC_READY_STATUSES = new Set(['active']);

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
}

function normalizeSocialLinks(value: unknown): Record<string, string> {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).filter(([, url]) => typeof url === 'string' && url.trim()),
    ) as Record<string, string>;
  }
  if (!Array.isArray(value)) return {};
  const pairs = value
    .map((item) => (typeof item === 'string' ? item.trim() : ''))
    .filter(Boolean)
    .map((url, index) => [`link${index + 1}`, url] as const);
  return Object.fromEntries(pairs);
}

function lifeLine(profile: PersonaProfilePack | null): string {
  if (!profile) return '';
  const years =
    profile.birth_year || profile.death_year
      ? `${profile.birth_year || ''}${profile.birth_year || profile.death_year ? ' - ' : ''}${profile.death_year || 'Present'}`
      : '';
  if (profile.nationality && years) return `${profile.nationality} • ${years}`;
  return profile.nationality || years;
}

function ToggleSection({
  title,
  items,
  isVisible,
  isSaving,
  onToggle,
}: {
  title: string;
  items?: string[];
  isVisible: boolean;
  isSaving: boolean;
  onToggle: () => void;
}) {
  if (!items || items.length === 0) return null;
  return (
    <section className={`rounded-[28px] border bg-white p-6 shadow-sm transition-all ${isVisible ? 'border-slate-200' : 'border-dashed border-slate-200 opacity-55'}`}>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">{title}</h2>
        <button
          onClick={onToggle}
          disabled={isSaving}
          aria-pressed={isVisible}
          className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold transition-all disabled:opacity-50 ${
            isVisible
              ? 'bg-[rgba(0,102,204,0.10)] text-[#0066cc]'
              : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
          }`}
        >
          {/* Toggle pill */}
          <span
            aria-hidden="true"
            className={`relative inline-block h-4 w-7 flex-shrink-0 rounded-full transition-colors ${isVisible ? 'bg-[#0066cc]' : 'bg-slate-300'}`}
          >
            <span className={`absolute top-0.5 left-0.5 h-3 w-3 rounded-full bg-white shadow transition-transform ${isVisible ? 'translate-x-3' : 'translate-x-0'}`} />
          </span>
          {isVisible ? 'Shown publicly' : 'Hidden'}
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        {items.map((item) => (
          <span key={`${title}-${item}`} className="rounded-full bg-slate-100 px-3 py-1.5 text-sm text-slate-700">
            {item}
          </span>
        ))}
      </div>
    </section>
  );
}

// Statuses that mean the twin has been through the build pipeline and can be toggled public/private

export default function SharePage() {
  const { activeTwin, user, refreshTwins } = useTwin();
  const [copied, setCopied] = useState(false);
  const [qrVisible, setQrVisible] = useState(false);
  const [isLoadingLink, setIsLoadingLink] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [shareInfo, setShareInfo] = useState<ShareLinkInfo | null>(null);
  const [profilePack, setProfilePack] = useState<PersonaProfilePack | null>(null);
  const [isSavingVisibility, setIsSavingVisibility] = useState(false);
  const [featuredItems, setFeaturedItems] = useState<FeaturedItem[]>([]);
  const [featuredUrlInput, setFeaturedUrlInput] = useState('');
  const [isSavingFeatured, setIsSavingFeatured] = useState(false);
  const [featuredError, setFeaturedError] = useState<string | null>(null);
  const [socialLinkVisibility, setSocialLinkVisibility] = useState<SocialLinkVisibility>({});
  const [isSavingSocialVisibility, setIsSavingSocialVisibility] = useState(false);
  const [visibilityError, setVisibilityError] = useState<string | null>(null);
  const [calendarConnected, setCalendarConnected] = useState<boolean>(false);
  const [isSavingBookingButton, setIsSavingBookingButton] = useState(false);
  const [bookingButtonError, setBookingButtonError] = useState<string | null>(null);
  const [sectionVisibility, setSectionVisibility] = useState<SectionVisibility>({
    areas_of_expertise: true,
    key_achievements: true,
    personality_traits: true,
    contributions: true,
    featured_content: true,
    social_links: true,
    pinned_questions: true,
  });


  const settings = (activeTwin?.settings || {}) as Record<string, unknown>;
  const handle = typeof settings.handle === 'string' ? settings.handle : '';

  // Sync section visibility state from server when twin data changes
  useEffect(() => {
    const raw = (settings.section_visibility as Partial<SectionVisibility> | undefined) ?? {};
    setSectionVisibility({
      areas_of_expertise: raw.areas_of_expertise !== false,
      key_achievements: raw.key_achievements !== false,
      personality_traits: raw.personality_traits !== false,
      contributions: raw.contributions !== false,
      featured_content: raw.featured_content !== false,
      social_links: raw.social_links !== false,
      pinned_questions: raw.pinned_questions !== false,
    });
  }, [activeTwin?.id, settings.section_visibility]);

  const saveSectionVisibility = useCallback(async (next: SectionVisibility) => {
    const id = activeTwin?.id;
    if (!id || isSavingVisibility) return;
    const previous = sectionVisibility;
    // Optimistic update — show the change immediately
    setSectionVisibility(next);
    setVisibilityError(null);
    setIsSavingVisibility(true);
    try {
      const res = await authFetchStandalone(API_ENDPOINTS.TWIN_DETAIL(id), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings: { section_visibility: next } }),
      });
      if (!res.ok) throw new Error(`Request failed (${res.status})`);
      await refreshTwins();
    } catch {
      setSectionVisibility(previous);
      setVisibilityError("Couldn't save visibility. Your public page was not changed.");
    } finally {
      setIsSavingVisibility(false);
    }
  }, [activeTwin?.id, isSavingVisibility, refreshTwins, sectionVisibility]);
  const publicProfile = useMemo(
    () => (
      settings.public_profile && typeof settings.public_profile === 'object' && !Array.isArray(settings.public_profile)
        ? (settings.public_profile as Record<string, unknown>)
        : {}
    ),
    [settings.public_profile],
  );

  // Sync featured content from server when twin data changes
  useEffect(() => {
    const raw = publicProfile.featured_content;
    setFeaturedItems(Array.isArray(raw) ? (raw as FeaturedItem[]) : []);
  }, [activeTwin?.id, publicProfile.featured_content]);

  const saveFeaturedContent = useCallback(async (items: FeaturedItem[], previousItems: FeaturedItem[]) => {
    const id = activeTwin?.id;
    if (!id || isSavingFeatured) {
      setFeaturedItems(previousItems);
      if (!id) {
        setFeaturedError("Couldn't save featured content. Your public page was not changed.");
      }
      return;
    }
    setIsSavingFeatured(true);
    setFeaturedError(null);
    try {
      const res = await authFetchStandalone(API_ENDPOINTS.TWIN_DETAIL(id), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          settings: {
            public_profile: { ...publicProfile, featured_content: items },
          },
        }),
      });
      if (!res.ok) throw new Error(`Request failed (${res.status})`);
      await refreshTwins();
    } catch {
      setFeaturedItems(previousItems);
      setFeaturedError("Couldn't save featured content. Your public page was not changed.");
    } finally {
      setIsSavingFeatured(false);
    }
  }, [activeTwin?.id, isSavingFeatured, publicProfile, refreshTwins]);

  const addFeaturedItem = useCallback(() => {
    const url = featuredUrlInput.trim();
    if (!url) return;
    if (!/^https?:\/\//i.test(url)) {
      setFeaturedError('Please enter a valid URL starting with https://');
      return;
    }
    const type = detectFeaturedType(url);
    const previous = featuredItems;
    const next = [...featuredItems, { type, url }];
    setFeaturedItems(next);
    setFeaturedUrlInput('');
    setFeaturedError(null);
    void saveFeaturedContent(next, previous);
  }, [featuredUrlInput, featuredItems, saveFeaturedContent]);

  const removeFeaturedItem = useCallback((index: number) => {
    const previous = featuredItems;
    const next = featuredItems.filter((_, i) => i !== index);
    setFeaturedItems(next);
    void saveFeaturedContent(next, previous);
  }, [featuredItems, saveFeaturedContent]);

  const toggleFeaturedItemHidden = useCallback((index: number) => {
    const previous = featuredItems;
    const next = featuredItems.map((item, i) =>
      i === index ? { ...item, hidden: !item.hidden } : item
    );
    setFeaturedItems(next);
    void saveFeaturedContent(next, previous);
  }, [featuredItems, saveFeaturedContent]);

  // Sync social link visibility from server
  useEffect(() => {
    const raw = (publicProfile.social_link_visibility as SocialLinkVisibility | undefined) ?? {};
    setSocialLinkVisibility(raw);
  }, [activeTwin?.id, publicProfile.social_link_visibility]);

  // Probe Google Calendar connection so the booking-button toggle can be
  // disabled-with-context when the owner hasn't connected yet.
  useEffect(() => {
    const id = activeTwin?.id;
    if (!id) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await authFetchStandalone(`/v2/calendar/${id}/status`);
        if (cancelled) return;
        if (!res.ok) {
          setCalendarConnected(false);
          return;
        }
        const data = await res.json().catch(() => ({}));
        setCalendarConnected(Boolean((data as { connected?: boolean }).connected));
      } catch {
        if (!cancelled) setCalendarConnected(false);
      }
    })();
    return () => { cancelled = true; };
  }, [activeTwin?.id]);

  const showBookingButton = Boolean(publicProfile.show_booking_button);

  const saveShowBookingButton = useCallback(async (next: boolean) => {
    const id = activeTwin?.id;
    if (!id || isSavingBookingButton) return;
    setIsSavingBookingButton(true);
    setBookingButtonError(null);
    try {
      const res = await authFetchStandalone(API_ENDPOINTS.TWIN_DETAIL(id), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          settings: {
            public_profile: { ...publicProfile, show_booking_button: next },
          },
        }),
      });
      if (!res.ok) throw new Error(`Request failed (${res.status})`);
      await refreshTwins();
    } catch {
      setBookingButtonError("Couldn't save the booking button setting. Try again.");
    } finally {
      setIsSavingBookingButton(false);
    }
  }, [activeTwin?.id, isSavingBookingButton, publicProfile, refreshTwins]);

  const saveSocialLinkVisibility = useCallback(async (next: SocialLinkVisibility) => {
    const id = activeTwin?.id;
    if (!id || isSavingSocialVisibility) return;
    const previous = socialLinkVisibility;
    setSocialLinkVisibility(next);
    setVisibilityError(null);
    setIsSavingSocialVisibility(true);
    try {
      const res = await authFetchStandalone(API_ENDPOINTS.TWIN_DETAIL(id), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          settings: {
            public_profile: { ...publicProfile, social_link_visibility: next },
          },
        }),
      });
      if (!res.ok) throw new Error(`Request failed (${res.status})`);
      await refreshTwins();
    } catch {
      setSocialLinkVisibility(previous);
      setVisibilityError("Couldn't save visibility. Your public page was not changed.");
    } finally {
      setIsSavingSocialVisibility(false);
    }
  }, [activeTwin?.id, isSavingSocialVisibility, publicProfile, refreshTwins, socialLinkVisibility]);

  // Deliberately ignores activeTwin.is_active: that DB column defaults to
  // TRUE at row-creation time and is never set explicitly by any
  // twin-creation path (POST /profile, onboarding, twins, auto_create), so
  // every twin — including brand-new drafts — has is_active=true from day
  // one. Only `status` reflects whether the owner has actually published.
  const isPublicReady = Boolean(activeTwin && PUBLIC_READY_STATUSES.has(activeTwin.status));
  const shareUrl = useMemo(() => {
    // Prefer handle-based URL with the canonical public domain
    if (handle) {
      const base = PUBLIC_SITE_URL.replace(/\/$/, '');
      return `${base}/p/${handle}`;
    }
    // Fall back to backend-provided share URL (token-based)
    return shareInfo?.share_url || '';
  }, [handle, shareInfo]);

  const fallbackProfile = useMemo<PersonaProfilePack>(() => {
    const rawDisplayName =
      (typeof publicProfile.display_name === 'string' && publicProfile.display_name.trim()) ||
      activeTwin?.name ||
      user?.full_name ||
      'Persona';
    const displayName = formatPersonaDisplayName(rawDisplayName);
    const headline = typeof publicProfile.headline === 'string' ? publicProfile.headline.trim() : '';
    const bio =
      (typeof publicProfile.bio === 'string' && publicProfile.bio.trim()) ||
      (typeof settings.public_intro === 'string' ? settings.public_intro : '') ||
      'Add a public summary so visitors know what this persona can help with.';
    const role = typeof publicProfile.role === 'string' ? publicProfile.role.trim() : '';
    const organization = typeof publicProfile.organization === 'string' ? publicProfile.organization.trim() : '';
    const occupation = role && organization ? `${role} at ${organization}` : role || headline || 'Public persona';
    const avatarUrl =
      (typeof publicProfile.avatar_url === 'string' && publicProfile.avatar_url.trim()) ||
      user?.avatar_url ||
      '';

    return {
      name: displayName,
      occupation,
      headline,
      bio,
      short_description: bio,
      avatar_url: avatarUrl,
      verified_profile: typeof publicProfile.verified_profile === 'boolean' ? Boolean(publicProfile.verified_profile) : false,
      speaking_style: typeof publicProfile.speaking_style === 'string' ? publicProfile.speaking_style.trim() : '',
      areas_of_expertise: Array.isArray(publicProfile.areas_of_expertise)
        ? publicProfile.areas_of_expertise.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
        : [],
      key_achievements: Array.isArray(publicProfile.key_achievements)
        ? publicProfile.key_achievements.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
        : [],
      personality_traits: Array.isArray(publicProfile.personality_traits)
        ? publicProfile.personality_traits.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
        : [],
      contributions: Array.isArray(publicProfile.contributions)
        ? publicProfile.contributions.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
        : [],
      pinned_questions: Array.isArray(publicProfile.pinned_questions)
        ? publicProfile.pinned_questions.filter((item): item is string => typeof item === 'string' && item.trim().length > 0).slice(0, 4)
        : [],
      social_links: normalizeSocialLinks(publicProfile.social_links),
    };
  }, [activeTwin?.name, publicProfile, settings.public_intro, user?.avatar_url, user?.full_name]);

  const previewProfile = profilePack || fallbackProfile;
  const socialLinks = Object.entries(previewProfile.social_links || {});

  useEffect(() => {
    let cancelled = false;

    const loadData = async () => {
      if (!activeTwin?.id) {
        setShareInfo(null);
        setProfilePack(null);
        setLinkError(null);
        return;
      }

      setIsLoadingLink(true);
      setLinkError(null);

      try {
        const [shareResponse, insightsResponse] = await Promise.all([
          authFetchStandalone(`/twins/${activeTwin.id}/share-link`),
          authFetchStandalone(API_ENDPOINTS.TWIN_PROFILE_INSIGHTS(activeTwin.id)),
        ]);

        if (!shareResponse.ok) {
          throw new Error(`Failed to load share link (${shareResponse.status})`);
        }

        const sharePayload = (await shareResponse.json()) as ShareLinkInfo;
        const insightsPayload = insightsResponse.ok
          ? ((await insightsResponse.json()) as ProfileInsightsResponse)
          : null;

        if (!cancelled) {
          setShareInfo(sharePayload);
          setProfilePack(insightsPayload?.profile_pack || null);
        }
      } catch (error) {
        console.error('[SharePage] Failed to load publish data:', error);
        if (!cancelled) {
          setShareInfo(null);
          setProfilePack(null);
          setLinkError('Unable to load the public link right now. Try refreshing in a moment.');
        }
      } finally {
        if (!cancelled) {
          setIsLoadingLink(false);
        }
      }
    };

    void loadData();

    return () => {
      cancelled = true;
    };
  }, [activeTwin?.id]);

  const copyToClipboard = (text: string) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  if (!activeTwin) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <div className="text-center">
          <h2 className="text-xl font-semibold text-slate-900">Select a persona</h2>
          <p className="mt-2 text-slate-500">Please select a persona to manage publishing.</p>
        </div>
      </div>
    );
  }

  const activePersonaName = formatPersonaDisplayName(activeTwin.name);
  const previewPersonaName = formatPersonaDisplayName(previewProfile.name || activeTwin.name);

  return (
    <div className="-mx-4 min-h-[calc(100vh-8rem)] bg-[#f3f1ef] px-4 pb-16 pt-4 md:-mx-8 md:px-8 md:pt-8">
      <div className="mx-auto max-w-5xl space-y-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-3xl font-black tracking-tight text-slate-900">Publish</h1>
          <p className="mt-1 text-slate-500">
            Preview how {activePersonaName} appears from the public link.
          </p>
        </div>

      </div>

      <PublishGateBanner
        twinId={activeTwin.id}
        isPublished={isPublicReady}
        refreshKey={activeTwin.updated_at}
        onPublished={(result) => {
          setShareInfo({ share_url: result.url, share_token: result.share_token, public_share_enabled: true });
          void refreshTwins();
        }}
      />

      {visibilityError && (
        <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-medium text-rose-700">
          {visibilityError}
        </div>
      )}

      <section className="rounded-[32px] border border-white/60 bg-white/80 p-8 shadow-[0_10px_30px_rgba(15,23,42,0.05)] backdrop-blur-sm">
        <div className="grid gap-8 lg:grid-cols-[1.1fr_0.9fr]">
          <div className="flex gap-5">
            {previewProfile.avatar_url ? (
              <img src={previewProfile.avatar_url} alt={previewPersonaName} className="h-24 w-24 rounded-[28px] object-cover" />
            ) : (
              <div className="flex h-24 w-24 items-center justify-center rounded-[28px] border border-[#b9d8ff] bg-[linear-gradient(135deg,#eaf4ff,#f8fbff)] text-2xl font-semibold text-[#004b9b] shadow-[inset_0_1px_0_rgba(255,255,255,0.75),0_18px_40px_rgba(0,102,204,0.10)]">
                {initials(previewPersonaName) || 'P'}
              </div>
            )}

            <div>
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="text-4xl font-semibold text-slate-950">{previewPersonaName}</h2>
                {previewProfile.verified_profile && (
                  <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-emerald-700">
                    Verified
                  </span>
                )}
                <span className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] ${
                  isPublicReady ? 'bg-slate-950 text-white' : 'bg-slate-100 text-slate-600'
                }`}>
                  {isPublicReady ? 'Public link ready' : 'Not public yet'}
                </span>
              </div>
              <p className="mt-2 text-lg text-slate-700">
                {previewProfile.occupation || previewProfile.headline || 'Public persona'}
              </p>
              {lifeLine(previewProfile) && <p className="mt-2 text-sm text-slate-500">{lifeLine(previewProfile)}</p>}
              <p className="mt-4 max-w-2xl text-base leading-7 text-slate-600">
                {previewProfile.short_description || previewProfile.bio}
              </p>

              {socialLinks.length > 0 && (
                <div className="mt-5 flex flex-wrap gap-2">
                  {socialLinks.map(([label, url]) => (
                    <a
                      key={`${label}-${url}`}
                      href={url}
                      target="_blank"
                      rel="noreferrer"
                      className="rounded-full bg-slate-100 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-200"
                    >
                      {label}
                    </a>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-1">
            <div className="rounded-[24px] bg-[#f8f5ef] p-5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Profile</p>
              <p className="mt-2 text-base font-semibold text-slate-950">
                {previewProfile.verified_profile ? 'Verified public persona' : 'Public digital persona'}
              </p>
            </div>
            <div className="rounded-[24px] bg-[#f8f5ef] p-5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Share Link</p>
              <p className="mt-2 text-sm font-semibold text-slate-950 break-all">
                {handle ? `personaon.com/p/${handle}` : 'Set a handle for a clean URL'}
              </p>
            </div>
            <div className="rounded-[24px] bg-[#f8f5ef] p-5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Speaking Style</p>
              <p className="mt-2 text-sm leading-6 text-slate-700">
                {previewProfile.speaking_style || 'Direct, clear, and grounded in the public profile.'}
              </p>
            </div>
          </div>
        </div>

        {isLoadingLink ? (
          <div className="mt-8 text-sm text-slate-500">Preparing your public link...</div>
        ) : linkError ? (
          <div className="mt-8 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {linkError}
          </div>
        ) : isPublicReady && shareUrl ? (
          <>
            <div className="mt-8 flex flex-col gap-3 md:flex-row md:items-center">
              <div className="flex-1 break-all rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 font-mono text-sm text-slate-700">
                {shareUrl}
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => copyToClipboard(shareUrl)}
                  className={`rounded-2xl px-6 py-4 text-sm font-semibold transition-colors ${
                    copied ? 'bg-emerald-500 text-white' : 'bg-slate-950 text-white hover:bg-slate-800'
                  }`}
                >
                  {copied ? 'Copied!' : 'Copy Link'}
                </button>
                <a
                  href={shareUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-2xl border border-slate-200 bg-white px-6 py-4 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                >
                  Open
                </a>
                <button
                  onClick={() => setQrVisible((value) => !value)}
                  className="rounded-2xl border border-slate-200 bg-white px-4 py-4 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                >
                  QR
                </button>
              </div>
            </div>

            {qrVisible && (
              <div className="mt-6 rounded-[28px] border border-slate-200 bg-slate-50 p-6">
                <div className="flex flex-col items-center justify-center">
                  <div className="rounded-2xl border border-slate-200 bg-white p-2">
                    <img
                      src={`https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(shareUrl)}`}
                      alt="QR Code"
                      className="h-44 w-44"
                    />
                  </div>
                <p className="mt-4 text-sm text-slate-500">Scan to open {activePersonaName} in public chat.</p>
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="mt-8 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-600">
            This persona is not public yet. Publish it above and the direct link will appear here automatically.
          </div>
        )}
      </section>

      {/* --- LAYOUT / THEME PICKER --- */}
      <div>
        <h3 className="mb-4 text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">Layout</h3>
        <ThemePicker />
      </div>


      {/* --- BOOKING BUTTON TOGGLE --- */}
      <div className="mb-8">
        <h3 className="mb-4 text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">Meetings</h3>
        <div className={`rounded-[28px] border bg-white p-6 shadow-sm transition-all ${
          calendarConnected
            ? showBookingButton ? 'border-slate-200' : 'border-dashed border-slate-200 opacity-75'
            : 'border-dashed border-slate-200 opacity-70'
        }`}>
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-start gap-4">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[#e8f2ff] text-[#0066cc]">
                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
                </svg>
              </span>
              <div className="min-w-0">
                <h3 className="text-lg font-semibold text-slate-900">Show "Schedule a meeting" button</h3>
                <p className="mt-1 text-sm text-slate-500">
                  When on, visitors see a persistent button on your public profile that opens your booking flow — no magic phrase required.
                </p>
              </div>
            </div>
            {calendarConnected ? (
              <button
                type="button"
                onClick={() => void saveShowBookingButton(!showBookingButton)}
                disabled={isSavingBookingButton}
                aria-pressed={showBookingButton}
                className={`flex shrink-0 items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold transition-all disabled:opacity-50 ${
                  showBookingButton ? 'bg-[rgba(0,102,204,0.10)] text-[#0066cc]' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
                }`}
              >
                <span aria-hidden="true" className={`relative inline-block h-4 w-7 flex-shrink-0 rounded-full transition-colors ${showBookingButton ? 'bg-[#0066cc]' : 'bg-slate-300'}`}>
                  <span className={`absolute top-0.5 left-0.5 h-3 w-3 rounded-full bg-white shadow transition-transform ${showBookingButton ? 'translate-x-3' : 'translate-x-0'}`} />
                </span>
                {showBookingButton ? 'Showing on profile' : 'Hidden'}
              </button>
            ) : (
              <Link
                href="/dashboard/actions"
                className="shrink-0 rounded-full bg-[#1d1d1f] px-4 py-2 text-xs font-semibold text-white transition hover:bg-black"
              >
                Connect calendar
              </Link>
            )}
          </div>
          {bookingButtonError && (
            <p className="mt-3 text-xs text-rose-600">{bookingButtonError}</p>
          )}
          {!calendarConnected && (
            <p className="mt-4 text-xs text-slate-500">
              Connect your Google Calendar in Actions first, then you can flip this on.
            </p>
          )}
        </div>
      </div>

      {/* --- FEATURED CONTENT SECTION (now above ABOUT) --- */}
      <div className="mb-8">
        <h3 className="mb-4 text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">Featured</h3>
        <div className={`rounded-[28px] border bg-white p-6 shadow-sm transition-all ${sectionVisibility.featured_content ? 'border-slate-200' : 'border-dashed border-slate-200 opacity-55'}`}>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-lg font-semibold text-slate-900">Featured Content</h3>
            <button
              onClick={() => void saveSectionVisibility({ ...sectionVisibility, featured_content: !sectionVisibility.featured_content })}
              disabled={isSavingVisibility}
              aria-pressed={sectionVisibility.featured_content}
              className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold transition-all disabled:opacity-50 ${sectionVisibility.featured_content ? 'bg-[rgba(0,102,204,0.10)] text-[#0066cc]' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'}`}
            >
              <span aria-hidden="true" className={`relative inline-block h-4 w-7 flex-shrink-0 rounded-full transition-colors ${sectionVisibility.featured_content ? 'bg-[#0066cc]' : 'bg-slate-300'}`}>
                <span className={`absolute top-0.5 left-0.5 h-3 w-3 rounded-full bg-white shadow transition-transform ${sectionVisibility.featured_content ? 'translate-x-3' : 'translate-x-0'}`} />
              </span>
              {sectionVisibility.featured_content ? 'Shown publicly' : 'Hidden'}
            </button>
          </div>
          <p className="mb-5 text-sm leading-6 text-slate-500">
            Add YouTube videos, Instagram posts, or website links. They'll appear as previews on your public profile.
          </p>

          {/* Add URL input */}
          <div className="flex gap-2">
            <input
              type="url"
              value={featuredUrlInput}
              onChange={(e) => { setFeaturedUrlInput(e.target.value); setFeaturedError(null); }}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addFeaturedItem(); } }}
              placeholder="https://youtube.com/watch?v=... or any link"
              disabled={isSavingFeatured}
              className="flex-1 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-800 placeholder:text-slate-400 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:opacity-50"
            />
            <button
              onClick={addFeaturedItem}
              disabled={isSavingFeatured || !featuredUrlInput.trim()}
              className="rounded-2xl bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-40 transition-colors"
            >
              {isSavingFeatured ? 'Saving…' : 'Add'}
            </button>
          </div>
          {featuredError && (
            <p className="mt-2 text-xs text-rose-600">{featuredError}</p>
          )}

          {/* Featured items list with embeds */}
          {featuredItems.length > 0 ? (
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              {featuredItems.map((item, i) => {
                // Always render the content, but if hidden, overlay a semi-transparent layer with a show button
                const renderOverlay = item.hidden ? (
                  <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-black/60 backdrop-blur-sm rounded-[20px]">
                    <span className="mb-2 text-white text-2xl">🔒</span>
                    <span className="mb-3 text-sm text-white font-medium">Hidden from public page</span>
                    <button
                      onClick={() => toggleFeaturedItemHidden(i)}
                      disabled={isSavingFeatured}
                      className="rounded-full bg-white/90 text-[#0066cc] px-4 py-2 text-xs font-semibold hover:bg-[#e6e6e6] transition disabled:opacity-50"
                      aria-label="Show"
                      title="Show on public page"
                    >
                      Show
                    </button>
                    {/* Remove */}
                    <button
                      onClick={() => removeFeaturedItem(i)}
                      disabled={isSavingFeatured}
                      aria-label="Remove"
                      className="absolute bottom-2 right-2 flex h-6 w-6 items-center justify-center rounded-full bg-white/80 text-slate-400 hover:bg-rose-100 hover:text-rose-600 transition disabled:opacity-40 z-30"
                    >
                      <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
                    </button>
                  </div>
                ) : null;
                if (item.type === 'youtube') {
                  const videoId = extractYouTubeId(item.url);
                  if (!videoId) return null;
                  return (
                    <div key={i} className="overflow-hidden rounded-[20px] border border-slate-200 bg-white shadow-sm h-[320px] relative">
                      <iframe
                        src={`https://www.youtube.com/embed/${videoId}`}
                        title={item.title || 'YouTube video'}
                        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                        allowFullScreen
                        className="h-full w-full"
                        style={{ border: 'none' }}
                      />
                      {/* Hide/show toggle */}
                      {!item.hidden && (
                        <button
                          onClick={() => toggleFeaturedItemHidden(i)}
                          disabled={isSavingFeatured}
                          aria-label="Hide"
                          title="Hide from public page"
                          className="absolute top-2 right-2 flex h-6 w-6 items-center justify-center rounded-full bg-white/80 text-slate-400 hover:bg-slate-200 hover:text-slate-700 transition disabled:opacity-40 z-10"
                        >
                          <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
                        </button>
                      )}
                      {/* Remove */}
                      {!item.hidden && (
                        <button
                          onClick={() => removeFeaturedItem(i)}
                          disabled={isSavingFeatured}
                          aria-label="Remove"
                          className="absolute bottom-2 right-2 flex h-6 w-6 items-center justify-center rounded-full bg-white/80 text-slate-400 hover:bg-rose-100 hover:text-rose-600 transition disabled:opacity-40 z-10"
                        >
                          <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
                        </button>
                      )}
                      {renderOverlay}
                    </div>
                  );
                }
                if (item.type === 'instagram') {
                  // Extract Instagram shortcode and embed type
                  const patterns = [
                    [/instagram\.com\/p\/([^/?#]+)/, 'p'],
                    [/instagram\.com\/reel\/([^/?#]+)/, 'reel'],
                    [/instagram\.com\/tv\/([^/?#]+)/, 'tv'],
                  ];
                  let shortcode = null, embedType = null;
                  for (const [pattern, type] of patterns) {
                    const m = item.url.match(pattern);
                    if (m?.[1]) { shortcode = m[1]; embedType = type; break; }
                  }
                  if (!shortcode || !embedType) return null;
                  const embedSrc = `https://www.instagram.com/${embedType}/${shortcode}/embed/`;
                  return (
                    <div key={i} className="relative overflow-hidden rounded-[20px] border border-slate-200 bg-white shadow-sm h-[320px] group">
                      <iframe
                        src={embedSrc}
                        title={item.title || 'Instagram post'}
                        scrolling="no"
                        className="h-full w-full pointer-events-none"
                        style={{ border: 'none' }}
                      />
                      {/* Hide/show toggle */}
                      {!item.hidden && (
                        <button
                          onClick={() => toggleFeaturedItemHidden(i)}
                          disabled={isSavingFeatured}
                          aria-label="Hide"
                          title="Hide from public page"
                          className="absolute top-2 right-2 flex h-6 w-6 items-center justify-center rounded-full bg-white/80 text-slate-400 hover:bg-slate-200 hover:text-slate-700 transition disabled:opacity-40 z-10"
                        >
                          <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
                        </button>
                      )}
                      {/* Remove */}
                      {!item.hidden && (
                        <button
                          onClick={() => removeFeaturedItem(i)}
                          disabled={isSavingFeatured}
                          aria-label="Remove"
                          className="absolute bottom-2 right-2 flex h-6 w-6 items-center justify-center rounded-full bg-white/80 text-slate-400 hover:bg-rose-100 hover:text-rose-600 transition disabled:opacity-40 z-10"
                        >
                          <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
                        </button>
                      )}
                      {renderOverlay}
                    </div>
                  );
                }
                // Generic link card
                const safeUrl = /^https?:\/\//i.test(item.url) ? item.url : `https://${item.url}`;
                let domain = '';
                try { domain = new URL(safeUrl).hostname.replace('www.', ''); } catch { domain = item.url; }
                return (
                  <div key={i} className="flex h-[320px] items-center gap-4 rounded-[20px] border border-slate-200 bg-white p-5 shadow-sm transition hover:border-slate-300 hover:shadow-md relative">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-xl">
                      🔗
                    </div>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-[#111111]">
                        {item.title || domain}
                      </p>
                      <p className="truncate text-xs text-slate-500 mt-0.5">{domain}</p>
                    </div>
                    <a
                      href={safeUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="ml-auto"
                      aria-label="Open link"
                    >
                      <svg className="h-4 w-4 shrink-0 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" /></svg>
                    </a>
                    {/* Hide/show toggle */}
                    {!item.hidden && (
                      <button
                        onClick={() => toggleFeaturedItemHidden(i)}
                        disabled={isSavingFeatured}
                        aria-label="Hide"
                        title="Hide from public page"
                        className="absolute top-2 right-2 flex h-6 w-6 items-center justify-center rounded-full bg-white/80 text-slate-400 hover:bg-slate-200 hover:text-slate-700 transition disabled:opacity-40 z-10"
                      >
                        <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
                      </button>
                    )}
                    {/* Remove */}
                    {!item.hidden && (
                      <button
                        onClick={() => removeFeaturedItem(i)}
                        disabled={isSavingFeatured}
                        aria-label="Remove"
                        className="absolute bottom-2 right-2 flex h-6 w-6 items-center justify-center rounded-full bg-white/80 text-slate-400 hover:bg-rose-100 hover:text-rose-600 transition disabled:opacity-40 z-10"
                      >
                        <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
                      </button>
                    )}
                    {renderOverlay}
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="mt-4 text-sm text-slate-400">No featured content yet. Add a link above.</p>
          )}
        </div>
      </div>

      {/* --- ABOUT SECTION HEADER AND PROFILE CARDS --- */}
      <div className="mt-10">
        <h3 className="mb-4 text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">About</h3>
        <div className="grid gap-6 lg:grid-cols-2">
          <ToggleSection
            title="Areas of Expertise"
            items={previewProfile.areas_of_expertise}
            isVisible={sectionVisibility.areas_of_expertise}
            isSaving={isSavingVisibility}
            onToggle={() => void saveSectionVisibility({ ...sectionVisibility, areas_of_expertise: !sectionVisibility.areas_of_expertise })}
          />
          <ToggleSection
            title="Key Achievements"
            items={previewProfile.key_achievements}
            isVisible={sectionVisibility.key_achievements}
            isSaving={isSavingVisibility}
            onToggle={() => void saveSectionVisibility({ ...sectionVisibility, key_achievements: !sectionVisibility.key_achievements })}
          />
          <ToggleSection
            title="Personality Traits"
            items={previewProfile.personality_traits}
            isVisible={sectionVisibility.personality_traits}
            isSaving={isSavingVisibility}
            onToggle={() => void saveSectionVisibility({ ...sectionVisibility, personality_traits: !sectionVisibility.personality_traits })}
          />
          <ToggleSection
            title="Contributions"
            items={previewProfile.contributions}
            isVisible={sectionVisibility.contributions}
            isSaving={isSavingVisibility}
            onToggle={() => void saveSectionVisibility({ ...sectionVisibility, contributions: !sectionVisibility.contributions })}
          />
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className={`rounded-[28px] border bg-white p-6 shadow-sm transition-all ${sectionVisibility.pinned_questions ? 'border-slate-200' : 'border-dashed border-slate-200 opacity-55'}`}>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-slate-900">Pinned Questions</h3>
            <button
              onClick={() => void saveSectionVisibility({ ...sectionVisibility, pinned_questions: !sectionVisibility.pinned_questions })}
              disabled={isSavingVisibility}
              aria-pressed={sectionVisibility.pinned_questions}
              className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold transition-all disabled:opacity-50 ${sectionVisibility.pinned_questions ? 'bg-[rgba(0,102,204,0.10)] text-[#0066cc]' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'}`}
            >
              <span aria-hidden="true" className={`relative inline-block h-4 w-7 flex-shrink-0 rounded-full transition-colors ${sectionVisibility.pinned_questions ? 'bg-[#0066cc]' : 'bg-slate-300'}`}>
                <span className={`absolute top-0.5 left-0.5 h-3 w-3 rounded-full bg-white shadow transition-transform ${sectionVisibility.pinned_questions ? 'translate-x-3' : 'translate-x-0'}`} />
              </span>
              {sectionVisibility.pinned_questions ? 'Shown publicly' : 'Hidden'}
            </button>
          </div>
          <div className="space-y-3">
            {(previewProfile.pinned_questions || []).slice(0, 4).map((question, index) => (
              <div key={`${question}-${index}`} className="rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-700">
                {question}
              </div>
            ))}
            {(!previewProfile.pinned_questions || previewProfile.pinned_questions.length === 0) && (
              <p className="text-sm text-slate-500">Add pinned questions in the profile editor to make the chat start stronger.</p>
            )}
          </div>
        </div>

        <div className={`rounded-[28px] border bg-white p-6 shadow-sm transition-all ${sectionVisibility.social_links ? 'border-slate-200' : 'border-dashed border-slate-200 opacity-55'}`}>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-lg font-semibold text-slate-900">Social Links</h3>
            <button
              onClick={() => void saveSectionVisibility({ ...sectionVisibility, social_links: !sectionVisibility.social_links })}
              disabled={isSavingVisibility}
              aria-pressed={sectionVisibility.social_links}
              className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold transition-all disabled:opacity-50 ${sectionVisibility.social_links ? 'bg-[rgba(0,102,204,0.10)] text-[#0066cc]' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'}`}
            >
              <span aria-hidden="true" className={`relative inline-block h-4 w-7 flex-shrink-0 rounded-full transition-colors ${sectionVisibility.social_links ? 'bg-[#0066cc]' : 'bg-slate-300'}`}>
                <span className={`absolute top-0.5 left-0.5 h-3 w-3 rounded-full bg-white shadow transition-transform ${sectionVisibility.social_links ? 'translate-x-3' : 'translate-x-0'}`} />
              </span>
              {sectionVisibility.social_links ? 'Shown publicly' : 'Hidden'}
            </button>
          </div>
          <p className="mb-5 text-sm leading-6 text-slate-500">
            Control which social links appear on your public profile. Edit links in{' '}
            <Link href="/dashboard/profile" className="text-[#0066cc] underline-offset-2 hover:underline">profile settings</Link>.
          </p>

          {socialLinks.length > 0 ? (
            <ul className="space-y-2">
              {socialLinks.map(([platform, url]) => {
                const isVisible = socialLinkVisibility[platform] !== false;
                return (
                  <li key={platform} className={`flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 transition-opacity ${!isVisible ? 'opacity-50' : ''}`}>
                    <span className="shrink-0 rounded-full bg-slate-200 px-2.5 py-0.5 text-[11px] font-semibold capitalize text-slate-600">{platform}</span>
                    <span className="flex-1 truncate font-mono text-xs text-slate-600">{url}</span>
                    <button
                      onClick={() => {
                        const next = { ...socialLinkVisibility, [platform]: !isVisible };
                        void saveSocialLinkVisibility(next);
                      }}
                      disabled={isSavingSocialVisibility}
                      aria-label={isVisible ? 'Hide' : 'Show'}
                      title={isVisible ? 'Hide from public page' : 'Show on public page'}
                      className={`shrink-0 flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold transition disabled:opacity-40 ${isVisible ? 'bg-[rgba(0,102,204,0.10)] text-[#0066cc]' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'}`}
                    >
                      <span aria-hidden="true" className={`relative inline-block h-3.5 w-6 flex-shrink-0 rounded-full transition-colors ${isVisible ? 'bg-[#0066cc]' : 'bg-slate-300'}`}>
                        <span className={`absolute top-0.5 left-0.5 h-2.5 w-2.5 rounded-full bg-white shadow transition-transform ${isVisible ? 'translate-x-2.5' : 'translate-x-0'}`} />
                      </span>
                      {isVisible ? 'Shown' : 'Hidden'}
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-sm text-slate-400">
              No social links yet.{' '}
              <Link href="/dashboard/profile" className="text-[#0066cc] underline-offset-2 hover:underline">Add them in profile settings</Link>.
            </p>
          )}
        </div>
      </div>
    </div>
    </div>
  );
}
