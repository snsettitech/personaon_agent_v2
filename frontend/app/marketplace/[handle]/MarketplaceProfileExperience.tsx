'use client';

import Link from 'next/link';
import React, { useEffect, useMemo, useState } from 'react';
import { useParams } from 'next/navigation';

import { resolveApiBaseUrl } from '@/lib/api';
import TryBeforeCommitChat from '@/components/marketplace/TryBeforeCommitChat';
import TopicCloud from '@/components/marketplace/TopicCloud';
import SampleQA from '@/components/marketplace/SampleQA';
import MarketplaceNav from '@/components/marketplace/MarketplaceNav';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PublicProfile {
  name?: string;
  occupation?: string;
  bio?: string;
  headline?: string;
  areas_of_expertise?: string[];
  key_achievements?: string[];
  work_experience?: Array<{
    company?: string;
    role?: string;
    description?: string;
    start_year?: number;
    end_year?: number;
  }>;
  education?: Array<{
    institution?: string;
    degree?: string;
    field?: string;
    end_year?: number;
  }>;
  social_links?: Record<string, string>;
  image_url?: string;
  avatar_url?: string;
  suggested_questions?: string[];
  verified_profile?: boolean;
  nationality?: string;
  public_topics?: Array<{ slug: string; name: string; answerability_score?: number }>;
  public_response_seeds?: Array<{
    question: string;
    answer: string;
    citations?: string[];
    title?: string;
    confidence?: number;
  }>;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------


// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getInitials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function MarketplaceProfileExperience() {
  const params = useParams<{ handle: string }>();
  const handle = Array.isArray(params?.handle) ? params.handle[0] : (params?.handle ?? '');
  const apiBaseUrl = useMemo(() => resolveApiBaseUrl(), []);

  const [twinId, setTwinId] = useState<string>('');
  const [shareToken, setShareToken] = useState<string>('');
  const [profile, setProfile] = useState<PublicProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Resolve handle -> twin_id + share_token -> profile
  useEffect(() => {
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
        setProfile(profileData.profile ?? profileData);
      } catch {
        setError('network_error');
      } finally {
        setLoading(false);
      }
    };

    void load();
  }, [handle, apiBaseUrl]);

  // ─── Loading state ───────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="min-h-screen" style={{ backgroundColor: 'var(--bg-base)' }}>
        {/* Nav skeleton */}
        <div
          className="fixed top-4 left-4 right-4 z-50 h-14 rounded-2xl"
          style={{ backgroundColor: 'var(--bg-elevated)', border: '1px solid var(--border-subtle)' }}
        />
        <div className="mx-auto max-w-7xl px-6 pt-32 pb-20 lg:px-12">
          <div className="lg:grid lg:grid-cols-[1fr_400px] lg:gap-10">
            {/* Left skeleton */}
            <div className="space-y-6">
              <div className="flex items-center gap-4">
                <div
                  className="w-24 h-24 rounded-full animate-pulse"
                  style={{ backgroundColor: 'var(--bg-surface)' }}
                />
                <div className="space-y-2">
                  <div
                    className="h-8 w-48 rounded animate-pulse"
                    style={{ backgroundColor: 'var(--bg-surface)' }}
                  />
                  <div
                    className="h-5 w-32 rounded animate-pulse"
                    style={{ backgroundColor: 'var(--bg-surface)' }}
                  />
                </div>
              </div>
              <div
                className="h-32 w-full rounded-2xl animate-pulse"
                style={{ backgroundColor: 'var(--bg-surface)' }}
              />
            </div>
            {/* Right skeleton */}
            <div
              className="mt-8 h-96 rounded-[20px] animate-pulse lg:mt-0"
              style={{ backgroundColor: 'var(--bg-surface)' }}
            />
          </div>
        </div>
      </div>
    );
  }

  // ─── Error / not found state ─────────────────────────────────────────────
  if (error) {
    return (
      <div
        className="min-h-screen flex items-center justify-center p-4"
        style={{ backgroundColor: 'var(--bg-base)' }}
      >
        <div
          className="w-full max-w-md rounded-2xl p-8 text-center"
          style={{
            backgroundColor: 'var(--bg-surface)',
            border: '1px solid var(--border-default)',
          }}
        >
          <h1 className="text-2xl font-semibold" style={{ color: 'var(--text-primary)' }}>
            This persona doesn&apos;t exist
          </h1>
          <p className="mt-2 text-base" style={{ color: 'var(--text-secondary)' }}>
            Check the URL and try again.
          </p>
          <Link
            href="/marketplace"
            className="mt-6 inline-block text-sm font-medium"
            style={{ color: 'var(--primary-600)' }}
          >
            &larr; Back to Marketplace
          </Link>
        </div>
      </div>
    );
  }

  const displayName = profile?.name ?? '';
  const occupation = profile?.occupation || profile?.headline || '';
  const avatarSrc = profile?.image_url || profile?.avatar_url;
  const initials = getInitials(displayName) || 'P';

  // Derive topic cloud data — prefer public_topics with scores, fall back to suggested_questions
  const topicCloudTopics: Array<{ slug: string; name: string; answerability_score?: number }> =
    profile?.public_topics && profile.public_topics.length > 0
      ? profile.public_topics
      : (profile?.suggested_questions ?? []).map((q, i) => ({ slug: String(i), name: q }));

  return (
    <div
      className="min-h-screen"
      style={{ backgroundColor: 'var(--bg-base)', color: 'var(--text-primary)' }}
    >
      {/* Subtle radial gradient background */}
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_top_left,rgba(251,191,36,0.18),transparent_28%),radial-gradient(circle_at_85%_15%,rgba(15,118,110,0.10),transparent_22%)]" />

      <MarketplaceNav />

      {/* ─── Main content ─── */}
      <main className="relative mx-auto max-w-7xl px-6 pb-20 pt-28 lg:px-12">

        {/* Breadcrumb */}
        <nav aria-label="Breadcrumb" className="mb-8">
          <ol className="flex items-center gap-2 text-sm">
            <li>
              <Link
                href="/marketplace"
                className="transition-colors hover:opacity-80"
                style={{ color: 'var(--text-tertiary)' }}
              >
                Marketplace
              </Link>
            </li>
            <li style={{ color: 'var(--text-tertiary)' }}>&rsaquo;</li>
            <li style={{ color: 'var(--text-primary)' }}>{displayName}</li>
          </ol>
        </nav>

        {/* Responsive grid: profile left, chat right */}
        <div className="lg:grid lg:grid-cols-[1fr_400px] lg:gap-10">

          {/* ── Left column: Profile ── */}
          <div className="space-y-8">

            {/* Profile header */}
            <div className="flex items-start gap-5">
              {avatarSrc ? (
                <img
                  src={avatarSrc}
                  alt={displayName}
                  className="w-24 h-24 rounded-full object-cover shrink-0"
                />
              ) : (
                <div
                  className="w-24 h-24 rounded-full flex items-center justify-center shrink-0 text-2xl font-semibold text-white"
                  style={{ background: 'linear-gradient(135deg, #F59E0B, #EA580C)' }}
                  aria-hidden="true"
                >
                  {initials}
                </div>
              )}

              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-3">
                  <h1
                    className="text-3xl font-semibold leading-tight"
                    style={{
                      fontFamily: "'Playfair Display', Georgia, serif",
                      color: 'var(--text-primary)',
                    }}
                  >
                    {displayName}
                  </h1>
                  {profile?.verified_profile && (
                    <span
                      className="inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em]"
                      style={{ backgroundColor: '#d1fae5', color: '#059669' }}
                    >
                      Verified
                    </span>
                  )}
                </div>
                {occupation && (
                  <p className="mt-1 text-lg" style={{ color: 'var(--text-secondary)' }}>
                    {occupation}
                  </p>
                )}
                {profile?.nationality && (
                  <p className="mt-1 flex items-center gap-1.5 text-sm" style={{ color: 'var(--text-tertiary)' }}>
                    <svg className="h-3.5 w-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
                      <circle cx="12" cy="10" r="3" />
                    </svg>
                    {profile.nationality}
                  </p>
                )}
              </div>
            </div>

            {/* Bio */}
            {profile?.bio && (
              <div
                className="rounded-2xl p-6"
                style={{
                  backgroundColor: 'var(--bg-elevated)',
                  border: '1px solid var(--border-subtle)',
                }}
              >
                <p
                  className="text-base leading-relaxed"
                  style={{ color: 'var(--text-secondary)' }}
                >
                  {profile.bio}
                </p>
              </div>
            )}

            {/* Areas of Expertise */}
            {profile?.areas_of_expertise && profile.areas_of_expertise.length > 0 && (
              <div>
                <p
                  className="mb-3 text-sm font-semibold uppercase tracking-widest"
                  style={{ color: 'var(--text-tertiary)' }}
                >
                  Expertise
                </p>
                <div className="flex flex-wrap gap-2">
                  {profile.areas_of_expertise.map((area) => (
                    <span
                      key={area}
                      className="rounded-full px-3 py-1 text-sm font-medium"
                      style={{
                        backgroundColor: 'rgba(13,148,136,0.1)',
                        color: 'var(--primary-600)',
                        border: '1px solid rgba(13,148,136,0.2)',
                      }}
                    >
                      {area}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* People ask me about (topic cloud) */}
            {topicCloudTopics.length > 0 && (
              <div>
                <p
                  className="mb-3 text-sm font-semibold uppercase tracking-widest"
                  style={{ color: 'var(--text-tertiary)' }}
                >
                  People ask me about
                </p>
                <TopicCloud topics={topicCloudTopics} />
              </div>
            )}

            {/* Sample Q&A */}
            {profile?.public_response_seeds && profile.public_response_seeds.length > 0 && (
              <div>
                <p
                  className="mb-3 text-sm font-semibold uppercase tracking-widest"
                  style={{ color: 'var(--text-tertiary)' }}
                >
                  Sample Q&amp;A
                </p>
                <SampleQA entries={profile.public_response_seeds} />
              </div>
            )}

            {/* Key achievements */}
            {profile?.key_achievements && profile.key_achievements.length > 0 && (
              <div>
                <p
                  className="mb-3 text-sm font-semibold uppercase tracking-widest"
                  style={{ color: 'var(--text-tertiary)' }}
                >
                  Key Achievements
                </p>
                <ul className="space-y-2">
                  {profile.key_achievements.map((achievement, i) => (
                    <li key={i} className="flex items-start gap-3">
                      <span
                        className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
                        style={{ backgroundColor: 'var(--accent-trust)' }}
                        aria-hidden="true"
                      />
                      <span className="text-sm" style={{ color: 'var(--text-secondary)' }}>
                        {achievement}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Back to marketplace */}
            <div className="pt-2">
              <Link
                href="/marketplace"
                className="inline-flex items-center gap-1.5 text-sm font-medium transition-opacity hover:opacity-80"
                style={{ color: 'var(--primary-600)' }}
              >
                <svg
                  className="h-4 w-4"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  aria-hidden="true"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 12H5m7-7l-7 7 7 7" />
                </svg>
                Back to Marketplace
              </Link>
            </div>
          </div>

          {/* ── Right column: Try Before Commit Chat ── */}
          <div className="mt-10 lg:mt-0 lg:sticky lg:top-24 lg:self-start">
            {twinId && shareToken ? (
              <TryBeforeCommitChat
                twinId={twinId}
                shareToken={shareToken}
                handle={handle}
                personaName={displayName}
                personaAvatar={avatarSrc}
              />
            ) : null}
          </div>
        </div>
      </main>
    </div>
  );
}
