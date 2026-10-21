'use client';

import { useState } from 'react';
import Link from 'next/link';
import { getSupabaseClient } from '@/lib/supabase/client';

export default function ForgotPasswordPage() {
    const [email, setEmail] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [success, setSuccess] = useState(false);

    const supabase = getSupabaseClient();

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setLoading(true);

        const { error } = await supabase.auth.resetPasswordForEmail(email, {
            redirectTo: `${window.location.origin}/auth/reset-password`,
        });

        if (error) {
            setError(error.message);
        } else {
            setSuccess(true);
        }
        setLoading(false);
    };

    if (success) {
        return (
            <div className="text-center">
                <div className="w-16 h-16 mx-auto mb-6 rounded-2xl bg-[var(--signal)] flex items-center justify-center">
                    <svg className="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                    </svg>
                </div>
                <h1 className="text-2xl font-bold text-[#1d1d1f] mb-2">Check your email</h1>
                <p className="text-[rgba(29,29,31,0.58)] mb-6">
                    We sent a password reset link to <span className="text-[#1d1d1f] font-medium">{email}</span>
                </p>
                <Link
                    href="/auth/login"
                    className="text-[var(--signal)] hover:text-[var(--signal-deep)] text-sm font-medium"
                >
                    ← Back to login
                </Link>
            </div>
        );
    }

    return (
        <div>
            {/* Logo/Brand */}
            <div className="text-center mb-8">
                <div className="w-14 h-14 mx-auto mb-4 rounded-xl bg-[var(--signal)] flex items-center justify-center">
                    <svg className="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                </div>
                <h1 className="text-2xl font-bold text-[#1d1d1f]">Reset your password</h1>
                <p className="text-[rgba(29,29,31,0.58)] mt-1">We&apos;ll send you a reset link</p>
            </div>

            {/* Auth Card */}
            <div className="bg-white border border-[rgba(29,29,31,0.10)] rounded-2xl p-8 shadow-md">
                {error && (
                    <div className="mb-4 p-3 bg-[#FEE2E2] border border-[#DC2626]/30 rounded-xl text-[#DC2626] text-sm">
                        {error}
                    </div>
                )}

                <form onSubmit={handleSubmit}>
                    <div className="space-y-4">
                        <div>
                            <label className="block text-sm font-medium text-[rgba(29,29,31,0.58)] mb-2">
                                Email
                            </label>
                            <input
                                type="email"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                placeholder="you@example.com"
                                required
                                className="w-full px-4 py-3 bg-white border border-[rgba(29,29,31,0.10)] rounded-xl text-[#1d1d1f] placeholder-[rgba(29,29,31,0.40)] focus:outline-none focus:ring-2 focus:ring-[rgba(0,102,204,0.20)] focus:border-[var(--signal)] transition-all"
                            />
                        </div>

                        <button
                            type="submit"
                            disabled={loading}
                            className="w-full py-3 px-4 bg-[var(--signal)] hover:bg-[var(--signal-deep)] text-white font-semibold rounded-xl transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                        >
                            {loading ? (
                                <span className="flex items-center justify-center gap-2">
                                    <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                                    </svg>
                                    Sending...
                                </span>
                            ) : (
                                'Send reset link'
                            )}
                        </button>
                    </div>
                </form>
            </div>

            {/* Back to login */}
            <p className="text-center mt-6 text-[rgba(29,29,31,0.58)]">
                Remember your password?{' '}
                <Link href="/auth/login" className="text-[var(--signal)] hover:text-[var(--signal-deep)] font-medium">
                    Sign in
                </Link>
            </p>
        </div>
    );
}
