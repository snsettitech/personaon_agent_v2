'use client';

import Link from 'next/link';
import type React from 'react';
import { usePathname } from 'next/navigation';
import {
  BarChart3,
  BookOpen,
  Calendar,
  Code2,
  CreditCard,
  Home,
  Inbox,
  Layers,
  MessageCircle,
  MessageSquare,
  PanelTop,
  Send,
  Settings,
  Share2,
  Shield,
  SlidersHorizontal,
  User,
  Zap,
  type LucideIcon,
} from 'lucide-react';

import { getVisibleDashboardGroups, isDashboardGroupActive } from '@/lib/navigation/utils';
import type { DashboardNavIcon } from '@/lib/navigation/types';
import { useTwin } from '@/lib/context/TwinContext';
import { usePendingBookingCount } from '@/lib/hooks/usePendingBookingCount';

const ICONS: Record<DashboardNavIcon, LucideIcon> = {
  home: Home,
  build: Layers,
  profile: User,
  knowledge: BookOpen,
  studio: SlidersHorizontal,
  chat: MessageCircle,
  conversations: MessageSquare,
  queued: Inbox,
  actions: Zap,
  meetings: Calendar,
  publish: Send,
  share: Share2,
  widget: PanelTop,
  integrations: Code2,
  control: SlidersHorizontal,
  responses: MessageSquare,
  insights: BarChart3,
  privacy: Shield,
  billing: CreditCard,
  settings: Settings,
};

export default function Sidebar(): React.JSX.Element {
  const pathname = usePathname();
  const visibleGroups = getVisibleDashboardGroups();
  const { activeTwin } = useTwin();

  // Pending booking count drives the badge over the Meetings icon — gives
  // the owner a "you have N to act on" signal without having to navigate.
  const pendingBookings = usePendingBookingCount(activeTwin?.id ?? null);

  return (
    <aside
      className="flex h-full w-[92px] shrink-0 flex-col items-center border-r px-3 py-4"
      style={{
        background: '#fafafa',
        borderColor: 'rgba(29,29,31,0.10)',
      }}
      aria-label="Primary dashboard navigation"
    >
      <nav className="flex w-full flex-1 flex-col gap-2">
        {visibleGroups.map((group) => {
          const Icon = ICONS[group.icon];
          const active = isDashboardGroupActive(group, pathname);
          const showBookingBadge = group.id === 'meetings' && pendingBookings > 0;
          const badgeLabel = pendingBookings > 9 ? '9+' : String(pendingBookings);

          return (
            <Link
              key={group.id}
              href={group.href}
              data-tour-id={`dashboard-nav-${group.id}`}
              aria-current={active ? 'page' : undefined}
              aria-label={
                showBookingBadge
                  ? `${group.label} (${pendingBookings} pending booking${pendingBookings === 1 ? '' : 's'})`
                  : undefined
              }
              className="group relative flex h-[68px] w-full flex-col items-center justify-center gap-1.5 rounded-[22px] text-[11px] font-semibold transition-colors duration-200"
              style={{
                backgroundColor: active ? '#1d1d1f' : 'transparent',
                color: active ? '#ffffff' : 'var(--fg-chrome)',
                boxShadow: 'none',
              }}
            >
              <div className="relative">
                <Icon className="h-5 w-5 transition-transform duration-200 group-hover:-translate-y-0.5" strokeWidth={1.8} />
                {showBookingBadge && (
                  <span
                    className={`absolute -right-2 -top-1.5 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-[#0066cc] px-1 text-[10px] font-bold leading-none text-white shadow-sm ring-2 ${
                      active ? 'ring-[#1d1d1f]' : 'ring-white'
                    }`}
                  >
                    {badgeLabel}
                  </span>
                )}
              </div>
              <span>{group.shortLabel ?? group.label}</span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
