'use client';

import { useCallback, useEffect, useState } from 'react';
import { authFetchTenant, authFetchTwin } from '@/lib/hooks/useAuthFetch';

export interface ReadinessStatus {
  score: number;
  max: number;
  label: string;
}

export interface PendingStatus {
  to_review: number;
  follow_ups: number;
  visitor_questions: number;
}

export interface HomeStatus {
  readiness: ReadinessStatus | null;
  pending: PendingStatus | null;
  conversationCount: number | null;
  loading: boolean;
}

const EMPTY: HomeStatus = {
  readiness: null,
  pending: null,
  conversationCount: null,
  loading: true,
};

async function safeJson<T>(req: Promise<Response>): Promise<T | null> {
  try {
    const res = await req;
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

/**
 * Fetches the three live "what's happening" reads for the Assistant Home
 * status cards (plan step A3, see plans/home-v1-assistant.md). Each read is
 * independent — one failing leaves the others intact — and a null/zero result
 * means "hide that card", never a fabricated placeholder.
 *
 * Endpoints (owner-/tenant-scoped, enforced by the authFetch helpers):
 *  - readiness     GET /v2/twins/{twinId}/readiness  -> { score, max, label }
 *  - pending       GET /v2/dashboard/pending         -> { data: {...counts} }
 *  - conversations GET /v2/chat/conversations        -> { conversations: [] }
 */
export function useHomeStatus(twinId: string | null | undefined): HomeStatus {
  const [status, setStatus] = useState<HomeStatus>(EMPTY);

  const load = useCallback(async () => {
    const [readiness, pendingEnv, convos] = await Promise.all([
      twinId
        ? safeJson<ReadinessStatus>(authFetchTwin(twinId, '/v2/twins/{twinId}/readiness'))
        : Promise.resolve(null),
      safeJson<{ data?: PendingStatus }>(authFetchTenant('/v2/dashboard/pending')),
      safeJson<{ conversations?: unknown[] }>(authFetchTenant('/v2/chat/conversations?limit=5')),
    ]);

    setStatus({
      readiness: readiness && typeof readiness.score === 'number' ? readiness : null,
      pending: pendingEnv?.data ?? null,
      conversationCount: convos ? (convos.conversations?.length ?? 0) : null,
      loading: false,
    });
  }, [twinId]);

  useEffect(() => {
    void load();
  }, [load]);

  return status;
}
