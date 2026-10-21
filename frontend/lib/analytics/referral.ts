'use client';

// Referral attribution for the persona-page viral loop ("Build yours free").
// The ref (persona handle) is stored at CTA click / login-page landing and
// consumed once the user is identified in PostHog, surviving the OAuth
// redirect round-trip. 30-day last-touch window.

const STORAGE_KEY = 'personaon_ref';
const WINDOW_MS = 30 * 24 * 60 * 60 * 1000;

interface StoredReferral {
  ref: string;
  source: string;
  ts: number;
}

export function storeReferral(ref: string, source: string): void {
  if (typeof window === 'undefined') return;
  const clean = ref.trim().slice(0, 120);
  if (!clean) return;
  try {
    const payload: StoredReferral = { ref: clean, source, ts: Date.now() };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // Storage unavailable (private mode) — attribution is best-effort.
  }
}

export function consumeReferral(): StoredReferral | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    window.localStorage.removeItem(STORAGE_KEY);
    const parsed = JSON.parse(raw) as StoredReferral;
    if (!parsed?.ref || typeof parsed.ts !== 'number') return null;
    if (Date.now() - parsed.ts > WINDOW_MS) return null;
    return parsed;
  } catch {
    return null;
  }
}
