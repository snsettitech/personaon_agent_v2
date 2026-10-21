'use client';

import { createBrowserClient } from '@supabase/ssr';

// Browser Supabase client — for use in Client Components only.
// Reads env vars at runtime (no hardcoded fallbacks — set in .env.local or Cloud Run).
let _client: ReturnType<typeof createBrowserClient> | null = null;

export function createClient() {
  if (_client) return _client;

  // SSR guard — createBrowserClient needs window/document
  if (typeof window === 'undefined') {
    // Return a stub during SSR that won't crash on .auth access
    return { auth: { getSession: async () => ({ data: { session: null } }), onAuthStateChange: () => ({ data: { subscription: { unsubscribe: () => {} } } }), signOut: async () => ({}) } } as any;
  }

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || 'http://127.0.0.1:54321';
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || '';

  try {
    _client = createBrowserClient(url, key);
  } catch (err) {
    console.error('[Supabase] createBrowserClient failed:', err);
    return { auth: { getSession: async () => ({ data: { session: null } }), onAuthStateChange: () => ({ data: { subscription: { unsubscribe: () => {} } } }), signOut: async () => ({}) } } as any;
  }
  return _client;
}

// Alias for backwards compatibility with existing pages
export const getSupabaseClient = createClient;
