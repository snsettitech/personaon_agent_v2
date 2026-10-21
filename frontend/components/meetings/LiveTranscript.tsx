'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TranscriptMessage {
  id: string;
  speaker: string;
  text: string;
  timestamp: string;
  isTwin: boolean;
  confidence?: number;
  isDeferral?: boolean;
}

interface LiveTranscriptProps {
  messages: TranscriptMessage[];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function LiveTranscript({ messages }: LiveTranscriptProps): React.JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [hasNewMessages, setHasNewMessages] = useState(false);
  const prevMessageCount = useRef(messages.length);

  // Track scroll position to decide auto-scroll behavior
  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;

    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;

    if (distanceFromBottom > 100) {
      setAutoScroll(false);
    } else if (distanceFromBottom < 50) {
      setAutoScroll(true);
      setHasNewMessages(false);
    }
  }, []);

  // Auto-scroll on new messages
  useEffect(() => {
    if (messages.length > prevMessageCount.current) {
      if (autoScroll) {
        const el = containerRef.current;
        if (el) {
          el.scrollTop = el.scrollHeight;
        }
      } else {
        setHasNewMessages(true);
      }
    }
    prevMessageCount.current = messages.length;
  }, [messages.length, autoScroll]);

  const scrollToBottom = useCallback(() => {
    const el = containerRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
      setAutoScroll(true);
      setHasNewMessages(false);
    }
  }, []);

  // Empty state
  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
          Waiting for meeting participants...
        </p>
      </div>
    );
  }

  return (
    <div className="relative flex flex-1 flex-col overflow-hidden">
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-2 space-y-2"
      >
        {messages.map((msg) => (
          <div
            key={msg.id}
            className="py-1.5"
            style={{
              borderLeft: msg.isTwin
                ? `3px solid ${msg.isDeferral ? 'var(--accent-trust)' : 'var(--primary-500)'}`
                : 'none',
              paddingLeft: msg.isTwin ? '12px' : '0',
            }}
          >
            {/* Speaker + timestamp */}
            <div className="flex items-center gap-2">
              <span
                className="text-xs font-bold"
                style={{
                  color: msg.isTwin ? 'var(--primary-600)' : 'var(--text-muted)',
                }}
              >
                {msg.speaker}
                {msg.isTwin && (
                  <span className="ml-1" style={{ color: 'var(--primary-500)' }}>[AI]</span>
                )}
              </span>
              {msg.isDeferral && (
                <span
                  className="rounded-full px-1.5 py-0.5 text-[10px] font-bold"
                  style={{
                    backgroundColor: 'var(--accent-trust-light)',
                    color: 'var(--accent-trust-dark)',
                  }}
                >
                  Deferred
                </span>
              )}
              <span className="text-[10px]" style={{ color: 'var(--text-tertiary, var(--text-muted))' }}>
                {msg.timestamp}
              </span>
            </div>

            {/* Body */}
            <p
              className="text-sm leading-relaxed mt-0.5"
              style={{
                color: 'var(--text-primary)',
                fontStyle: msg.isDeferral ? 'italic' : 'normal',
              }}
            >
              {msg.text}
            </p>

            {/* Confidence bar for twin messages (non-deferral) */}
            {msg.isTwin && !msg.isDeferral && msg.confidence != null && (
              <div className="flex items-center gap-2 mt-1">
                <div
                  className="h-1 flex-1 rounded-full"
                  style={{ backgroundColor: 'var(--bg-surface)', maxWidth: '120px' }}
                >
                  <div
                    className="h-1 rounded-full"
                    style={{
                      backgroundColor: 'var(--primary-400)',
                      width: `${Math.round(msg.confidence * 100)}%`,
                    }}
                  />
                </div>
                <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                  {Math.round(msg.confidence * 100)}% confident
                </span>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* New messages pill */}
      {hasNewMessages && (
        <button
          type="button"
          onClick={scrollToBottom}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full px-3 py-1 text-xs font-bold cursor-pointer shadow-md"
          style={{
            backgroundColor: 'var(--primary-50)',
            color: 'var(--primary-500)',
          }}
        >
          New messages below
        </button>
      )}
    </div>
  );
}
