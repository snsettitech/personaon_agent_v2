'use client';

import React, { useEffect, useMemo, useState } from 'react';

import { AnimatePresence, motion } from 'framer-motion';

import EmptyState from '@/components/ui/EmptyState';
import MarketplaceNav from '@/components/marketplace/MarketplaceNav';
import PersonaCard from '@/components/marketplace/PersonaCard';
import PersonaCardSkeleton from '@/components/marketplace/PersonaCardSkeleton';
import AskResultCard from '@/components/marketplace/AskResultCard';
import CategoryPillBar from '@/components/marketplace/CategoryPillBar';
import GeographyFilter from '@/components/marketplace/GeographyFilter';
import { inferCategory, type ProfessionCategory } from '@/components/marketplace/categoryUtils';
import { useMarketplaceAsk } from '@/lib/hooks/useMarketplaceAsk';
import { resolveApiBaseUrl } from '@/lib/api';
import { analytics } from '@/lib/analytics/events';

type MarketplaceTopic = {
  slug: string;
  name: string;
  count: number;
};

type MarketplacePersona = {
  twin_id: string;
  display_name: string;
  occupation: string;
  headline: string;
  bio: string;
  short_description: string;
  avatar_url: string;
  verified_claims_count: number;
  public_topics: Array<{ slug: string; name: string }>;
  areas_of_expertise: string[];
  pinned_questions: string[];
  public_url: string | null;
  verified_profile: boolean;
  nationality?: string;
};

type MarketplaceResponse = {
  items: MarketplacePersona[];
  facets: { topics: MarketplaceTopic[] };
  next_cursor: string | null;
};

export default function MarketplaceDirectory() {
  const apiBaseUrl = useMemo(() => resolveApiBaseUrl(), []);
  const [searchInput, setSearchInput] = useState('');
  const [query, setQuery] = useState('');
  const [selectedTopic, setSelectedTopic] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<ProfessionCategory | null>(null);
  const [selectedGeography, setSelectedGeography] = useState<string | null>(null);
  const [items, setItems] = useState<MarketplacePersona[]>([]);
  const [topics, setTopics] = useState<MarketplaceTopic[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // "Ask the Marketplace" semantic search hook
  const askHook = useMarketplaceAsk();
  const askFn = askHook.ask;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const trimmed = searchInput.trim();
      setQuery(trimmed);
      // Feed the search input to the ask hook — it auto-detects question mode
      askFn(trimmed);
    }, 200);
    return () => window.clearTimeout(timer);
  }, [searchInput, askFn]);

  const fetchMarketplace = async (cursor?: string | null, append = false) => {
    const searchParams = new URLSearchParams();
    if (query) searchParams.set('q', query);
    if (selectedTopic) searchParams.set('topic', selectedTopic);
    if (cursor) searchParams.set('cursor', cursor);
    searchParams.set('limit', '24');

    setError(null);
    if (append) {
      setLoadingMore(true);
    } else {
      setLoading(true);
    }

    try {
      const response = await fetch(`${apiBaseUrl}/public/marketplace?${searchParams.toString()}`, {
        cache: 'no-store',
      });
      if (!response.ok) {
        throw new Error(`Failed to load marketplace (${response.status})`);
      }

      const data = (await response.json()) as MarketplaceResponse;
      setTopics(data.facets?.topics || []);
      setNextCursor(data.next_cursor || null);
      setItems((previous) => (append ? [...previous, ...(data.items || [])] : data.items || []));
      if (query) {
        analytics.marketplaceSearched({ query, result_count: data.items?.length ?? 0 });
      }
    } catch (err) {
      console.error('[Marketplace] Failed to load personas:', err);
      setError('Unable to load the marketplace right now. Please try again in a moment.');
      if (!append) {
        setItems([]);
        setNextCursor(null);
      }
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  };

  useEffect(() => {
    void fetchMarketplace(null, false);
  }, [apiBaseUrl, query, selectedTopic]);

  const hasActiveFilters = Boolean(query || selectedTopic || selectedGeography);

  const uniqueRegions = useMemo(
    () =>
      [...new Set(items.map((p) => p.nationality).filter(Boolean))].sort() as string[],
    [items]
  );

  const filteredItems = useMemo(() => {
    let result = selectedCategory
      ? items.filter((p) => inferCategory(p.occupation) === selectedCategory)
      : items;
    if (selectedGeography) {
      result = result.filter((p) => p.nationality === selectedGeography);
    }
    return result;
  }, [items, selectedCategory, selectedGeography]);

  return (
    <div
      className="min-h-screen"
      style={{ backgroundColor: 'var(--bg-base)', color: 'var(--text-primary)' }}
    >
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_top_left,rgba(251,191,36,0.18),transparent_28%),radial-gradient(circle_at_85%_15%,rgba(15,118,110,0.10),transparent_22%)]" />

      <MarketplaceNav />

      <main className="relative mx-auto max-w-7xl px-6 pb-20 pt-24 lg:px-12">
        <section className="max-w-2xl">
          <p
            className="text-xs font-semibold uppercase tracking-[0.22em]"
            style={{ color: 'var(--accent-trust-dark)' }}
          >
            Live Personas
          </p>
          <h1
            className="mt-3 text-4xl font-semibold leading-tight md:text-5xl"
            style={{ color: 'var(--text-primary)' }}
          >
            Portfolios that answer, browsable.
          </h1>
          <p
            className="mt-3 text-base leading-7"
            style={{ color: 'var(--text-secondary)' }}
          >
            Search by role or ask a question in plain language — every result is a real person's page, grounded in what they have actually done.
          </p>
        </section>

        <section
          className="mt-10 rounded-[32px] p-5 shadow-sm"
          style={{
            backgroundColor: 'var(--bg-elevated)',
            border: '1px solid var(--border-subtle)',
          }}
        >
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <label className="relative flex-1">
              <span className="sr-only">Search personas</span>
              <input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="What do you want to learn about? Or search by name..."
                className="w-full rounded-2xl border px-5 py-4 placeholder:text-[var(--text-tertiary)] focus:outline-none focus:ring-2 focus:border-[var(--accent-trust)] focus:ring-[var(--accent-trust)]"
                style={{
                  backgroundColor: 'var(--bg-surface)',
                  borderColor: askHook.isAskMode ? 'var(--accent-trust)' : 'var(--border-default)',
                  color: 'var(--text-primary)',
                }}
              />
              {/* Mode indicator */}
              {searchInput.trim().length > 0 && (
                <span
                  className="absolute right-4 top-1/2 -translate-y-1/2 rounded-full px-2.5 py-1 text-[11px] font-medium"
                  style={{
                    backgroundColor: askHook.isAskMode
                      ? 'rgba(13,148,136,0.1)'
                      : 'var(--bg-surface)',
                    color: askHook.isAskMode
                      ? 'var(--accent-trust)'
                      : 'var(--text-tertiary)',
                  }}
                >
                  {askHook.isAskMode ? 'Finding experts...' : 'Searching names...'}
                </span>
              )}
            </label>
            {(hasActiveFilters || askHook.isAskMode) && (
              <button
                type="button"
                onClick={() => {
                  setSearchInput('');
                  setQuery('');
                  setSelectedTopic(null);
                  setSelectedGeography(null);
                  askHook.clear();
                }}
                className="rounded-2xl px-4 py-3 text-sm font-medium transition-colors hover:opacity-80"
                style={{
                  color: 'var(--text-secondary)',
                  border: '1px solid var(--border-default)',
                }}
              >
                Clear filters
              </button>
            )}
          </div>

          {/* Category pill bar */}
          <div className="mt-5">
            <CategoryPillBar
              selected={selectedCategory}
              onSelect={setSelectedCategory}
            />
          </div>

          {/* Geography filter */}
          {uniqueRegions.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <GeographyFilter
                regions={uniqueRegions}
                selected={selectedGeography}
                onSelect={setSelectedGeography}
              />
            </div>
          )}

          {topics.length > 0 && (
            <div
              className="mt-3 pt-3 flex flex-wrap gap-2"
              style={{ borderTop: '1px solid var(--border-subtle)' }}
            >
              <button
                type="button"
                onClick={() => setSelectedTopic(null)}
                className="rounded-full px-4 py-2 text-sm font-medium transition-colors"
                style={
                  selectedTopic === null
                    ? { backgroundColor: 'var(--primary-500)', color: '#ffffff' }
                    : { backgroundColor: 'var(--bg-surface)', color: 'var(--text-secondary)' }
                }
              >
                All topics
              </button>
              {topics.map((topic) => (
                <button
                  key={topic.slug}
                  type="button"
                  onClick={() => setSelectedTopic(topic.slug)}
                  className="rounded-full px-4 py-2 text-sm font-medium transition-colors"
                  style={
                    selectedTopic === topic.slug
                      ? { backgroundColor: 'var(--accent-trust)', color: '#ffffff' }
                      : { backgroundColor: 'var(--bg-surface)', color: 'var(--text-secondary)' }
                  }
                >
                  {topic.name} <span className="text-xs opacity-70">({topic.count})</span>
                </button>
              ))}
            </div>
          )}
        </section>

        {/* ─── Ask Mode: Semantic search results ─── */}
        {askHook.isAskMode ? (
          <section className="mt-10">
            {askHook.loading ? (
              <div className="flex min-h-[240px] items-center justify-center">
                <div className="text-center">
                  <div
                    className="mx-auto h-10 w-10 animate-spin rounded-full border-[3px]"
                    style={{
                      borderColor: 'var(--border-default)',
                      borderTopColor: 'var(--accent-trust)',
                    }}
                  />
                  <p className="mt-4 text-sm font-medium" style={{ color: 'var(--text-tertiary)' }}>
                    Finding the best experts for your question...
                  </p>
                </div>
              </div>
            ) : askHook.error ? (
              <div className="rounded-[28px] border border-rose-200 bg-rose-50 p-6 text-rose-700">
                {askHook.error}
              </div>
            ) : askHook.results.length === 0 && askHook.query ? (
              <div
                className="rounded-[32px] p-8 shadow-sm"
                style={{
                  backgroundColor: 'var(--bg-elevated)',
                  border: '1px solid var(--border-subtle)',
                }}
              >
                <EmptyState
                  illustration="chat-bubble"
                  title="No experts found for this question"
                  description="Try rephrasing your question, or browse the personas below."
                  primaryAction={{
                    label: 'Clear search',
                    onClick: () => {
                      setSearchInput('');
                      askHook.clear();
                    },
                  }}
                  theme="light"
                />
              </div>
            ) : (
              <>
                <div className="mb-4 flex items-center gap-3">
                  <p
                    className="text-sm font-medium"
                    style={{ color: 'var(--text-tertiary)' }}
                  >
                    {askHook.results.length} expert{askHook.results.length !== 1 ? 's' : ''} found
                  </p>
                  <div
                    className="h-px flex-1"
                    style={{ backgroundColor: 'var(--border-subtle)' }}
                  />
                </div>
                <AnimatePresence mode="wait">
                  <motion.div
                    key={askHook.query}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="space-y-4"
                  >
                    {askHook.results.map((result, i) => (
                      <AskResultCard
                        key={result.persona.twin_id}
                        result={result}
                        rank={i}
                      />
                    ))}
                  </motion.div>
                </AnimatePresence>
              </>
            )}
          </section>

        ) : loading ? (
          <div className="mt-10 grid gap-6 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <PersonaCardSkeleton key={i} />
            ))}
          </div>
        ) : error ? (
          <div className="mt-10 rounded-[28px] border border-rose-200 bg-rose-50 p-6 text-rose-700">
            {error}
          </div>
        ) : filteredItems.length === 0 && (selectedCategory !== null || selectedGeography !== null) && items.length > 0 ? (
          <div
            className="mt-10 rounded-[32px] p-8 shadow-sm"
            style={{
              backgroundColor: 'var(--bg-elevated)',
              border: '1px solid var(--border-subtle)',
            }}
          >
            <EmptyState
              illustration="chat-bubble"
              title={
                selectedCategory && selectedGeography
                  ? `No ${selectedCategory} personas in ${selectedGeography}`
                  : selectedCategory
                  ? `No ${selectedCategory} personas yet`
                  : `No personas found in ${selectedGeography}`
              }
              description="Try a different category, region, or search to find what you're looking for."
              primaryAction={{
                label: 'Clear filters',
                onClick: () => {
                  setSelectedCategory(null);
                  setSelectedGeography(null);
                },
              }}
              theme="light"
            />
          </div>
        ) : items.length === 0 ? (
          <div
            className="mt-10 rounded-[32px] p-8 shadow-sm"
            style={{
              backgroundColor: 'var(--bg-elevated)',
              border: '1px solid var(--border-subtle)',
            }}
          >
            <EmptyState
              illustration="chat-bubble"
              title={hasActiveFilters ? 'No personas matched those filters' : 'No public personas yet'}
              description={
                hasActiveFilters
                  ? 'Try a broader search or clear the selected topic to see more personas.'
                  : 'Personas with strong public profile data will appear here automatically once they are ready.'
              }
              primaryAction={
                hasActiveFilters
                  ? {
                      label: 'Clear filters',
                      onClick: () => {
                        setSearchInput('');
                        setQuery('');
                        setSelectedTopic(null);
                        setSelectedGeography(null);
                      },
                    }
                  : {
                      label: 'Create a persona',
                      href: '/auth/signup?utm_source=marketplace',
                    }
              }
              theme="light"
            />
          </div>
        ) : (
          <>
            <div className="mt-10 grid gap-6 md:grid-cols-2 xl:grid-cols-3">
              {filteredItems.map((persona) => (
                <PersonaCard key={persona.twin_id} persona={persona} />
              ))}
            </div>

            {nextCursor && (
              <div className="mt-10 flex justify-center">
                <button
                  type="button"
                  onClick={() => void fetchMarketplace(nextCursor, true)}
                  disabled={loadingMore}
                  className="rounded-full px-6 py-3 text-sm font-medium transition-colors disabled:opacity-60"
                  style={{ backgroundColor: 'var(--primary-500)', color: '#ffffff' }}
                >
                  {loadingMore ? 'Loading more...' : 'Load more personas'}
                </button>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
