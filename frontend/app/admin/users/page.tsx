'use client';

import { useCallback, useEffect, useState } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { downloadCsv } from '../_components/download';
import { UserDrawer } from './UserDrawer';

interface UserRow {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  plan: string;
  created_at: string;
  last_active_at: string | null;
}

const LIMIT = 100;

const PLAN_BADGE: Record<string, string> = {
  free: 'bg-slate-100 text-slate-600',
  pro: 'bg-indigo-50 text-indigo-700',
  business: 'bg-sky-50 text-sky-700',
  believer: 'bg-amber-50 text-amber-700',
};
const ROLE_BADGE: Record<string, string> = {
  owner: 'bg-purple-50 text-purple-700',
  admin: 'bg-blue-50 text-blue-700',
  support: 'bg-amber-50 text-amber-700',
  viewer: 'bg-slate-100 text-slate-600',
};

function Badge({ text, map }: { text: string; map: Record<string, string> }) {
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${map[text] || 'bg-slate-100 text-slate-600'}`}>
      {text}
    </span>
  );
}

export default function AdminUsersPage() {
  const [q, setQ] = useState('');
  const [users, setUsers] = useState<UserRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  const load = useCallback(async (query: string, off: number, append: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetchStandalone(
        `/admin/users/search?limit=${LIMIT}&offset=${off}${query ? `&q=${encodeURIComponent(query)}` : ''}`
      );
      if (!res.ok) throw new Error(`Failed: ${res.status}`);
      const data: UserRow[] = await res.json();
      setUsers((prev) => (append ? [...prev, ...data] : data));
      setHasMore(data.length === LIMIT);
      setOffset(off + data.length);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Load failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load('', 0, false);
  }, [load]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <form
          className="flex flex-1 gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            void load(q, 0, false);
          }}
        >
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by email…"
            className="flex-1 rounded-lg border border-slate-300 px-4 py-2 text-sm"
          />
          <button type="submit" className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700">
            Search
          </button>
        </form>
        <button
          onClick={() => void downloadCsv('/admin/users/export', 'personaon-users.csv')}
          className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          Export CSV
        </button>
      </div>

      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">{error}</div>}

      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 bg-slate-50 text-left text-slate-600">
              <th className="px-5 py-3 font-medium">User</th>
              <th className="px-5 py-3 font-medium">Plan</th>
              <th className="px-5 py-3 font-medium">Role</th>
              <th className="px-5 py-3 font-medium">Joined</th>
              <th className="px-5 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && users.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-5 py-12 text-center text-slate-500">
                  Loading…
                </td>
              </tr>
            ) : users.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-5 py-12 text-center text-slate-500">
                  No users found
                </td>
              </tr>
            ) : (
              users.map((u) => (
                <tr key={u.id} className="hover:bg-slate-50">
                  <td className="px-5 py-3">
                    <div className="font-medium text-slate-900">{u.full_name || '(no name)'}</div>
                    <div className="text-xs text-slate-500">{u.email}</div>
                  </td>
                  <td className="px-5 py-3">
                    <Badge text={u.plan || 'free'} map={PLAN_BADGE} />
                  </td>
                  <td className="px-5 py-3">
                    <Badge text={u.role || 'viewer'} map={ROLE_BADGE} />
                  </td>
                  <td className="px-5 py-3 text-slate-500">{new Date(u.created_at).toLocaleDateString()}</td>
                  <td className="px-5 py-3 text-right">
                    <button
                      onClick={() => setSelected(u.id)}
                      className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                    >
                      Manage
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        {hasMore && (
          <div className="border-t border-slate-100 bg-slate-50 px-5 py-3 text-center">
            <button
              onClick={() => void load(q, offset, true)}
              disabled={loading}
              className="rounded-lg border border-slate-300 px-4 py-1.5 text-sm font-medium text-slate-700 hover:bg-white disabled:opacity-50"
            >
              {loading ? 'Loading…' : 'Load more'}
            </button>
          </div>
        )}
      </div>

      {selected && (
        <UserDrawer userId={selected} onClose={() => setSelected(null)} onChanged={() => void load(q, 0, false)} />
      )}
    </div>
  );
}
