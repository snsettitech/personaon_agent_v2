'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { API_BASE_URL, API_ENDPOINTS } from '@/lib/constants';
import { getSupabaseClient } from '@/lib/supabase/client';
import { resolvePostAuthRoute } from '@/lib/onboarding';

interface InvitationInfo {
  email: string;
  role: string;
  expires_at?: string;
}

interface AcceptInvitationSession {
  access_token: string;
  refresh_token: string;
}

interface AcceptInvitationApiResponse {
  status: string;
  token?: string;
  session?: AcceptInvitationSession;
}

export default function AcceptInvitationPage() {
  const params = useParams();
  const router = useRouter();
  const token = params?.token as string;
  const supabase = getSupabaseClient();

  const [invitation, setInvitation] = useState<InvitationInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [accepting, setAccepting] = useState(false);
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState('');

  const validateInvitation = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.AUTH_INVITATION(token)}`);
      if (response.ok) {
        const data = await response.json();
        setInvitation(data);
        setName(data.email.split('@')[0]); // Pre-fill name from email
      } else {
        setError('Invalid or expired invitation link');
      }
    } catch {
      setError('Failed to validate invitation');
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (token) {
      validateInvitation();
    }
  }, [token, validateInvitation]);

  const handleAcceptInvitation = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password.trim()) {
      setError('Password is required');
      return;
    }

    setAccepting(true);
    setError('');

    try {
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.AUTH_ACCEPT_INVITATION}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          token,
          password,
          name: name.trim() || undefined
        })
      });

      if (response.ok) {
        const data: AcceptInvitationApiResponse = await response.json();
        const accessToken = data.session?.access_token || data.token;
        const refreshToken = data.session?.refresh_token;

        if (accessToken && refreshToken) {
          const { error: sessionError } = await supabase.auth.setSession({
            access_token: accessToken,
            refresh_token: refreshToken,
          });
          if (sessionError) {
            setError(sessionError.message || 'Failed to initialize session');
            return;
          }
        }

        // Route through onboarding/consent like any other sign-in.
        const dest = await resolvePostAuthRoute('/dashboard');
        router.push(dest);
        router.refresh();
      } else {
        const errorData = await response.json();
        setError(errorData.detail || 'Failed to accept invitation');
      }
    } catch {
      setError('Failed to accept invitation. Please try again.');
    } finally {
      setAccepting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--signal)] border-t-transparent" />
      </div>
    );
  }

  if (error && !invitation) {
    return (
      <div className="text-center">
        <h2 className="text-xl font-semibold text-[#1d1d1f] mb-2">Invalid Invitation</h2>
        <p className="text-[rgba(29,29,31,0.58)] mb-6">{error}</p>
        <button
          onClick={() => router.push('/')}
          className="py-3 px-6 bg-[var(--signal)] text-white font-semibold rounded-full text-sm hover:bg-[var(--signal-deep)] transition-colors"
        >
          Go Home
        </button>
      </div>
    );
  }

  return (
    <div className="w-full max-w-md mx-auto">
      <h1 className="text-center text-3xl font-semibold tracking-[-0.03em] text-[#1d1d1f] mb-2">Accept Invitation</h1>
      <p className="text-center text-sm text-[rgba(29,29,31,0.58)] mb-8">
        You&apos;ve been invited to join as <strong>{invitation?.role}</strong>
      </p>

      {invitation && (
        <form onSubmit={handleAcceptInvitation} className="space-y-4">
          <div>
            <label className="block text-sm font-semibold text-[#1d1d1f] mb-2">Email</label>
            <input
              type="email"
              value={invitation.email}
              disabled
              className="w-full px-5 py-4 bg-[#f5f5f7] border border-[rgba(29,29,31,0.10)] rounded-full text-[rgba(29,29,31,0.50)] text-base"
            />
          </div>

          <div>
            <label className="block text-sm font-semibold text-[#1d1d1f] mb-2">Name <span className="font-normal text-black/40">(optional)</span></label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-5 py-4 bg-white border border-[rgba(29,29,31,0.10)] rounded-full text-[#1d1d1f] focus:outline-none focus:ring-4 focus:ring-[rgba(0,102,204,0.14)] focus:border-[var(--signal)] transition-all text-base"
            />
          </div>

          <div>
            <label className="block text-sm font-semibold text-[#1d1d1f] mb-2">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="new-password"
              className="w-full px-5 py-4 bg-white border border-[rgba(29,29,31,0.10)] rounded-full text-[#1d1d1f] placeholder-[rgba(29,29,31,0.40)] focus:outline-none focus:ring-4 focus:ring-[rgba(0,102,204,0.14)] focus:border-[var(--signal)] transition-all text-base"
              placeholder="Choose a password"
            />
          </div>

          {error && (
            <div className="p-3 bg-[#FEE2E2] border border-[#DC2626]/30 rounded-2xl text-[#DC2626] text-sm">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={accepting || !password.trim()}
            className="w-full py-4 px-5 bg-[#f0f0f2] text-[rgba(29,29,31,0.58)] enabled:bg-[var(--signal)] enabled:hover:bg-[var(--signal-deep)] enabled:text-white font-semibold rounded-full transition-all duration-150 disabled:cursor-not-allowed cursor-pointer text-base"
          >
            {accepting ? 'Creating account…' : 'Accept invitation'}
          </button>
        </form>
      )}
    </div>
  );
}
