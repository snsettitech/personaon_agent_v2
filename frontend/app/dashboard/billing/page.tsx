'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { loadStripe } from '@stripe/stripe-js';
import { EmbeddedCheckout, EmbeddedCheckoutProvider } from '@stripe/react-stripe-js';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { API_BASE_URL } from '@/lib/constants';

const stripePromise = loadStripe(process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY!);

type Tier = 'free' | 'pro' | 'believer' | 'business';

interface CurrentPlan {
  tier: Tier;
  status: string;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  trial_kind: 'no_card' | 'card_required' | null;
  trial_ends_at: string | null;
}

interface Usage {
  tier: string;
  messages_used: number;
  messages_cap: number;
  voice_used: number;
  voice_cap: number;
  period_started_at: string | null;
}

interface BelieverSeats {
  sold: number;
  cap: number;
  available: number;
}

function UsageBar({ label, used, cap }: { label: string; used: number; cap: number }) {
  const pct = cap > 0 ? Math.min(100, Math.round((used / cap) * 100)) : 0;
  const over = used > cap;
  const barColor = pct >= 90 ? 'var(--accent-red)' : 'var(--primary-600)';
  const textColor = pct >= 90 ? 'var(--accent-red)' : 'var(--text-muted)';
  return (
    <div>
      <div className="flex justify-between text-sm mb-1.5">
        <span className="font-medium" style={{ color: 'var(--text-secondary)' }}>{label}</span>
        <span className="font-medium" style={{ color: 'var(--text-primary)' }}>
          {used.toLocaleString()} <span className="font-normal" style={{ color: 'var(--text-muted)' }}>of {cap.toLocaleString()} used</span>
          {over && <span className="ml-1" style={{ color: 'var(--accent-red)' }}>(+{(used - cap).toLocaleString()} overage)</span>}
        </span>
      </div>
      <div className="h-1.5 rounded-full overflow-hidden" style={{ backgroundColor: 'var(--bg-surface)' }}>
        <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, backgroundColor: barColor }} />
      </div>
      {pct >= 90 && (
        <p className="text-xs mt-1" style={{ color: textColor }}>
          Running low —{' '}
          <a href="/dashboard/billing" className="underline">upgrade for more →</a>
        </p>
      )}
    </div>
  );
}

const PRO_FEATURES = ['5,000 conversations / month', '30 voice minutes / month', 'Unlimited knowledge sources', 'Widget embed + AI lead capture', 'Share Studio (QR, social, email signature)', 'Insights & analytics', 'Remove PersonaOn branding'] as const;

const FAQS = [
  { q: 'How does the 14-day trial work?', a: 'Start the trial with a card on file — full Pro access for 14 days. Card auto-charges $14.99 on day 14. Cancel anytime in the trial and you owe nothing.' },
  { q: 'What happens when I hit my monthly cap?', a: 'On Free, new visitor messages receive a "come back next month" reply. On Pro, overages are billed at $5 per 1,000 extra messages and $0.20 per voice minute.' },
  { q: 'What happens if I downgrade or cancel?', a: 'Nothing is deleted. Features above your tier are disabled at the end of your billing period. Within 14 days of your first payment, email admin@personaon.com for a full refund.' },
] as const;


export default function BillingPage() {
  const [currentPlan, setCurrentPlan] = useState<CurrentPlan | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [seats, setSeats] = useState<BelieverSeats | null>(null);
  const [checkoutKey, setCheckoutKey] = useState<string | null>(null);
  const [portalLoading, setPortalLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successTier, setSuccessTier] = useState<Tier | null>(null);
  const [annual, setAnnual] = useState(false);
  const searchParams = useSearchParams();
  const router = useRouter();

  useEffect(() => {
    authFetchStandalone('/billing/current')
      .then((r) => r.json())
      .then((d: CurrentPlan) => setCurrentPlan(d))
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load billing status');
      });

    // Public endpoint — no auth required, shows available seat count
    fetch(`${API_BASE_URL}/billing/believer-seats`)
      .then((r) => r.json())
      .then((d: { data: BelieverSeats }) => setSeats(d.data))
      .catch(() => setSeats({ sold: 0, cap: 50, available: 50 }));
  }, []);

  useEffect(() => {
    if (!currentPlan) return;
    authFetchStandalone('/billing/usage')
      .then((r) => r.json())
      .then((d: Usage) => setUsage(d))
      .catch(() => {});
  }, [currentPlan]);

  // Deep-link from /pricing → auto-open Stripe Checkout for the requested plan.
  // Only triggers if user is NOT already paid (prevents accidental re-checkout).
  useEffect(() => {
    const planParam = searchParams.get('plan');
    if (!planParam) return;
    if (!currentPlan) return;          // wait until plan loads
    if (currentPlan.tier !== 'free') {
      // already paid — clean URL and skip
      router.replace('/dashboard/billing');
      return;
    }
    const allowedPlans = ['pro_monthly_v2', 'pro_annual_v2', 'believer_ltd'];
    if (allowedPlans.includes(planParam)) {
      setCheckoutKey(planParam);
      if (planParam === 'pro_annual_v2') setAnnual(true);
    }
    // Clean URL after triggering (keep existing plan state in component)
    router.replace('/dashboard/billing');
  }, [searchParams, currentPlan, router]);

  // Post-payment success polling
  useEffect(() => {
    const sessionId = searchParams.get('session_id');
    if (!sessionId) return;
    let attempts = 0;
    const poll = async () => {
      attempts++;
      try {
        const r = await authFetchStandalone('/billing/current');
        const d: CurrentPlan = await r.json();
        if (d.tier !== 'free' || attempts >= 10) {
          setCurrentPlan(d);
          if (d.tier !== 'free') setSuccessTier(d.tier as Tier);
          else setError('Your upgrade is processing — refresh in a moment to see your new plan.');
          router.replace('/dashboard/billing');
          return;
        }
      } catch {
        if (attempts >= 10) {
          setError('Your upgrade is processing — refresh in a moment to see your new plan.');
          router.replace('/dashboard/billing');  // clean URL even on error
          return;
        }
      }
      if (attempts < 10) setTimeout(poll, 2000);
    };
    poll();
  }, [searchParams, router]);

  const fetchClientSecret = useCallback(async (): Promise<string> => {
    const res = await authFetchStandalone('/billing/checkout', {
      method: 'POST',
      body: JSON.stringify({ lookup_key: checkoutKey }),
    });
    if (!res.ok) {
      const msg = await res.text();
      setError(res.status === 410 ? 'All Believer seats have been claimed.' : msg);
      setCheckoutKey(null);  // collapse checkout UI on error
      throw new Error(msg);
    }
    const data = (await res.json()) as { client_secret: string };
    return data.client_secret;
  }, [checkoutKey]);

  const handlePortal = async () => {
    setPortalLoading(true);
    setError(null);
    try {
      const res = await authFetchStandalone('/billing/portal');
      if (!res.ok) throw new Error(await res.text());
      const data = (await res.json()) as { url: string };
      window.location.href = data.url;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not open billing portal');
    } finally {
      setPortalLoading(false);
    }
  };

  const tier: Tier = currentPlan?.tier ?? 'free';
  const isPaid = tier !== 'free';
  const isBeliever = tier === 'believer';

  const renewalText = currentPlan?.current_period_end
    ? `${currentPlan.cancel_at_period_end ? 'Cancels' : 'Renews'} ${new Date(currentPlan.current_period_end).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`
    : null;

  // Trial banner: show days-left if user is in any trial state.
  // Stripe trialing → trial_kind === 'card_required' OR status === 'trialing' with current_period_end
  // No-card trial → trial_kind === 'no_card' with trial_ends_at
  const trialEndsAt = currentPlan?.trial_kind === 'no_card'
    ? currentPlan?.trial_ends_at
    : (currentPlan?.status === 'trialing' ? currentPlan?.current_period_end : null);
  const trialDaysLeft = trialEndsAt
    ? Math.max(0, Math.ceil((new Date(trialEndsAt).getTime() - Date.now()) / (1000 * 60 * 60 * 24)))
    : null;
  const isTrialNoCard = currentPlan?.trial_kind === 'no_card';

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-3xl font-black tracking-tight text-[var(--text-primary)]">Billing</h1>
        <p className="text-[var(--text-secondary)] mt-1 text-sm">Manage your plan and usage</p>
      </div>

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">{error}</div>
      )}

      {trialDaysLeft !== null && trialDaysLeft >= 0 && (
        <div className="rounded-xl border border-[#0F766E]/30 bg-[#0F766E]/5 px-4 py-3 text-sm">
          <div className="flex items-center justify-between gap-3">
            <span className="text-[#0F766E] font-semibold">
              {trialDaysLeft === 0 ? 'Trial ends today' : `Trial — ${trialDaysLeft} day${trialDaysLeft === 1 ? '' : 's'} left`}
            </span>
            {isTrialNoCard && (
              <button
                onClick={() => setCheckoutKey('pro_monthly_v2')}
                className="rounded-lg bg-[#0F766E] px-3 py-1 text-xs font-semibold text-white hover:bg-[#0D9488]"
              >
                Add card to keep Pro →
              </button>
            )}
          </div>
          <p className="mt-1 text-xs text-[#57534E]">
            {isTrialNoCard
              ? 'Your no-card trial is active. Add a card any time to extend Pro past day 7.'
              : 'Card on file. We\'ll auto-charge $14.99 when the trial ends — cancel anytime before.'}
          </p>
        </div>
      )}

      {/* Hero strip */}
      <div className="flex items-center justify-between py-4 border-b border-[var(--border-subtle)]">
        <div>
          <div className="flex items-center gap-2">
            <span className={`inline-block w-2 h-2 rounded-full ${isPaid ? 'bg-[var(--primary-600)]' : 'bg-[var(--text-muted)]'}`} />
            <span className="text-lg font-bold text-[var(--text-primary)] capitalize">
              {isBeliever ? 'Believer' : tier === 'business' ? 'Business' : tier === 'pro' ? 'Pro' : 'Free'} Plan
            </span>
          </div>
          {renewalText && <p className="text-xs text-[var(--text-muted)] mt-0.5 ml-4">{renewalText}</p>}
        </div>
        {isPaid ? (
          <button
            onClick={handlePortal}
            disabled={portalLoading}
            className="px-4 py-2 text-sm font-medium bg-[var(--bg-surface)] text-[var(--text-primary)] hover:bg-[var(--bg-card-hover)] rounded-xl transition-colors disabled:opacity-50 cursor-pointer"
          >
            {portalLoading ? 'Opening…' : 'Manage subscription'}
          </button>
        ) : (
          <button
            onClick={() => setCheckoutKey(annual ? 'pro_annual_v2' : 'pro_monthly_v2')}
            className="px-4 py-2 text-sm font-semibold bg-[var(--primary-600)] hover:bg-[var(--primary-700)] text-white rounded-xl transition-colors cursor-pointer"
          >
            Upgrade to Pro →
          </button>
        )}
      </div>

      {/* Usage — shown for every tier, including free */}
      {usage && (
        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border-subtle)] shadow-sm p-6 space-y-4">
          <h2 className="text-sm font-semibold text-[var(--text-secondary)] uppercase tracking-wide">Usage this period</h2>
          <UsageBar label="Messages" used={usage.messages_used} cap={usage.messages_cap} />
          {usage.voice_cap > 0 && (
            <UsageBar label="Voice minutes" used={usage.voice_used} cap={usage.voice_cap} />
          )}
        </div>
      )}

      {/* Plan cards — only show if not in checkout */}
      {!checkoutKey && (
        <>
          {/* Monthly/annual toggle */}
          <div className="flex items-center gap-3">
            <span className={`text-sm ${!annual ? 'font-semibold text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}`}>Monthly</span>
            <button
              onClick={() => setAnnual(!annual)}
              aria-label="Toggle annual billing"
              className={`relative w-10 h-5 rounded-full transition-colors cursor-pointer ${annual ? 'bg-[var(--primary-600)]' : 'bg-[var(--border-default)]'}`}
            >
              <span className={`absolute left-0 top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${annual ? 'translate-x-5' : 'translate-x-0.5'}`} />
            </button>
            <span className={`text-sm ${annual ? 'font-semibold text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}`}>
              Annual <span className="text-[var(--primary-600)] font-semibold text-xs">17% off</span>
            </span>
          </div>

          {/* Two plan cards */}
          <div className="grid sm:grid-cols-2 gap-4">
            {/* Left: current plan (subdued) */}
            <div className="bg-[var(--bg-surface)] rounded-2xl border border-[var(--border-subtle)] p-6 flex flex-col gap-3">
              <p className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wide">Your current plan</p>
              <p className="text-2xl font-black text-[var(--text-primary)] capitalize">
                {isBeliever ? 'Believer' : tier === 'pro' ? 'Pro' : 'Free'}
              </p>
              {tier === 'free' && (
                <ul className="space-y-1.5 text-sm text-[var(--text-secondary)]">
                  <li>• 1 persona</li>
                  <li>• 500 messages / month</li>
                  <li>• Public profile</li>
                </ul>
              )}
              {(tier === 'pro' || isBeliever) && (
                <ul className="space-y-1.5 text-sm text-[var(--text-secondary)]">
                  {PRO_FEATURES.map((f) => <li key={f}>• {f}</li>)}
                  {isBeliever && <li>• 20,000 messages (2× Pro)</li>}
                  {isBeliever && <li>• Meeting bot (3 hrs / month)</li>}
                </ul>
              )}
            </div>

            {/* Right: upgrade target */}
            {tier === 'free' && (
              <div className="bg-[var(--bg-card)] rounded-2xl border-2 border-[var(--primary-600)] p-6 flex flex-col gap-3">
                <p className="text-xs font-semibold text-[var(--primary-600)] uppercase tracking-wide">Upgrade to</p>
                <div>
                  <p className="text-2xl font-black text-[var(--text-primary)]">
                    Pro <span className="text-base font-normal text-[var(--text-secondary)]">{annual ? '$12.42' : '$14.99'}/mo</span>
                  </p>
                  {annual && <p className="text-xs text-[var(--primary-600)]">$149 billed annually</p>}
                </div>
                <ul className="space-y-1.5 text-sm text-[var(--text-secondary)] flex-1">
                  {PRO_FEATURES.map((f) => <li key={f}>✓ {f}</li>)}
                </ul>
                <button
                  onClick={() => setCheckoutKey(annual ? 'pro_annual_v2' : 'pro_monthly_v2')}
                  className="w-full py-2.5 bg-[var(--primary-600)] hover:bg-[var(--primary-700)] text-white text-sm font-semibold rounded-xl transition-colors cursor-pointer"
                >
                  Upgrade to Pro
                </button>
              </div>
            )}
          </div>

          {/* Believer LTD — hidden by default; surfaced via ?show_believer=1 only.
              Per launch spec: post-30-day-Pro upsell, not a default marketing surface. */}
          {tier === 'free' && seats && seats.available > 0 && searchParams.get('show_believer') === '1' && (
            <div
              className="rounded-2xl border bg-[var(--bg-card)] p-6 shadow-sm"
              style={{
                borderColor: 'rgba(30, 124, 255, 0.22)',
                boxShadow: '0 18px 48px rgba(15, 23, 42, 0.06)',
              }}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-bold tracking-widest text-[var(--primary-600)] uppercase">Believer</span>
                    <span className="text-xs text-[var(--text-muted)]">· Early supporter · {seats.available} of {seats.cap} seats left</span>
                  </div>
                  <p className="text-xl font-black mt-1 text-[var(--text-primary)]">
                    $999 <span className="text-sm font-normal text-[var(--text-secondary)]">one-time · lifetime Pro</span>
                  </p>
                  <ul className="mt-3 space-y-1.5 text-sm text-[var(--text-secondary)]">
                    <li>• 20,000 messages/month (2× Pro)</li>
                    <li>• Meeting bot (3 hrs/month)</li>
                    <li>• Direct founder access</li>
                    <li>• Quarterly roadmap calls</li>
                    <li>• Grandfathered forever</li>
                  </ul>
                </div>
                <button
                  onClick={() => setCheckoutKey('believer_ltd')}
                  className="shrink-0 px-4 py-2.5 bg-[var(--primary-600)] hover:bg-[var(--primary-700)] text-white text-sm font-bold rounded-xl transition-colors cursor-pointer"
                >
                  Claim a seat
                </button>
              </div>
            </div>
          )}

          {/* FAQ */}
          <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border-subtle)] shadow-sm p-6 space-y-4">
            <h2 className="text-sm font-semibold text-[var(--text-secondary)] uppercase tracking-wide">FAQ</h2>
            {FAQS.map(({ q, a }) => (
              <details key={q} className="group">
                <summary className="cursor-pointer text-sm font-medium text-[var(--text-primary)] list-none flex justify-between items-center">
                  {q}
                  <span className="text-[var(--text-muted)] group-open:rotate-180 transition-transform ml-2 shrink-0">▾</span>
                </summary>
                <p className="text-sm text-[var(--text-secondary)] mt-2 leading-relaxed">{a}</p>
              </details>
            ))}
          </div>
        </>
      )}

      {/* Embedded checkout */}
      {checkoutKey && (
        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border-subtle)] shadow-sm p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-bold text-[var(--text-primary)]">Complete your upgrade</h2>
            <button
              onClick={() => setCheckoutKey(null)}
              className="text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] cursor-pointer"
            >
              ← Back
            </button>
          </div>
          <EmbeddedCheckoutProvider stripe={stripePromise} options={{ fetchClientSecret }}>
            <EmbeddedCheckout />
          </EmbeddedCheckoutProvider>
        </div>
      )}

      {/* Post-payment success modal */}
      {successTier && successTier !== 'free' && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-[var(--bg-card)] rounded-2xl shadow-2xl max-w-sm w-full p-8 text-center">
            <div className="text-5xl mb-3">🎉</div>
            <h2 className="text-2xl font-black text-[var(--text-primary)]">
              You&apos;re on {successTier === 'believer' ? 'Believer' : 'Pro'}
            </h2>
            <p className="text-[var(--text-secondary)] mt-2 text-sm leading-relaxed">
              All premium features are now unlocked. Welcome aboard.
            </p>
            <button
              onClick={() => setSuccessTier(null)}
              className="mt-6 px-6 py-2.5 bg-[var(--primary-600)] hover:bg-[var(--primary-700)] text-white text-sm font-semibold rounded-xl cursor-pointer"
            >
              Start using it
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
