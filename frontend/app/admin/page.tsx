'use client';

import { useCallback, useEffect, useState } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { BarList, KpiCard, Sparkline, type SeriesPoint } from './_components/charts';

interface CockpitSummary {
  ops: {
    users: { total: number; new_24h: number; new_7d: number };
    twins: { total: number; active: number };
    conversations: { total: number; new_7d: number };
    leads: { total: number; new_7d: number };
  };
  plans: Record<string, number>;
  revenue: {
    mrr: number;
    active_subscriptions: number;
    scheduled_cancellations: number;
    believer_seats: { sold: number; cap: number };
  };
  engagement: { dau: number | null; mau: number | null };
}

interface FunnelStep {
  step: string;
  event: string;
  count: number;
}
interface Engagement {
  funnel: FunnelStep[] | null;
  weekly_active: SeriesPoint[] | null;
}

const PLAN_COLORS: Record<string, string> = {
  free: '#94a3b8',
  pro: '#6366f1',
  business: '#0ea5e9',
  believer: '#f59e0b',
};

function money(n: number): string {
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

export default function AdminCockpitPage() {
  const [summary, setSummary] = useState<CockpitSummary | null>(null);
  const [signups, setSignups] = useState<SeriesPoint[]>([]);
  const [leads, setLeads] = useState<SeriesPoint[]>([]);
  const [engagement, setEngagement] = useState<Engagement | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, su, le, en] = await Promise.all([
        authFetchStandalone('/admin/cockpit/summary'),
        authFetchStandalone('/admin/cockpit/timeseries?metric=signups&days=30'),
        authFetchStandalone('/admin/cockpit/timeseries?metric=leads&days=30'),
        authFetchStandalone('/admin/cockpit/engagement?days=30'),
      ]);
      if (!s.ok) throw new Error(`Summary failed: ${s.status}`);
      setSummary(await s.json());
      setSignups(su.ok ? await su.json() : []);
      setLeads(le.ok ? await le.json() : []);
      setEngagement(en.ok ? await en.json() : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load cockpit');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return <div className="py-20 text-center text-sm text-slate-500">Loading cockpit…</div>;
  }
  if (error) {
    return <div className="rounded-2xl border border-rose-200 bg-rose-50 p-6 text-sm text-rose-900">{error}</div>;
  }
  if (!summary) return null;

  const { ops, plans, revenue, engagement: eng } = summary;
  const planItems = Object.entries(plans).map(([label, value]) => ({ label, value, color: PLAN_COLORS[label] }));
  const funnelItems = engagement?.funnel?.map((f) => ({ label: f.step, value: f.count, color: '#8b5cf6' })) ?? [];

  return (
    <div className="space-y-8">
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard label="MRR" value={money(revenue.mrr)} sub={`${revenue.active_subscriptions} active subs`} accent="text-indigo-600" />
        <KpiCard label="Total Users" value={ops.users.total} sub={`+${ops.users.new_7d} this week`} />
        <KpiCard
          label="DAU / MAU"
          value={`${eng.dau ?? '—'} / ${eng.mau ?? '—'}`}
          sub={eng.dau == null ? 'PostHog key not set' : 'Active people'}
        />
        <KpiCard label="Leads" value={ops.leads.total} sub={`+${ops.leads.new_7d} this week`} />
        <KpiCard label="Active Personas" value={ops.twins.active} sub={`${ops.twins.total} total`} />
        <KpiCard label="Conversations" value={ops.conversations.total} sub={`+${ops.conversations.new_7d} this week`} />
        <KpiCard label="New Signups (24h)" value={ops.users.new_24h} />
        <KpiCard
          label="Believer Seats"
          value={`${revenue.believer_seats.sold}/${revenue.believer_seats.cap}`}
          sub={`${revenue.scheduled_cancellations} scheduled cancels`}
        />
      </section>

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 lg:col-span-2">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-slate-900">Signups · last 30 days</h2>
            <span className="text-sm text-slate-500">+{ops.users.new_7d} this week</span>
          </div>
          <div className="mt-4">
            <Sparkline data={signups} color="#6366f1" height={120} />
          </div>
        </section>
        <section className="rounded-2xl border border-slate-200 bg-white p-5">
          <h2 className="text-base font-semibold text-slate-900">Plan distribution</h2>
          <div className="mt-4">
            <BarList items={planItems} />
          </div>
        </section>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="rounded-2xl border border-slate-200 bg-white p-5">
          <h2 className="text-base font-semibold text-slate-900">Acquisition funnel · 30 days</h2>
          <div className="mt-4">
            {engagement?.funnel ? (
              <BarList items={funnelItems} />
            ) : (
              <div className="py-6 text-sm text-slate-400">
                PostHog personal key not set — funnel unavailable.
              </div>
            )}
          </div>
        </section>
        <section className="rounded-2xl border border-slate-200 bg-white p-5 lg:col-span-2">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-slate-900">Weekly active users</h2>
            <a href="/admin/users" className="text-sm text-blue-600 hover:underline">
              Manage users →
            </a>
          </div>
          <div className="mt-4">
            {engagement?.weekly_active && engagement.weekly_active.length > 0 ? (
              <Sparkline data={engagement.weekly_active} color="#10b981" height={120} />
            ) : (
              <div className="flex h-[120px] items-center justify-center text-sm text-slate-400">
                PostHog personal key not set — WAU unavailable.
              </div>
            )}
          </div>
        </section>
      </div>

      <section className="rounded-2xl border border-slate-200 bg-white p-5">
        <h2 className="text-base font-semibold text-slate-900">Leads captured · last 30 days</h2>
        <div className="mt-4">
          <Sparkline data={leads} color="#0ea5e9" height={100} />
        </div>
      </section>
    </div>
  );
}
