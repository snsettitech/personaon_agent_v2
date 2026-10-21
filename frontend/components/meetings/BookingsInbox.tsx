'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { CalendarDays, Check, X, ExternalLink, Loader2 } from 'lucide-react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type BookingStatus = 'pending' | 'approved' | 'rejected';

interface BookingRequest {
  id: string;
  twin_id: string;
  visitor_name: string;
  visitor_email: string;
  visitor_message: string | null;
  visitor_timezone: string | null;
  proposed_start: string;
  proposed_end: string;
  slot_duration_minutes: number;
  status: BookingStatus;
  approved_at: string | null;
  rejected_at: string | null;
  rejection_reason: string | null;
  gcal_event_id: string | null;
  meet_link: string | null;
  event_link: string | null;
  created_at: string;
}

interface BookingsInboxProps {
  twinId: string;
  /** Called after every approve/reject so the sidebar pending-count can refresh. */
  onCountChange?: (pendingCount: number) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDateRange(startIso: string, endIso: string, timezone?: string): string {
  try {
    const start = new Date(startIso);
    const end = new Date(endIso);
    const opts: Intl.DateTimeFormatOptions = timezone ? { timeZone: timezone } : {};
    const dateStr = start.toLocaleDateString('en-US', {
      ...opts,
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
    const startTime = start.toLocaleTimeString('en-US', { ...opts, hour: 'numeric', minute: '2-digit' });
    const endTime = end.toLocaleTimeString('en-US', { ...opts, hour: 'numeric', minute: '2-digit' });
    const tzAbbr = start
      .toLocaleString('en-US', { ...opts, timeZoneName: 'short' })
      .split(' ')
      .pop();
    return `${dateStr} · ${startTime} – ${endTime} ${tzAbbr ?? ''}`.trim();
  } catch {
    return `${startIso} – ${endIso}`;
  }
}

/** Visitor's local timezone (or undefined if unknown). */
function ownerTimezone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return undefined;
  }
}


function formatRelative(iso: string): string {
  try {
    const diffMs = Date.now() - new Date(iso).getTime();
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return 'just now';
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffH = Math.floor(diffMin / 60);
    if (diffH < 24) return `${diffH}h ago`;
    const diffD = Math.floor(diffH / 24);
    return `${diffD}d ago`;
  } catch {
    return '';
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function BookingsInbox({ twinId, onCountChange }: BookingsInboxProps) {
  const apiBase = resolveApiBaseUrl();
  const [bookings, setBookings] = useState<BookingRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<BookingStatus | 'all'>('pending');
  const [actingId, setActingId] = useState<string | null>(null);

  const fetchBookings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetchStandalone(`${apiBase}/v2/calendar/${twinId}/bookings`);
      if (!res.ok) {
        const detail = await res.text().catch(() => String(res.status));
        setError(`Could not load bookings: ${detail}`);
        return;
      }
      const data = await res.json() as { bookings?: BookingRequest[]; count?: number };
      const list = data.bookings ?? [];
      setBookings(list);
      const pendingCount = list.filter((b) => b.status === 'pending').length;
      onCountChange?.(pendingCount);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Network error';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [apiBase, twinId, onCountChange]);

  useEffect(() => {
    void fetchBookings();
  }, [fetchBookings]);

  const filtered = useMemo(() => {
    if (statusFilter === 'all') return bookings;
    return bookings.filter((b) => b.status === statusFilter);
  }, [bookings, statusFilter]);

  const counts = useMemo(() => ({
    pending: bookings.filter((b) => b.status === 'pending').length,
    approved: bookings.filter((b) => b.status === 'approved').length,
    rejected: bookings.filter((b) => b.status === 'rejected').length,
  }), [bookings]);

  const handleApprove = useCallback(async (booking: BookingRequest) => {
    if (actingId) return;
    setActingId(booking.id);
    try {
      const res = await authFetchStandalone(
        `${apiBase}/v2/calendar/${twinId}/bookings/${booking.id}/approve`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' } },
      );
      if (!res.ok) {
        const detail = await res.text().catch(() => String(res.status));
        setError(`Approve failed: ${detail}`);
        return;
      }
      await fetchBookings();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Network error';
      setError(msg);
    } finally {
      setActingId(null);
    }
  }, [apiBase, twinId, fetchBookings, actingId]);

  const handleReject = useCallback(async (booking: BookingRequest) => {
    if (actingId) return;
    const reason = window.prompt(
      `Reject booking from ${booking.visitor_name}? Optional reason (sent to visitor):`,
      '',
    );
    if (reason === null) return; // user cancelled
    setActingId(booking.id);
    try {
      const res = await authFetchStandalone(
        `${apiBase}/v2/calendar/${twinId}/bookings/${booking.id}/reject`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reason: reason.trim() || null }),
        },
      );
      if (!res.ok) {
        const detail = await res.text().catch(() => String(res.status));
        setError(`Reject failed: ${detail}`);
        return;
      }
      await fetchBookings();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Network error';
      setError(msg);
    } finally {
      setActingId(null);
    }
  }, [apiBase, twinId, fetchBookings, actingId]);

  // ── Status filter pills ────────────────────────────────────────────────────
  const statusPill = (label: string, value: BookingStatus | 'all', count: number | null) => {
    const active = statusFilter === value;
    return (
      <button
        key={value}
        type="button"
        onClick={() => setStatusFilter(value)}
        aria-pressed={active}
        className={`flex items-center gap-2 rounded-full px-4 py-1.5 text-xs font-semibold transition-all ${
          active
            ? 'bg-[#1d1d1f] text-white shadow-md'
            : 'border border-black/10 bg-white text-[#1d1d1f] hover:bg-black/[0.03]'
        }`}
      >
        {label}
        {count !== null && (
          <span
            className={`inline-flex h-5 min-w-[20px] items-center justify-center rounded-full px-1.5 text-[10px] font-bold ${
              active ? 'bg-white text-[#1d1d1f]' : 'bg-[#0066cc]/10 text-[#0066cc]'
            }`}
          >
            {count}
          </span>
        )}
      </button>
    );
  };

  // ── Loading / error / empty states ────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex min-h-[300px] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[#0066cc]" />
      </div>
    );
  }

  if (error && bookings.length === 0) {
    return (
      <div className="rounded-3xl border border-rose-200 bg-rose-50 p-6 text-sm text-rose-700">
        {error}
        <button
          type="button"
          onClick={() => void fetchBookings()}
          className="ml-3 font-semibold underline"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Filter pills */}
      <div className="flex flex-wrap gap-2">
        {statusPill('Pending', 'pending', counts.pending)}
        {statusPill('Approved', 'approved', counts.approved)}
        {statusPill('Rejected', 'rejected', counts.rejected)}
        {statusPill('All', 'all', bookings.length)}
      </div>

      {error && (
        <div className="rounded-2xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">
          {error}
        </div>
      )}

      {/* Empty state for current filter */}
      {filtered.length === 0 ? (
        <div className="rounded-3xl border border-dashed border-black/10 bg-white p-10 text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-[#e8f2ff] text-[#0066cc]">
            <CalendarDays className="h-6 w-6" />
          </div>
          <p className="text-sm font-semibold text-[#1d1d1f]">
            {statusFilter === 'pending'
              ? 'No pending requests'
              : statusFilter === 'approved'
                ? 'No approved bookings yet'
                : statusFilter === 'rejected'
                  ? 'No rejected bookings'
                  : 'No bookings yet'}
          </p>
          <p className="mt-1 text-xs text-black/56">
            {statusFilter === 'pending'
              ? 'When visitors book a meeting from your public profile, requests appear here for you to approve.'
              : 'Booking history will show up here once you start approving or rejecting requests.'}
          </p>
        </div>
      ) : (
        <ul className="space-y-3">
          {filtered.map((b) => (
            <li
              key={b.id}
              className="rounded-3xl border border-black/[0.08] bg-white p-5 shadow-sm transition-shadow hover:shadow-md"
            >
              <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-base font-semibold text-[#1d1d1f]">{b.visitor_name}</p>
                    <a
                      href={`mailto:${b.visitor_email}`}
                      className="text-sm text-[#0066cc] hover:underline"
                    >
                      {b.visitor_email}
                    </a>
                    <span className="text-xs text-black/40">· requested {formatRelative(b.created_at)}</span>
                  </div>
                  {(() => {
                    const ownerTz = ownerTimezone();
                    const visitorTz = b.visitor_timezone || undefined;
                    const showVisitorRow = !!visitorTz && !!ownerTz && visitorTz !== ownerTz;
                    return (
                      <>
                        <p className="mt-1 text-sm font-medium text-[#1d1d1f]">
                          {formatDateRange(b.proposed_start, b.proposed_end, ownerTz)}
                          <span className="ml-2 text-xs font-normal text-black/56">
                            (your time · {b.slot_duration_minutes} min)
                          </span>
                        </p>
                        {showVisitorRow && (
                          <p className="mt-0.5 text-xs text-black/56">
                            {formatDateRange(b.proposed_start, b.proposed_end, visitorTz)}
                            <span className="ml-1.5 text-black/40">(visitor's time · {visitorTz})</span>
                          </p>
                        )}
                      </>
                    );
                  })()}
                  {b.visitor_message && (
                    <p className="mt-3 rounded-2xl bg-black/[0.03] p-3 text-sm text-black/70">
                      &ldquo;{b.visitor_message}&rdquo;
                    </p>
                  )}
                  {b.status === 'rejected' && b.rejection_reason && (
                    <p className="mt-2 text-xs text-black/56">
                      Rejected: {b.rejection_reason}
                    </p>
                  )}
                  {b.status === 'approved' && b.meet_link && (
                    <a
                      href={b.meet_link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-3 inline-flex items-center gap-1.5 text-xs font-semibold text-[#0066cc] hover:underline"
                    >
                      Open Google Meet link
                      <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  )}
                </div>

                {/* Actions */}
                {b.status === 'pending' ? (
                  <div className="flex shrink-0 gap-2 md:flex-col md:items-end">
                    <button
                      type="button"
                      onClick={() => void handleApprove(b)}
                      disabled={actingId === b.id}
                      className="inline-flex items-center gap-1.5 rounded-full bg-[#1d1d1f] px-4 py-2 text-xs font-semibold text-white transition hover:bg-black disabled:opacity-50"
                    >
                      {actingId === b.id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Check className="h-3.5 w-3.5" />
                      )}
                      Approve
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleReject(b)}
                      disabled={actingId === b.id}
                      className="inline-flex items-center gap-1.5 rounded-full border border-black/10 bg-white px-4 py-2 text-xs font-semibold text-[#1d1d1f] transition hover:bg-black/[0.03] disabled:opacity-50"
                    >
                      <X className="h-3.5 w-3.5" />
                      Reject
                    </button>
                  </div>
                ) : (
                  <span
                    className={`shrink-0 rounded-full px-3 py-1 text-xs font-semibold ${
                      b.status === 'approved'
                        ? 'bg-emerald-50 text-emerald-700'
                        : 'bg-slate-100 text-slate-600'
                    }`}
                  >
                    {b.status === 'approved' ? 'Approved' : 'Rejected'}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
