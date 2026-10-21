'use client';

/**
 * The unified, phase-aware meeting page is now the DEFAULT and only supported
 * meeting UI. This hook returns `true` for everyone; the legacy layout remains
 * reachable ONLY as a debug/emergency escape hatch via `?meetings_v2=0`
 * (persisted to localStorage) until the legacy code is removed.
 *
 * `?meetings_v2=1` (or clearing the opt-out) returns to the default v2.
 * See docs/product/meetings-spec-and-plan.md.
 */
import { useEffect, useState } from 'react';

const KEY = 'meetings_v2';

export function useMeetingsV2(): boolean {
  // Default ON. SSR + first client paint both render v2 (no hydration flash for
  // the >99% of users who never opted out); the effect only flips for the rare
  // dev who pinned ?meetings_v2=0.
  const [enabled, setEnabled] = useState<boolean>(true);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      const param = new URLSearchParams(window.location.search).get(KEY);
      if (param === '0') localStorage.setItem(KEY, '0');  // opt OUT to legacy
      if (param === '1') localStorage.removeItem(KEY);     // back to default v2
      setEnabled(localStorage.getItem(KEY) !== '0');
    } catch {
      setEnabled(true);
    }
  }, []);

  return enabled;
}
