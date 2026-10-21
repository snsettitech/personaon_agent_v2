'use client';

import { useCallback, useEffect, useState } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';

const PLANS = ['free', 'pro', 'business', 'believer'] as const;
// Mirror of FlagName in packages/core/src/flags/index.ts.
const FLAGS = [
  'workspace_v2',
  'recap_edit_v2',
  'commitments_v1',
  'memory_review_v1',
  'people_v1',
  'preview_mode_v1',
  'heads_up_v1',
  'granola_live_notes',
  'granola_segment_persist',
  'granola_enhanced_notes',
  'granola_realtime',
  'granola_watchdog',
  'transcript_tools_v1',
  'persona_v1',
];

interface Detail {
  user: {
    id: string;
    email: string;
    full_name: string | null;
    role: string;
    plan: string;
    trial_kind: string | null;
    trial_ends_at: string | null;
    created_at: string;
    last_active_at: string | null;
  };
  twins: { id: string; name: string; status: string; is_active: boolean }[];
  subscription: { tier: string; status: string } | null;
  flags: Record<string, boolean | null>;
}

export function UserDrawer({
  userId,
  onClose,
  onChanged,
}: {
  userId: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [plan, setPlan] = useState('free');
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetchStandalone(`/admin/users/${userId}`);
      if (!res.ok) throw new Error(`Failed: ${res.status}`);
      const d: Detail = await res.json();
      setDetail(d);
      setPlan(d.user.plan || 'free');
      const f: Record<string, boolean> = {};
      for (const k of FLAGS) f[k] = d.flags[k] === true;
      setFlags(f);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Load failed');
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    void load();
  }, [load]);

  const post = useCallback(async (path: string, body?: unknown) => {
    return authFetchStandalone(path, { method: 'POST', ...(body ? { body: JSON.stringify(body) } : {}) });
  }, []);

  const save = useCallback(async () => {
    setSaving(true);
    setMsg(null);
    try {
      const res = await post(`/admin/users/${userId}/entitlements`, { plan, flags });
      if (!res.ok) throw new Error(`Save failed: ${res.status}`);
      setMsg('Saved. Flag changes apply on the user’s next sign-in.');
      onChanged();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  }, [userId, plan, flags, post, onChanged]);

  const grantAll = useCallback(async () => {
    setSaving(true);
    setMsg(null);
    try {
      const res = await post(`/admin/users/${userId}/grant-all`);
      if (!res.ok) throw new Error(`Failed: ${res.status}`);
      setMsg('Granted all features (business plan + all flags).');
      await load();
      onChanged();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : 'Failed');
    } finally {
      setSaving(false);
    }
  }, [userId, post, load, onChanged]);

  const suspend = useCallback(
    async (on: boolean) => {
      setSaving(true);
      setMsg(null);
      try {
        const res = await post(`/admin/users/${userId}/${on ? 'suspend' : 'unsuspend'}`);
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        setMsg(on ? 'User suspended.' : 'User unsuspended.');
      } catch (err) {
        setMsg(err instanceof Error ? err.message : 'Failed');
      } finally {
        setSaving(false);
      }
    },
    [userId, post]
  );

  const removeUser = useCallback(async () => {
    if (!window.confirm('Delete this user permanently? Removes their auth identity and profile row.')) return;
    setSaving(true);
    setMsg(null);
    try {
      const res = await authFetchStandalone(`/admin/users/${userId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`Failed: ${res.status}`);
      onChanged();
      onClose();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : 'Failed');
      setSaving(false);
    }
  }, [userId, onChanged, onClose]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/30" onClick={onClose}>
      <div className="h-full w-full max-w-lg overflow-y-auto bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
          <h2 className="text-base font-semibold text-slate-900">Manage user</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600" aria-label="Close">
            ✕
          </button>
        </div>

        {loading ? (
          <div className="p-6 text-sm text-slate-500">Loading…</div>
        ) : error ? (
          <div className="m-6 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">{error}</div>
        ) : detail ? (
          <div className="space-y-6 p-6">
            <div>
              <div className="text-lg font-semibold text-slate-900">{detail.user.full_name || detail.user.email}</div>
              <div className="text-sm text-slate-500">{detail.user.email}</div>
              <div className="mt-1 text-xs text-slate-400">
                Role: {detail.user.role} · Joined {new Date(detail.user.created_at).toLocaleDateString()}
              </div>
            </div>

            {msg && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{msg}</div>}

            <div className="rounded-xl border border-slate-200 p-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-900">Plan</h3>
                <button
                  onClick={() => void grantAll()}
                  disabled={saving}
                  className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
                >
                  Grant all features
                </button>
              </div>
              <select
                value={plan}
                onChange={(e) => setPlan(e.target.value)}
                className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              >
                {PLANS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
              {detail.user.trial_kind && (
                <div className="mt-2 text-xs text-amber-600">
                  Trial: {detail.user.trial_kind} until{' '}
                  {detail.user.trial_ends_at ? new Date(detail.user.trial_ends_at).toLocaleDateString() : '—'}
                </div>
              )}
            </div>

            <div className="rounded-xl border border-slate-200 p-4">
              <h3 className="text-sm font-semibold text-slate-900">Feature flags</h3>
              <p className="mt-1 text-xs text-slate-500">Applies on the user’s next sign-in / token refresh.</p>
              <div className="mt-3 grid grid-cols-1 gap-2">
                {FLAGS.map((f) => (
                  <label key={f} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm">
                    <span className="text-slate-700">{f}</span>
                    <input
                      type="checkbox"
                      checked={!!flags[f]}
                      onChange={(e) => setFlags((prev) => ({ ...prev, [f]: e.target.checked }))}
                      className="h-4 w-4"
                    />
                  </label>
                ))}
              </div>
            </div>

            <button
              onClick={() => void save()}
              disabled={saving}
              className="w-full rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              {saving ? 'Saving…' : 'Save changes'}
            </button>

            <div className="rounded-xl border border-rose-200 p-4">
              <h3 className="text-sm font-semibold text-rose-900">Danger zone</h3>
              <div className="mt-3 flex gap-3">
                <button
                  onClick={() => void suspend(true)}
                  disabled={saving}
                  className="rounded-lg border border-amber-300 px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-50 disabled:opacity-50"
                >
                  Suspend
                </button>
                <button
                  onClick={() => void suspend(false)}
                  disabled={saving}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  Unsuspend
                </button>
                <button
                  onClick={() => void removeUser()}
                  disabled={saving}
                  className="ml-auto rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-500 disabled:opacity-50"
                >
                  Delete
                </button>
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 p-4">
              <h3 className="text-sm font-semibold text-slate-900">Personas ({detail.twins.length})</h3>
              <div className="mt-2 space-y-1">
                {detail.twins.length === 0 ? (
                  <div className="text-xs text-slate-400">None</div>
                ) : (
                  detail.twins.map((t) => (
                    <div key={t.id} className="flex items-center justify-between text-sm">
                      <span className="text-slate-700">{t.name}</span>
                      <span className="text-xs text-slate-400">{t.status}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
