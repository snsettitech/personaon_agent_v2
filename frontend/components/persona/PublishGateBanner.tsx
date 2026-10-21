'use client';

import { useCallback, useEffect, useState } from 'react';

import { Card, CardContent } from '@/components/ui';
import { API_ENDPOINTS } from '@/lib/constants';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';

type PublishGateStatus = {
  passed: boolean;
  reasons: string[];
};

type PublishResult = {
  url: string;
  handle: string | null;
  share_token: string;
};

// Belt-and-suspenders re-check while the gate is failing, in case the fix
// happened somewhere that doesn't refresh this page's twin object (e.g. a
// chat-driven edit). The primary "no refresh needed" path is the effect
// below keyed on `refreshKey`, which the parent bumps after every save.
const POLL_INTERVAL_MS = 15000;

interface PublishGateBannerProps {
  twinId: string | null;
  /** Twin is already live — banner/button both hide once true. */
  isPublished: boolean;
  /** Bump this (e.g. from activeTwin?.updated_at) after any save so the gate
   * re-checks without requiring a page refresh. */
  refreshKey?: string | number | null;
  onPublished: (result: PublishResult) => void;
}

/**
 * Dashboard publish-gate banner + manual Publish button (execution-board 0.6).
 *
 * Reads the real backend gate status from GET /profile/publish-gate —
 * the same content-quality check (modules.share_links.get_publish_gate_status)
 * that POST /profile/publish enforces server-side. This component does not
 * decide publishability itself; it only renders whatever the backend says,
 * so the dashboard can never drift from the actual gate.
 */
export function PublishGateBanner({ twinId, isPublished, refreshKey, onPublished }: PublishGateBannerProps) {
  const [gateStatus, setGateStatus] = useState<PublishGateStatus | null>(null);
  const [isCheckingGate, setIsCheckingGate] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);

  const fetchGateStatus = useCallback(async () => {
    if (!twinId) {
      setGateStatus(null);
      return;
    }
    setIsCheckingGate(true);
    try {
      const res = await authFetchStandalone(API_ENDPOINTS.PROFILE_PUBLISH_GATE);
      if (!res.ok) throw new Error(`Request failed (${res.status})`);
      const data = (await res.json()) as PublishGateStatus;
      setGateStatus(data);
    } catch (error) {
      console.error('[PublishGateBanner] Failed to load gate status:', error);
      setGateStatus(null);
    } finally {
      setIsCheckingGate(false);
    }
  }, [twinId]);

  // Re-fetch on mount, whenever the twin changes, and whenever the parent
  // bumps refreshKey after a save — this is what makes the banner disappear
  // and Publish enable without a page refresh.
  useEffect(() => {
    if (isPublished) return;
    void fetchGateStatus();
  }, [fetchGateStatus, isPublished, refreshKey]);

  useEffect(() => {
    if (isPublished || !gateStatus || gateStatus.passed) return;
    const interval = setInterval(() => void fetchGateStatus(), POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [isPublished, gateStatus, fetchGateStatus]);

  const handlePublish = useCallback(async () => {
    if (!twinId || isPublishing) return;
    setIsPublishing(true);
    setPublishError(null);
    try {
      const res = await authFetchStandalone(API_ENDPOINTS.PROFILE_PUBLISH, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ twin_id: twinId }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null) as { detail?: { reasons?: string[]; message?: string } } | null;
        const reasons = body?.detail?.reasons;
        throw new Error(
          Array.isArray(reasons) && reasons.length > 0 ? reasons.join(' ') : `Publish failed (${res.status})`
        );
      }
      const data = (await res.json()) as PublishResult;
      onPublished(data);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Could not publish. Try again.';
      setPublishError(message);
    } finally {
      setIsPublishing(false);
    }
  }, [twinId, isPublishing, onPublished]);

  if (isPublished) return null;

  const passed = gateStatus?.passed ?? false;
  const showBanner = gateStatus !== null && !passed && gateStatus.reasons.length > 0;

  return (
    <div className="space-y-3">
      {showBanner && (
        <Card className="border-amber-200 bg-amber-50/90">
          <CardContent>
            <p className="text-sm font-bold text-amber-900">Finish your profile to go public</p>
            <ul className="mt-2 list-disc space-y-1 pl-4 text-sm text-amber-800">
              {gateStatus.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => void handlePublish()}
          disabled={!passed || isPublishing || isCheckingGate}
          className="rounded-2xl bg-slate-950 px-6 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isPublishing ? 'Publishing…' : 'Publish'}
        </button>
        {isCheckingGate && gateStatus === null && (
          <span className="text-xs text-slate-400">Checking your profile…</span>
        )}
      </div>
      {publishError && <p className="text-xs text-rose-600">{publishError}</p>}
    </div>
  );
}
