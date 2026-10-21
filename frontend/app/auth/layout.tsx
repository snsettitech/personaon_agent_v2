'use client';

import { ReactNode } from 'react';
import { Wordmark } from '@/components/brand/Wordmark';

export default function AuthLayout({ children }: { children: ReactNode }) {
    return (
        <div className="min-h-screen bg-[var(--fog)] flex items-center justify-center relative overflow-hidden">
            {/* Subtle PersonaOn radial background */}
            <div className="absolute inset-0 pointer-events-none">
                <div className="absolute top-1/2 left-1/2 h-[800px] w-[800px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-white blur-3xl opacity-70" />
                <div className="absolute top-0 right-0 h-96 w-96 rounded-full bg-[rgba(0,102,204,0.10)] blur-3xl" />
                <div className="absolute bottom-0 left-0 h-96 w-96 rounded-full bg-[rgba(29,29,31,0.06)] blur-3xl" />
            </div>

            {/* Content */}
            <div className="relative z-10 w-full max-w-md px-6 py-12">
                <div className="mb-10 flex justify-center">
                    <Wordmark href="/" size="md" />
                </div>
                {children}
            </div>

            {/* Footer */}
            <div className="absolute bottom-6 left-0 right-0 text-center">
                <p className="text-[#A8A29E] text-sm">
                    &copy; {new Date().getFullYear()} PersonaOn. All rights reserved.
                </p>
            </div>
        </div>
    );
}
