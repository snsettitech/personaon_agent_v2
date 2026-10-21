import { isRuntimeFeatureEnabled } from '@/lib/features/runtimeFlags';
import { DASHBOARD_NAV } from './config';
import type { DashboardNavGroup, DashboardNavItem } from './types';

type DashboardFeatureFlag = DashboardNavGroup['featureFlag'] | DashboardNavItem['featureFlag'];

export function isDashboardNavVisible(featureFlag?: DashboardFeatureFlag): boolean {
  return !featureFlag || isRuntimeFeatureEnabled(featureFlag);
}

export function matchesDashboardPath(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  if (href === '/dashboard') return pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function isDashboardGroupActive(group: DashboardNavGroup, pathname: string | null): boolean {
  return (
    matchesDashboardPath(pathname, group.href) ||
    group.items.some((item) => matchesDashboardPath(pathname, item.href))
  );
}

export function getVisibleDashboardGroups(): DashboardNavGroup[] {
  return DASHBOARD_NAV
    .filter((group) => isDashboardNavVisible(group.featureFlag))
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => isDashboardNavVisible(item.featureFlag)),
    }));
}

export function getActiveDashboardGroup(
  pathname: string | null,
  groups: DashboardNavGroup[] = getVisibleDashboardGroups(),
): DashboardNavGroup | undefined {
  return groups.find((group) => isDashboardGroupActive(group, pathname));
}
