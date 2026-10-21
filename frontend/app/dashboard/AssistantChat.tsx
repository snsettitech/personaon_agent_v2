'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { LucideIcon } from 'lucide-react';
import { resolveApiBaseUrl, getChatAuthToken } from '@/lib/api';
import { parseChatStream } from '@/lib/chat/streamParser';

// Stable plugin reference so ReactMarkdown can bail out of re-parsing on every
// streamed chunk (a new [remarkGfm] literal each render would defeat that).
const REMARK_PLUGINS = [remarkGfm];

export interface AssistantSuggestion {
  key: string;
  /** Lucide glyph rendered before the label. Muted ink (var(--fg-2)), never status/accent color. */
  icon?: LucideIcon;
  label: string;
  hint?: string;
  /** Sends this prompt to the assistant. Ignored if onClick is set. */
  prompt?: string;
  /** Overrides prompt — e.g. navigate somewhere instead of chatting. */
  onClick?: () => void;
}

interface ChatMsg {
  role: 'user' | 'assistant';
  content: string;
}

interface AssistantChatProps {
  twinId: string;
  prefill?: string | null;
  heading?: string;
  subtitle?: string;
  suggestions?: AssistantSuggestion[];
  /** Rendered under the suggestions on the empty hero only (e.g. status cards). */
  belowSuggestions?: React.ReactNode;
  /** Owner avatar for the empty-state hero mark (the persona this Home is about). */
  markImageUrl?: string;
  /** Initials fallback when there is no avatar (e.g. "SS"). */
  markInitials?: string;
}

/**
 * ChatGPT-style chief-of-staff chat for the Assistant Home.
 *
 * Two states, both living in the dashboard's scrolling <main> (no fixed-height
 * box — that created dead space):
 *  - EMPTY: a centered hero — owner mark, heading, the composer as the focal
 *    point, contextual suggestion chips, then the "what's happening" cards.
 *  - ACTIVE: messages flow top-down; the same composer sticks to the bottom.
 *
 * Owner-facing: streams from /v2/chat/assistant/{twin}/stream (the chief-of-staff
 * agent that talks TO the owner about their persona), via the shared parseChatStream.
 */
export default function AssistantChat({
  twinId,
  prefill,
  heading = 'What should your persona do today?',
  subtitle,
  suggestions = [],
  belowSuggestions,
  markImageUrl,
  markInitials,
}: AssistantChatProps) {
  const apiBaseUrl = useMemo(() => resolveApiBaseUrl(), []);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const conversationIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  // Synchronous guards (read/written without a render) — avoid the stale-closure
  // double-send race and setState-after-unmount.
  const loadingRef = useRef(false);
  const mountedRef = useRef(true);

  const isEmpty = messages.length === 0;

  useEffect(() => {
    if (!isEmpty) bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, isEmpty]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
    };
  }, []);

  // Switching twins must start a fresh conversation thread. (The parent also
  // remounts via key, but this keeps the ref correct if that ever changes.)
  useEffect(() => {
    conversationIdRef.current = null;
  }, [twinId]);

  // A chip/job click can prefill the composer (owner edits, then sends).
  useEffect(() => {
    const next = (prefill || '').trim();
    if (next) {
      setInput(next);
      inputRef.current?.focus();
    }
  }, [prefill]);

  const send = useCallback(
    async (raw: string) => {
      const text = raw.trim();
      if (!text || loadingRef.current) return;
      loadingRef.current = true;
      setError(null);
      setInput('');
      setMessages((prev) => [...prev, { role: 'user', content: text }, { role: 'assistant', content: '' }]);
      setLoading(true);

      const controller = new AbortController();
      abortRef.current = controller;

      const appendToAssistant = (chunk: string) => {
        if (!mountedRef.current) return;
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last && last.role === 'assistant') next[next.length - 1] = { ...last, content: last.content + chunk };
          return next;
        });
      };

      try {
        const token = await getChatAuthToken();
        const headers: Record<string, string> = { 'Content-Type': 'application/json' };
        if (token) headers.Authorization = `Bearer ${token}`;

        const res = await fetch(`${apiBaseUrl}/v2/chat/assistant/${twinId}/stream`, {
          method: 'POST',
          headers,
          body: JSON.stringify({ message: text, conversation_id: conversationIdRef.current }),
          signal: controller.signal,
        });
        if (!res.ok || !res.body) throw new Error(`Request failed (${res.status})`);

        await parseChatStream(
          res.body,
          {
            onMetadata: (d) => {
              const sid = d.session_id as string | undefined;
              if (sid) conversationIdRef.current = sid;
            },
            onContent: (d) => { if (d.content) appendToAssistant(d.content); },
            onError: () => { if (mountedRef.current) setError('Something went wrong. Please try again.'); },
          },
          { signal: controller.signal },
        );
      } catch (err) {
        if (mountedRef.current && (err as Error)?.name !== 'AbortError') {
          setError(err instanceof Error ? err.message : 'Something went wrong.');
        }
      } finally {
        loadingRef.current = false;
        if (mountedRef.current) {
          setLoading(false);
          // Drop a trailing empty assistant bubble if nothing streamed (error or
          // empty response) so a blank row never lingers; the error banner shows
          // the failure separately.
          setMessages((prev) =>
            prev.length &&
            prev[prev.length - 1].role === 'assistant' &&
            !prev[prev.length - 1].content
              ? prev.slice(0, -1)
              : prev,
          );
        }
      }
    },
    [apiBaseUrl, twinId],
  );

  const onSuggestion = (s: AssistantSuggestion) => {
    if (s.onClick) s.onClick();
    else if (s.prompt) void send(s.prompt);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void send(input);
    }
  };

  const composer = (
    <div className="flex items-end gap-2 rounded-[26px] border border-[var(--fog-line-2)] bg-[var(--fog-2)] px-2.5 py-2 transition focus-within:border-[var(--signal)]">
      <textarea
        ref={inputRef}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={onKeyDown}
        rows={1}
        placeholder="Ask me anything, or tell me what to do…"
        className="max-h-44 flex-1 resize-none bg-transparent px-3 py-2 text-[15px] text-[var(--ink)] outline-none placeholder:text-[var(--fg-2)]"
      />
      <button
        type="button"
        onClick={() => void send(input)}
        disabled={loading || !input.trim()}
        aria-label="Send message"
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[var(--signal)] text-base text-white transition hover:bg-[var(--signal-hot)] disabled:cursor-not-allowed disabled:opacity-25"
      >
        ↑
      </button>
    </div>
  );

  if (isEmpty) {
    return (
      <div className="mx-auto w-full max-w-2xl px-4 pb-16 pt-[4vh] text-center">
        <div
          aria-hidden
          className="mx-auto flex h-12 w-12 items-center justify-center overflow-hidden rounded-[14px] bg-[var(--ink)] text-white"
        >
          {markImageUrl ? (
            <img src={markImageUrl} alt="" className="h-full w-full object-cover" />
          ) : (
            <span className="font-display text-[22px] leading-none">{markInitials || 'P'}</span>
          )}
        </div>
        <h1 className="mt-6 text-[28px] font-semibold tracking-tight text-[var(--ink)] md:text-[32px]">
          {heading}
        </h1>
        {subtitle && (
          <p className="mx-auto mt-2.5 max-w-xl text-[15px] leading-relaxed text-[var(--fg-2)]">{subtitle}</p>
        )}

        <div className="mt-7 text-left">{composer}</div>
        {error && <p className="mt-2 text-center text-xs text-[var(--rec)]">{error}</p>}

        {suggestions.length > 0 && (
          <div className="mt-4 flex flex-wrap justify-center gap-2">
            {suggestions.map((s) => (
              <button
                key={s.key}
                type="button"
                onClick={() => onSuggestion(s)}
                disabled={loading}
                className="inline-flex items-center gap-1.5 rounded-full border border-[var(--fog-line-2)] bg-[var(--fog-2)] px-3.5 py-2 text-sm text-[var(--fg-2)] transition hover:bg-[var(--fog-3)] disabled:opacity-50"
              >
                {s.icon && <s.icon aria-hidden className="h-4 w-4 text-[var(--fg-2)]" />}
                <span className="font-medium text-[var(--ink)]">{s.label}</span>
                {s.hint && <span className="text-[var(--fg-2)]">· {s.hint}</span>}
              </button>
            ))}
          </div>
        )}

        {belowSuggestions && <div className="mt-12 text-left">{belowSuggestions}</div>}
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-2xl px-4">
      <div className="space-y-6 py-6" aria-live="polite">
        {messages.map((m, i) =>
          m.role === 'user' ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-[85%] whitespace-pre-wrap rounded-3xl bg-[var(--fog)] px-4 py-2.5 text-[15px] leading-relaxed text-[var(--ink)]">
                {m.content}
              </div>
            </div>
          ) : (
            <div key={i} className="text-[15px] leading-relaxed text-[var(--ink)]">
              {m.content ? (
                <div className="prose prose-sm prose-neutral max-w-none">
                  <ReactMarkdown remarkPlugins={REMARK_PLUGINS}>{m.content}</ReactMarkdown>
                </div>
              ) : (
                loading && <span className="animate-pulse text-[var(--fg-2)]" aria-label="Assistant is typing">●</span>
              )}
            </div>
          ),
        )}
        {/* Spacer so the last message clears the sticky composer after autoscroll. */}
        <div ref={bottomRef} className="h-28" />
      </div>

      <div className="sticky bottom-0 -mx-4 bg-gradient-to-t from-[var(--fog)] via-[var(--fog)] to-transparent px-4 pb-4 pt-6">
        {error && <p className="mb-2 text-center text-xs text-[var(--rec)]">{error}</p>}
        {composer}
        <p className="mt-2 text-center text-[11px] text-[var(--fg-chrome)]">
          Drafts are saved for your approval — nothing is sent without you.
        </p>
      </div>
    </div>
  );
}
