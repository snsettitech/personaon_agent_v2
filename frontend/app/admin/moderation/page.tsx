'use client';

import { useCallback, useEffect, useState } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { downloadCsv } from '../_components/download';

interface Persona {
  id: string;
  name: string | null;
  status: string;
  is_active: boolean;
  public: boolean;
  taken_down: boolean;
  created_at: string;
}

interface Lead {
  id: string;
  twin_id: string;
  visitor_name: string | null;
  visitor_email: string | null;
  source_domain: string | null;
  inferred_intent: string | null;
  created_at: string;
}

export default function AdminModerationPage() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [p, l] = await Promise.all([
        authFetchStandalone('/admin/moderation/twins?limit=200'),
        authFetchStandalone('/admin/moderation/leads?limit=100'),
      ]);
      if (!p.ok) throw new Error(`Failed: ${p.status}`);
      setPersonas(await p.json());
      setLeads(l.ok ? await l.json() : []);
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
    async (id: string, takenDown: boolean) => {
      setBusy(id);
      setMsg(null);
      try {
        const path = takenDown ? `/admin/twins/${id}/restore` : `/admin/twins/${id}/takedown`;
        const res = await authFetchStandalone(path, {
          method: 'POST',
          ...(takenDown ? {} : { body: JSON.stringify({ reason: 'admin moderation' }) }),
        });
        if (!res.ok) throw new Error((await res.text()) || `Failed: ${res.status}`);
        setMsg(takenDown ? 'Persona restored.' : 'Persona taken down.');
        await load();
      } catch (err) {
        setMsg(err instanceof Error ? err.message : 'Failed');
      } finally {
        setBusy(null);
      }
    },
    [load]
  );

  return (
    <div className="space-y-6">
      {msg && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{msg}</div>}
      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">{error}</div>}

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-5 py-3">
          <h2 className="text-base font-semibold text-slate-900">Public personas</h2>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 bg-slate-50 text-left text-slate-600">
              <th className="px-5 py-3 font-medium">Persona</th>
              <th className="px-5 py-3 font-medium">Status</th>
              <th className="px-5 py-3 font-medium">Visibility</th>
              <th className="px-5 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr>
                <td colSpan={4} className="px-5 py-12 text-center text-slate-500">
                  Loading…
                </td>
              </tr>
            ) : personas.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-5 py-12 text-center text-slate-500">
                  No personas
                </td>
              </tr>
            ) : (
              personas.map((p) => (
                <tr key={p.id} className="hover:bg-slate-50">
                  <td className="px-5 py-3">
                    <div className="font-medium text-slate-900">{p.name || '(unnamed)'}</div>
                    <div className="text-xs text-slate-400">{p.id}</div>
                  </td>
                  <td className="px-5 py-3 text-slate-600">{p.status}</td>
                  <td className="px-5 py-3">
                    {p.taken_down ? (
                      <span className="inline-flex rounded-full bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-700">
                        Taken down
                      </span>
                    ) : p.public ? (
                      <span className="inline-flex rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                        Public
                      </span>
                    ) : (
                      <span className="inline-flex rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                        Private
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-3 text-right">
                    {p.public || p.taken_down ? (
                      <button
                        onClick={() => void act(p.id, p.taken_down)}
                        disabled={busy === p.id}
                        className={`rounded-lg px-3 py-1.5 text-xs font-medium disabled:opacity-50 ${
                          p.taken_down
                            ? 'border border-slate-300 text-slate-700 hover:bg-slate-50'
                            : 'bg-rose-600 text-white hover:bg-rose-500'
                        }`}
                      >
                        {busy === p.id ? '…' : p.taken_down ? 'Restore' : 'Take down'}
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </section>

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <h2 className="text-base font-semibold text-slate-900">Recent leads</h2>
          <button
            onClick={() => void downloadCsv('/admin/moderation/leads/export', 'personaon-leads.csv')}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            Export CSV
          </button>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 bg-slate-50 text-left text-slate-600">
              <th className="px-5 py-3 font-medium">Visitor</th>
              <th className="px-5 py-3 font-medium">Source</th>
              <th className="px-5 py-3 font-medium">Intent</th>
              <th className="px-5 py-3 font-medium">When</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {leads.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-5 py-10 text-center text-slate-500">
                  No leads
                </td>
              </tr>
            ) : (
              leads.map((l) => (
                <tr key={l.id} className="hover:bg-slate-50">
                  <td className="px-5 py-3">
                    <div className="text-slate-900">{l.visitor_name || '—'}</div>
                    <div className="text-xs text-slate-500">{l.visitor_email || ''}</div>
                  </td>
                  <td className="px-5 py-3 text-slate-500">{l.source_domain || '—'}</td>
                  <td className="px-5 py-3 text-slate-500">{l.inferred_intent || '—'}</td>
                  <td className="px-5 py-3 text-slate-500">{new Date(l.created_at).toLocaleDateString()}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
