'use client';

import { useCallback, useEffect, useState } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';

interface QualityAudit {
  id: string;
  twin_id: string;
  intent_label: string | null;
  workflow_intent: string | null;
  response_action: string | null;
  confidence_score: number | null;
  refusal_reason: string | null;
  escalation_reason: string | null;
  created_at: string;
}

interface ReviewItem {
  id: string;
  twin_id: string;
  reason: string;
  priority: string | null;
  status: string;
  created_at: string;
  resolved_at: string | null;
}

interface LearningInput {
  id: string;
  twin_id: string;
  input_type: string;
  status: string;
  created_at: string;
  updated_at: string;
  applied_at: string | null;
}

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return 'Never';
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function confidenceBadge(score: number | null) {
  if (score === null) return <span className="text-slate-400">N/A</span>;
  const pct = Math.round(score * 100);
  const color =
    pct >= 80 ? 'bg-emerald-50 text-emerald-700'
    : pct >= 50 ? 'bg-amber-50 text-amber-700'
    : 'bg-rose-50 text-rose-700';
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${color}`}>
      {pct}%
    </span>
  );
}

function statusBadge(status: string) {
  const colors: Record<string, string> = {
    pending: 'bg-amber-50 text-amber-700',
    resolved: 'bg-emerald-50 text-emerald-700',
    applied: 'bg-blue-50 text-blue-700',
    rejected: 'bg-rose-50 text-rose-700',
  };
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${colors[status] || 'bg-slate-100 text-slate-600'}`}>
      {status}
    </span>
  );
}

type TabId = 'quality' | 'review' | 'learning';

export default function AdminInsightsPage() {
  const [tab, setTab] = useState<TabId>('quality');
  const [audits, setAudits] = useState<QualityAudit[]>([]);
  const [reviews, setReviews] = useState<ReviewItem[]>([]);
  const [learnings, setLearnings] = useState<LearningInput[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadTab = useCallback(async (t: TabId) => {
    setLoading(true);
    setError(null);
    try {
      if (t === 'quality') {
        const res = await authFetchStandalone('/admin/insights/conversation-quality?limit=100');
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        setAudits(await res.json());
      } else if (t === 'review') {
        const res = await authFetchStandalone('/admin/insights/review-queue?limit=100');
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        setReviews(await res.json());
      } else {
        const res = await authFetchStandalone('/admin/insights/learning-inputs?limit=100');
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        setLearnings(await res.json());
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Load failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTab(tab);
  }, [tab, loadTab]);

  return (
    <div className="space-y-6">
      {/* Tab bar */}
      <div className="flex gap-1 rounded-xl bg-slate-100 p-1 w-fit">
        {([
          { id: 'quality' as const, label: 'Response Quality' },
          { id: 'review' as const, label: 'Review Queue' },
          { id: 'learning' as const, label: 'Learning Inputs' },
        ]).map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
              tab === id ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">
          {error}
        </div>
      )}

      {/* Quality Audits Table */}
      {tab === 'quality' && (
        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                <th className="px-5 py-3 text-left font-medium text-slate-600">Twin</th>
                <th className="px-5 py-3 text-left font-medium text-slate-600">Intent</th>
                <th className="px-5 py-3 text-left font-medium text-slate-600">Action</th>
                <th className="px-5 py-3 text-left font-medium text-slate-600">Confidence</th>
                <th className="px-5 py-3 text-left font-medium text-slate-600">Issues</th>
                <th className="px-5 py-3 text-left font-medium text-slate-600">When</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-5 py-12 text-center text-slate-500">Loading...</td>
                </tr>
              ) : audits.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-5 py-12 text-center text-slate-500">No audits found</td>
                </tr>
              ) : (
                audits.map((a) => (
                  <tr key={a.id} className="hover:bg-slate-50">
                    <td className="px-5 py-3 text-slate-900 font-mono text-xs">
                      {a.twin_id.slice(0, 8)}
                    </td>
                    <td className="px-5 py-3 text-slate-600">{a.intent_label || a.workflow_intent || '-'}</td>
                    <td className="px-5 py-3 text-slate-600">{a.response_action || '-'}</td>
                    <td className="px-5 py-3">{confidenceBadge(a.confidence_score)}</td>
                    <td className="px-5 py-3 text-xs text-slate-500">
                      {a.refusal_reason && <span className="text-rose-600">Refused: {a.refusal_reason}</span>}
                      {a.escalation_reason && <span className="text-amber-600">Escalated: {a.escalation_reason}</span>}
                      {!a.refusal_reason && !a.escalation_reason && '-'}
                    </td>
                    <td className="px-5 py-3 text-slate-500">{timeAgo(a.created_at)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Review Queue Table */}
      {tab === 'review' && (
        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                <th className="px-5 py-3 text-left font-medium text-slate-600">Twin</th>
                <th className="px-5 py-3 text-left font-medium text-slate-600">Reason</th>
                <th className="px-5 py-3 text-left font-medium text-slate-600">Priority</th>
                <th className="px-5 py-3 text-left font-medium text-slate-600">Status</th>
                <th className="px-5 py-3 text-left font-medium text-slate-600">Created</th>
                <th className="px-5 py-3 text-left font-medium text-slate-600">Resolved</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-5 py-12 text-center text-slate-500">Loading...</td>
                </tr>
              ) : reviews.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-5 py-12 text-center text-slate-500">Review queue is empty</td>
                </tr>
              ) : (
                reviews.map((r) => (
                  <tr key={r.id} className="hover:bg-slate-50">
                    <td className="px-5 py-3 text-slate-900 font-mono text-xs">{r.twin_id.slice(0, 8)}</td>
                    <td className="px-5 py-3 text-slate-600">{r.reason}</td>
                    <td className="px-5 py-3">{r.priority || '-'}</td>
                    <td className="px-5 py-3">{statusBadge(r.status)}</td>
                    <td className="px-5 py-3 text-slate-500">{timeAgo(r.created_at)}</td>
                    <td className="px-5 py-3 text-slate-500">{timeAgo(r.resolved_at)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Learning Inputs Table */}
      {tab === 'learning' && (
        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                <th className="px-5 py-3 text-left font-medium text-slate-600">Twin</th>
                <th className="px-5 py-3 text-left font-medium text-slate-600">Type</th>
                <th className="px-5 py-3 text-left font-medium text-slate-600">Status</th>
                <th className="px-5 py-3 text-left font-medium text-slate-600">Created</th>
                <th className="px-5 py-3 text-left font-medium text-slate-600">Applied</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr>
                  <td colSpan={5} className="px-5 py-12 text-center text-slate-500">Loading...</td>
                </tr>
              ) : learnings.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-5 py-12 text-center text-slate-500">No learning inputs</td>
                </tr>
              ) : (
                learnings.map((l) => (
                  <tr key={l.id} className="hover:bg-slate-50">
                    <td className="px-5 py-3 text-slate-900 font-mono text-xs">{l.twin_id.slice(0, 8)}</td>
                    <td className="px-5 py-3 text-slate-600">{l.input_type}</td>
                    <td className="px-5 py-3">{statusBadge(l.status)}</td>
                    <td className="px-5 py-3 text-slate-500">{timeAgo(l.created_at)}</td>
                    <td className="px-5 py-3 text-slate-500">{timeAgo(l.applied_at)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
