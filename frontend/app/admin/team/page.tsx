'use client';

import { useCallback, useEffect, useState } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';

const ROLES = ['owner', 'admin', 'support', 'viewer'];

interface Staff {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  created_at: string;
  last_active_at: string | null;
}

export default function AdminTeamPage() {
  const [staff, setStaff] = useState<Staff[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [email, setEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('support');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetchStandalone('/admin/team');
      if (!res.ok) throw new Error(`Failed: ${res.status}`);
      const d = await res.json();
      setStaff(d.staff || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Load failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const changeRole = useCallback(
    async (id: string, role: string) => {
      setMsg(null);
      try {
        const res = await authFetchStandalone(`/admin/users/${id}/role`, {
          method: 'PUT',
          body: JSON.stringify({ role }),
        });
        if (!res.ok) throw new Error((await res.text()) || `Failed: ${res.status}`);
        setMsg('Role updated.');
        await load();
      } catch (err) {
        setMsg(err instanceof Error ? err.message : 'Failed');
      }
    },
    [load]
  );

  const invite = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setBusy(true);
      setMsg(null);
      try {
        const res = await authFetchStandalone('/admin/team/invite', {
          method: 'POST',
          body: JSON.stringify({ email, role: inviteRole }),
        });
        if (!res.ok) throw new Error((await res.text()) || `Failed: ${res.status}`);
        setMsg(`Invited ${email} as ${inviteRole}.`);
        setEmail('');
        await load();
      } catch (err) {
        setMsg(err instanceof Error ? err.message : 'Failed');
      } finally {
        setBusy(false);
      }
    },
    [email, inviteRole, load]
  );

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-5">
        <h2 className="text-base font-semibold text-slate-900">Invite teammate</h2>
        <form className="mt-3 flex flex-col gap-3 sm:flex-row" onSubmit={invite}>
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            type="email"
            required
            placeholder="teammate@personaon.com"
            className="flex-1 rounded-lg border border-slate-300 px-4 py-2 text-sm"
          />
          <select
            value={inviteRole}
            onChange={(e) => setInviteRole(e.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          >
            {busy ? 'Inviting…' : 'Send invite'}
          </button>
        </form>
        <p className="mt-2 text-xs text-slate-500">
          Sends a Supabase invite email and pre-assigns the role. For existing users, change their role in the table below.
        </p>
      </section>

      {msg && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{msg}</div>}
      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">{error}</div>}

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-5 py-3">
          <h2 className="text-base font-semibold text-slate-900">Staff</h2>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 bg-slate-50 text-left text-slate-600">
              <th className="px-5 py-3 font-medium">Member</th>
              <th className="px-5 py-3 font-medium">Role</th>
              <th className="px-5 py-3 font-medium">Last active</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr>
                <td colSpan={3} className="px-5 py-12 text-center text-slate-500">
                  Loading…
                </td>
              </tr>
            ) : staff.length === 0 ? (
              <tr>
                <td colSpan={3} className="px-5 py-12 text-center text-slate-500">
                  No staff yet
                </td>
              </tr>
            ) : (
              staff.map((s) => (
                <tr key={s.id} className="hover:bg-slate-50">
                  <td className="px-5 py-3">
                    <div className="font-medium text-slate-900">{s.full_name || '(no name)'}</div>
                    <div className="text-xs text-slate-500">{s.email}</div>
                  </td>
                  <td className="px-5 py-3">
                    <select
                      value={s.role}
                      onChange={(e) => void changeRole(s.id, e.target.value)}
                      className="rounded-lg border border-slate-300 px-2 py-1 text-xs"
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-5 py-3 text-slate-500">
                    {s.last_active_at ? new Date(s.last_active_at).toLocaleDateString() : 'Never'}
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
