'use client';

import { useCallback, useEffect, useState } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';

type Run = {
  id: string;
  flow_id: string;
  trigger_kind: string;
  audience_count: number;
  enqueued: number;
  skipped: number;
  failed: number;
  open_count: number | null;
  click_count: number | null;
  conversion_count: number | null;
  outcome_measured_at: string | null;
  created_at: string;
};

type Recipient = {
  id: string;
  user_id: string;
  recipient_email: string;
  status: string;
  resend_message_id: string | null;
  error_message: string | null;
  skip_reason: string | null;
  sent_at: string | null;
  created_at: string;
};

async function readJson<T>(path: string): Promise<T> {
  const response = await authFetchStandalone(path);
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return (await response.json()) as T;
}

export function RunDetailShell({ runId }: { runId: string }) {
  const [run, setRun] = useState<Run | null>(null);
  const [recipients, setRecipients] = useState<Recipient[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await readJson<{ data: { run: Run; recipients: Recipient[] } }>(`/admin/notifications/runs/${runId}`);
      setRun(payload.data.run);
      setRecipients(payload.data.recipients);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Load failed');
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <div className="py-20 text-center text-sm text-slate-500">Loading run...</div>;

  return (
    <div className="space-y-6">
      <div>
        <a className="text-sm font-medium text-slate-600 hover:text-slate-950" href="/admin/notifications">Back to notifications</a>
        <h1 className="mt-3 text-2xl font-semibold text-slate-950">Notification run</h1>
        <p className="mt-1 text-sm text-slate-500">{runId}</p>
      </div>

      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">{error}</div>}

      {run && (
        <div className="grid gap-3 sm:grid-cols-4">
          <Metric label="Audience" value={run.audience_count} />
          <Metric label="Sent" value={run.enqueued} />
          <Metric label="Skipped" value={run.skipped} />
          <Metric label="Failed" value={run.failed} />
        </div>
      )}

      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <tbody className="divide-y divide-slate-100">
            {recipients.map((recipient) => (
              <tr key={recipient.id}>
                <td className="px-4 py-3 font-medium text-slate-900">{recipient.recipient_email}</td>
                <td className="px-4 py-3 text-slate-500">{recipient.status}</td>
                <td className="px-4 py-3 text-slate-500">{recipient.sent_at ? new Date(recipient.sent_at).toLocaleString() : recipient.skip_reason ?? recipient.error_message ?? 'Pending'}</td>
                <td className="px-4 py-3 text-right text-slate-500">{recipient.resend_message_id ?? 'No provider id'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {recipients.length === 0 && <div className="p-10 text-center text-sm text-slate-500">No recipient events yet</div>}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4">
      <div className="text-xs font-medium uppercase text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-slate-950">{value}</div>
    </div>
  );
}
