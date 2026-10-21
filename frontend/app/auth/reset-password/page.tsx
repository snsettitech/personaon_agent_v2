'use client';

import { Suspense, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { getSupabaseClient } from '@/lib/supabase/client';

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const supabase = getSupabaseClient();

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [sessionReady, setSessionReady] = useState(false);
  const [sessionError, setSessionError] = useState('');

  // Supabase sends a PKCE code in the URL for password recovery.
  // Exchange it for a session before allowing the user to set a new password.
  useEffect(() => {
    let cancelled = false;

    async function initSession() {
      const code = searchParams.get('code');

      if (!code) {
        // Older magic-link flow embeds tokens in the hash fragment.
        const hash = typeof window !== 'undefined' ? window.location.hash : '';
        if (hash.includes('access_token')) {
          // Supabase client handles the hash automatically on mount.
          const { data } = await supabase.auth.getSession();
          if (!cancelled) {
            if (data.session) {
              setSessionReady(true);
            } else {
              setSessionError('Your password reset link is invalid or has expired.');
            }
          }
        } else {
          if (!cancelled) setSessionError('Your password reset link is invalid or has expired.');
        }
        return;
      }

      const { data, error } = await supabase.auth.exchangeCodeForSession(code);
      if (!cancelled) {
        if (error || !data.session) {
          setSessionError('Your password reset link is invalid or has expired.');
        } else {
          setSessionReady(true);
        }
      }
    }

    initSession();
    return () => { cancelled = true; };
  }, [searchParams, supabase]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    if (password !== confirm) {
      setError('Passwords do not match.');
      return;
    }

    setLoading(true);
    const { error: updateError } = await supabase.auth.updateUser({ password });
    setLoading(false);

    if (updateError) {
      setError(updateError.message);
    } else {
      setSuccess(true);
      setTimeout(() => router.push('/dashboard'), 2000);
    }
  };

  if (sessionError) {
    return (
      <div className="text-center">
        <div className="w-16 h-16 mx-auto mb-6 rounded-2xl bg-[#FEE2E2] flex items-center justify-center">
          <svg className="w-8 h-8 text-[#DC2626]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
          </svg>
        </div>
        <h1 className="text-2xl font-bold text-[#1d1d1f] mb-2">Link expired</h1>
        <p className="text-[rgba(29,29,31,0.58)] mb-6">{sessionError}</p>
        <Link
          href="/auth/forgot-password"
          className="inline-block py-3 px-6 bg-[var(--signal)] hover:bg-[var(--signal-deep)] text-white font-semibold rounded-full transition-colors text-sm"
        >
          Request a new link
        </Link>
      </div>
    );
  }

  if (!sessionReady) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--signal)] border-t-transparent" />
      </div>
    );
  }

  if (success) {
    return (
      <div className="text-center">
        <div className="w-16 h-16 mx-auto mb-6 rounded-2xl bg-[rgba(0,102,204,0.10)] flex items-center justify-center">
          <svg className="w-8 h-8 text-[var(--signal)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h1 className="text-2xl font-bold text-[#1d1d1f] mb-2">Password updated</h1>
        <p className="text-[rgba(29,29,31,0.58)]">Taking you to the dashboard…</p>
      </div>
    );
  }

  return (
    <div className="w-full max-w-md mx-auto">
      <h1 className="text-center text-3xl font-semibold tracking-[-0.03em] text-[#1d1d1f] mb-2">
        Set a new password
      </h1>
      <p className="text-center text-sm text-[rgba(29,29,31,0.58)] mb-8">
        Choose a strong password for your account.
      </p>

      {error && (
        <div className="mb-5 p-3 bg-[#FEE2E2] border border-[#DC2626]/30 rounded-2xl text-[#DC2626] text-sm text-center">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="password" className="block text-sm font-semibold text-[#1d1d1f] mb-2">
            New password
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="At least 8 characters"
            autoComplete="new-password"
            autoFocus
            className="w-full px-5 py-4 bg-white border border-[rgba(29,29,31,0.10)] rounded-full text-[#1d1d1f] placeholder-[rgba(29,29,31,0.40)] focus:outline-none focus:ring-4 focus:ring-[rgba(0,102,204,0.14)] focus:border-[var(--signal)] transition-all text-base"
          />
        </div>
        <div>
          <label htmlFor="confirm" className="block text-sm font-semibold text-[#1d1d1f] mb-2">
            Confirm password
          </label>
          <input
            id="confirm"
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder="Re-enter your password"
            autoComplete="new-password"
            className="w-full px-5 py-4 bg-white border border-[rgba(29,29,31,0.10)] rounded-full text-[#1d1d1f] placeholder-[rgba(29,29,31,0.40)] focus:outline-none focus:ring-4 focus:ring-[rgba(0,102,204,0.14)] focus:border-[var(--signal)] transition-all text-base"
          />
        </div>
        <button
          type="submit"
          disabled={loading || !password.trim() || !confirm.trim()}
          className="w-full py-4 px-5 bg-[#f0f0f2] text-[rgba(29,29,31,0.58)] enabled:bg-[var(--signal)] enabled:hover:bg-[var(--signal-deep)] enabled:text-white font-semibold rounded-full transition-all duration-150 disabled:cursor-not-allowed cursor-pointer text-base"
        >
          {loading ? 'Saving…' : 'Set new password'}
        </button>
      </form>

      <p className="text-center mt-6 text-sm text-[rgba(29,29,31,0.58)]">
        <Link href="/auth/login" className="text-[var(--signal)] hover:text-[var(--signal-deep)] font-medium">
          ← Back to sign in
        </Link>
      </p>
    </div>
  );
}

function ResetPasswordFallback() {
  return (
    <div className="flex items-center justify-center py-16">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--signal)] border-t-transparent" />
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<ResetPasswordFallback />}>
      <ResetPasswordForm />
    </Suspense>
  );
}
