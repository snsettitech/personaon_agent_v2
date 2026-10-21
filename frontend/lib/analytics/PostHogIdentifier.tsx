'use client';

import { usePostHogIdentify } from './usePostHogIdentify';

/**
 * Invisible component that identifies the Supabase user in PostHog.
 * Drop into any authenticated layout.
 */
export function PostHogIdentifier(): null {
  usePostHogIdentify();
  return null;
}
