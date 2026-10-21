'use client';

import React from 'react';

interface SkipNavLinkProps {
    href: string;
    children: React.ReactNode;
}

/**
 * SkipNavigation - Accessibility component for keyboard navigation
 * 
 * Add this to the top of your layout. It provides a hidden link that becomes
 * visible when focused, allowing keyboard users to skip repetitive navigation.
 * 
 * Usage:
 * <SkipNavigation>
 *   <SkipNavLink href="#main-content">Skip to main content</SkipNavLink>
 *   <SkipNavLink href="#chat-input">Skip to chat</SkipNavLink>
 * </SkipNavigation>
 * 
 * Then add id="main-content" or id="chat-input" to your target elements.
 */

export function SkipNavLink({ href, children }: SkipNavLinkProps) {
    return (
        <a
            href={href}
            className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-[100] focus:px-4 focus:py-2 focus:bg-blue-600 focus:text-white focus:rounded-lg focus:shadow-lg focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2 transition-all"
        >
            {children}
        </a>
    );
}

export function SkipNavigation({ children }: { children: React.ReactNode }) {
    return (
        <nav aria-label="Skip navigation" className="sr-only focus-within:not-sr-only">
            {children}
        </nav>
    );
}

/**
 * VisuallyHidden - Hides content visually but keeps it accessible to screen readers
 */
export function VisuallyHidden({ children }: { children: React.ReactNode }) {
    return (
        <span className="sr-only">
            {children}
        </span>
    );
}

export default SkipNavigation;
