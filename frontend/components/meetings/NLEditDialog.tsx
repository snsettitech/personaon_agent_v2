'use client';

import React, { useCallback, useState } from 'react';
import Dialog from '@/components/ui/Dialog';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';

interface NLEditDialogProps<T> {
  open: boolean;
  onClose: () => void;
  twinId: string;
  meetingId: string;
  field: string;
  fieldLabel: string;            // human label, e.g. "Recap"
  currentValue: T;
  /** Called with the proposed value when the user clicks Apply.
   *  Caller is responsible for PATCH + state update. */
  onApply: (proposedValue: T, prompt: string) => Promise<void>;
}

type Phase = 'idle' | 'thinking' | 'preview' | 'error';

const QUICK_PROMPTS = [
  'Make it shorter',
  'More formal tone',
  'More casual tone',
  'Remove jargon',
  'Add more detail',
];

/**
 * Granola-style natural-language edit modal.
 * Two-step: prompt → preview diff → apply.
 */
export default function NLEditDialog<T>({
  open,
  onClose,
  twinId,
  meetingId,
  field,
  fieldLabel,
  currentValue,
  onApply,
}: NLEditDialogProps<T>): React.JSX.Element {
  const apiBase = resolveApiBaseUrl();
  const [phase, setPhase] = useState<Phase>('idle');
  const [prompt, setPrompt] = useState('');
  const [proposed, setProposed] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  const reset = useCallback(() => {
    setPhase('idle');
    setPrompt('');
    setProposed(null);
    setError(null);
    setApplying(false);
  }, []);

  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [reset, onClose]);

  const handleSuggest = useCallback(async () => {
    const p = prompt.trim();
    if (!p) return;
    setPhase('thinking');
    setError(null);
    try {
      const res = await authFetchStandalone(
        `${apiBase}/v2/meetings/${twinId}/${meetingId}/recap/nl-edit`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ field, prompt: p }),
        },
      );
      if (!res.ok) {
        if (res.status === 429) {
          setError('Too many edits — wait a moment and try again.');
        } else {
          const body = await res.json().catch(() => null);
          setError(body?.detail || `Request failed (${res.status})`);
        }
        setPhase('error');
        return;
      }
      const body = await res.json() as {
        status: string;
        data: { proposed_value: T };
      };
      setProposed(body.data.proposed_value);
      setPhase('preview');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Network error');
      setPhase('error');
    }
  }, [apiBase, twinId, meetingId, field, prompt]);

  const handleApply = useCallback(async () => {
    if (proposed === null) return;
    setApplying(true);
    try {
      await onApply(proposed, prompt);
      handleClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not apply');
      setPhase('error');
      setApplying(false);
    }
  }, [proposed, prompt, onApply, handleClose]);

  const handleReject = useCallback(() => {
    setProposed(null);
    setPhase('idle');
  }, []);

  // Render the current vs proposed value. Strings render as text; structured
  // fields render as pretty-printed JSON (concise, no library deps).
  const isStringField = typeof currentValue === 'string' || currentValue === null;

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      title={`Edit "${fieldLabel}" with a prompt`}
      width={640}
      footer={
        phase === 'preview' ? (
          <>
            <button
              type="button"
              onClick={handleReject}
              disabled={applying}
              style={{
                padding: '8px 14px',
                borderRadius: '9999px',
                backgroundColor: 'transparent',
                color: 'var(--fg-2)',
                fontSize: '13px',
                fontWeight: 500,
                border: '1px solid var(--fog-line-2)',
                cursor: applying ? 'not-allowed' : 'pointer',
                opacity: applying ? 0.6 : 1,
              }}
            >
              Reject
            </button>
            <button
              type="button"
              onClick={() => void handleApply()}
              disabled={applying}
              style={{
                padding: '8px 16px',
                borderRadius: '9999px',
                backgroundColor: 'var(--ink)',
                color: '#fff',
                fontSize: '13px',
                fontWeight: 500,
                border: 'none',
                cursor: applying ? 'not-allowed' : 'pointer',
                opacity: applying ? 0.7 : 1,
              }}
            >
              {applying ? 'Applying…' : 'Apply →'}
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              onClick={handleClose}
              style={{
                padding: '8px 14px',
                borderRadius: '9999px',
                backgroundColor: 'transparent',
                color: 'var(--fg-2)',
                fontSize: '13px',
                fontWeight: 500,
                border: '1px solid var(--fog-line-2)',
                cursor: 'pointer',
              }}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void handleSuggest()}
              disabled={phase === 'thinking' || !prompt.trim()}
              style={{
                padding: '8px 16px',
                borderRadius: '9999px',
                backgroundColor: prompt.trim() && phase !== 'thinking' ? 'var(--ink)' : 'var(--fog-line-2)',
                color: '#fff',
                fontSize: '13px',
                fontWeight: 500,
                border: 'none',
                cursor: prompt.trim() && phase !== 'thinking' ? 'pointer' : 'not-allowed',
              }}
            >
              {phase === 'thinking' ? 'Thinking…' : 'Suggest changes →'}
            </button>
          </>
        )
      }
    >
      {phase !== 'preview' && (
        <>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                void handleSuggest();
              }
            }}
            placeholder="e.g. make it shorter and more direct"
            rows={2}
            maxLength={200}
            disabled={phase === 'thinking'}
            style={{
              width: '100%',
              padding: '10px 12px',
              borderRadius: '12px',
              border: '1px solid var(--fog-line-2)',
              backgroundColor: 'var(--fog-3)',
              color: 'var(--ink)',
              fontSize: '14px',
              fontFamily: 'inherit',
              resize: 'vertical',
              outline: 'none',
            }}
          />
          <div
            style={{
              marginTop: 10,
              display: 'flex',
              gap: 6,
              flexWrap: 'wrap',
            }}
          >
            <span
              style={{
                fontSize: '11px',
                color: 'var(--fg-3)',
                alignSelf: 'center',
                marginRight: 4,
              }}
            >
              Try:
            </span>
            {QUICK_PROMPTS.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => setPrompt(q)}
                disabled={phase === 'thinking'}
                style={{
                  padding: '4px 10px',
                  borderRadius: '9999px',
                  border: '1px solid var(--fog-line-2)',
                  backgroundColor: 'transparent',
                  fontSize: '12px',
                  color: 'var(--ink-2)',
                  cursor: 'pointer',
                }}
              >
                {q}
              </button>
            ))}
          </div>
          <p
            style={{
              marginTop: 10,
              fontSize: '11px',
              color: 'var(--fg-3)',
            }}
          >
            ⌘/Ctrl+Enter to suggest. Max 200 chars.
          </p>
          {phase === 'error' && error && (
            <div
              style={{
                marginTop: 12,
                padding: 10,
                borderRadius: 8,
                backgroundColor: 'rgba(229,72,77,0.08)',
                color: 'var(--rec)',
                fontSize: '12px',
              }}
            >
              {error}
            </div>
          )}
        </>
      )}

      {phase === 'preview' && proposed !== null && (
        <>
          <p style={{ margin: '0 0 12px', fontSize: '12px', color: 'var(--fg-3)' }}>
            Prompt: <em>{prompt}</em>
          </p>
          <div style={{ display: 'grid', gap: 12 }}>
            <DiffBlock label="Before" value={currentValue} isString={isStringField} variant="before" />
            <DiffBlock label="After" value={proposed} isString={isStringField} variant="after" />
          </div>
        </>
      )}
    </Dialog>
  );
}

interface DiffBlockProps<T> {
  label: string;
  value: T;
  isString: boolean;
  variant: 'before' | 'after';
}

function DiffBlock<T>({ label, value, isString, variant }: DiffBlockProps<T>): React.JSX.Element {
  const accent = variant === 'before' ? 'var(--rec)' : 'var(--ok)';
  const bg = variant === 'before' ? 'rgba(229,72,77,0.05)' : 'rgba(43,182,115,0.05)';
  const text = isString
    ? (typeof value === 'string' ? value : value === null ? '(empty)' : JSON.stringify(value, null, 2))
    : JSON.stringify(value, null, 2);
  return (
    <div
      style={{
        borderLeft: `3px solid ${accent}`,
        backgroundColor: bg,
        padding: '10px 14px',
        borderRadius: '0 8px 8px 0',
      }}
    >
      <div
        style={{
          fontSize: '10.5px',
          textTransform: 'uppercase',
          letterSpacing: '0.10em',
          color: accent,
          fontFamily: "'JetBrains Mono', monospace",
          marginBottom: 6,
        }}
      >
        {label}
      </div>
      <pre
        style={{
          margin: 0,
          fontFamily: isString ? 'inherit' : "'JetBrains Mono', monospace",
          fontSize: isString ? '14px' : '12px',
          color: 'var(--ink)',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          lineHeight: 1.5,
        }}
      >
        {text}
      </pre>
    </div>
  );
}
