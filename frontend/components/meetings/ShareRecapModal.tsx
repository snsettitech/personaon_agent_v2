'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Dialog from '@/components/ui/Dialog';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';

interface ShareState {
  share_token: string | null;
  share_url: string | null;
  share_enabled: boolean;
  share_expires_at: string | null;
  share_view_count: number;
  share_last_viewed_at: string | null;
}

interface ShareRecapModalProps {
  open: boolean;
  onClose: () => void;
  twinId: string;
  meetingId: string;
}

type Status = 'idle' | 'loading' | 'ready' | 'error' | 'revoked';

function formatViewCount(count: number, lastViewedAt: string | null): string | null {
  if (!count || count <= 0) return null;
  if (!lastViewedAt) return `Viewed ${count} time${count === 1 ? '' : 's'}`;
  const ago = formatRelative(lastViewedAt);
  return `Viewed ${count} time${count === 1 ? '' : 's'} · last ${ago}`;
}

function formatRelative(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return 'recently';
  const diffMin = Math.round((Date.now() - d.getTime()) / 60_000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin} min ago`;
  const hours = Math.round(diffMin / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

const EXPIRES_OPTIONS: Array<{ label: string; days: number | null }> = [
  { label: '7 days', days: 7 },
  { label: '30 days', days: 30 },
  { label: 'Never', days: null },
];

export default function ShareRecapModal({
  open,
  onClose,
  twinId,
  meetingId,
}: ShareRecapModalProps): React.JSX.Element {
  const apiBase = resolveApiBaseUrl();
  const [status, setStatus] = useState<Status>('idle');
  const [share, setShare] = useState<ShareState | null>(null);
  const [expiresChoice, setExpiresChoice] = useState<number | null>(7);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Mint or fetch existing token when modal opens
  const ensureShare = useCallback(
    async (newExpiresIn?: number | null) => {
      setStatus('loading');
      setError(null);
      try {
        const res = await authFetchStandalone(
          `${apiBase}/v2/meetings/${twinId}/${meetingId}/share`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              expires_in_days: newExpiresIn === undefined ? expiresChoice : newExpiresIn,
            }),
          },
        );
        if (!res.ok) {
          setStatus('error');
          setError(`Failed to create share link (${res.status})`);
          return;
        }
        const body = await res.json() as { status: string; data: ShareState };
        setShare(body.data);
        setStatus(body.data.share_enabled ? 'ready' : 'revoked');
      } catch (err: unknown) {
        setStatus('error');
        setError(err instanceof Error ? err.message : 'Network error');
      }
    },
    [apiBase, twinId, meetingId, expiresChoice],
  );

  // Open lifecycle
  useEffect(() => {
    if (open && status === 'idle') {
      void ensureShare();
    }
    if (!open) {
      // Reset transient state on close so a fresh open is clean.
      setCopied(false);
    }
  }, [open, status, ensureShare]);

  const handleCopy = useCallback(async () => {
    if (!share?.share_url) return;
    try {
      await navigator.clipboard.writeText(share.share_url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // fall back: prompt the user to copy manually
      window.prompt('Copy share link:', share.share_url);
    }
  }, [share]);

  const handleRevoke = useCallback(async () => {
    setStatus('loading');
    setError(null);
    try {
      const res = await authFetchStandalone(
        `${apiBase}/v2/meetings/${twinId}/${meetingId}/share`,
        { method: 'DELETE' },
      );
      if (!res.ok) {
        setStatus('error');
        setError(`Failed to revoke (${res.status})`);
        return;
      }
      setStatus('revoked');
      setShare((s) => (s ? { ...s, share_enabled: false } : s));
    } catch (err: unknown) {
      setStatus('error');
      setError(err instanceof Error ? err.message : 'Network error');
    }
  }, [apiBase, twinId, meetingId]);

  const handleExpiresChange = useCallback(
    (newValue: number | null) => {
      setExpiresChoice(newValue);
      // If we already have a token, regen to apply the new expiry
      if (share?.share_token) {
        void ensureShare(newValue);
      }
    },
    [share, ensureShare],
  );

  const handleRegenerate = useCallback(() => {
    // Calling POST after revoke mints a fresh token + clears revoked.
    void ensureShare();
  }, [ensureShare]);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Share this summary"
      width={520}
      footer={
        <>
          {status === 'ready' && share?.share_url && (
            <button
              type="button"
              onClick={() => void handleRevoke()}
              style={{
                padding: '8px 14px',
                borderRadius: '9999px',
                backgroundColor: 'transparent',
                color: 'var(--rec)',
                fontSize: '13px',
                fontWeight: 500,
                border: '1px solid var(--fog-line-2)',
                cursor: 'pointer',
              }}
            >
              Revoke link
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            style={{
              padding: '8px 16px',
              borderRadius: '9999px',
              backgroundColor: 'var(--ink)',
              color: '#fff',
              fontSize: '13px',
              fontWeight: 500,
              border: 'none',
              cursor: 'pointer',
            }}
          >
            Done
          </button>
        </>
      }
    >
      <p
        style={{
          marginTop: 0,
          marginBottom: 16,
          fontSize: '13px',
          color: 'var(--fg-2)',
          lineHeight: 1.5,
        }}
      >
        Anyone with this link can read the summary.
        Your private notes stay hidden.
      </p>

      {/* URL row */}
      {status === 'loading' && !share && (
        <div
          style={{
            padding: '12px',
            borderRadius: '12px',
            backgroundColor: 'var(--fog)',
            fontSize: '13px',
            color: 'var(--fg-2)',
          }}
        >
          Generating link…
        </div>
      )}
      {status === 'error' && (
        <div
          style={{
            padding: '12px',
            borderRadius: '12px',
            backgroundColor: 'rgba(229,72,77,0.08)',
            color: 'var(--rec)',
            fontSize: '13px',
          }}
        >
          {error ?? 'Could not generate share link'}
          <button
            type="button"
            onClick={() => void ensureShare()}
            style={{
              marginLeft: 12,
              fontSize: '12px',
              textDecoration: 'underline',
              background: 'none',
              border: 'none',
              color: 'var(--rec)',
              cursor: 'pointer',
            }}
          >
            Retry
          </button>
        </div>
      )}
      {status === 'revoked' && (
        <div
          style={{
            padding: '12px',
            borderRadius: '12px',
            backgroundColor: 'var(--fog)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 12,
          }}
        >
          <span style={{ fontSize: '13px', color: 'var(--fg-2)' }}>
            Link revoked.
          </span>
          <button
            type="button"
            onClick={handleRegenerate}
            style={{
              padding: '6px 12px',
              borderRadius: '9999px',
              backgroundColor: 'var(--ink)',
              color: '#fff',
              fontSize: '12px',
              fontWeight: 500,
              border: 'none',
              cursor: 'pointer',
            }}
          >
            Generate new
          </button>
        </div>
      )}
      {status === 'ready' && share?.share_url && (
        <>
          <div
            style={{
              display: 'flex',
              alignItems: 'stretch',
              gap: 0,
              borderRadius: '12px',
              border: '1px solid var(--fog-line-2)',
              overflow: 'hidden',
            }}
          >
            <input
              type="text"
              value={share.share_url}
              readOnly
              onFocus={(e) => e.currentTarget.select()}
              style={{
                flex: 1,
                padding: '10px 12px',
                fontSize: '13px',
                border: 'none',
                outline: 'none',
                backgroundColor: 'var(--fog-3)',
                color: 'var(--ink)',
                fontFamily: 'var(--font-geist-mono, JetBrains Mono, monospace)',
              }}
            />
            <button
              type="button"
              onClick={() => void handleCopy()}
              style={{
                padding: '10px 16px',
                fontSize: '13px',
                fontWeight: 500,
                backgroundColor: 'var(--ink)',
                color: '#fff',
                border: 'none',
                cursor: 'pointer',
              }}
            >
              {copied ? '✓ Copied' : 'Copy'}
            </button>
          </div>

          {/* Expires dropdown */}
          <div style={{ marginTop: 16 }}>
            <label
              style={{
                display: 'block',
                fontSize: '11px',
                textTransform: 'uppercase',
                color: 'var(--fg-3)',
                fontFamily: 'var(--font-geist-mono, JetBrains Mono, monospace)',
                letterSpacing: '0.10em',
                marginBottom: 6,
              }}
            >
              Expires
            </label>
            <div style={{ display: 'flex', gap: 8 }}>
              {EXPIRES_OPTIONS.map((opt) => {
                const isActive = expiresChoice === opt.days;
                return (
                  <button
                    key={opt.label}
                    type="button"
                    onClick={() => handleExpiresChange(opt.days)}
                    style={{
                      padding: '6px 14px',
                      borderRadius: '9999px',
                      fontSize: '12px',
                      fontWeight: 500,
                      cursor: 'pointer',
                      backgroundColor: isActive ? 'var(--ink)' : 'transparent',
                      color: isActive ? '#fff' : 'var(--ink)',
                      border: `1px solid ${isActive ? 'var(--ink)' : 'var(--fog-line-2)'}`,
                    }}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
            {share.share_expires_at && (
              <p
                style={{
                  marginTop: 6,
                  fontSize: '11px',
                  color: 'var(--fg-3)',
                  fontFamily: 'var(--font-geist-mono, JetBrains Mono, monospace)',
                }}
              >
                Expires {new Date(share.share_expires_at).toLocaleDateString()}
              </p>
            )}
          </div>

          {/* View count footer */}
          {formatViewCount(share.share_view_count, share.share_last_viewed_at) && (
            <p
              style={{
                marginTop: 16,
                paddingTop: 12,
                borderTop: '1px solid var(--fog-line)',
                fontSize: '11px',
                color: 'var(--fg-3)',
                fontFamily: 'var(--font-geist-mono, JetBrains Mono, monospace)',
              }}
            >
              {formatViewCount(share.share_view_count, share.share_last_viewed_at)}
            </p>
          )}
        </>
      )}
    </Dialog>
  );
}
