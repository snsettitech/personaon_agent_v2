'use client';

import React from 'react';

interface SkeletonProps {
    className?: string;
    variant?: 'text' | 'circular' | 'rectangular' | 'rounded';
    width?: string | number;
    height?: string | number;
    animation?: 'pulse' | 'shimmer' | 'none';
}

export function Skeleton({
    className = '',
    variant = 'rectangular',
    width,
    height,
    animation = 'shimmer'
}: SkeletonProps) {
    const baseClasses = 'bg-white/5';

    const variantClasses = {
        text: 'rounded',
        circular: 'rounded-full',
        rectangular: '',
        rounded: 'rounded-xl'
    };

    const animationClasses = {
        pulse: 'animate-pulse',
        shimmer: 'skeleton-shimmer',
        none: ''
    };

    const style: React.CSSProperties = {
        width: width,
        height: height
    };

    return (
        <div
            className={`${baseClasses} ${variantClasses[variant]} ${animationClasses[animation]} ${className}`}
            style={style}
        />
    );
}

// Preset skeleton components for common use cases
export function SkeletonText({ lines = 1, className = '' }: { lines?: number; className?: string }) {
    return (
        <div className={`space-y-2 ${className}`}>
            {Array.from({ length: lines }).map((_, i) => (
                <Skeleton
                    key={i}
                    variant="text"
                    height={16}
                    className={i === lines - 1 ? 'w-3/4' : 'w-full'}
                />
            ))}
        </div>
    );
}

export function SkeletonAvatar({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' | 'xl' }) {
    const sizes = {
        sm: 'w-8 h-8',
        md: 'w-10 h-10',
        lg: 'w-12 h-12',
        xl: 'w-16 h-16'
    };

    return <Skeleton variant="circular" className={sizes[size]} />;
}

export function SkeletonCard({ className = '' }: { className?: string }) {
    return (
        <div className={`bg-white/5 border border-white/10 rounded-2xl p-6 ${className}`}>
            <div className="flex items-start gap-4">
                <SkeletonAvatar size="lg" />
                <div className="flex-1 space-y-3">
                    <Skeleton variant="rounded" height={20} className="w-1/3" />
                    <Skeleton variant="rounded" height={14} className="w-1/2" />
                </div>
            </div>
            <div className="mt-6 space-y-3">
                <Skeleton variant="rounded" height={14} className="w-full" />
                <Skeleton variant="rounded" height={14} className="w-5/6" />
                <Skeleton variant="rounded" height={14} className="w-4/6" />
            </div>
        </div>
    );
}

export function SkeletonTable({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
    return (
        <div className="bg-white/5 border border-white/10 rounded-2xl overflow-hidden">
            {/* Header */}
            <div className="grid gap-4 px-6 py-3 bg-white/5 border-b border-white/10" style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}>
                {Array.from({ length: cols }).map((_, i) => (
                    <Skeleton key={i} variant="rounded" height={12} className="w-20" />
                ))}
            </div>
            {/* Rows */}
            {Array.from({ length: rows }).map((_, rowIdx) => (
                <div
                    key={rowIdx}
                    className="grid gap-4 px-6 py-4 border-b border-white/5 last:border-b-0"
                    style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}
                >
                    {Array.from({ length: cols }).map((_, colIdx) => (
                        <Skeleton
                            key={colIdx}
                            variant="rounded"
                            height={14}
                            className={colIdx === 0 ? 'w-32' : 'w-16'}
                        />
                    ))}
                </div>
            ))}
        </div>
    );
}

export function SkeletonStats({ count = 4 }: { count?: number }) {
    return (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {Array.from({ length: count }).map((_, i) => (
                <div key={i} className="bg-white/5 border border-white/10 rounded-2xl p-5">
                    <Skeleton variant="rounded" height={14} className="w-20 mb-2" />
                    <Skeleton variant="rounded" height={28} className="w-16 mb-1" />
                    <Skeleton variant="rounded" height={12} className="w-24" />
                </div>
            ))}
        </div>
    );
}

export function SkeletonChat({ messages = 4 }: { messages?: number }) {
    return (
        <div className="space-y-4 p-4">
            {Array.from({ length: messages }).map((_, i) => {
                const isUser = i % 2 === 1;
                return (
                    <div key={i} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                        <div className={`flex items-end gap-2 max-w-[70%] ${isUser ? 'flex-row-reverse' : ''}`}>
                            <SkeletonAvatar size="sm" />
                            <Skeleton
                                variant="rounded"
                                className={`${isUser ? 'bg-blue-500/20' : 'bg-white/5'}`}
                                height={isUser ? 40 : 60}
                                width={isUser ? 120 : 200}
                            />
                        </div>
                    </div>
                );
            })}
        </div>
    );
}

export default Skeleton;
