'use client';

import React, { useEffect, useRef } from 'react';

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  /** Optional footer slot for actions, rendered with a top border. */
  footer?: React.ReactNode;
  /** Pixel width of the modal panel. Defaults to 480. */
  width?: number;
}

/**
 * Minimal modal shell. Reused across Wave 5 (Share recap) and Wave 7
 * (Natural-language recap edit). ESC closes, click-outside closes,
 * focus is moved to the dialog on open, body scroll is locked.
 *
 * Intentionally no animation library — pure CSS for the fade.
 */
export default function Dialog({
  open,
  onClose,
  title,
  children,
  footer,
  width = 480,
}: DialogProps): React.JSX.Element | null {
  const panelRef = useRef<HTMLDivElement | null>(null);

  // Lock body scroll while open
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  // ESC closes
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  // Move focus to panel when opening
  useEffect(() => {
    if (open && panelRef.current) {
      panelRef.current.focus();
    }
  }, [open]);

  if (!open) return null;

  return (
    <div
      onClick={onClose}
      role="presentation"
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(29,29,31,0.45)',
        backdropFilter: 'blur(4px)',
        WebkitBackdropFilter: 'blur(4px)',
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'center',
        paddingTop: '10vh',
        zIndex: 100,
        animation: 'dialogFadeIn 150ms ease-out',
      }}
    >
      <style jsx global>{`
        @keyframes dialogFadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        @keyframes dialogPanelIn {
          from { opacity: 0; transform: translateY(-8px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
      <div
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? 'dialog-title' : undefined}
        onClick={(e) => e.stopPropagation()}
        style={{
          width: `min(${width}px, calc(100vw - 32px))`,
          maxHeight: 'calc(100vh - 20vh)',
          overflowY: 'auto',
          backgroundColor: 'var(--fog-2)',
          borderRadius: '24px',
          boxShadow: '0 24px 70px rgba(0,0,0,0.18), 0 2px 8px rgba(29,29,31,0.06)',
          outline: 'none',
          animation: 'dialogPanelIn 180ms cubic-bezier(.2,.7,.2,1)',
        }}
      >
        {title && (
          <div
            style={{
              padding: '20px 24px 12px 24px',
              borderBottom: '1px solid var(--fog-line)',
            }}
          >
            <h2
              id="dialog-title"
              style={{
                fontSize: '17px',
                fontWeight: 600,
                color: 'var(--ink)',
                letterSpacing: '-0.012em',
                margin: 0,
              }}
            >
              {title}
            </h2>
          </div>
        )}
        <div style={{ padding: '20px 24px' }}>{children}</div>
        {footer && (
          <div
            style={{
              padding: '14px 24px 18px 24px',
              borderTop: '1px solid var(--fog-line)',
              display: 'flex',
              justifyContent: 'flex-end',
              gap: '8px',
            }}
          >
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
