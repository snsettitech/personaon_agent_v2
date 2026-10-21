'use client';

import Link from 'next/link';
import type React from 'react';
import { usePathname } from 'next/navigation';
import {
  Calendar,
  Home,
  Layers,
  MessageCircle,
  Send,
  type LucideIcon,
} from 'lucide-react';

import { getVisibleDashboardGroups, isDashboardGroupActive } from '@/lib/navigation/utils';
import type { DashboardNavIcon } from '@/lib/navigation/types';

const ICONS: Partial<Record<DashboardNavIcon, LucideIcon>> = {
  home: Home,
  build: Layers,
  chat: MessageCircle,
  meetings: Calendar,
  publish: Send,
};

export default function MobileTabBar(): React.JSX.Element {
  const pathname = usePathname();
  const mobileGroups = getVisibleDashboardGroups().filter((group) => group.mobile);

  return (
    <nav
      className="fixed bottom-3 left-3 right-3 z-50 flex rounded-[28px] border p-1.5 shadow-[0_20px_70px_rgba(0,0,0,0.20)] md:hidden"
      style={{
        background: 'rgba(255,255,255,0.86)',
        borderColor: 'rgba(29,29,31,0.10)',
        backdropFilter: 'saturate(180%) blur(24px)',
        WebkitBackdropFilter: 'saturate(180%) blur(24px)',
      }}
      aria-label="Mobile dashboard navigation"
    >
      {mobileGroups.map((group) => {
        const Icon = ICONS[group.icon] ?? Home;
        const active = isDashboardGroupActive(group, pathname);

        return (
          <Link
            key={group.id}
            href={group.href}
            data-tour-id={`dashboard-nav-${group.id}`}
            aria-label={group.label}
            aria-current={active ? 'page' : undefined}
            className="flex min-w-0 flex-1 flex-col items-center justify-center gap-1 rounded-[22px] px-2 py-2.5 text-[11px] font-semibold transition-all duration-200"
            style={{
              backgroundColor: active ? '#1d1d1f' : 'transparent',
              color: active ? '#ffffff' : 'rgba(29,29,31,0.54)',
            }}
          >
            <Icon className="h-5 w-5" strokeWidth={1.8} />
            <span className="truncate">{group.shortLabel ?? group.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
