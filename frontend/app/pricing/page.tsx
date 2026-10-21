'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import Nav from '@/components/LandingClassy/Nav';
import Footer from '@/components/LandingClassy/Footer';

type Cycle = 'monthly' | 'annual';

const PRO_FEATURES: ReadonlyArray<string> = [
  '5,000 conversations / month',
  '30 voice minutes / month',
  'Unlimited knowledge sources',
  'Widget embed + AI lead capture',
  'Share Studio (QR, social, email signature, LinkedIn)',
  'Public profile page (personaon.com/your-handle)',
  'Calendar booking handoff',
  'Insights & analytics',
  'Remove PersonaOn branding',
] as const;

const FREE_FEATURES: ReadonlyArray<string> = [
  '500 conversations / month',
  'Public profile page',
  'AI lead capture',
  '1 persona',
  'Basic analytics',
] as const;

interface ComparisonRow {
  feature: string;
  free: string | boolean;
  pro: string | boolean;
}

const COMPARISON: ReadonlyArray<ComparisonRow> = [
  { feature: 'Conversations / month', free: '500', pro: '5,000' },
  { feature: 'Voice minutes / month', free: '—', pro: '30' },
  { feature: 'Knowledge sources', free: '5', pro: 'Unlimited' },
  { feature: 'Widget embed', free: false, pro: true },
  { feature: 'AI lead capture', free: true, pro: true },
  { feature: 'Share Studio (QR, social, email)', free: false, pro: true },
  { feature: 'Public profile page', free: true, pro: true },
  { feature: 'Insights & analytics', free: 'Basic', pro: 'Full' },
  { feature: 'Remove branding', free: false, pro: true },
];

const FAQS: ReadonlyArray<{ q: string; a: string }> = [
  {
    q: 'Do I need a card to start the trial?',
    a: 'For the 14-day trial, yes — your card is auto-charged on day 14 unless you cancel. Want to try without a card? Pick the 7-day no-card option on signup.',
  },
  {
    q: 'What happens after the 14-day trial ends?',
    a: 'You\'re automatically charged $14.99 and your Pro features continue. You can cancel anytime during the trial — no charge if you do.',
  },
  {
    q: 'Can I cancel anytime?',
    a: 'Yes. Cancel from your billing page in one click. Your features stay active until the end of the current billing period.',
  },
  {
    q: 'What if I exceed the 5,000 conversation cap?',
    a: 'On Pro you continue uninterrupted — extra messages are billed at $5 per 1,000 above the cap. Voice overage is $0.20 / minute. On Free, new visitor messages get a "come back next month" reply.',
  },
  {
    q: 'Will my data be used to train AI models?',
    a: 'No. Your knowledge stays yours. We use Gemini and ElevenLabs for inference, not training. Full data export and deletion available anytime.',
  },
];

function Check() {
  return (
    <span aria-hidden style={{ color: '#0F766E' }}>✓</span>
  );
}

function Dash() {
  return (
    <span aria-hidden style={{ color: '#A8A29E' }}>—</span>
  );
}

function CellValue({ v }: { v: string | boolean }) {
  if (v === true) return <Check />;
  if (v === false) return <Dash />;
  return <span className="text-[#1C1917]">{v}</span>;
}

// sessionStorage key that survives the onboarding hop. Dashboard reads this on
// mount to honour the original /pricing intent for brand-new users whose
// resolvePostAuthRoute returns /onboarding (which strips the ?redirect= param).
const PRICING_INTENT_KEY = 'personaon:pricing-intent-v1';

function rememberPricingIntent(target: string) {
  try {
    if (typeof window !== 'undefined') {
      window.sessionStorage.setItem(PRICING_INTENT_KEY, target);
    }
  } catch {
    // sessionStorage may be disabled in some contexts — silent fallback to URL param only
  }
}

export default function PricingPage() {
  const [cycle, setCycle] = useState<Cycle>('monthly');
  const proPrice = cycle === 'monthly' ? '$14.99' : '$12.42';
  const proSubtext = cycle === 'monthly' ? '/month' : '/month, billed $149/yr';
  const proLookupKey = cycle === 'monthly' ? 'pro_monthly_v2' : 'pro_annual_v2';
  // Use 'redirect' param — that's what /auth/login and /auth/callback read (not 'next').
  // Also stash the intent in sessionStorage so the dashboard can restore it after
  // the onboarding flow (which strips redirect= for new-without-persona users).
  const proRedirectTarget = `/dashboard/billing?plan=${proLookupKey}`;
  const noCardRedirectTarget = '/dashboard?action=start_trial_no_card';
  const proCtaHref = `/auth/login?redirect=${encodeURIComponent(proRedirectTarget)}`;
  const noCardCtaHref = `/auth/login?redirect=${encodeURIComponent(noCardRedirectTarget)}`;
  const freeCtaHref = '/auth/login';

  return (
    <div style={{ backgroundColor: '#F5F5F7', minHeight: '100vh' }}>
      <Nav />

      {/* Hero */}
      <section className="px-5 pt-32 pb-12 md:px-8 md:pt-40 md:pb-16">
        <div className="mx-auto max-w-[1120px] text-center">
          <h1 className="text-[40px] font-black leading-[1.05] tracking-tight text-[#1C1917] md:text-[56px]">
            Your professional page, always on.
          </h1>
          <p className="mt-4 text-[18px] text-[#57534E] md:text-[20px]">
            Free to start. Upgrade when your persona needs to do more — more conversations, more knowledge, a page that never says come back later.
          </p>

          {/* Cycle toggle */}
          <div className="mt-9 inline-flex items-center gap-3 rounded-full border border-[#E7E5E4] bg-white px-1 py-1">
            <button
              onClick={() => setCycle('monthly')}
              className={`rounded-full px-4 py-1.5 text-sm font-semibold transition-colors ${
                cycle === 'monthly' ? 'bg-[#1C1917] text-white' : 'text-[#57534E]'
              }`}
            >
              Monthly
            </button>
            <button
              onClick={() => setCycle('annual')}
              className={`rounded-full px-4 py-1.5 text-sm font-semibold transition-colors ${
                cycle === 'annual' ? 'bg-[#1C1917] text-white' : 'text-[#57534E]'
              }`}
            >
              Annual <span className="text-[#0F766E]">save 17%</span>
            </button>
          </div>
        </div>
      </section>

      {/* Pricing cards */}
      <section className="px-5 pb-16 md:px-8 md:pb-24">
        <div className="mx-auto grid max-w-[1120px] gap-5 sm:grid-cols-1 md:grid-cols-2">
          {/* Free */}
          <div className="rounded-2xl border border-[#E7E5E4] bg-white p-7 flex flex-col">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-[#A8A29E]">Free</h3>
            <p className="mt-2 text-3xl font-black text-[#1C1917]">$0</p>
            <p className="text-sm text-[#A8A29E]">Forever — no card needed</p>
            <ul className="mt-5 space-y-2 text-sm text-[#57534E] flex-1">
              {FREE_FEATURES.map((f) => (
                <li key={f}>• {f}</li>
              ))}
            </ul>
            <Link
              href={freeCtaHref}
              className="mt-6 block rounded-xl border border-[#E7E5E4] bg-[#F5F0EB] py-2.5 text-center text-sm font-semibold text-[#1C1917] hover:bg-[#E7E5E4] transition-colors"
            >
              Start free
            </Link>
          </div>

          {/* Pro — highlighted */}
          <div className="relative rounded-2xl border-2 border-[#0F766E] bg-white p-7 flex flex-col shadow-lg">
            <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-[#0F766E] px-3 py-1 text-xs font-semibold text-white">
              Most popular
            </span>
            <h3 className="text-sm font-semibold uppercase tracking-wide text-[#0F766E]">Pro</h3>
            <p className="mt-2 text-3xl font-black text-[#1C1917]">
              {proPrice}
              <span className="text-base font-normal text-[#57534E]"> {proSubtext}</span>
            </p>
            <p className="text-sm text-[#0F766E] font-semibold">14-day free trial</p>
            <ul className="mt-5 space-y-2 text-sm text-[#57534E] flex-1">
              {PRO_FEATURES.map((f) => (
                <li key={f}>✓ {f}</li>
              ))}
            </ul>
            <Link
              href={proCtaHref}
              onClick={() => rememberPricingIntent(proRedirectTarget)}
              className="mt-6 block rounded-xl bg-[#0F766E] py-2.5 text-center text-sm font-semibold text-white hover:bg-[#0D9488] transition-colors"
            >
              Start 14-day trial
            </Link>
            {cycle === 'monthly' && (
              <Link
                href={noCardCtaHref}
                onClick={() => rememberPricingIntent(noCardRedirectTarget)}
                className="mt-2 block text-center text-xs text-[#A8A29E] underline-offset-2 hover:text-[#57534E] hover:underline"
              >
                Or try 7 days, no card needed →
              </Link>
            )}
          </div>

        </div>
      </section>

      {/* Comparison table */}
      <section className="px-5 py-16 md:px-8 md:py-20">
        <div className="mx-auto max-w-[1120px]">
          <h2 className="text-center text-2xl font-black tracking-tight text-[#1C1917] md:text-3xl">
            What&apos;s in each plan
          </h2>
          <div className="mt-8 overflow-x-auto rounded-2xl border border-[#E7E5E4] bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#E7E5E4] bg-[#F5F0EB]">
                  <th className="px-4 py-3 text-left font-semibold text-[#57534E]">Feature</th>
                  <th className="px-4 py-3 text-center font-semibold text-[#57534E]">Free</th>
                  <th className="px-4 py-3 text-center font-semibold text-[#0F766E]">Pro</th>
                </tr>
              </thead>
              <tbody>
                {COMPARISON.map((row, i) => (
                  <tr
                    key={row.feature}
                    className={i % 2 === 0 ? '' : 'bg-[#FAFAF9]'}
                  >
                    <td className="px-4 py-2.5 text-[#1C1917]">{row.feature}</td>
                    <td className="px-4 py-2.5 text-center"><CellValue v={row.free} /></td>
                    <td className="px-4 py-2.5 text-center"><CellValue v={row.pro} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="px-5 py-16 md:px-8 md:py-20" style={{ backgroundColor: '#FFFFFF' }}>
        <div className="mx-auto max-w-[760px]">
          <h2 className="text-center text-2xl font-black tracking-tight text-[#1C1917] md:text-3xl">
            Questions
          </h2>
          <div className="mt-8 space-y-3">
            {FAQS.map(({ q, a }) => (
              <details key={q} className="group rounded-xl border border-[#E7E5E4] bg-[#F5F5F7] px-5 py-4">
                <summary className="flex cursor-pointer items-center justify-between text-sm font-semibold text-[#1C1917] [&::-webkit-details-marker]:hidden">
                  <span>{q}</span>
                  <span className="text-[#A8A29E] transition-transform group-open:rotate-180">▾</span>
                </summary>
                <p className="mt-3 text-sm leading-relaxed text-[#57534E]">{a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="px-5 py-16 md:px-8 md:py-20" style={{ backgroundColor: '#F5F5F7' }}>
        <div className="mx-auto max-w-[760px] text-center">
          <h2 className="text-2xl font-black tracking-tight text-[#1C1917] md:text-3xl">
            Ready to scale yourself?
          </h2>
          <p className="mt-3 text-[#57534E]">
            Spin up your AI persona today. Cancel anytime. No long-term commitment.
          </p>
          <Link
            href={proCtaHref}
            onClick={() => rememberPricingIntent(proRedirectTarget)}
            className="mt-7 inline-block rounded-xl bg-[#0F766E] px-8 py-3 text-sm font-semibold text-white hover:bg-[#0D9488] transition-colors"
          >
            Start your 14-day trial →
          </Link>
        </div>
      </section>

      <Footer />
    </div>
  );
}
