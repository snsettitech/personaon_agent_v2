'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { resolveApiBaseUrl } from '@/lib/api';

const PROBE_TIMEOUT_MS = 7000;

/** HEAD /health is a pure reachability probe (returns 200 instantly). GET /health
 * runs slow dependency checks that can exceed the timeout on a cold instance and
 * falsely report "offline" while the app is serving traffic. Manual
 * AbortController (not AbortSignal.timeout) for older-browser support. */
async function probeHealth(baseUrl: string): Promise<boolean> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  try {
    const res = await fetch(`${baseUrl}/health`, { method: 'HEAD', signal: controller.signal });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timeout);
  }
}

export function ApiConnectivityBanner() {
  // Resolve at use-time, not module load, so the client localhost branch applies.
  const apiBaseUrl = useMemo(() => resolveApiBaseUrl(), []);
  const [isVisible, setIsVisible] = useState(false);
  const [status, setStatus] = useState<'checking' | 'online' | 'offline'>('checking');
  const [retryCount, setRetryCount] = useState(0);

  const checkConnection = useCallback(async () => {
    const ok = await probeHealth(apiBaseUrl);
    setStatus(ok ? 'online' : 'offline');
    setIsVisible(!ok);
  }, [apiBaseUrl]);

  useEffect(() => {
    void checkConnection();
  }, [checkConnection]);

  // Poll only while offline to avoid constant background pressure on /health.
  useEffect(() => {
    if (status !== 'offline') return;
    const interval = setInterval(() => void checkConnection(), 20000);
    return () => clearInterval(interval);
  }, [status, checkConnection]);

  const handleRetry = async () => {
    setRetryCount((c) => c + 1);
    setStatus('checking');
    const ok = await probeHealth(apiBaseUrl);
    setStatus(ok ? 'online' : 'offline');
    // Recovery hides the banner in place — no full reload (that would wipe an
    // in-progress chat / unsent input / navigation state).
    if (ok) setIsVisible(false);
  };

  const showTechnicalDetails = process.env.NODE_ENV !== 'production';

  if (!isVisible) return null;

  return (
    <div className="fixed left-1/2 top-4 z-[100] w-[min(92vw,760px)] -translate-x-1/2 rounded-[22px] border border-black/10 bg-white/90 px-4 py-3 text-[#1d1d1f] shadow-[0_24px_80px_rgba(15,23,42,0.18)] backdrop-blur-2xl">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 rounded-full bg-amber-100 p-2 text-amber-700">
            <svg className="h-4 w-4 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <div>
            <p className="text-sm font-bold tracking-tight">PersonaOn services are temporarily unreachable.</p>
            <p className="text-xs font-medium text-[#6e6e73]">
              Some dashboard actions may pause while we reconnect
              {showTechnicalDetails ? ` (${apiBaseUrl}, attempt ${retryCount + 1})` : '.'}
            </p>
          </div>
        </div>
        <div className="flex items-center justify-end gap-3">
          <button
            onClick={handleRetry}
            disabled={status === 'checking'}
            className="rounded-full bg-[#0066cc] px-4 py-2 text-sm font-bold text-white shadow-[0_12px_30px_rgba(0,102,204,0.22)] transition hover:bg-[#0057b8] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {status === 'checking' ? 'Retrying...' : 'Retry Connection'}
          </button>
        </div>
      </div>
    </div>
  );
}
