'use client';

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { ProposedFlowCard } from './ProposedFlowCard';

export type Flow = {
  id: string;
  key: string;
  name: string;
  kind: string;
  status: string;
  email_type: string;
  created_by: string;
  audience_spec: { segment?: string };
  context_overrides?: {
    subject?: string;
    body?: string;
    cta_label?: string;
    cta_path?: string;
  };
};

type Run = {
  id: string;
  flow_id: string;
  trigger_kind: string;
  audience_count: number;
  enqueued: number;
  skipped: number;
  open_count: number | null;
  click_count: number | null;
  conversion_count: number | null;
  outcome_measured_at: string | null;
  created_at: string;
};

type Tab = 'proposed' | 'active' | 'history';

const tabs: { id: Tab; label: string }[] = [
  { id: 'proposed', label: 'Proposed' },
  { id: 'active', label: 'Active' },
  { id: 'history', label: 'History' },
];

async function readJson<T>(path: string): Promise<T> {
  const response = await authFetchStandalone(path);
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return (await response.json()) as T;
}

export function NotificationsShell() {
  const [tab, setTab] = useState<Tab>('proposed');
  const [flows, setFlows] = useState<Flow[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [flowPayload, runPayload] = await Promise.all([
        readJson<{ data: { flows: Flow[] } }>('/admin/notifications/flows'),
        readJson<{ data: { runs: Run[] } }>('/admin/notifications/runs'),
      ]);
      setFlows(flowPayload.data.flows);
      setRuns(runPayload.data.runs);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Load failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const act = useCallback(
    async (path: string, success: string) => {
      setMessage(null);
      setError(null);
      try {
        const response = await authFetchStandalone(path, { method: 'POST' });
        if (!response.ok) throw new Error(`Request failed: ${response.status}`);
        setMessage(success);
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Action failed');
      }
    },
    [load],
  );

  const proposed = useMemo(() => flows.filter((flow) => flow.status === 'proposed'), [flows]);
  const active = useMemo(() => flows.filter((flow) => flow.status === 'active'), [flows]);
  const flowNames = useMemo(
    () => Object.fromEntries(flows.map((flow) => [flow.id, flow.name])),
    [flows],
  );
  const lastRuns = useMemo(() => {
    const byFlow: Record<string, Run | undefined> = {};
    for (const run of runs) {
      const current = byFlow[run.flow_id];
      if (!current || new Date(run.created_at).getTime() > new Date(current.created_at).getTime()) {
        byFlow[run.flow_id] = run;
      }
    }
    return byFlow;
  }, [runs]);

  if (loading) return <div className="py-20 text-center text-sm text-slate-500">Loading notifications...</div>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-950">Notifications</h1>
        <p className="mt-1 text-sm text-slate-500">Review proposed flows, manage active sends, and inspect run history.</p>
      </div>

      <div className="flex gap-2 border-b border-slate-200">
        {tabs.map((item) => (
          <button
            key={item.id}
            onClick={() => setTab(item.id)}
            className={`border-b-2 px-3 py-2 text-sm font-medium ${
              tab === item.id ? 'border-slate-950 text-slate-950' : 'border-transparent text-slate-500 hover:text-slate-800'
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {message && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">{message}</div>}
      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">{error}</div>}

      {tab === 'proposed' && (
        <div className="grid gap-4">
          {proposed.map((flow) => (
            <ProposedFlowCard key={flow.id} flow={flow} onAction={act} onRefresh={load} />
          ))}
          {proposed.length === 0 && <Empty label="No proposed flows" />}
        </div>
      )}

      {tab === 'active' && (
        <Table rows={active} render={(flow) => (
          <>
            <td className="px-4 py-3 font-medium text-slate-900">{flow.name}</td>
            <td className="px-4 py-3 text-slate-500">{lastRuns[flow.id] ? formatOutcome(lastRuns[flow.id]) : flow.kind}</td>
            <td className="px-4 py-3 text-slate-500">{formatDate(lastRuns[flow.id]?.created_at)}</td>
            <td className="px-4 py-3 text-right">
              <button onClick={() => void act(`/admin/notifications/flows/${flow.id}/run`, 'Dry run complete')} className="mr-2 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium">Run dry</button>
              <button onClick={() => window.confirm('Run this flow live?') && void act(`/admin/notifications/flows/${flow.id}/run?dry_run=false`, 'Live run queued')} className="mr-2 rounded-lg bg-slate-950 px-3 py-1.5 text-xs font-medium text-white">Run live</button>
              <button onClick={() => void act(`/admin/notifications/flows/${flow.id}/pause`, 'Flow paused')} className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium">Pause</button>
            </td>
          </>
        )} empty="No active flows" />
      )}

      {tab === 'history' && (
        <Table rows={runs} render={(run) => (
          <>
            <td className="px-4 py-3 font-medium text-slate-900"><a className="hover:underline" href={`/admin/notifications/runs/${run.id}`}>{flowNames[run.flow_id] ?? run.flow_id}</a></td>
            <td className="px-4 py-3 text-slate-500">{new Date(run.created_at).toLocaleString()}</td>
            <td className="px-4 py-3 text-slate-500">{run.enqueued} sent · {run.skipped} skipped</td>
            <td className="px-4 py-3 text-right text-slate-500">{formatOutcome(run)}</td>
          </>
        )} empty="No runs yet" />
      )}
    </div>
  );
}

function Empty({ label }: { label: string }) {
  return <div className="rounded-2xl border border-dashed border-slate-300 p-10 text-center text-sm text-slate-500">{label}</div>;
}

function formatDate(value: string | undefined) { return value ? new Date(value).toLocaleString() : 'Never'; }

function rate(part: number | null, total: number) { return total ? `${Math.round(((part ?? 0) / total) * 100)}%` : '0%'; }

function formatOutcome(run: Run | undefined) {
  if (!run) return 'Pending outcome';
  return run.outcome_measured_at
    ? `${rate(run.open_count, run.enqueued)} open · ${rate(run.click_count, run.enqueued)} click · ${rate(run.conversion_count, run.enqueued)} convert`
    : 'Pending outcome';
}

function Table<T extends { id: string }>({ rows, render, empty }: { rows: T[]; render: (row: T) => ReactNode; empty: string }) {
  if (rows.length === 0) return <Empty label={empty} />;
  return <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white"><table className="w-full text-sm"><tbody className="divide-y divide-slate-100">{rows.map((row) => <tr key={row.id}>{render(row)}</tr>)}</tbody></table></div>;
}
