'use client';

import React, { useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';

export interface Citation {
  id: string;
  filename?: string | null;
  citation_url?: string | null;
  chunk_preview?: string;
}

interface CitationsDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  citations: Citation[];
}

export function CitationsDrawer({ isOpen, onClose, citations }: CitationsDrawerProps) {
  const drawerRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  // Handle escape key
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      onClose();
    }
  }, [onClose]);

  // Lock body scroll when open
  useEffect(() => {
    if (isOpen) {
      // Store previously focused element
      previouslyFocusedRef.current = document.activeElement as HTMLElement;

      // Lock scroll
      const originalStyle = window.getComputedStyle(document.body).overflow;
      document.body.style.overflow = 'hidden';

      // Add escape key listener
      document.addEventListener('keydown', handleKeyDown);

      // Focus close button after animation
      const timer = setTimeout(() => {
        closeButtonRef.current?.focus();
      }, 100);

      return () => {
        document.body.style.overflow = originalStyle;
        document.removeEventListener('keydown', handleKeyDown);
        clearTimeout(timer);
      };
    } else {
      // Restore focus when closing
      if (previouslyFocusedRef.current) {
        previouslyFocusedRef.current.focus();
      }
    }
  }, [isOpen, handleKeyDown]);

  // Handle backdrop click
  const handleBackdropClick = useCallback((e: React.MouseEvent) => {
    // Only close if clicking the backdrop itself, not the drawer
    if (e.target === e.currentTarget) {
      onClose();
    }
  }, [onClose]);

  if (!isOpen || typeof document === 'undefined') return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[100]"
      onClick={handleBackdropClick}
      role="dialog"
      aria-modal="true"
      aria-labelledby="citations-title"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/35 backdrop-blur-sm transition-opacity animate-in fade-in duration-200"
        aria-hidden="true"
      />

      {/* Drawer */}
      <div
        ref={drawerRef}
        className="absolute bottom-0 right-0 top-0 flex h-full w-full max-w-[440px] transform flex-col bg-[var(--bg-card)] shadow-2xl transition-transform duration-300 ease-out animate-in slide-in-from-right"
      >
        <div className="flex flex-col h-full">
          {/* Header */}
          <div className="flex shrink-0 items-center justify-between border-b border-[var(--border-subtle)] p-6">
            <div>
              <h2 id="citations-title" className="text-lg font-bold text-[var(--text-primary)]">Sources</h2>
              <p className="text-sm text-[var(--text-muted)] mt-1">
                {citations.length} source{citations.length !== 1 ? 's' : ''} referenced
              </p>
            </div>
            <button
              ref={closeButtonRef}
              onClick={onClose}
              className="p-2 rounded-xl text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-surface)] hover:text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--primary-500)]"
              aria-label="Close drawer"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto bg-[var(--bg-surface)] p-6">
            {citations.length === 0 ? (
              <div className="text-center py-12">
                <div className="w-16 h-16 bg-[var(--bg-card)] rounded-2xl flex items-center justify-center mx-auto mb-4">
                  <svg className="w-8 h-8 text-[var(--text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
                  </svg>
                </div>
                <p className="text-[var(--text-secondary)]">No sources available for this response</p>
                <p className="text-sm text-[var(--text-muted)] mt-2">
                  Try asking a question about your uploaded documents
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {citations.map((citation, index) => (
                  <div
                    key={citation.id}
                    className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 shadow-sm transition-colors hover:border-[rgba(30,124,255,0.35)] focus-within:ring-2 focus-within:ring-[var(--primary-500)]"
                    tabIndex={0}
                  >
                    <div className="flex items-start gap-3">
                      <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-[var(--primary-100)] text-sm font-bold text-[var(--primary-700)]">
                        {index + 1}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <p className="font-medium text-[var(--text-primary)] break-words">
                            {citation.filename || 'Unknown Source'}
                          </p>
                        </div>

                        {citation.citation_url && (
                          <a
                            href={citation.citation_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="mt-2 inline-flex items-center gap-1 text-sm text-[var(--primary-600)] hover:text-[var(--primary-700)] hover:underline"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                            </svg>
                            View source
                          </a>
                        )}
                        <p className="mt-2 text-xs text-[var(--text-muted)] font-mono">
                          Source ID: {citation.id.slice(0, 8)}...
                        </p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="shrink-0 border-t border-[var(--border-subtle)] bg-[var(--bg-card)] p-6">
            <button
              onClick={onClose}
              className="w-full rounded-xl bg-[var(--ink)] py-3 font-semibold text-white transition-colors hover:bg-[var(--ink-2)] focus:outline-none focus:ring-2 focus:ring-[var(--primary-500)]"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}

// Inline citation component — Wikipedia-style [n] with hover tooltip
interface InlineCitationProps {
  number: number;
  sourceName?: string;
  chunkPreview?: string;
  citationUrl?: string | null;
  onClick: () => void;
}

export function InlineCitation({ number, sourceName, chunkPreview, citationUrl, onClick }: InlineCitationProps) {
  const tooltipLines: string[] = [];
  if (sourceName) tooltipLines.push(sourceName);
  if (citationUrl) tooltipLines.push(citationUrl);
  if (chunkPreview) tooltipLines.push(`"${chunkPreview.slice(0, 120)}…"`);
  const tooltip = tooltipLines.join('\n');

  return (
    <button
      onClick={onClick}
      className="inline text-[10px] font-semibold text-teal-600 hover:text-teal-800 hover:underline
        align-super leading-none ml-px cursor-pointer
        focus:outline-none"
      title={tooltip}
      aria-label={`Citation ${number}${sourceName ? ` — ${sourceName}` : ''}`}
      type="button"
    >
      [{number}]
    </button>
  );
}

// Parse content and insert inline citations
export function parseCitations(
  content: string,
  citations: Citation[],
  onCitationClick: (index: number) => void
): React.ReactNode[] {
  if (!citations || citations.length === 0) {
    return [<span key="content">{content}</span>];
  }

  const parts: React.ReactNode[] = [];
  let lastIndex = 0;

  // Simple regex to find citation markers like [source:uuid] or [1], [2]
  // This is a basic implementation - can be enhanced based on actual citation format
  const citationRegex = /\[(?:source:)?([a-f0-9-]{36}|\d+)\]/gi;
  let match;
  let citationIndex = 0;

  while ((match = citationRegex.exec(content)) !== null && citationIndex < citations.length) {
    // Add text before citation
    if (match.index > lastIndex) {
      parts.push(
        <span key={`text-${lastIndex}`}>
          {content.slice(lastIndex, match.index)}
        </span>
      );
    }

    // Add citation marker
    const currentIndex = citationIndex;
    parts.push(
      <InlineCitation
        key={`cite-${match.index}`}
        number={currentIndex + 1}
        sourceName={citations[currentIndex]?.filename ?? undefined}
        onClick={() => onCitationClick(currentIndex)}
      />
    );

    lastIndex = match.index + match[0].length;
    citationIndex++;
  }

  // Add remaining text
  if (lastIndex < content.length) {
    parts.push(<span key={`text-${lastIndex}`}>{content.slice(lastIndex)}</span>);
  }

  // If no citations found in text, append them at the end
  if (parts.length === 1 && citations.length > 0) {
    parts.push(
      <span key="citations" className="inline-flex gap-1 ml-1">
        {citations.map((citation, idx) => (
          <InlineCitation
            key={`end-cite-${idx}`}
            number={idx + 1}
            sourceName={citation.filename ?? undefined}
            onClick={() => onCitationClick(idx)}
          />
        ))}
      </span>
    );
  }

  return parts;
}
