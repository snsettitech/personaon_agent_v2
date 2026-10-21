'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import Link from 'next/link';
import { AnimatePresence, motion } from 'framer-motion';
import { useTwin } from '@/lib/context/TwinContext';
import { listWidgetLeads, markLeadContacted, deleteLead, type WidgetLead } from '@/lib/widget/api';

// ── Offer state badge ────────────────────────────────────────────────────────

const OFFER_STATE_LABELS: Record<string, { label: string; cls: string }> = {
  offered:  { label: 'Offered',  cls: 'bg-amber-100 text-amber-800 border-amber-200' },
  accepted: { label: 'Accepted', cls: 'bg-teal-100 text-teal-800 border-teal-200' },
  booked:   { label: 'Booked',   cls: 'bg-teal-100 text-teal-800 border-teal-200' },
  declined: { label: 'Declined', cls: 'bg-[#F5F0EB] text-[#78716C] border-[#E7E5E4]' },
};

function OfferBadge({ state }: { state: string | null }) {
  if (!state) return <span className="text-[#A8A29E] text-xs">—</span>;
  const cfg = OFFER_STATE_LABELS[state] ?? { label: state, cls: 'bg-[#F5F0EB] text-[#57534E] border-[#E7E5E4]' };
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${cfg.cls}`}>
      {cfg.label}
    </span>
  );
}

// ── Intent pill ──────────────────────────────────────────────────────────────

function IntentPill({ intent, visitorType }: { intent: string | null; visitorType: string | null }) {
  if (!intent && !visitorType) return <span className="text-[#A8A29E] text-xs">—</span>;
  return (
    <div className="flex flex-wrap gap-1 items-center">
      {visitorType && (
        <span className="inline-flex items-center rounded-full bg-[#EEF2FF] border border-[#C7D7FE] text-[#3730A3] px-2 py-0.5 text-[11px] font-medium">
          {visitorType}
        </span>
      )}
      {intent && <span className="text-xs text-[#57534E] max-w-[120px] truncate" title={intent}>{intent}</span>}
    </div>
  );
}

// ── Detail panel row ─────────────────────────────────────────────────────────

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <span className="text-xs text-[#78716C] shrink-0">{label}</span>
      <span className="text-xs text-[#1C1917] text-right">{value}</span>
    </div>
  );
}

// ── Lead detail slide-over ───────────────────────────────────────────────────

function LeadPanel({
  lead,
  onClose,
  onContacted,
  onDelete,
}: {
  lead: WidgetLead;
  onClose: () => void;
  onContacted: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [marking, setMarking] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const isContacted = Boolean(lead.contacted_at);

  async function handleMarkContacted() {
    setMarking(true);
    setActionError(null);
    try {
      await markLeadContacted(lead.id);
      onContacted(lead.id);
    } catch {
      setActionError('Failed to mark as contacted.');
    } finally {
      setMarking(false);
    }
  }

  async function handleDelete() {
    if (!deleteConfirm) { setDeleteConfirm(true); return; }
    setDeleting(true);
    setActionError(null);
    try {
      await deleteLead(lead.id);
      onDelete(lead.id);
    } catch {
      setActionError('Failed to delete lead.');
      setDeleting(false);
    }
  }

  return (
    <>
      <motion.div
        className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        onKeyDown={(e) => { if (e.key === 'Escape') onClose(); }}
        role="presentation"
      />
      <motion.div
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col bg-white shadow-2xl"
        initial={{ x: '100%' }}
        animate={{ x: 0 }}
        exit={{ x: '100%' }}
        transition={{ type: 'spring', damping: 28, stiffness: 300 }}
      >
        <div className="flex items-center justify-between border-b border-[#F5F0EB] px-5 py-4">
          <h2 className="text-base font-bold text-[#1C1917]">Lead detail</h2>
          <button
            type="button"
            onClick={onClose}
            autoFocus
            aria-label="Close panel"
            className="flex h-8 w-8 items-center justify-center rounded-full text-[#78716C] hover:bg-[#F5F0EB] transition-colors"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Contact */}
          <section className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-[#A8A29E]">Contact</p>
            <div className="rounded-xl border border-[#E7E5E4] bg-[#FAFAF7] p-4 space-y-2">
              <Row label="Name" value={lead.visitor_name || '—'} />
              <Row label="Email" value={lead.visitor_email
                ? <a href={`mailto:${lead.visitor_email}`} className="text-[#0F766E] hover:underline">{lead.visitor_email}</a>
                : '—'} />
              <Row label="Source" value={lead.source_domain || '—'} />
              <Row label="Captured" value={isNaN(new Date(lead.created_at).getTime()) ? '—' : new Date(lead.created_at).toLocaleString()} />
              <Row label="Messages" value={String(lead.turn_count ?? 0)} />
              {isContacted && lead.contacted_at && (
                <Row label="Contacted" value={new Date(lead.contacted_at).toLocaleDateString()} />
              )}
            </div>
          </section>

          {/* Intent */}
          {(lead.inferred_intent || lead.inferred_visitor_type || lead.offer_state) && (
            <section className="space-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-[#A8A29E]">Intent</p>
              <div className="rounded-xl border border-[#E7E5E4] bg-[#FAFAF7] p-4 space-y-2">
                {lead.inferred_visitor_type && (
                  <Row label="Visitor type" value={
                    <span className="inline-flex items-center rounded-full bg-[#EEF2FF] border border-[#C7D7FE] text-[#3730A3] px-2 py-0.5 text-[11px] font-medium">
                      {lead.inferred_visitor_type}
                    </span>
                  } />
                )}
                {lead.inferred_intent && <Row label="Intent" value={lead.inferred_intent} />}
                {lead.offer_state && <Row label="Offer state" value={<OfferBadge state={lead.offer_state} />} />}
              </div>
            </section>
          )}

          {/* Actions */}
          <section className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-[#A8A29E]">Actions</p>
            {actionError && <p className="text-xs text-red-600">{actionError}</p>}
            <div className="flex flex-col gap-2">
              <button
                type="button"
                onClick={handleMarkContacted}
                disabled={isContacted || marking}
                className="flex items-center justify-center gap-2 rounded-xl border border-[#E7E5E4] bg-white px-4 py-2.5 text-sm font-medium text-[#1C1917] hover:bg-[#F5F0EB] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {marking ? 'Marking…' : isContacted ? '✓ Marked as contacted' : 'Mark as contacted'}
              </button>
              <button
                type="button"
                onClick={handleDelete}
                disabled={deleting}
                className={`flex items-center justify-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-medium transition-colors disabled:opacity-50 ${
                  deleteConfirm
                    ? 'border-red-300 bg-red-50 text-red-700 hover:bg-red-100'
                    : 'border-[#E7E5E4] bg-white text-[#78716C] hover:bg-[#F5F0EB]'
                }`}
              >
                {deleting ? 'Deleting…' : deleteConfirm ? 'Confirm delete' : 'Delete lead'}
              </button>
              {deleteConfirm && !deleting && (
                <button type="button" onClick={() => setDeleteConfirm(false)} className="text-xs text-[#A8A29E] hover:text-[#57534E] text-center">
                  Cancel
                </button>
              )}
            </div>
          </section>
        </div>
      </motion.div>
    </>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

function SourceBadge({ lead }: { lead: WidgetLead }) {
  const isPublic = lead.api_key_id === null;
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium"
      style={{
        backgroundColor: isPublic ? 'var(--bg-surface)' : '#F0FDF4',
        color: isPublic ? 'var(--text-muted)' : '#15803D',
        border: `1px solid ${isPublic ? 'var(--border-subtle)' : '#BBF7D0'}`,
      }}
    >
      {isPublic ? 'Public page' : 'Widget'}
    </span>
  );
}

export default function WidgetLeadsPage() {
  const { activeTwin } = useTwin();
  const [leads, setLeads] = useState<WidgetLead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [filterState, setFilterState] = useState('');
  const [selectedLead, setSelectedLead] = useState<WidgetLead | null>(null);

  const twinId = activeTwin?.id;

  const loadLeads = useCallback(async () => {
    if (!twinId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await listWidgetLeads(twinId);
      setLeads(data);
    } catch {
      setError('Failed to load leads');
    } finally {
      setLoading(false);
    }
  }, [twinId]);

  useEffect(() => { loadLeads(); }, [loadLeads]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return leads.filter((l) => {
      const matchSearch = !q
        || (l.visitor_name ?? '').toLowerCase().includes(q)
        || (l.visitor_email ?? '').toLowerCase().includes(q)
        || (l.source_domain ?? '').toLowerCase().includes(q);
      const matchState = !filterState || l.offer_state === filterState;
      return matchSearch && matchState;
    });
  }, [leads, search, filterState]);

  function sanitizeCsvCell(value: string): string {
    return /^[=+\-@\t\r]/.test(value) ? `\t${value}` : value;
  }

  function exportCsv() {
    const header = ['Name', 'Email', 'Source', 'Intent', 'Visitor Type', 'Offer State', 'Messages', 'Captured'];
    const rows = leads.map((l) => [
      l.visitor_name ?? '', l.visitor_email ?? '', l.api_key_id === null ? 'Public page' : 'Widget',
      l.inferred_intent ?? '', l.inferred_visitor_type ?? '', l.offer_state ?? '',
      String(l.turn_count ?? 0), new Date(l.created_at).toISOString(),
    ]);
    const csv = [header, ...rows]
      .map((row) => row.map((v) => `"${sanitizeCsvCell(String(v)).replace(/"/g, '""')}"`).join(','))
      .join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `personaon-leads-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function handleContacted(id: string) {
    const ts = new Date().toISOString();
    setLeads((prev) => prev.map((l) => l.id === id ? { ...l, contacted_at: ts } : l));
    setSelectedLead((prev) => prev?.id === id ? { ...prev, contacted_at: ts } : prev);
  }

  function handleDelete(id: string) {
    setLeads((prev) => prev.filter((l) => l.id !== id));
    setSelectedLead(null);
  }

  if (!twinId) {
    return <div className="p-8 text-center text-[#57534E]">Create a persona first to see leads.</div>;
  }

  return (
    <div className="space-y-6 max-w-5xl">
      <div className="flex items-center justify-between">
        <div>
          <Link
            href="/dashboard/settings?tab=twin"
            className="text-sm text-[#0F766E] hover:text-[#0D9488] mb-2 inline-block"
          >
            ← Capture settings
          </Link>
          <h1 className="text-3xl font-black tracking-tight text-[#1C1917]">Your leads</h1>
          <p className="text-[#57534E] mt-1">
            People who started a conversation with your persona.
          </p>
        </div>
        <button
          onClick={exportCsv}
          disabled={leads.length === 0}
          className="px-4 py-2 text-sm font-semibold bg-[#F5F0EB] text-[#1C1917] hover:bg-[#E7E5E4] rounded-xl transition-colors disabled:opacity-40 cursor-pointer"
        >
          Export CSV ({leads.length})
        </button>
      </div>

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">{error}</div>
      )}

      {!loading && leads.length > 0 && (
        <div className="flex gap-3 flex-wrap">
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name, email, domain…"
            className="flex-1 min-w-[200px] px-4 py-2 text-sm border border-[#D6D3D1] rounded-xl text-[#1C1917] placeholder-[#A8A29E] focus:outline-none focus:ring-2 focus:ring-[#0D9488]"
          />
          <select
            value={filterState}
            onChange={(e) => setFilterState(e.target.value)}
            className="px-4 py-2 text-sm border border-[#D6D3D1] rounded-xl text-[#1C1917] bg-white focus:outline-none focus:ring-2 focus:ring-[#0D9488]"
          >
            <option value="">All statuses</option>
            <option value="offered">Offered</option>
            <option value="accepted">Accepted</option>
            <option value="booked">Booked</option>
            <option value="declined">Declined</option>
          </select>
        </div>
      )}

      {loading ? (
        <div className="p-8 text-center text-[#A8A29E]">Loading…</div>
      ) : leads.length === 0 ? (
        <div className="bg-white rounded-2xl border border-[#E7E5E4] p-12 text-center">
          <div className="text-4xl mb-3">📭</div>
          <h2 className="text-lg font-bold text-[#1C1917]">No leads yet</h2>
          <p className="text-sm text-[#57534E] mt-1 max-w-md mx-auto">
            When visitors chat with your persona, their contact info will show up here.
            Make sure lead capture is on in{' '}
            <Link href="/dashboard/settings?tab=twin" className="text-[#0F766E] hover:underline">
              persona settings
            </Link>
            .
          </p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="bg-white rounded-2xl border border-[#E7E5E4] p-8 text-center">
          <p className="text-sm text-[#57534E]">No leads match your search.</p>
          <button onClick={() => { setSearch(''); setFilterState(''); }} className="mt-2 text-xs text-[#0F766E] hover:underline">
            Clear filters
          </button>
        </div>
      ) : (
        <div className="bg-white rounded-2xl border border-[#E7E5E4] shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-[#F5F0EB] text-left">
                <tr>
                  <th className="px-4 py-3 font-semibold text-[#57534E]">Name</th>
                  <th className="px-4 py-3 font-semibold text-[#57534E] hidden sm:table-cell">Email</th>
                  <th className="px-4 py-3 font-semibold text-[#57534E] hidden md:table-cell">Source</th>
                  <th className="px-4 py-3 font-semibold text-[#57534E] hidden md:table-cell">Intent</th>
                  <th className="px-4 py-3 font-semibold text-[#57534E]">Status</th>
                  <th className="px-4 py-3 font-semibold text-[#57534E] hidden lg:table-cell">Msgs</th>
                  <th className="px-4 py-3 font-semibold text-[#57534E] hidden lg:table-cell">Captured</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F5F0EB]">
                {filtered.map((lead) => (
                  <tr key={lead.id} onClick={() => setSelectedLead(lead)} className="hover:bg-[#FAFAF7] cursor-pointer">
                    <td className="px-4 py-3 text-[#1C1917] font-medium max-w-[160px]">
                      <span className="block truncate">{lead.visitor_name || '—'}</span>
                      {lead.contacted_at && (
                        <span className="inline-flex items-center rounded-full bg-teal-50 border border-teal-100 text-teal-700 px-1.5 py-0.5 text-[10px] font-medium">contacted</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[#57534E] hidden sm:table-cell">{lead.visitor_email || '—'}</td>
                    <td className="px-4 py-3 hidden md:table-cell">
                      <SourceBadge lead={lead} />
                    </td>
                    <td className="px-4 py-3 hidden md:table-cell">
                      <IntentPill intent={lead.inferred_intent} visitorType={lead.inferred_visitor_type} />
                    </td>
                    <td className="px-4 py-3"><OfferBadge state={lead.offer_state} /></td>
                    <td className="px-4 py-3 text-[#57534E] hidden lg:table-cell">{lead.turn_count}</td>
                    <td className="px-4 py-3 text-[#57534E] hidden lg:table-cell">
                      {isNaN(new Date(lead.created_at).getTime()) ? '—' : new Date(lead.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <AnimatePresence>
        {selectedLead && (
          <LeadPanel
            lead={selectedLead}
            onClose={() => setSelectedLead(null)}
            onContacted={handleContacted}
            onDelete={handleDelete}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
