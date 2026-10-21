/**
 * Dashboard navigation configuration.
 *
 * Dashboard V2 is organized by user jobs, not implementation folders:
 * build the persona, operate it in chat/meetings, publish it, and control scope.
 */

import type { DashboardNavConfig, SidebarConfig } from './types';

export const DASHBOARD_NAV: DashboardNavConfig = [
    {
        id: 'home',
        label: 'Home',
        shortLabel: 'Home',
        href: '/dashboard',
        icon: 'home',
        mobile: true,
        items: [],
    },
    {
        id: 'build',
        label: 'Build',
        shortLabel: 'Build',
        href: '/dashboard/knowledge',
        icon: 'build',
        mobile: true,
        items: [
            { id: 'profile', label: 'Profile', href: '/dashboard/profile', icon: 'profile' },
            { id: 'knowledge', label: 'Knowledge', href: '/dashboard/knowledge', icon: 'knowledge' },
            { id: 'studio', label: 'Studio', href: '/dashboard/studio', icon: 'studio' },
        ],
    },
    {
        id: 'chat',
        label: 'Chat',
        shortLabel: 'Chat',
        href: '/dashboard/chat',
        icon: 'chat',
        mobile: true,
        items: [
            { id: 'chat-workspace', label: 'Chat', href: '/dashboard/chat', icon: 'chat', featureFlag: 'dashboardChat' },
            { id: 'conversations', label: 'Conversations', href: '/dashboard/conversations', icon: 'conversations' },
            { id: 'queued-questions', label: 'Queued Questions', href: '/dashboard/queued-questions', icon: 'queued' },

        ],
    },
    {
        id: 'meetings',
        label: 'Meetings',
        shortLabel: 'Meet',
        href: '/dashboard/meetings',
        icon: 'meetings',
        mobile: true,
        items: [
            // Bookings is the default tab on /dashboard/meetings (universally
            // available — calendar booking requests land here for approval).
            { id: 'meetings-bookings', label: 'Bookings', href: '/dashboard/meetings?tab=bookings', icon: 'meetings' },
            { id: 'meetings-room', label: 'Meeting Room', href: '/dashboard/meetings?tab=room', icon: 'meetings' },
        ],
    },
    {
        id: 'publish',
        label: 'Publish',
        shortLabel: 'Publish',
        href: '/dashboard/share',
        icon: 'publish',
        mobile: true,
        items: [
            { id: 'share-studio', label: 'Share Studio', href: '/dashboard/widget', icon: 'widget' },
            { id: 'widget-settings', label: 'Widget Settings', href: '/dashboard/widget/settings', icon: 'widget' },
            { id: 'leads', label: 'Leads', href: '/dashboard/widget/leads', icon: 'widget' },
        ],
    },
    {
        id: 'control',
        label: 'Control',
        shortLabel: 'Control',
        href: '/dashboard/insights',
        icon: 'control',
        mobile: false,
        items: [
            { id: 'insights', label: 'Insights', href: '/dashboard/insights', icon: 'insights' },
            { id: 'responses', label: 'Responses', href: '/dashboard/responses', icon: 'responses' },
            { id: 'billing', label: 'Billing', href: '/dashboard/billing', icon: 'billing' },
            { id: 'settings', label: 'Settings', href: '/dashboard/settings', icon: 'settings' },
        ],
    },
];

// Compatibility export for any legacy sidebar consumers during migration.
export const SIDEBAR_CONFIG: SidebarConfig = DASHBOARD_NAV.map((group) => ({
    title: group.id === 'home' ? '' : group.label,
    items: (group.items.length > 0 ? group.items : [group]).map((item) => ({
        name: item.label,
        href: item.href,
        icon: item.icon,
        badge: item.badge,
        requiresCapability: item.requiresCapability,
        featureFlag: item.featureFlag,
    })),
}));

export const APP_NAME = 'PersonaOn';
export const APP_TAGLINE = 'Command Center';
