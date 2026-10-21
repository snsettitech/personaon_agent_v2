'use client';

import { useEffect, useState } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import type { Flow } from './NotificationsShell';

type DryRunResult = {
  audience_count: number;
};

export function ProposedFlowCard({
  flow,
  onAction,
  onRefresh,
}: {
  flow: Flow;
  onAction: (path: string, success: string) => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  const [dryRun, setDryRun] = useState<DryRunResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState({
    subject: flow.context_overrides?.subject ?? '',
    body: flow.context_overrides?.body ?? '',
    cta_label: flow.context_overrides?.cta_label ?? '',
    cta_path: flow.context_overrides?.cta_path ?? '',
  });

  useEffect(() => {
    setDraft({
      subject: flow.context_overrides?.subject ?? '',
      body: flow.context_overrides?.body ?? '',
      cta_label: flow.context_overrides?.cta_label ?? '',
      cta_path: flow.context_overrides?.cta_path ?? '',
    });
  }, [flow.context_overrides]);

  async function preview() {
    setPreviewing(true);
    setError(null);
    try {
      const response = await authFetchStandalone(`/admin/notifications/flows/${flow.id}/run`, { method: 'POST' });
      if (!response.ok) throw new Error(`Request failed: ${response.status}`);
      const payload = (await response.json()) as { data: DryRunResult };
      setDryRun(payload.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Dry run failed');
    } finally {
      setPreviewing(false);
    }
  }

  async function saveDraft() {
    setSaving(true);
    setError(null);
    try {
      const response = await authFetchStandalone(`/admin/notifications/flows/${flow.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(draft),
      });
      if (!response.ok) throw new Error(`Request failed: ${response.status}`);
      await onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5">
      <div className="space-y-4">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
          <h2 className="font-semibold text-slate-950">{flow.name}</h2>
          <p className="text-sm text-slate-500">{flow.audience_spec.segment ?? 'custom'} · {flow.email_type} · {flow.created_by}</p>
          {dryRun && <p className="mt-2 text-sm font-medium text-slate-700">Dry run: {dryRun.audience_count} recipients</p>}
          {error && <p className="mt-2 text-sm text-rose-700">{error}</p>}
          </div>
          <div className="flex gap-2">
          <button onClick={() => void preview()} disabled={previewing} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 disabled:opacity-60">{previewing ? 'Checking' : 'Dry run'}</button>
          <button onClick={() => void saveDraft()} disabled={saving} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 disabled:opacity-60">{saving ? 'Saving' : 'Save draft'}</button>
          <button onClick={() => void onAction(`/admin/notifications/flows/${flow.id}/approve`, 'Flow approved')} className="rounded-lg bg-slate-950 px-3 py-2 text-sm font-medium text-white">Approve</button>
          <button onClick={() => void onAction(`/admin/notifications/flows/${flow.id}/reject`, 'Flow rejected')} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700">Reject</button>
          </div>
        </div>
        <div className="grid gap-3">
          <input value={draft.subject} onChange={(event) => setDraft({ ...draft, subject: event.target.value })} className="rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="Subject" />
          <textarea value={draft.body} onChange={(event) => setDraft({ ...draft, body: event.target.value })} className="min-h-24 rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="Body" />
          <div className="grid gap-3 sm:grid-cols-2">
            <input value={draft.cta_label} onChange={(event) => setDraft({ ...draft, cta_label: event.target.value })} className="rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="CTA label" />
            <input value={draft.cta_path} onChange={(event) => setDraft({ ...draft, cta_path: event.target.value })} className="rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="CTA path" />
          </div>
        </div>
      </div>
    </div>
  );
}
