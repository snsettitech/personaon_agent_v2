'use client';

import { useCallback, useEffect, useState } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';

/**
 * Fetches the pending-booking count for a twin so the sidebar can render a
 * "you have N things to act on" badge over the Meetings icon.
 *
 * Refetches on mount, on twinId change, and on window focus — covers the
 * common case where the owner approves a booking and switches back to the
 * sidebar without needing explicit context plumbing.
 */
export function usePendingBookingCount(twinId: string | null | undefined): number {
  const [count, setCount] = useState(0);

  const fetchCount = useCallback(async () => {
    if (!twinId) {
      setCount(0);
      return;
    }
    try {
      const apiBase = resolveApiBaseUrl();
      const res = await authFetchStandalone(`${apiBase}/v2/calendar/${twinId}/bookings?status=pending`);
      if (!res.ok) {
        // Don't surface network errors as a "0 pending" — keep prior count
        return;
      }
      const data = await res.json() as { bookings?: { status?: string }[]; count?: number };
      const list = data.bookings ?? [];
      const pending = list.filter((b) => b.status === 'pending' || !b.status).length;
      setCount(pending);
    } catch {
      // Same — silent failure, keep last known count
    }
  }, [twinId]);

  useEffect(() => {
    void fetchCount();
  }, [fetchCount]);

  useEffect(() => {
    const onFocus = () => { void fetchCount(); };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [fetchCount]);

  return count;
}
