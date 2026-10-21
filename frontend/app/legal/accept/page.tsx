'use client';

import { Suspense, useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { CheckCircle2, ShieldCheck } from 'lucide-react';
import { Wordmark } from '@/components/brand/Wordmark';

import {
  acceptOnboardingConsent,
  getOnboardingStatus,
  syncAuthenticatedUser,
  type OnboardingStatus,
} from '@/lib/onboarding';

function safeNext(value: string | null): string {
  return value && /^\/[^/]/.test(value) ? value : '/onboarding';
}

function routeAfterConsent(status: OnboardingStatus, requestedNext: string): string {
  if (status.consent_required) return '/legal/accept';
  if (status.has_persona) return requestedNext !== '/onboarding' ? requestedNext : '/dashboard';
  return '/onboarding';
}

function ConsentPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedNext = useMemo(() => safeNext(searchParams.get('next')), [searchParams]);
  const [checked, setChecked] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;

    async function loadStatus() {
      try {
        await syncAuthenticatedUser();
        const status = await getOnboardingStatus();
        if (cancelled) return;
        if (!status.consent_required || status.consent.accepted) {
          router.replace(routeAfterConsent(status, requestedNext));
          return;
        }
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : 'Unable to load consent status.';
          if (message === 'Authentication required.') {
            router.replace(`/auth/login?redirect=${encodeURIComponent(`/legal/accept?next=${encodeURIComponent(requestedNext)}`)}`);
            return;
          }
          setError(message);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadStatus();
    return () => {
      cancelled = true;
    };
  }, [requestedNext, router]);

  const handleAccept = async () => {
    if (!checked || saving) return;
    setSaving(true);
    setError('');
    try {
      await acceptOnboardingConsent();
      const status = await getOnboardingStatus();
      router.replace(routeAfterConsent(status, requestedNext));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to save consent. Please try again.');
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f5f5f7] px-6">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--signal)] border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#f5f5f7] px-6 py-12">
      <div className="mx-auto max-w-2xl">
        <div className="mb-8 flex justify-center">
          <Wordmark href="/" size="md" />
        </div>
        <div className="rounded-[32px] border border-black/[0.08] bg-white p-8 shadow-[0_24px_80px_rgba(0,0,0,0.08)] md:p-10">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[rgba(0,102,204,0.10)] text-[var(--signal)]">
            <ShieldCheck className="h-7 w-7" />
          </div>
          <h1 className="mt-7 text-3xl font-semibold tracking-[-0.04em] text-[#1d1d1f]">
            Review platform consent
          </h1>
          <p className="mt-3 text-base leading-7 text-black/62">
            Before creating your persona, confirm that PersonaOn can set up your account, store your profile details, and use the information you add to power your persona.
          </p>

          <div className="mt-7 rounded-[24px] border border-black/[0.08] bg-[#f5f5f7] p-5">
            <p className="text-sm font-semibold text-[#1d1d1f]">PersonaOn platform consent</p>
            <p className="mt-2 text-sm leading-6 text-black/58">
              This acceptance is recorded with your account, timestamp, sign-in provider, IP address, and browser details.
            </p>
          </div>

          <label className="mt-6 flex cursor-pointer items-start gap-3 rounded-[22px] border border-black/[0.08] bg-white p-4">
            <input
              type="checkbox"
              checked={checked}
              onChange={(event) => setChecked(event.target.checked)}
              className="mt-1 h-4 w-4 rounded border-black/20 accent-[var(--signal)] focus:ring-[rgba(0,102,204,0.25)]"
            />
            <span>
              <span className="block text-sm font-semibold text-[#1d1d1f]">
                I agree to PersonaOn&apos;s platform consent.
              </span>
              <span className="mt-1 block text-sm leading-6 text-black/52">
                This lets PersonaOn create and operate my digital persona using the information I provide. I have reviewed the{' '}
                <a href="/legal/terms" target="_blank" rel="noreferrer" className="text-[var(--signal)] underline hover:no-underline">Terms of Use</a>
                ,{' '}
                <a href="/legal/privacy" target="_blank" rel="noreferrer" className="text-[var(--signal)] underline hover:no-underline">Privacy Policy</a>
                , and{' '}
                <a href="/legal/biometric-consent" target="_blank" rel="noreferrer" className="text-[var(--signal)] underline hover:no-underline">Biometric Consent</a>
                .
              </span>
            </span>
          </label>

          {error && (
            <div className="mt-5 rounded-2xl border border-[#b42318]/20 bg-[#fff4f2] px-4 py-3 text-sm text-[#b42318]">
              {error}
            </div>
          )}

          <button
            type="button"
            onClick={handleAccept}
            disabled={!checked || saving}
            className="mt-7 inline-flex w-full items-center justify-center gap-2 rounded-full bg-[var(--signal)] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[var(--signal-deep)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <CheckCircle2 className="h-4 w-4" />
            {saving ? 'Saving...' : 'Continue'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function ConsentPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[#f5f5f7]" />}>
      <ConsentPageContent />
    </Suspense>
  );
}
