'use client';

import React, { Suspense, useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { useSearchParams } from 'next/navigation';
import ChatInterface from '@/components/Chat/ChatInterface';
import FeatureGate from '@/components/ui/FeatureGate';
import { useTwin } from '@/lib/context/TwinContext';
import { isRuntimeFeatureEnabled } from '@/lib/features/runtimeFlags';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { API_ENDPOINTS } from '@/lib/constants';

function DashboardChatPageContent() {
  const { activeTwin, isLoading, twins, setActiveTwin } = useTwin();
  const searchParams = useSearchParams();
  const [canonicalProfileId, setCanonicalProfileId] = useState<string | null>(null);
  const [profileQuestions, setProfileQuestions] = useState<string[]>([]);

  const chatEnabled = isRuntimeFeatureEnabled('dashboardChat');
  const requestedTwinId = searchParams.get('twinId');
  const twinId = activeTwin?.id;
  const effectiveTwinId = canonicalProfileId || twinId;
  const effectiveTwin = useMemo(() => {
    if (!effectiveTwinId) return null;
    return twins.find((t) => t.id === effectiveTwinId) || (activeTwin?.id === effectiveTwinId ? activeTwin : null);
  }, [effectiveTwinId, twins, activeTwin]);
  const chatSource = searchParams.get('source');
  const seededQuestion = searchParams.get('q');
  const canChat = useMemo(() => {
    const status = String(effectiveTwin?.status || '').toLowerCase();
    const settings = (effectiveTwin as { settings?: Record<string, unknown> })?.settings ?? {};
    const autoState = String((settings as Record<string, unknown>).auto_create_state || '').toLowerCase();
    const byStatus = ['active', 'persona_built', 'live', 'draft', 'claims_ready'].includes(status);
    const byAutoState = autoState === 'active';
    const byLegacyFlag = !status && Boolean((effectiveTwin as unknown as Record<string, unknown>)?.is_active);
    return byStatus || byAutoState || byLegacyFlag;
  }, [effectiveTwin]);

  useEffect(() => {
    let cancelled = false;
    async function resolveCanonicalProfile() {
      try {
        const response = await authFetchStandalone('/profile');
        if (!response.ok) return;
        const payload = await response.json() as { id?: string };
        if (!cancelled) {
          setCanonicalProfileId(typeof payload?.id === 'string' ? payload.id : null);
        }
      } catch {
        // silently fail — canonical profile is optional
      }
    }
    void resolveCanonicalProfile();
    return () => { cancelled = true; };
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

  useEffect(() => {
    let cancelled = false;
    async function loadProfileQuestions() {
      if (!effectiveTwinId || chatSource !== 'profile') {
        setProfileQuestions([]);
        return;
      }
      try {
        const response = await authFetchStandalone(API_ENDPOINTS.TWIN_PROFILE_INSIGHTS(effectiveTwinId));
        if (!response.ok) throw new Error(`${response.status}`);
        const payload = await response.json() as { question_suggestions?: unknown[] };
        const suggested = Array.isArray(payload?.question_suggestions)
          ? payload.question_suggestions
              .map((q) => (typeof q === 'string' ? q.trim() : ''))
              .filter((q) => q.length > 0)
          : [];
        const withSeed: string[] = seededQuestion?.trim()
          ? [seededQuestion.trim(), ...suggested]
          : suggested;
        const deduped = Array.from(new Set(withSeed)).slice(0, 12);
        if (!cancelled) setProfileQuestions(deduped);
      } catch {
        if (!cancelled) {
          setProfileQuestions(seededQuestion?.trim() ? [seededQuestion.trim()] : []);
        }
      }
    }
    void loadProfileQuestions();
    return () => { cancelled = true; };
  }, [effectiveTwinId, chatSource, seededQuestion]);

  // ── Loading ──────────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div
        className="flex h-[calc(100vh-88px)] items-center justify-center rounded-3xl"
        style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
      >
        <div
          className="w-8 h-8 rounded-full border-2 border-t-transparent animate-spin"
          style={{ borderColor: 'var(--brand-primary)', borderTopColor: 'transparent' }}
        />
      </div>
    );
  }

  // ── No twin ──────────────────────────────────────────────────────────────
  if (!effectiveTwinId) {
    return (
      <div
        className="flex h-[calc(100vh-88px)] items-center justify-center rounded-3xl"
        style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
      >
        <div className="text-center max-w-sm px-8">
          <h2 className="text-lg font-bold mb-2" style={{ color: 'var(--text-primary)' }}>
            No persona selected
          </h2>
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
            Select a persona to start chatting.
          </p>
        </div>
      </div>
    );
  }

  // ── Not ready ────────────────────────────────────────────────────────────
  if (!canChat) {
    return (
      <div
        className="flex h-[calc(100vh-88px)] items-center justify-center rounded-3xl"
        style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
      >
        <div className="text-center max-w-sm px-8">
          <div
            className="w-12 h-12 rounded-2xl flex items-center justify-center mx-auto mb-4"
            style={{ backgroundColor: '#eef5ff' }}
          >
            <svg className="w-6 h-6 text-[#0066cc]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5"
                d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h2 className="text-lg font-bold mb-2" style={{ color: 'var(--text-primary)' }}>
            Still building…
          </h2>
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
            Chat unlocks once research and ingestion complete for this persona.
          </p>
        </div>
      </div>
    );
  }

  // ── Chat ─────────────────────────────────────────────────────────────────
  return (
    <FeatureGate
      enabled={chatEnabled}
      title="Chat Workspace"
      description="Enable NEXT_PUBLIC_FF_DASHBOARD_CHAT to turn on the dashboard chat workspace."
    >
      <motion.div
        className="min-h-[calc(100vh-88px)] overflow-hidden rounded-[2rem] border bg-[#f5f5f7] shadow-[0_24px_80px_rgba(15,23,42,0.08)]"
        style={{
          borderColor: 'rgba(0,0,0,0.08)',
        }}
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: 'easeOut' }}
      >
        <ChatInterface
          twinId={effectiveTwinId}
          tenantId={activeTwin?.tenant_id}
          presetQuestions={profileQuestions}
          initialInput={seededQuestion}
        />
      </motion.div>
    </FeatureGate>
  );
}

function DashboardChatFallback() {
  return (
    <div
      className="flex h-[calc(100vh-88px)] items-center justify-center rounded-3xl"
      style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
    >
      <div
        className="w-8 h-8 rounded-full border-2 border-t-transparent animate-spin"
        style={{ borderColor: 'var(--brand-primary)', borderTopColor: 'transparent' }}
      />
    </div>
  );
}

export default function DashboardChatPage() {
  return (
    <Suspense fallback={<DashboardChatFallback />}>
      <DashboardChatPageContent />
    </Suspense>
  );
}
