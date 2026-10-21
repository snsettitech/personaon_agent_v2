'use client';

import React from 'react';
import { ToastProvider, SkipNavigation, SkipNavLink } from '@/components/ui';
import { ApiConnectivityBanner } from '@/components/ui/ApiConnectivityBanner';
import { EnvironmentBadge } from '@/components/ui/EnvironmentBadge';
import { DebugPanel } from '@/components/ui/DebugPanel';
import { TwinProvider } from '@/lib/context/TwinContext';
import { ProfileProvider } from '@/lib/context/ProfileContext';
import { ThemeProvider } from '@/lib/context/ThemeContext';
import DashboardShell from '@/components/DashboardShell';
import { PostHogIdentifier } from '@/lib/analytics/PostHogIdentifier';

/**
 * Dashboard Layout
 *
 * Provider hierarchy:
 * - ThemeProvider: dark/light mode
 * - TwinProvider: manages twin state (which twin is active)
 * - ProfileProvider: manages profile/headline data
 * - ToastProvider: notification system
 *
 * DashboardShell owns the sidebar and conditionally renders EmptyStatePage
 * for first-time users with no twins.
 */
export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ThemeProvider>
      <TwinProvider>
        <ProfileProvider>
          <ToastProvider>
            <SkipNavigation>
              <SkipNavLink href="#main-content">Skip to main content</SkipNavLink>
              <SkipNavLink href="#chat-input">Skip to chat</SkipNavLink>
            </SkipNavigation>
            <ApiConnectivityBanner />
            <EnvironmentBadge />
            <DebugPanel />
            <PostHogIdentifier />
            <DashboardShell>{children}</DashboardShell>
          </ToastProvider>
        </ProfileProvider>
      </TwinProvider>
    </ThemeProvider>
  );
}
