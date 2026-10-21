'use client';

import { useCallback, useEffect, useState } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { KpiCard } from '../_components/charts';

interface Health {
  graph_outbox: { pending: number; processing: number; failed: number; completed_24h: number };
}

interface Job {
  id: string;
  operation: string;
  status: string;
  attempt_count: number;
  max_attempts: number;
  error_message: string | null;
  updated_at: string;
}

interface OpsAlert {
  id: string;
  source: 'gcp_uptime' | 'gcp_billing' | string;
  severity: string;
  title: string;
  detail: unknown;
  created_at: string;
  resolved_at: string | null;
}

export default function AdminOpsPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobsLoadError, setJobsLoadError] = useState(false);
  const [alerts, setAlerts] = useState<OpsAlert[]>([]);
  const [alertsLoadError, setAlertsLoadError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [h, j, a] = await Promise.all([
        authFetchStandalone('/admin/ops/health'),
        authFetchStandalone('/admin/graph-outbox/failed?limit=100'),
        authFetchStandalone('/admin/ops/alerts?limit=50'),
      ]);
      if (!h.ok) throw new Error(`Failed: ${h.status}`);
      setHealth(await h.json());
      setJobs(j.ok ? await j.json() : []);
      setJobsLoadError(!j.ok);
      setAlerts(a.ok ? await a.json() : []);
      setAlertsLoadError(!a.ok);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Load failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const retry = useCallback(
    async (id: string) => {
      setBusy(id);
      setMsg(null);
      try {
        const res = await authFetchStandalone(`/admin/graph-outbox/retry/${id}`, { method: 'POST' });
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        setMsg('Job requeued.');
        await load();
      } catch (err) {
        setMsg(err instanceof Error ? err.message : 'Failed');
      } finally {
        setBusy(null);
      }
    },
    [load]
  );

  if (loading) {
    return <div className="py-20 text-center text-sm text-slate-500">Loading ops…</div>;
  }
  if (error) {
    return <div className="rounded-2xl border border-rose-200 bg-rose-50 p-6 text-sm text-rose-900">{error}</div>;
  }

  return (
    <div className="space-y-6">
      {msg && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{msg}</div>}

      {health && (
        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard label="Pending jobs" value={health.graph_outbox.pending} />
          <KpiCard label="Processing" value={health.graph_outbox.processing} />
          <KpiCard
            label="Failed"
            value={health.graph_outbox.failed}
            accent={health.graph_outbox.failed > 0 ? 'text-rose-600' : 'text-slate-900'}
          />
          <KpiCard label="Completed (24h)" value={health.graph_outbox.completed_24h} accent="text-emerald-600" />
        </section>
      )}

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-5 py-3">
          <h2 className="text-base font-semibold text-slate-900">Failed jobs</h2>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 bg-slate-50 text-left text-slate-600">
              <th className="px-5 py-3 font-medium">Operation</th>
              <th className="px-5 py-3 font-medium">Attempts</th>
              <th className="px-5 py-3 font-medium">Error</th>
              <th className="px-5 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {jobsLoadError ? (
              <tr>
                <td colSpan={4} className="px-5 py-10 text-center text-sm text-rose-700">
                  Could not load failed jobs — the request to /admin/graph-outbox/failed did not
                  succeed. This is not a confirmed healthy state.
                </td>
              </tr>
            ) : jobs.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-5 py-10 text-center text-slate-500">
                  No failed jobs 🎉
                </td>
              </tr>
            ) : (
              jobs.map((j) => (
                <tr key={j.id} className="hover:bg-slate-50">
                  <td className="px-5 py-3 text-slate-900">{j.operation}</td>
                  <td className="px-5 py-3 text-slate-500">
                    {j.attempt_count}/{j.max_attempts}
                  </td>
                  <td className="max-w-md truncate px-5 py-3 text-xs text-slate-500" title={j.error_message || ''}>
                    {j.error_message || '—'}
                  </td>
                  <td className="px-5 py-3 text-right">
                    <button
                      onClick={() => void retry(j.id)}
                      disabled={busy === j.id}
                      className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                    >
                      {busy === j.id ? '…' : 'Retry'}
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </section>

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-5 py-3">
          <h2 className="text-base font-semibold text-slate-900">Infra alerts</h2>
          <p className="mt-0.5 text-xs text-slate-500">GCP Cloud Monitoring uptime + billing alerts routed to this page.</p>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 bg-slate-50 text-left text-slate-600">
              <th className="px-5 py-3 font-medium">Alert</th>
              <th className="px-5 py-3 font-medium">Source</th>
              <th className="px-5 py-3 font-medium">Severity</th>
              <th className="px-5 py-3 font-medium">Created</th>
              <th className="px-5 py-3 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {alertsLoadError ? (
              <tr>
                <td colSpan={5} className="px-5 py-10 text-center text-sm text-rose-700">
                  Could not load infra alerts — the request to /admin/ops/alerts did not succeed.
                  This is not a confirmed healthy state.
                </td>
              </tr>
            ) : alerts.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-5 py-10 text-center text-slate-500">
                  No infra alerts 🎉
                </td>
              </tr>
            ) : (
              alerts.map((a) => (
                <tr key={a.id} className="hover:bg-slate-50">
                  <td className="max-w-md truncate px-5 py-3 text-slate-900" title={a.title}>
                    {a.title}
                  </td>
                  <td className="px-5 py-3 text-slate-500">{a.source}</td>
                  <td className="px-5 py-3">
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${severityBadgeClass(a.severity)}`}>
                      {a.severity}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-slate-500">{new Date(a.created_at).toLocaleString()}</td>
                  <td className="px-5 py-3">
                    {a.resolved_at ? (
                      <span className="inline-flex rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                        Resolved
                      </span>
                    ) : (
                      <span className="inline-flex rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
                        Open
                      </span>
                    )}
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

function severityBadgeClass(severity: string): string {
  switch (severity) {
    case 'critical':
      return 'bg-rose-50 text-rose-700';
    case 'warning':
      return 'bg-amber-50 text-amber-700';
    default:
      return 'bg-slate-100 text-slate-600';
  }
}
