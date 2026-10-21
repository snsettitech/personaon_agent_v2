'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import NLEditDialog from './NLEditDialog';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';

export type SaveState = 'idle' | 'saving' | 'saved' | 'error';

export interface EditableSectionRenderProps<T> {
  /** Current value (server-truth + local edits). */
  value: T;
  /** True while inline-editing. */
  isEditing: boolean;
  /** Call from your inline editor when user commits a change. */
  commit: (newValue: T) => void;
  /** Cancel inline edit, revert to last-saved. */
  cancel: () => void;
  /** Save state — drive your inline UI affordance. */
  saveState: SaveState;
}

interface EditableSectionProps<T> {
  twinId: string;
  meetingId: string;
  field: string;
  /** Human label, used by NLEditDialog title + aria. */
  fieldLabel: string;
  /** Current value from the page state. */
  value: T;
  /** Caller's current recap_version (for If-Match concurrency). */
  recapVersion: number;
  /** Called after a successful save with the new value + new recap_version. */
  onSaved: (newValue: T, newRecapVersion: number) => void;
  /** Pencil button: renders an inline editor. Caller controls the editor. */
  renderEditor?: (props: EditableSectionRenderProps<T>) => React.ReactNode;
  /** Read-only view of the value. */
  children: React.ReactNode;
}

/**
 * Wraps a recap section with edit affordances:
 *  - Pencil icon → toggles inline edit mode (via renderEditor prop)
 *  - 🪄 wand icon → opens the Granola-style NL-edit modal
 *
 * The component manages PATCH calls + concurrency (If-Match: recap_version).
 * Read-only display is the children. Inline editor is the renderEditor prop.
 */
export default function EditableSection<T>({
  twinId,
  meetingId,
  field,
  fieldLabel,
  value,
  recapVersion,
  onSaved,
  renderEditor,
  children,
}: EditableSectionProps<T>): React.JSX.Element {
  const apiBase = resolveApiBaseUrl();
  const [isEditing, setIsEditing] = useState(false);
  const [nlOpen, setNlOpen] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [error, setError] = useState<string | null>(null);

  // Use a ref to track the latest recap_version so back-to-back saves
  // (e.g. NL-edit Apply then immediate pencil edit before the parent
  // re-renders with the new prop) use the freshest If-Match value
  // instead of the version captured at useCallback-creation time.
  const recapVersionRef = useRef<number>(recapVersion);
  useEffect(() => {
    recapVersionRef.current = recapVersion;
  }, [recapVersion]);

  const savePatch = useCallback(
    async (newValue: T, opts?: { editReason?: string; nlPrompt?: string }): Promise<void> => {
      setSaveState('saving');
      setError(null);
      try {
        const res = await authFetchStandalone(
          `${apiBase}/v2/meetings/${twinId}/${meetingId}/recap`,
          {
            method: 'PATCH',
            headers: {
              'Content-Type': 'application/json',
              'If-Match': String(recapVersionRef.current),
            },
            body: JSON.stringify({
              field,
              value: newValue,
              edit_reason: opts?.editReason || 'correction',
              nl_prompt: opts?.nlPrompt || null,
            }),
          },
        );
        if (res.status === 409) {
          setSaveState('error');
          setError('Recap was updated in another tab. Reload to see the latest.');
          throw new Error('version_conflict');
        }
        if (!res.ok) {
          setSaveState('error');
          const body = await res.json().catch(() => null);
          const detail = body?.detail || `Could not save (${res.status})`;
          setError(typeof detail === 'string' ? detail : 'Could not save');
          throw new Error('save_failed');
        }
        const body = await res.json() as {
          status: string;
          data: { recap_version: number; value: T };
        };
        // Update the ref synchronously so the NEXT save uses the new
        // version, even before the parent re-render lands.
        recapVersionRef.current = body.data.recap_version;
        onSaved(body.data.value, body.data.recap_version);
        setSaveState('saved');
        setTimeout(() => setSaveState('idle'), 1500);
      } catch (err: unknown) {
        // Use a functional updater so we don't depend on the (possibly
        // stale) saveState closure value.
        setSaveState((prev) => (prev === 'saved' ? 'saved' : 'error'));
        setError((prev) => prev ?? (err instanceof Error ? err.message : 'Save failed'));
        throw err;
      }
    },
    // saveState is intentionally NOT in deps — we use setSaveState's
    // functional form and recapVersionRef for the cross-save state.
    [apiBase, twinId, meetingId, field, onSaved],
  );

  const commit = useCallback(
    async (newValue: T): Promise<void> => {
      try {
        await savePatch(newValue);
        setIsEditing(false);
      } catch {
        // savePatch already set error state — keep edit mode open
      }
    },
    [savePatch],
  );

  const handleNLApply = useCallback(
    async (proposedValue: T, prompt: string): Promise<void> => {
      await savePatch(proposedValue, { editReason: 'nl_prompt', nlPrompt: prompt });
    },
    [savePatch],
  );

  // The render-prop adapter: convert our internal commit (async) into the
  // sync signature the editor expects. Editors call commit(newValue) and
  // optimistically clear edit-mode after the save completes.
  const editorCommit = useCallback(
    (newValue: T): void => {
      void commit(newValue);
    },
    [commit],
  );

  return (
    <div style={{ position: 'relative' }}>
      {/* Edit affordances — pencil + wand, positioned top-right of the section */}
      <div
        style={{
          position: 'absolute',
          top: 8,
          right: 8,
          display: 'flex',
          gap: 4,
          zIndex: 2,
        }}
      >
        {renderEditor && !isEditing && (
          <IconButton
            label={`Edit ${fieldLabel}`}
            onClick={() => setIsEditing(true)}
            disabled={saveState === 'saving'}
          >
            <PencilIcon />
          </IconButton>
        )}
        {!isEditing && (
          <IconButton
            label={`Edit ${fieldLabel} with a prompt`}
            onClick={() => setNlOpen(true)}
            disabled={saveState === 'saving'}
          >
            <WandIcon />
          </IconButton>
        )}
      </div>

      {/* Body — inline editor when editing, otherwise children */}
      {isEditing && renderEditor ? (
        renderEditor({
          value,
          isEditing,
          commit: editorCommit,
          cancel: () => setIsEditing(false),
          saveState,
        })
      ) : (
        children
      )}

      {/* Save status footer (only when not idle) */}
      {saveState !== 'idle' && (
        <div
          style={{
            marginTop: 8,
            fontSize: 11,
            color:
              saveState === 'error' ? 'var(--rec)' :
              saveState === 'saved' ? 'var(--ok)' :
              'var(--fg-3)',
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {saveState === 'saving' && 'Saving…'}
          {saveState === 'saved' && '✓ Saved'}
          {saveState === 'error' && (error || 'Could not save')}
        </div>
      )}

      <NLEditDialog
        open={nlOpen}
        onClose={() => setNlOpen(false)}
        twinId={twinId}
        meetingId={meetingId}
        field={field}
        fieldLabel={fieldLabel}
        currentValue={value}
        onApply={handleNLApply}
      />
    </div>
  );
}

interface IconButtonProps {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}

function IconButton({ label, onClick, disabled, children }: IconButtonProps): React.JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      disabled={disabled}
      style={{
        width: 28,
        height: 28,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: 8,
        backgroundColor: 'transparent',
        border: '1px solid transparent',
        color: 'var(--fg-2)',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.4 : 1,
        transition: 'background-color 120ms, color 120ms',
      }}
      onMouseEnter={(e) => {
        if (!disabled) e.currentTarget.style.backgroundColor = 'rgba(0,0,0,0.04)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.backgroundColor = 'transparent';
      }}
    >
      {children}
    </button>
  );
}

function PencilIcon(): React.JSX.Element {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path strokeLinecap="round" strokeLinejoin="round" d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
    </svg>
  );
}

function WandIcon(): React.JSX.Element {
  // Sparkle/wand glyph for natural-language edit
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
      <path d="M9.5 3.25a.75.75 0 01.75.75v1.5h1.5a.75.75 0 010 1.5h-1.5v1.5a.75.75 0 01-1.5 0V7h-1.5a.75.75 0 010-1.5h1.5V4a.75.75 0 01.75-.75z" />
      <path d="M18 12a.75.75 0 01.75.75v1.5h1.5a.75.75 0 010 1.5h-1.5v1.5a.75.75 0 01-1.5 0v-1.5h-1.5a.75.75 0 010-1.5h1.5V12.75A.75.75 0 0118 12z" />
      <path d="M14.78 6.22a.75.75 0 010 1.06l-8.5 8.5a.75.75 0 11-1.06-1.06l8.5-8.5a.75.75 0 011.06 0z" />
    </svg>
  );
}
