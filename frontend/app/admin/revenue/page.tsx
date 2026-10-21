'use client';

import { useCallback, useEffect, useState } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { KpiCard } from '../_components/charts';

interface RevenueSummary {
  mrr: number;
  active_subscriptions: number;
  scheduled_cancellations: number;
  believer_seats: { sold: number; cap: number };
  by_tier: Record<string, { count: number; mrr: number }>;
}

interface Sub {
  id: string;
  user_id: string;
  tier: string;
  status: string;
  price_lookup_key: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  created_at: string;
}

function money(n: number): string {
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

export default function AdminRevenuePage() {
  const [summary, setSummary] = useState<RevenueSummary | null>(null);
  const [subs, setSubs] = useState<Sub[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, l] = await Promise.all([
        authFetchStandalone('/admin/revenue/summary'),
        authFetchStandalone('/admin/revenue/subscriptions?limit=200'),
      ]);
      if (!s.ok) throw new Error(`Revenue failed: ${s.status}`);
      setSummary(await s.json());
      setSubs(l.ok ? await l.json() : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load revenue');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return <div className="py-20 text-center text-sm text-slate-500">Loading revenue…</div>;
  }
  if (error) {
    return <div className="rounded-2xl border border-rose-200 bg-rose-50 p-6 text-sm text-rose-900">{error}</div>;
  }
  if (!summary) return null;

  return (
    <div className="space-y-8">
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard label="MRR" value={money(summary.mrr)} accent="text-indigo-600" />
        <KpiCard label="Active subscriptions" value={summary.active_subscriptions} />
        <KpiCard label="Scheduled cancellations" value={summary.scheduled_cancellations} />
        <KpiCard label="Believer seats" value={`${summary.believer_seats.sold}/${summary.believer_seats.cap}`} />
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5">
        <h2 className="text-base font-semibold text-slate-900">MRR by tier</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Object.entries(summary.by_tier).length === 0 ? (
            <div className="text-sm text-slate-500">No active subscriptions</div>
          ) : (
            Object.entries(summary.by_tier).map(([tier, v]) => (
              <div key={tier} className="rounded-xl border border-slate-100 bg-slate-50 p-4">
                <div className="text-sm font-medium capitalize text-slate-700">{tier}</div>
                <div className="mt-1 text-xl font-semibold text-slate-900">{money(v.mrr)}</div>
                <div className="text-xs text-slate-500">{v.count} subs</div>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-5 py-3">
          <h2 className="text-base font-semibold text-slate-900">Subscriptions</h2>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 bg-slate-50 text-left text-slate-600">
              <th className="px-5 py-3 font-medium">Tier</th>
              <th className="px-5 py-3 font-medium">Status</th>
              <th className="px-5 py-3 font-medium">Plan key</th>
              <th className="px-5 py-3 font-medium">Renews</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {subs.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-5 py-10 text-center text-slate-500">
                  No subscriptions
                </td>
              </tr>
            ) : (
              subs.map((s) => (
                <tr key={s.id} className="hover:bg-slate-50">
                  <td className="px-5 py-3 capitalize text-slate-900">{s.tier}</td>
                  <td className="px-5 py-3 text-slate-600">{s.status}</td>
                  <td className="px-5 py-3 text-slate-500">{s.price_lookup_key || '—'}</td>
                  <td className="px-5 py-3 text-slate-500">
                    {s.current_period_end ? new Date(s.current_period_end).toLocaleDateString() : '—'}
                    {s.cancel_at_period_end ? ' (cancels)' : ''}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
