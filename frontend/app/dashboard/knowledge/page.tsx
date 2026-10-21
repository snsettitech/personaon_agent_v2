'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
import { useTwin } from '@/lib/context/TwinContext';
import { getSupabaseClient } from '@/lib/supabase/client';
import UnifiedIngestion from '@/components/ingestion/UnifiedIngestion';
import SourceExplorer from '@/components/Knowledge/SourceExplorer';
import { API_BASE_URL, API_ENDPOINTS } from '@/lib/constants';
import type { Source } from '@/lib/types/source';

interface KnowledgeProfile {
  total_chunks: number;
  total_sources: number;
  fact_count: number;
  opinion_count: number;
  tone_distribution: Record<string, number>;
  top_tone: string;
}

// ─── Animation variants ────────────────────────────────────────────────────
const fadeUp: Variants = {
  hidden: { opacity: 0, y: 16 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.35, ease: 'easeOut' as const, delay: i * 0.07 },
  }),
};

// ─── Main page ──────────────────────────────────────────────────────────────
export default function KnowledgePage() {
  const { activeTwin, isLoading: twinLoading } = useTwin();
  const supabase = getSupabaseClient();
  const [sources, setSources] = useState<Record<string, Source[]>>({});
  const [profile, setProfile] = useState<KnowledgeProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const twinId = activeTwin?.id;

  // Reset state when twin switches
  useEffect(() => {
    setSources({});
    setProfile(null);
    setLoading(true);
    setError(null);
  }, [twinId]);

  const getAuthToken = useCallback(async () => {
    const { data: { session } } = await supabase.auth.getSession();
    return session?.access_token;
  }, [supabase]);

  const fetchData = useCallback(async () => {
    if (!twinId) return;
    const token = await getAuthToken();
    if (!token) return;
    try {
      const [sourcesRes, profileRes] = await Promise.all([
        fetch(`${API_BASE_URL}${API_ENDPOINTS.TWIN_SOURCES_GROUPED(twinId)}`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetch(`${API_BASE_URL}${API_ENDPOINTS.TWIN_KNOWLEDGE_PROFILE(twinId)}`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
      ]);

      if (sourcesRes.ok) {
        const sourcesData = await sourcesRes.json();
        setSources(sourcesData.data || {});
      }
      if (profileRes.ok) setProfile(await profileRes.json());
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load knowledge';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [twinId, getAuthToken]);

  useEffect(() => {
    if (twinId) fetchData();
  }, [twinId, fetchData]);

  // Poll every 15s while any source is still queued/processing
  useEffect(() => {
    const hasPending = Object.values(sources).flat().some(
      (s) => ['queued', 'processing'].includes(s.status ?? '')
    );
    if (!hasPending || loading) return;
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, [sources, loading, fetchData]);

  const handleDelete = async (sourceId: string) => {
    if (!twinId) return;
    const token = await getAuthToken();
    if (!token) return;
    try {
      const res = await fetch(
        `${API_BASE_URL}${API_ENDPOINTS.TWIN_SOURCE_DETAIL(twinId, sourceId)}`,
        { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } }
      );
      if (res.ok) {
        const updated: Record<string, Source[]> = {};
        for (const [type, list] of Object.entries(sources)) {
          const filtered = list.filter((s) => s.id !== sourceId);
          if (filtered.length > 0) updated[type] = filtered;
        }
        setSources(updated);
        const profileRes = await fetch(
          `${API_BASE_URL}${API_ENDPOINTS.TWIN_KNOWLEDGE_PROFILE(twinId)}`,
          { headers: { Authorization: `Bearer ${token}` } }
        );
        if (profileRes.ok) setProfile(await profileRes.json());
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to delete source';
      setError(msg);
    }
  };

  const handleUpdate = useCallback((updated: Source) => {
    setSources((prev) => {
      const next: Record<string, Source[]> = {};
      for (const [key, list] of Object.entries(prev)) {
        const filtered = list.filter((s) => s.id !== updated.id);
        if (filtered.length > 0) next[key] = filtered;
      }
      const targetKey = updated.source_type ?? 'document';
      next[targetKey] = [...(next[targetKey] ?? []), updated];
      return next;
    });
  }, []);

  // ── Loading ────────────────────────────────────────────────────────────
  if (twinLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center">
          <div
            className="w-10 h-10 rounded-full border-2 border-t-transparent animate-spin mx-auto mb-3"
            style={{ borderColor: 'var(--brand-primary)', borderTopColor: 'transparent' }}
          />
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Loading your persona…</p>
        </div>
      </div>
    );
  }

  // ── No twin ────────────────────────────────────────────────────────────
  if (!twinId) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center max-w-sm p-8">
          <div
            className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-5"
            style={{ backgroundColor: 'var(--bg-elevated)' }}
          >
            <svg className="w-7 h-7" style={{ color: 'var(--text-muted)' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5"
                d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
            </svg>
          </div>
          <h2 className="text-xl font-bold mb-2" style={{ color: 'var(--text-primary)' }}>No persona found</h2>
          <p className="text-sm mb-6" style={{ color: 'var(--text-muted)' }}>
            Create your persona first to add knowledge.
          </p>
          <a
            href="/dashboard/studio"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-opacity hover:opacity-90"
            style={{ backgroundColor: 'var(--brand-primary)' }}
          >
            Create your persona
          </a>
        </div>
      </div>
    );
  }

  // ── Main render ────────────────────────────────────────────────────────
  return (
    <div className="max-w-6xl mx-auto pb-24 pt-4" style={{ backgroundColor: 'var(--bg-base)' }}>
      <div className="px-0 space-y-8">

        {/* Ingestion */}
        <motion.div initial="hidden" animate="visible" custom={0} variants={fadeUp}>
          <UnifiedIngestion
            twinId={twinId}
            onComplete={() => fetchData()}
            onError={(err) => setError(err)}
          />
        </motion.div>

        {/* Error */}
        <AnimatePresence>
          {error && (
            <motion.div
              className="flex items-center gap-3 p-4 rounded-2xl text-sm font-medium"
              style={{ backgroundColor: '#fef2f2', color: '#dc2626', border: '1px solid #fecaca' }}
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
            >
              <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2"
                  d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              {error}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Knowledge library */}
        <motion.div
          className="rounded-3xl overflow-hidden"
          style={{
            backgroundColor: 'var(--bg-card)',
            border: '1px solid var(--border-subtle)',
            boxShadow: '0 1px 4px rgba(0,0,0,0.04)',
          }}
          initial="hidden" animate="visible" custom={1} variants={fadeUp}
        >
          {/* Card header */}
          <div
            className="px-8 py-5 flex items-center justify-between"
            style={{ borderBottom: '1px solid var(--border-subtle)' }}
          >
            <div>
              <div className="flex items-center gap-3">
                <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
                  Knowledge library
                </h3>
                <span
                  className="px-2.5 py-0.5 rounded-full text-[11px] font-semibold"
                  style={{ backgroundColor: 'var(--bg-elevated)', color: 'var(--text-muted)' }}
                >
                  {Object.values(sources).flat().length} items
                </span>
              </div>
              <p className="mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>
                Review, update, or remove the information your persona can use.
              </p>
            </div>
            {profile && profile.total_chunks > 0 && (
              <span
                className="hidden rounded-full px-3 py-1 text-[11px] font-semibold sm:inline-flex"
                style={{ backgroundColor: 'var(--bg-elevated)', color: 'var(--text-muted)' }}
              >
                {profile.total_chunks.toLocaleString()} segments ready
              </span>
            )}
          </div>

          {/* Content */}
          <SourceExplorer
            groupedSources={sources}
            loading={loading}
            onDelete={handleDelete}
            onUpdate={handleUpdate}
          />
        </motion.div>

      </div>
    </div>
  );
}
