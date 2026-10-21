'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import {
  LogOut,
  Settings,
} from 'lucide-react';
import React, { useMemo, useState } from 'react';

import { useTwin } from '@/lib/context/TwinContext';
import { formatPersonaDisplayName, formatPersonaRoleOrganization } from '@/lib/branding/personaName';
import { createClient } from '@/lib/supabase/client';
import { Wordmark } from '@/components/brand/Wordmark';
import { getDashboardRouteMeta } from '@/lib/navigation/routeMeta';
import {
  getActiveDashboardGroup,
  getVisibleDashboardGroups,
  matchesDashboardPath,
} from '@/lib/navigation/utils';
import type { DashboardNavGroup, DashboardNavItem } from '@/lib/navigation/types';
import { DashboardPageHeader } from './dashboard/CommandUI';
import { EnrichmentStatusPill } from './ui/EnrichmentStatusPill';
import { Select } from './ui/Select';
import Sidebar from './Sidebar';
import EmptyStatePage from './dashboard/EmptyStatePage';
import MobileTabBar from './MobileTabBar';
import DashboardWalkthrough from './dashboard/DashboardWalkthrough';

function DashboardTopBar(): React.JSX.Element {
  const router = useRouter();
  const { activeTwin, twins, setActiveTwin } = useTwin();
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const settings = (activeTwin?.settings ?? {}) as Record<string, unknown>;
  const descriptor = formatPersonaRoleOrganization(settings);

  const handleLogout = async () => {
    setIsLoggingOut(true);
    try {
      const supabase = createClient();
      await supabase.auth.signOut();
      router.push('/');
    } catch (error) {
      console.error('Logout error:', error);
    } finally {
      setIsLoggingOut(false);
    }
  };

  return (
    <header
      className="flex h-[72px] shrink-0 items-center justify-between border-b px-4 md:px-6 lg:px-8"
      style={{
        background: '#f5f5f7',
        borderColor: 'rgba(29,29,31,0.10)',
      }}
    >
      <div className="flex min-w-0 items-center gap-4">
        <Wordmark href="/dashboard" size="sm" />


        <div className="hidden h-8 w-px bg-black/10 md:block" />

        <div className="min-w-0">
          {twins.length > 1 ? (
            <Select
              ariaLabel="Active persona"
              value={activeTwin?.id ?? ''}
              onValueChange={setActiveTwin}
              options={twins.map((twin) => ({ value: twin.id, label: formatPersonaDisplayName(twin.name) }))}
            />
          ) : (
            <div className="truncate text-sm font-semibold text-[#1d1d1f]">
              {formatPersonaDisplayName(activeTwin?.name)}
            </div>
          )}
          <div className="hidden max-w-[340px] truncate text-xs md:block" style={{ color: 'var(--fg-chrome)' }}>{descriptor}</div>
        </div>
      </div>

      <div className="flex items-center gap-2 md:gap-3">
        <EnrichmentStatusPill />
        <Link
          href="/dashboard/settings"
          className="flex h-10 w-10 items-center justify-center rounded-full border bg-white text-[var(--fg-chrome)] transition hover:text-[#0066cc]"
          style={{ borderColor: 'rgba(29,29,31,0.10)' }}
          aria-label="Dashboard settings"
        >
          <Settings className="h-4.5 w-4.5" />
        </Link>
        <button
          onClick={handleLogout}
          disabled={isLoggingOut}
          className="hidden h-10 items-center gap-2 rounded-full border bg-white px-4 text-sm font-semibold text-[var(--fg-chrome)] transition hover:text-[#0066cc] disabled:opacity-50 sm:flex"
          style={{ borderColor: 'rgba(29,29,31,0.10)' }}
        >
          <LogOut className="h-4 w-4" />
          {isLoggingOut ? 'Signing out' : 'Sign out'}
        </button>
      </div>
    </header>
  );
}

function DashboardSubnav({ activeGroup }: { activeGroup?: DashboardNavGroup }): React.JSX.Element | null {
  if (!activeGroup || activeGroup.items.length === 0) return null;

  return (
    <div
      className="sticky top-0 z-30 border-b px-4 py-3 md:px-6 lg:px-8"
      style={{
        background: '#f5f5f7',
        borderColor: 'rgba(29,29,31,0.10)',
      }}
    >
      <div className="mx-auto flex max-w-[1180px] items-center gap-2 overflow-x-auto">
        <div className="mr-2 hidden items-center text-xs font-semibold uppercase tracking-[0.18em] md:flex" style={{ color: 'var(--fg-chrome)' }}>
          {activeGroup.label}
        </div>
        {activeGroup.items.map((item) => (
          <SubnavLink key={item.id} item={item} />
        ))}
      </div>
    </div>
  );
}

function SubnavLink({ item }: { item: DashboardNavItem }): React.JSX.Element {
  const pathname = usePathname();
  const active = matchesDashboardPath(pathname, item.href);

  return (
    <Link
      href={item.href}
      aria-current={active ? 'page' : undefined}
      className="shrink-0 rounded-full px-4 py-2 text-sm font-semibold transition-colors"
      style={{
        backgroundColor: active ? '#1d1d1f' : '#ffffff',
        border: active ? '1px solid #1d1d1f' : '1px solid rgba(29,29,31,0.10)',
        color: active ? '#ffffff' : 'var(--fg-chrome)',
      }}
    >
      {item.label}
    </Link>
  );
}

function DashboardRouteHeader({ pathname }: { pathname: string | null }): React.JSX.Element | null {
  const meta = getDashboardRouteMeta(pathname);

  if (!meta || meta.showHeader === false) return null;
  const primaryAction = meta.primaryAction?.href === pathname ? undefined : meta.primaryAction;
  const secondaryAction = meta.secondaryAction?.href === pathname ? undefined : meta.secondaryAction;

  return (
    <DashboardPageHeader
      title={meta.title}
      description={meta.description}
      primaryAction={primaryAction}
      secondaryAction={secondaryAction}
      status={meta.status}
    />
  );
}

export default function DashboardShell({
  children,
}: {
  children: React.ReactNode;
}): React.JSX.Element {
  const { twins, isLoading } = useTwin();
  const pathname = usePathname();
  const visibleGroups = useMemo(() => getVisibleDashboardGroups(), []);
  const activeGroup = getActiveDashboardGroup(pathname, visibleGroups);

  // CRITICAL: Gate on !isLoading to prevent empty-state flash for users who have twins
  if (!isLoading && twins.length === 0) {
    return (
      <div className="dashboard-v2 min-h-screen bg-[#f5f5f7] text-[#1d1d1f]">
        <EmptyStatePage />
      </div>
    );
  }

  return (
    <div className="dashboard-v2 h-screen overflow-hidden bg-[#f5f5f7] text-[#1d1d1f]">
      <DashboardTopBar />
      <div className="flex h-[calc(100vh-72px)] overflow-hidden">
        <div className="hidden lg:flex">
          <Sidebar />
        </div>
        <main
          id="main-content"
          role="main"
          className="relative flex-1 overflow-y-auto pb-28 md:pb-8"
        >
          <DashboardSubnav activeGroup={activeGroup} />
          <div className="dashboard-command-page mx-auto max-w-[1180px] px-4 py-6 md:px-6 lg:px-8">
            <DashboardRouteHeader pathname={pathname} />
            <div className="dashboard-command-content">{children}</div>
          </div>
        </main>
      </div>
      <MobileTabBar />
      <DashboardWalkthrough />
    </div>
  );
}
