'use client';

import React from 'react';

type BadgeVariant = 'success' | 'warning' | 'danger' | 'info' | 'trust' | 'neutral' | 'beta';

interface BadgeProps {
    children: React.ReactNode;
    variant?: BadgeVariant;
    dot?: boolean;
    className?: string;
}

const variantStyles: Record<BadgeVariant, string> = {
    success: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/20',
    warning: 'bg-amber-500/15 text-amber-300 border-amber-500/20',
    danger:  'bg-red-500/15 text-red-400 border-red-500/20',
    info:    'bg-blue-600/15 text-blue-300 border-blue-500/20',
    trust:   'bg-amber-500/20 text-amber-400 border-amber-500/35',
    neutral: 'bg-white/8 text-slate-400 border-white/10',
    beta:    'bg-amber-500/15 text-amber-400 border-amber-500/35 uppercase tracking-wider text-[0.6875rem]',
};

const dotStyles: Record<BadgeVariant, string> = {
    success: 'bg-emerald-400',
    warning: 'bg-amber-400',
    danger:  'bg-red-400',
    info:    'bg-blue-400',
    trust:   'bg-amber-400',
    neutral: 'bg-slate-500',
    beta:    'bg-amber-400',
};

export function Badge({ children, variant = 'neutral', dot = false, className = '' }: BadgeProps) {
    return (
        <span className={`
            inline-flex items-center gap-1.5 px-2.5 py-1
            rounded-full text-xs font-semibold border
            ${variantStyles[variant]} ${className}
        `}>
            {dot && (
                <span className={`w-1.5 h-1.5 rounded-full ${dotStyles[variant]} animate-pulse`} />
            )}
            {children}
        </span>
    );
}
