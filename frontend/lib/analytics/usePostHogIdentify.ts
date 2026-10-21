'use client';

import { useEffect, useRef } from 'react';
import { usePostHog } from 'posthog-js/react';
import { createClient } from '@/lib/supabase/client';
import { consumeReferral } from '@/lib/analytics/referral';

type PostHogClient = NonNullable<ReturnType<typeof usePostHog>>;

// One-shot referral attribution: if a stored ref exists (set when the user
// clicked "Build yours free" on a persona page), attach it to the identified
// person and emit an event. Consumed exactly once; survives OAuth redirects.
function attributeReferral(posthog: PostHogClient, userId: string): void {
  const referral = consumeReferral();
  if (!referral) return;
  posthog.capture('referral_attributed', {
    ref: referral.ref,
    ref_source: referral.source,
    user_id: userId,
  });
  posthog.setPersonProperties({}, {
    referred_by_handle: referral.ref,
    referred_by_source: referral.source,
  });
}

/**
 * Identifies the current Supabase user in PostHog.
 * Call once near the top of your authenticated layout tree.
 *
 * - On sign-in: calls posthog.identify(user_id, { email, name, ... })
 * - On sign-out: calls posthog.reset() to clear the identity
 */
export function usePostHogIdentify(): void {
  const posthog = usePostHog();
  const identifiedRef = useRef<string | null>(null);

  useEffect(() => {
    if (!posthog) return;

    const supabase = createClient();

    // Identify on mount if session exists
    supabase.auth.getSession().then(({ data: { session } }: { data: { session: any } }) => {
      if (session?.user && identifiedRef.current !== session.user.id) {
        const user = session.user;
        posthog.identify(user.id, {
          email: user.email,
          name: user.user_metadata?.full_name ?? user.user_metadata?.name,
          avatar_url: user.user_metadata?.avatar_url,
          provider: user.app_metadata?.provider,
          created_at: user.created_at,
        });
        identifiedRef.current = user.id;
        attributeReferral(posthog, user.id);
      }
    });

    // Listen for auth state changes
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (_event: string, session: any) => {
        if (session?.user && identifiedRef.current !== session.user.id) {
          const user = session.user;
          posthog.identify(user.id, {
            email: user.email,
            name: user.user_metadata?.full_name ?? user.user_metadata?.name,
            avatar_url: user.user_metadata?.avatar_url,
            provider: user.app_metadata?.provider,
            created_at: user.created_at,
          });
          identifiedRef.current = user.id;
          attributeReferral(posthog, user.id);
        } else if (!session?.user && identifiedRef.current) {
          posthog.reset();
          identifiedRef.current = null;
        }
      }
    );

    return () => {
      subscription.unsubscribe();
    };
  }, [posthog]);
}
