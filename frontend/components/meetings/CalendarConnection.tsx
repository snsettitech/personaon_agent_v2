'use client';

import { useEffect, useState, useCallback } from 'react';
import { MoreHorizontal, RefreshCw, Unplug } from 'lucide-react';
import { resolveApiBaseUrl } from '@/lib/api';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { DropdownMenu } from '@/components/ui/DropdownMenu';

interface ProviderState {
  connected: boolean;
  is_active?: boolean;
  last_error?: string | null;
  updated_at?: string | null;
  recall_synced?: boolean;
}

interface StatusResponse {
  connected: boolean;
  twin_id: string;
  providers: {
    google: ProviderState;
    microsoft: ProviderState;
  };
}

type LoadState = 'loading' | 'loaded' | 'error';

interface CalendarConnectionProps {
  twinId: string;
}

export default function CalendarConnection({ twinId }: CalendarConnectionProps): React.JSX.Element {
  const apiBaseUrl = resolveApiBaseUrl();
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Read URL params for post-OAuth notices and clear them from the URL
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    const gcal = params.get('gcal');
    const outlook = params.get('outlook');
    if (gcal === 'connected') setNotice('Google Calendar connected.');
    else if (gcal === 'error') setNotice('Google Calendar could not be connected. Try again.');
    else if (outlook === 'connected') setNotice('Microsoft Outlook connected.');
    else if (outlook === 'error') setNotice('Microsoft Outlook could not be connected. Try again.');
    if (gcal || outlook) {
      params.delete('gcal');
      params.delete('outlook');
      params.delete('reason');
      const next = `${window.location.pathname}${params.toString() ? `?${params.toString()}` : ''}`;
      window.history.replaceState({}, '', next);
    }
  }, []);

  const fetchStatus = useCallback(async () => {
    setLoadState('loading');
    try {
      const res = await authFetchStandalone(`${apiBaseUrl}/v2/calendar/${twinId}/status`);
      if (!res.ok) {
        setLoadState('error');
        return;
      }
      const data: StatusResponse = await res.json();
      setStatus(data);
      setLoadState('loaded');
    } catch {
      setLoadState('error');
    }
  }, [apiBaseUrl, twinId]);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  const startGoogleConnect = useCallback(async () => {
    try {
      const res = await authFetchStandalone(
        `${apiBaseUrl}/v2/calendar/oauth/authorize?twin_id=${twinId}`,
      );
      if (!res.ok) return;
      const data: { authorization_url?: string; url?: string } = await res.json();
      const url = data.authorization_url || data.url;
      if (url) window.location.href = url;
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      setNotice(`Could not start Google connect: ${msg}`);
    }
  }, [apiBaseUrl, twinId]);

  const startMicrosoftConnect = useCallback(async () => {
    try {
      const res = await authFetchStandalone(
        `${apiBaseUrl}/v2/calendar/microsoft/oauth/authorize?twin_id=${twinId}`,
      );
      if (!res.ok) {
        if (res.status === 500) {
          setNotice('Microsoft Outlook is not configured yet. Use Google Calendar for now.');
        }
        return;
      }
      const data: { authorization_url?: string; url?: string } = await res.json();
      const url = data.authorization_url || data.url;
      if (url) window.location.href = url;
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      setNotice(`Could not start Microsoft connect: ${msg}`);
    }
  }, [apiBaseUrl, twinId]);

  const disconnect = useCallback(async () => {
    if (!confirm('Disconnect calendar? Public bookings and meeting auto-sync will stop until you reconnect.')) {
      return;
    }
    try {
      const res = await authFetchStandalone(`${apiBaseUrl}/v2/calendar/${twinId}/disconnect`, {
        method: 'DELETE',
      });
      if (res.ok) {
        setNotice('Disconnected.');
        await fetchStatus();
      } else {
        setNotice('Could not disconnect. Please try again.');
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      setNotice(`Disconnect failed: ${msg}`);
    }
  }, [apiBaseUrl, twinId, fetchStatus]);

  // ---- Render ----

  if (loadState === 'loading') {
    return (
      <div className="rounded-2xl border border-black/[0.06] bg-white/60 p-4 text-sm" style={{ color: 'var(--text-muted)' }}>
        Loading calendar connection…
      </div>
    );
  }

  if (loadState === 'error') {
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
        Could not load calendar status.
        <button onClick={() => void fetchStatus()} className="ml-2 underline">Retry</button>
      </div>
    );
  }

  if (!status?.connected) {
    return (
      <div className="rounded-3xl p-6" style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}>
        {notice && (
          <div className="mb-4 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">{notice}</div>
        )}
        <h2 className="text-lg font-semibold" style={{ color: 'var(--text-primary)' }}>
          Connect your calendar to see upcoming meetings
        </h2>
        <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary)' }}>
          Pick the provider you use. PersonaOn will sync upcoming meetings and dispatch a bot to record them.
        </p>
        <div className="mt-4 flex flex-wrap gap-3">
          <button
            onClick={() => void startGoogleConnect()}
            className="rounded-xl px-5 py-2.5 text-sm font-semibold transition-opacity hover:opacity-90"
            style={{ backgroundColor: 'var(--brand-primary)', color: 'white' }}
          >
            Connect Google Calendar
          </button>
          <button
            onClick={() => void startMicrosoftConnect()}
            className="rounded-xl border px-5 py-2.5 text-sm font-semibold transition-opacity hover:bg-black/[0.03]"
            style={{ borderColor: 'var(--border-default)', color: 'var(--text-primary)' }}
          >
            Connect Outlook
          </button>
        </div>
        <p className="mt-3 text-xs" style={{ color: 'var(--text-muted)' }}>
          We only read your meetings and create events when you approve a booking. We never modify your calendar without consent.
        </p>
      </div>
    );
  }

  // Connected state — compact badge with menu
  const google = status.providers.google;
  const microsoft = status.providers.microsoft;
  const connectedProvider = google.connected ? 'Google' : microsoft.connected ? 'Outlook' : '';

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-black/[0.06] bg-white/60 px-4 py-2.5">
      {notice && (
        <div className="w-full rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">{notice}</div>
      )}
      <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
        ✓ Connected: {connectedProvider}
      </span>
      <div className="ml-auto">
        <DropdownMenu
          align="end"
          trigger={
            <button
              type="button"
              aria-label="Calendar connection menu"
              className="rounded-lg px-2 py-1 text-[var(--fg-chrome)] transition hover:bg-black/[0.04]"
            >
              <MoreHorizontal className="h-4 w-4" />
            </button>
          }
          items={[
            { label: 'Refresh status', icon: RefreshCw, onSelect: () => void fetchStatus() },
            { label: 'Disconnect', icon: Unplug, destructive: true, onSelect: () => void disconnect() },
          ]}
        />
      </div>
    </div>
  );
}
