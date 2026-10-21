'use client';

import { useState, Suspense, useEffect } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { getSupabaseClient } from '@/lib/supabase/client';
import { analytics } from '@/lib/analytics/events';
import { storeReferral } from '@/lib/analytics/referral';
import { OTPVerifyScreen } from '@/components/auth/OTPVerifyScreen';
import { resolvePostAuthRouteWithStatus } from '@/lib/onboarding';

type AuthView = 'form' | 'otp';

function AuthForm() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const rawRedirect = searchParams.get('redirect') || '/dashboard';
    const redirectTo = /^\/[^/]/.test(rawRedirect) ? rawRedirect : '/dashboard';
    const errorFromUrl = searchParams.get('error');
    const refFromUrl = searchParams.get('ref');

    const [view, setView] = useState<AuthView>('form');
    const [email, setEmail] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const supabase = getSupabaseClient();

    useEffect(() => {
        // Persist referral attribution (e.g. arriving from a persona page's
        // "Build yours free" CTA) so it survives the OAuth redirect round-trip.
        if (refFromUrl) {
            storeReferral(refFromUrl, searchParams.get('utm_source') || 'url');
        }
    }, [refFromUrl, searchParams]);

    useEffect(() => {
        // Handle hash fragment errors from OAuth (e.g. #error=server_error)
        if (typeof window !== 'undefined' && window.location.hash) {
            const hashParams = new URLSearchParams(window.location.hash.substring(1));
            const hashError = hashParams.get('error');
            const errorDescription = hashParams.get('error_description');
            if (hashError) {
                const decoded = errorDescription
                    ? decodeURIComponent(errorDescription.replace(/\+/g, ' '))
                    : '';
                const errorMessages: Record<string, string> = {
                    server_error: decoded || 'A server error occurred during sign in.',
                    unexpected_failure: decoded || 'An unexpected error occurred. Please try again.',
                    access_denied: 'Access was denied. Please try again or use a different account.',
                    configuration_error: 'Authentication configuration error. Please contact support.',
                };
                setError(errorMessages[hashError] || decoded || 'Sign in failed. Please try again.');
                window.history.replaceState(null, '', `/auth/login?redirect=${encodeURIComponent(redirectTo)}`);
                if (hashError === 'server_error' || hashError === 'unexpected_failure') {
                    supabase.auth.signOut().catch(() => {});
                }
            }
        }

        if (errorFromUrl) {
            const errorMessages: Record<string, string> = {
                session_exchange_failed: 'Your sign-in link expired or was opened in a different browser. Try again below.',
                callback_error: 'An error occurred during sign in. Please try again.',
                server_error: 'A server error occurred. Please try again.',
                unexpected_failure: 'An unexpected error occurred. Please try again.',
            };
            setError(errorMessages[errorFromUrl] || 'Sign in failed. Please try again.');
            router.replace(`/auth/login?redirect=${encodeURIComponent(redirectTo)}`, { scroll: false });
        }
    }, [errorFromUrl, redirectTo, router, supabase]);

    const handleGoogleLogin = async () => {
        setLoading(true);
        setError('');
        // This page handles both signup and login for every method — we
        // cannot tell which until the OAuth round-trip completes, so both
        // *_started events fire here and the *_completed side (in the OAuth
        // callback route / handleOTPSuccess below) resolves which funnel it
        // belongs to.
        analytics.authLoginAttempted({ method: 'google' });
        analytics.authSignupStarted({ method: 'google' });
        const { error } = await supabase.auth.signInWithOAuth({
            provider: 'google',
            options: {
                redirectTo: `${window.location.origin}/auth/callback?redirect=${encodeURIComponent(redirectTo)}`,
            },
        });
        if (error) {
            analytics.authLoginFailed({ method: 'google', error: error.message });
            analytics.authSignupFailed({ method: 'google', error: error.message });
            setError(error.message);
            setLoading(false);
        }
    };

    const handleLinkedInLogin = async () => {
        setLoading(true);
        setError('');
        analytics.authLoginAttempted({ method: 'linkedin' });
        analytics.authSignupStarted({ method: 'linkedin' });
        const { error } = await supabase.auth.signInWithOAuth({
            provider: 'linkedin_oidc',
            options: {
                redirectTo: `${window.location.origin}/auth/callback?redirect=${encodeURIComponent(redirectTo)}`,
            },
        });
        if (error) {
            analytics.authLoginFailed({ method: 'linkedin', error: error.message });
            analytics.authSignupFailed({ method: 'linkedin', error: error.message });
            setError(error.message);
            setLoading(false);
        }
    };

    // Unified email auth — same flow for new and returning users.
    // shouldCreateUser:true means: if this email has never been seen,
    // a new account is created when they verify the OTP. Returning
    // users are simply signed in. Mirrors Linear/Vercel/Notion.
    const handleEmailContinue = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!email.trim()) return;
        setLoading(true);
        setError('');
        analytics.authLoginAttempted({ method: 'email_otp' });
        analytics.authSignupStarted({ method: 'email_otp' });

        const { error } = await supabase.auth.signInWithOtp({
            email,
            options: { shouldCreateUser: true },
        });

        if (error) {
            analytics.authLoginFailed({ method: 'email_otp', error: error.message });
            analytics.authSignupFailed({ method: 'email_otp', error: error.message });
            setError(error.message);
            setLoading(false);
            return;
        }

        analytics.otpSent({ context: 'login' });
        setLoading(false);
        setView('otp');
    };

    const handleOTPSuccess = async (_session: { access_token: string; user: { id: string; email?: string } }) => {
        // syncStatus comes straight from the backend's sync-user response
        // (created vs. exists) — NOT the resolved route. The route alone is
        // ambiguous: /onboarding is also where a returning user without a
        // finished persona, one who deleted their persona, or the
        // network-failure fallback all land, and the consent-gate branch
        // wraps a genuine new-signup route in /legal/accept?next=..., which
        // doesn't even start with /onboarding. syncStatus === null (sync
        // failed) intentionally falls back to authLoginCompleted rather than
        // guessing signup, since the failure could hit any user.
        const { route, syncStatus } = await resolvePostAuthRouteWithStatus(redirectTo);
        if (syncStatus === 'created') {
            analytics.authSignupCompleted({ method: 'email_otp' });
        } else {
            analytics.authLoginCompleted({ method: 'email_otp' });
        }
        router.push(route);
        router.refresh();
    };

    if (view === 'otp') {
        return (
            <OTPVerifyScreen
                email={email}
                context="login"
                onSuccess={handleOTPSuccess}
                onBack={() => setView('form')}
            />
        );
    }

    return (
        <div className="w-full max-w-md mx-auto">
            <h1 className="text-center text-3xl md:text-4xl font-semibold tracking-[-0.03em] text-[#1d1d1f] mb-10">
                Sign In or Create Your Account
            </h1>

            {error && (
                <div className="mb-5 p-3 bg-[#FEE2E2] border border-[#DC2626]/30 rounded-2xl text-[#DC2626] text-sm text-center">
                    {error}
                </div>
            )}

            <form onSubmit={handleEmailContinue} className="space-y-4">
                <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="email"
                    autoComplete="email"
                    autoFocus
                    className="w-full px-5 py-4 bg-white border border-[rgba(29,29,31,0.10)] rounded-full text-[#1d1d1f] placeholder-[rgba(29,29,31,0.40)] focus:outline-none focus:ring-4 focus:ring-[rgba(0,102,204,0.14)] focus:border-[var(--signal)] transition-all text-base"
                />
                <button
                    type="submit"
                    disabled={loading || !email.trim()}
                    className="w-full py-4 px-5 bg-[#f0f0f2] hover:bg-[#e8e8eb] text-[rgba(29,29,31,0.58)] enabled:bg-[var(--signal)] enabled:hover:bg-[var(--signal-deep)] enabled:text-white font-semibold rounded-full transition-all duration-150 disabled:cursor-not-allowed cursor-pointer text-base"
                >
                    {loading ? 'Sending code…' : 'Continue with Email'}
                </button>
            </form>

            <div className="relative my-7">
                <div className="absolute inset-0 flex items-center">
                    <div className="w-full border-t border-[rgba(29,29,31,0.10)]"></div>
                </div>
                <div className="relative flex justify-center text-sm">
                    <span className="px-3 bg-[#f5f5f7] text-[rgba(29,29,31,0.58)]">or</span>
                </div>
            </div>

            <button
                onClick={handleGoogleLogin}
                disabled={loading}
                className="w-full flex items-center justify-center gap-3 px-5 py-4 bg-[#1d1d1f] hover:bg-[#2a2a2e] text-white font-semibold rounded-full transition-colors duration-150 disabled:opacity-50 cursor-pointer text-base"
            >
                <svg className="w-5 h-5" viewBox="0 0 24 24">
                    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                </svg>
                Continue with Google
            </button>

            <button
                onClick={handleLinkedInLogin}
                disabled={loading}
                className="w-full flex items-center justify-center gap-3 px-5 py-4 mt-3 bg-white hover:bg-[#f5f5f7] text-[#1d1d1f] font-semibold rounded-full border border-[rgba(29,29,31,0.10)] transition-colors duration-150 disabled:opacity-50 cursor-pointer text-base"
            >
                <svg className="w-5 h-5" fill="#0A66C2" viewBox="0 0 24 24">
                    <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
                </svg>
                Continue with LinkedIn
            </button>

            <p className="text-center mt-8 text-xs text-[rgba(29,29,31,0.40)]">
                By continuing, you agree to PersonaOn&apos;s{' '}
                <Link href="/legal/terms" className="underline hover:text-[#1d1d1f] transition-colors">
                    Terms
                </Link>
                {' '}and{' '}
                <Link href="/legal/privacy" className="underline hover:text-[#1d1d1f] transition-colors">
                    Privacy Policy
                </Link>
                .
            </p>
        </div>
    );
}

function AuthFormFallback() {
    return (
        <div className="text-center py-12">
            <div className="w-12 h-12 border-4 border-[var(--signal)] border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
            <p className="text-[rgba(29,29,31,0.58)]">Loading…</p>
        </div>
    );
}

export default function LoginPage() {
    return (
        <Suspense fallback={<AuthFormFallback />}>
            <AuthForm />
        </Suspense>
    );
}
