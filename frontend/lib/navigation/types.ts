/**
 * Navigation Types
 *
 * Single source of truth for dashboard navigation structure types.
 */

import type { RuntimeFeatureFlag } from '@/lib/features/runtimeFlags';

export interface NavItem {
    name: string;
    href: string;
    icon: string;
    badge?: string;
    /** Optional: require a capability to show this item */
    requiresCapability?: string;
    /** Optional runtime feature flag gate */
    featureFlag?: string;
}

export interface NavSection {
    title: string;
    items: NavItem[];
}

export type SidebarConfig = NavSection[];

export type DashboardNavIcon =
    | 'home'
    | 'build'
    | 'profile'
    | 'knowledge'
    | 'studio'
    | 'chat'
    | 'conversations'
    | 'queued'
    | 'actions'
    | 'meetings'
    | 'publish'
    | 'share'
    | 'widget'
    | 'integrations'
    | 'control'
    | 'responses'
    | 'insights'
    | 'privacy'
    | 'billing'
    | 'settings';

export interface DashboardNavItem {
    id: string;
    label: string;
    shortLabel?: string;
    href: string;
    icon: DashboardNavIcon;
    badge?: string;
    requiresCapability?: string;
    featureFlag?: RuntimeFeatureFlag;
    mobile?: boolean;
}

export interface DashboardNavGroup extends DashboardNavItem {
    items: DashboardNavItem[];
}

export type DashboardNavConfig = DashboardNavGroup[];
