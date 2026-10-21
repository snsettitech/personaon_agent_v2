'use client';

import React from 'react';
import { PostHogIdentifier } from '@/lib/analytics/PostHogIdentifier';

/**
 * Onboarding Layout
 *
 * Mounts PostHogIdentifier so that new users are identified in PostHog
 * during onboarding — before they reach the dashboard layout.
 * This ensures onboarding events are linked to named user profiles.
 */
export default function OnboardingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      <PostHogIdentifier />
      {children}
    </>
  );
}
