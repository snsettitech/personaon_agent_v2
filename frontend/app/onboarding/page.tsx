'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { ArrowRight, CheckCircle2, Copy, Globe2, Loader2, Sparkles, X } from 'lucide-react';
import { Suspense, useEffect, useMemo, useState } from 'react';

import { PUBLIC_SITE_URL } from '@/lib/constants';
import { analytics } from '@/lib/analytics/events';
import {
  createOnboardingPersona,
  sessionInit,
  type CreatePersonaResponse,
} from '@/lib/onboarding';
import { headlineTextError, meaningfulTextError } from '@/lib/validation/textQuality';

interface PersonaFormState {
  full_name: string;
  headline: string;
  short_intro: string;
  linkedin_url: string;
  website_url: string;
  avatar_url: string;
}

type Stage = 'loading' | 'form' | 'creating' | 'ready';

const emptyForm: PersonaFormState = {
  full_name: '',
  headline: '',
  short_intro: '',
  linkedin_url: '',
  website_url: '',
  avatar_url: '',
};

function absolutePublicUrl(path: string): string {
  const base = PUBLIC_SITE_URL.replace(/\/$/, '');
  return `${base}${path.startsWith('/') ? path : `/${path}`}`;
}

function characterCount(value: string, max: number): string {
  return `${value.length} / ${max}`;
}

function OnboardingPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [stage, setStage] = useState<Stage>('loading');
  const [form, setForm] = useState<PersonaFormState>(emptyForm);
  const [result, setResult] = useState<CreatePersonaResponse | null>(null);
  const [error, setError] = useState('');
  const [callbackError, setCallbackError] = useState('');

  useEffect(() => {
    const code = searchParams.get('error');
    if (code === 'status_unavailable') {
      setCallbackError(
        "We couldn't reach the onboarding service. Please refresh, or sign in again if this keeps happening.",
      );
    }
  }, [searchParams]);
  const [urlErrors, setUrlErrors] = useState<{ linkedin_url?: string; website_url?: string }>({});
  const [textErrors, setTextErrors] = useState<{ headline?: string; short_intro?: string }>({});
  const [copied, setCopied] = useState(false);

  const publicUrl = useMemo(() => (result ? absolutePublicUrl(result.public_url) : ''), [result]);

  useEffect(() => {
    let cancelled = false;

    async function prepareOnboarding() {
      try {
        const init = await sessionInit();
        if (cancelled) return;

        // Backend is the sole source of truth for consent_required.
        if (init.consent_required) {
          router.replace('/legal/accept?next=/onboarding');
          return;
        }

        if (init.has_persona) {
          router.replace('/dashboard');
          return;
        }

        const emailPrefix = (init.email ?? '').split('@')[0];
        const identity = init.identity;

        setForm({
          full_name: identity.display_name || init.display_name || emailPrefix || '',
          headline: identity.headline || '',
          linkedin_url: identity.profile_url || '',
          avatar_url: identity.image_url || init.avatar_url || '',
          short_intro: '',
          website_url: '',
        });
        setStage('form');
        // Restored after PR #37 silently dropped these — see the "Restore
        // onboarding analytics" work item. auth_provider is the actual
        // Supabase provider (google/linkedin_oidc/email), not
        // identity.provider, which only reflects a verified LinkedIn
        // profile used for form pre-fill and is null for most signups.
        analytics.onboardingStarted({ input_source: init.auth_provider || 'manual' });
        analytics.onboardingStepViewed({ step: 'profile_form', step_index: 0 });
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : 'Unable to start onboarding.';
          if (message === 'Authentication required.') {
            router.replace('/auth/login?redirect=/onboarding');
            return;
          }
          setError(message);
          setStage('form');
        }
      }
    }

    prepareOnboarding();
    return () => {
      cancelled = true;
    };
  }, [router]);

  const updateField = (field: keyof PersonaFormState, value: string) => {
    setForm((current) => ({ ...current, [field]: value }));
    // Clear URL error on edit; revalidate on blur.
    if (field === 'linkedin_url' || field === 'website_url') {
      setUrlErrors((prev) => ({ ...prev, [field]: undefined }));
    }
    if (field === 'headline' || field === 'short_intro') {
      setTextErrors((prev) => ({ ...prev, [field]: undefined }));
    }
  };

  /**
   * Returns the error string for the value (or undefined if valid) AND
   * updates state in the same call. Returning the value synchronously means
   * handleSubmit can decide before React's next render — avoiding the stale-
   * state race where a freshly-pasted invalid URL would still submit because
   * setUrlErrors hadn't flushed yet.
   */
  const validateUrlField = (field: 'linkedin_url' | 'website_url', value: string): string | undefined => {
    const trimmed = value.trim();
    if (!trimmed) {
      setUrlErrors((prev) => ({ ...prev, [field]: undefined }));
      return undefined;
    }
    const candidate = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
    let error: string | undefined;
    try {
      const url = new URL(candidate);
      if (url.protocol !== 'https:' && url.protocol !== 'http:') {
        error = 'Enter a valid URL like https://example.com.';
      } else if (field === 'linkedin_url' && !/(^|\.)linkedin\.com$/i.test(url.hostname)) {
        error = 'Use a linkedin.com profile URL (e.g. https://linkedin.com/in/your-handle).';
      }
    } catch {
      error = 'Enter a valid URL like https://example.com.';
    }
    setUrlErrors((prev) => ({ ...prev, [field]: error }));
    return error;
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');

    if (!form.full_name.trim() || !form.headline.trim()) {
      setError('Add your name and professional headline to create your persona.');
      return;
    }

    // Re-validate URL fields on submit. The validator returns the error
    // synchronously so we can branch on the current value instead of stale
    // urlErrors state (setState is async and would not have flushed yet).
    const linkedinError = validateUrlField('linkedin_url', form.linkedin_url);
    const websiteError = validateUrlField('website_url', form.website_url);
    if (linkedinError || websiteError) {
      setError('Please fix the URL fields highlighted below.');
      return;
    }

    // Reject "nill"-style garbage: too short, single word, all-whitespace,
    // or repeated-character filler (e.g. "asdf asdf asdf"). Mirrors the
    // server-side check in modules/text_quality.py — this is a fail-fast UX
    // nicety, the backend is still the real enforcement boundary.
    const headlineError = headlineTextError(form.headline);
    // short_intro is optional — only validate what the user actually typed.
    const shortIntroError = form.short_intro.trim() ? meaningfulTextError(form.short_intro) : undefined;
    if (headlineError || shortIntroError) {
      setTextErrors({ headline: headlineError ?? undefined, short_intro: shortIntroError ?? undefined });
      setError('Please fix the fields highlighted below.');
      return;
    }

    setStage('creating');
    try {
      const created = await createOnboardingPersona({
        full_name: form.full_name.trim(),
        headline: form.headline.trim(),
        short_intro: form.short_intro.trim() || undefined,
        linkedin_url: form.linkedin_url.trim() || undefined,
        website_url: form.website_url.trim() || undefined,
        avatar_url: form.avatar_url.trim() || undefined,
      });
      setResult(created);
      setStage('ready');
      analytics.onboardingPublished({ twin_id: created.twin_id, handle: created.handle });
      analytics.onboardingStepViewed({ step: 'persona_ready', step_index: 1 });
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create your persona. Please try again.');
      setStage('form');
    }
  };

  const copyPublicLink = async () => {
    if (!publicUrl) return;
    try {
      await navigator.clipboard.writeText(publicUrl);
    } catch {
      const textarea = document.createElement('textarea');
      textarea.value = publicUrl;
      textarea.setAttribute('readonly', '');
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  if (stage === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f5f5f7]">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--signal)] border-t-transparent" />
      </div>
    );
  }

  if (stage === 'creating') {
    return (
      <div className="min-h-screen bg-[#f5f5f7] px-6 py-16">
        <div className="mx-auto max-w-xl rounded-[34px] border border-black/[0.08] bg-white p-10 text-center shadow-[0_24px_80px_rgba(0,0,0,0.08)]">
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-3xl bg-[rgba(0,102,204,0.10)] text-[var(--signal)]">
            <Loader2 className="h-8 w-8 animate-spin" />
          </div>
          <h1 className="mt-8 text-3xl font-semibold tracking-[-0.04em] text-[#1d1d1f]">Setting up your persona</h1>
          <p className="mt-3 text-base leading-7 text-black/58">
            Your profile and public link are being prepared now. We will gather additional information in the background to enhance your persona.
          </p>
        </div>
      </div>
    );
  }

  if (stage === 'ready' && result) {
    const publicViewReady = result.enrichment_status === 'completed';
    return (
      <div className="min-h-screen bg-[#f5f5f7] px-6 py-16">
        <div className="mx-auto max-w-2xl rounded-[34px] border border-black/[0.08] bg-white p-8 shadow-[0_24px_80px_rgba(0,0,0,0.08)] md:p-10">
          <div className="flex h-16 w-16 items-center justify-center rounded-3xl bg-[rgba(0,102,204,0.10)] text-[var(--signal)]">
            <CheckCircle2 className="h-8 w-8" />
          </div>
          <h1 className="mt-8 text-3xl font-semibold tracking-[-0.04em] text-[#1d1d1f]">Your persona is ready</h1>
          <p className="mt-3 text-base leading-7 text-black/58">
            Your persona profile is ready. You can publish and improve it from the dashboard.
          </p>

          <button
            type="button"
            onClick={copyPublicLink}
            className="mt-7 flex w-full items-center justify-between gap-4 rounded-[24px] border border-black/[0.08] bg-[#f5f5f7] px-5 py-4 text-left transition hover:border-[rgba(0,102,204,0.30)]"
          >
            <span className="min-w-0">
              <span className="block text-xs font-semibold uppercase tracking-[0.16em] text-black/40">Public link</span>
              <span className="mt-1 block truncate text-lg font-semibold text-[#1d1d1f]">{publicUrl}</span>
            </span>
            <span className="inline-flex shrink-0 items-center gap-2 rounded-full bg-white px-3 py-1.5 text-xs font-semibold text-[var(--signal)]">
              <Copy className="h-3.5 w-3.5" />
              {copied ? 'Copied' : 'Copy'}
            </span>
          </button>

          <div className="mt-7 flex flex-col gap-3 sm:flex-row">
            <Link
              href="/dashboard"
              className="inline-flex flex-1 items-center justify-center gap-2 rounded-full bg-[var(--signal)] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[var(--signal-deep)]"
            >
              Go to dashboard
              <ArrowRight className="h-4 w-4" />
            </Link>
            {publicViewReady && (
              <Link
                href={result.public_url}
                className="inline-flex flex-1 items-center justify-center gap-2 rounded-full border border-black/[0.10] bg-white px-5 py-3 text-sm font-semibold text-[#1d1d1f] transition hover:bg-[#f5f5f7]"
              >
                <Globe2 className="h-4 w-4" />
                View persona
              </Link>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#f5f5f7] px-6 py-10 md:py-16">
      <div className="mx-auto grid max-w-6xl gap-8 lg:grid-cols-[0.9fr_1.1fr]">
        <section className="rounded-[36px] border border-black/[0.08] bg-[#1d1d1f] p-8 text-white shadow-[0_30px_90px_rgba(0,0,0,0.18)] md:p-10">
          <div className="inline-flex items-center gap-2 rounded-full border border-white/14 bg-white/10 px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.18em] text-white/64">
            <Sparkles className="h-3.5 w-3.5" />
            PersonaOn onboarding
          </div>
          <h1 className="mt-8 text-4xl font-semibold tracking-[-0.05em] text-[#f5f5f7] md:text-6xl">
            Create your persona.
          </h1>
          <p className="mt-5 text-lg leading-8 text-white/68">
            Start with a clear identity. PersonaOn creates your profile first, then enriches it in the background.
          </p>

          <div className="mt-10 space-y-4">
            {[
              ['1', 'Add your basic professional details'],
              ['2', 'PersonaOn reserves your personaon.com/p/handle link'],
              ['3', 'Improve it later with LinkedIn, websites, files, and questions'],
            ].map(([step, label]) => (
              <div key={step} className="flex items-center gap-3 rounded-2xl bg-white/[0.07] px-4 py-3">
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-white text-sm font-semibold text-[#1d1d1f]">{step}</span>
                <span className="text-sm text-white/72">{label}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-[36px] border border-black/[0.08] bg-white p-6 shadow-[0_24px_80px_rgba(0,0,0,0.08)] md:p-8">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-black/38">Required</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-[#1d1d1f]">Tell us who this persona represents</h2>
            <p className="mt-2 text-sm leading-6 text-black/56">You can add more detail after the persona is created.</p>
          </div>

          {callbackError && (
            <div
              role="alert"
              className="mt-6 rounded-2xl border border-[#b42318]/20 bg-[#fff4f2] px-4 py-3 text-sm text-[#b42318]"
            >
              {callbackError}
            </div>
          )}

          <form onSubmit={handleSubmit} className="mt-7 space-y-5">
            {form.avatar_url && (
              <div className="flex items-center gap-3 rounded-2xl border border-black/[0.08] bg-[#f5f5f7] p-3">
                <img
                  src={form.avatar_url}
                  alt="Profile photo preview"
                  className="h-12 w-12 rounded-full object-cover"
                  onError={() => updateField('avatar_url', '')}
                />
                <div className="flex-1 text-sm leading-5 text-black/70">
                  <span className="block font-medium text-[#1d1d1f]">Profile photo</span>
                  <span className="text-xs text-black/50">Pre-filled from your account.</span>
                </div>
                <button
                  type="button"
                  onClick={() => updateField('avatar_url', '')}
                  className="inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-xs font-semibold text-black/60 transition hover:bg-white hover:text-[#1d1d1f]"
                  aria-label="Remove profile photo"
                >
                  <X className="h-3.5 w-3.5" />
                  Remove
                </button>
              </div>
            )}

            <div>
              <label htmlFor="full_name" className="block text-sm font-semibold text-[#1d1d1f]">Full name</label>
              <input
                id="full_name"
                value={form.full_name}
                onChange={(event) => updateField('full_name', event.target.value)}
                maxLength={120}
                required
                placeholder="Sainath Setti"
                className="mt-2 w-full rounded-2xl border border-black/[0.10] bg-white px-4 py-3 text-[#1d1d1f] outline-none transition focus:border-[var(--signal)] focus:ring-4 focus:ring-[rgba(0,102,204,0.10)]"
              />
            </div>

            <div>
              <label htmlFor="headline" className="block text-sm font-semibold text-[#1d1d1f]">Professional headline</label>
              <input
                id="headline"
                value={form.headline}
                onChange={(event) => updateField('headline', event.target.value)}
                maxLength={180}
                required
                placeholder="Founder, consultant, product leader..."
                aria-invalid={!!textErrors.headline}
                aria-describedby={textErrors.headline ? 'headline_error' : undefined}
                className={`mt-2 w-full rounded-2xl border bg-white px-4 py-3 text-[#1d1d1f] outline-none transition focus:ring-4 ${
                  textErrors.headline
                    ? 'border-[#b42318]/40 focus:border-[#b42318] focus:ring-[#b42318]/10'
                    : 'border-black/[0.10] focus:border-[var(--signal)] focus:ring-[rgba(0,102,204,0.10)]'
                }`}
              />
              {textErrors.headline && (
                <p id="headline_error" className="mt-1.5 text-xs text-[#b42318]">{textErrors.headline}</p>
              )}
            </div>

            <div>
              <label htmlFor="short_intro" className="flex items-center justify-between text-sm font-semibold text-[#1d1d1f]">
                <span>Short intro</span>
                <span className="text-xs font-medium text-black/38">{characterCount(form.short_intro, 800)}</span>
              </label>
              <textarea
                id="short_intro"
                value={form.short_intro}
                onChange={(event) => updateField('short_intro', event.target.value)}
                maxLength={800}
                rows={4}
                placeholder="A few sentences about what you do and who you help."
                aria-invalid={!!textErrors.short_intro}
                aria-describedby={textErrors.short_intro ? 'short_intro_error' : undefined}
                className={`mt-2 w-full resize-none rounded-2xl border bg-white px-4 py-3 text-[#1d1d1f] outline-none transition focus:ring-4 ${
                  textErrors.short_intro
                    ? 'border-[#b42318]/40 focus:border-[#b42318] focus:ring-[#b42318]/10'
                    : 'border-black/[0.10] focus:border-[var(--signal)] focus:ring-[rgba(0,102,204,0.10)]'
                }`}
              />
              {textErrors.short_intro && (
                <p id="short_intro_error" className="mt-1.5 text-xs text-[#b42318]">{textErrors.short_intro}</p>
              )}
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label htmlFor="linkedin_url" className="block text-sm font-semibold text-[#1d1d1f]">LinkedIn URL</label>
                <input
                  id="linkedin_url"
                  type="url"
                  inputMode="url"
                  autoComplete="url"
                  value={form.linkedin_url}
                  onChange={(event) => updateField('linkedin_url', event.target.value)}
                  onBlur={(event) => validateUrlField('linkedin_url', event.target.value)}
                  maxLength={500}
                  placeholder="https://linkedin.com/in/..."
                  aria-invalid={!!urlErrors.linkedin_url}
                  aria-describedby={urlErrors.linkedin_url ? 'linkedin_url_error' : undefined}
                  className={`mt-2 w-full rounded-2xl border bg-white px-4 py-3 text-[#1d1d1f] outline-none transition focus:ring-4 ${
                    urlErrors.linkedin_url
                      ? 'border-[#b42318]/40 focus:border-[#b42318] focus:ring-[#b42318]/10'
                      : 'border-black/[0.10] focus:border-[var(--signal)] focus:ring-[rgba(0,102,204,0.10)]'
                  }`}
                />
                {urlErrors.linkedin_url && (
                  <p id="linkedin_url_error" className="mt-1.5 text-xs text-[#b42318]">{urlErrors.linkedin_url}</p>
                )}
              </div>
              <div>
                <label htmlFor="website_url" className="block text-sm font-semibold text-[#1d1d1f]">Website URL</label>
                <input
                  id="website_url"
                  type="url"
                  inputMode="url"
                  autoComplete="url"
                  value={form.website_url}
                  onChange={(event) => updateField('website_url', event.target.value)}
                  onBlur={(event) => validateUrlField('website_url', event.target.value)}
                  maxLength={500}
                  placeholder="https://yourwebsite.com"
                  aria-invalid={!!urlErrors.website_url}
                  aria-describedby={urlErrors.website_url ? 'website_url_error' : undefined}
                  className={`mt-2 w-full rounded-2xl border bg-white px-4 py-3 text-[#1d1d1f] outline-none transition focus:ring-4 ${
                    urlErrors.website_url
                      ? 'border-[#b42318]/40 focus:border-[#b42318] focus:ring-[#b42318]/10'
                      : 'border-black/[0.10] focus:border-[var(--signal)] focus:ring-[rgba(0,102,204,0.10)]'
                  }`}
                />
                {urlErrors.website_url && (
                  <p id="website_url_error" className="mt-1.5 text-xs text-[#b42318]">{urlErrors.website_url}</p>
                )}
              </div>
            </div>

            {error && (
              <div className="rounded-2xl border border-[#b42318]/20 bg-[#fff4f2] px-4 py-3 text-sm text-[#b42318]">
                {error}
              </div>
            )}

            <button
              type="submit"
              className="inline-flex w-full items-center justify-center gap-2 rounded-full bg-[var(--signal)] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[var(--signal-deep)]"
            >
              Create persona
              <ArrowRight className="h-4 w-4" />
            </button>
          </form>
        </section>
      </div>
    </div>
  );
}

export default function OnboardingPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-[#f5f5f7]">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--signal)] border-t-transparent" />
        </div>
      }
    >
      <OnboardingPageContent />
    </Suspense>
  );
}
