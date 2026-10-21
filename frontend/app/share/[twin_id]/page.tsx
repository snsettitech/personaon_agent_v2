'use client';

import React, { useEffect, useState, useMemo } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { resolveApiBaseUrl } from '@/lib/api';

/**
 * Handle Slug Redirection Page
 * 
 * This page catches /share/[twin_id] URLs and resolves them to the 
 * correct secured /share/[twin_id]/[token] URL.
 */
export default function ShareSlugPage() {
    const params = useParams();
    const router = useRouter();
    const twin_id = params?.twin_id as string;
    const [status, setStatus] = useState<'resolving' | 'error'>('resolving');
    const [error, setError] = useState<string>('');
    const apiBaseUrl = useMemo(() => resolveApiBaseUrl(), []);

    useEffect(() => {
        if (!twin_id) return;

        const resolveHandle = async () => {
            try {
                const response = await fetch(`${apiBaseUrl}/handles/resolve?handle=${encodeURIComponent(twin_id)}`);
                if (!response.ok) {
                    if (response.status === 404) {
                        throw new Error('Twin handle not found.');
                    } else if (response.status === 403) {
                        throw new Error('This twin is not currently available for public sharing.');
                    }
                    throw new Error('Failed to resolve share link.');
                }

                const data = await response.json();
                if (data.twin_id && data.share_token) {
                    router.replace(`/share/${data.twin_id}/${data.share_token}`);
                } else {
                    throw new Error('Invalid resolution data received.');
                }
            } catch (err: any) {
                setStatus('error');
                setError(err.message || 'An unexpected error occurred.');
            }
        };

        resolveHandle();
    }, [twin_id, apiBaseUrl, router]);

    return (
        <div className="min-h-screen bg-slate-900 flex items-center justify-center p-4">
            <div className="max-w-md w-full text-center">
                {status === 'resolving' ? (
                    <div className="space-y-4">
                        <div className="w-12 h-12 border-4 border-blue-500/30 border-t-blue-500 rounded-full animate-spin mx-auto"></div>
                        <p className="text-slate-400 font-medium">Connecting to persona...</p>
                    </div>
                ) : (
                    <div className="bg-white/5 border border-white/10 rounded-3xl p-8 backdrop-blur-xl">
                        <div className="w-16 h-16 bg-red-500/20 rounded-2xl flex items-center justify-center mx-auto mb-6">
                            <svg className="w-8 h-8 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                            </svg>
                        </div>
                        <h1 className="text-xl font-bold text-white mb-2">Unable to load persona</h1>
                        <p className="text-slate-400 text-sm mb-6">{error}</p>
                        <button
                            onClick={() => window.location.reload()}
                            className="px-6 py-2 bg-white/10 hover:bg-white/20 text-white rounded-xl transition-all"
                        >
                            Try Again
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}
