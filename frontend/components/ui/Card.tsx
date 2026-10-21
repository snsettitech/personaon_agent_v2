'use client';

import React from 'react';

type CardProps = React.HTMLAttributes<HTMLDivElement> & {
    children: React.ReactNode;
    className?: string;
    hover?: boolean;
    /** @deprecated gradient prop removed — use solid surfaces per TOKENS.md */
    gradient?: boolean;
    /** @deprecated glass prop removed — use overlay-panel for blur over visuals */
    glass?: boolean;
};

export function Card({
    children,
    className = '',
    hover = false,
    // gradient and glass accepted but ignored — solid surfaces only
    gradient: _gradient,
    glass: _glass,
    ...props
}: CardProps) {
    const base = 'rounded-[28px] border border-black/10 bg-white/75 shadow-[0_18px_55px_rgba(0,0,0,0.08)] backdrop-blur-2xl transition-all duration-200';
    const hoverStyles = hover ? 'hover:-translate-y-0.5 hover:shadow-[0_28px_70px_rgba(0,0,0,0.13)]' : '';

    return (
        <div className={`${base} ${hoverStyles} ${className}`} {...props}>
            {children}
        </div>
    );
}

interface CardHeaderProps {
    children: React.ReactNode;
    className?: string;
}

export function CardHeader({ children, className = '' }: CardHeaderProps) {
    return (
        <div className={`px-6 py-4 border-b border-black/10 ${className}`}>
            {children}
        </div>
    );
}

interface CardContentProps {
    children: React.ReactNode;
    className?: string;
}

export function CardContent({ children, className = '' }: CardContentProps) {
    return (
        <div className={`px-6 py-4 ${className}`}>
            {children}
        </div>
    );
}

interface CardFooterProps {
    children: React.ReactNode;
    className?: string;
}

export function CardFooter({ children, className = '' }: CardFooterProps) {
    return (
        <div className={`px-6 py-4 border-t border-black/10 rounded-b-[28px] ${className}`}>
            {children}
        </div>
    );
}
