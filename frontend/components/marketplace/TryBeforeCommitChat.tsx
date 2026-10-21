'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { resolveApiBaseUrl } from '@/lib/api';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_ANON_MESSAGES = 3;

const countKey = (twinId: string) => `anon_chat_${twinId}_count`;
const convKey = (twinId: string) => `anon_conv_${twinId}_id`;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TryBeforeCommitChatProps {
  twinId: string;
  shareToken: string;
  handle: string;
  personaName: string;
  personaAvatar?: string;
}

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

// ---------------------------------------------------------------------------
// localStorage / sessionStorage helpers (adapted from DemoChat.tsx pattern)
// ---------------------------------------------------------------------------

function readAnonCount(twinId: string): number {
  try {
    return parseInt(localStorage.getItem(countKey(twinId)) || '0', 10);
  } catch {
    return 0;
  }
}

function writeAnonCount(twinId: string, count: number): void {
  try {
    localStorage.setItem(countKey(twinId), String(count));
  } catch {
    // SSR or storage unavailable — silent fail
  }
}

function saveConversationId(twinId: string, conversationId: string): void {
  try {
    sessionStorage.setItem(convKey(twinId), conversationId);
  } catch {
    // ignore
  }
}

function readSavedConversationId(twinId: string): string | null {
  try {
    return sessionStorage.getItem(convKey(twinId));
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Initials helper
// ---------------------------------------------------------------------------

function getInitials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function TryBeforeCommitChat({
  twinId,
  shareToken,
  handle,
  personaName,
  personaAvatar,
}: TryBeforeCommitChatProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [messageCount, setMessageCount] = useState(0);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const showOverlay = messageCount >= MAX_ANON_MESSAGES;

  // Initialize from localStorage and add greeting
  useEffect(() => {
    const storedCount = readAnonCount(twinId);
    setMessageCount(storedCount);
    setMessages([
      {
        role: 'assistant',
        content: `Hi! I'm ${personaName}. Ask me anything — I'll answer from my published expertise.`,
      },
    ]);
  }, [twinId, personaName]);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  const sendMessage = async () => {
    const text = input.trim();
    if (showOverlay || isLoading || !text) return;

    const userMessage: Message = { role: 'user', content: text };
    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    const nextCount = messageCount + 1;
    setMessageCount(nextCount);
    writeAnonCount(twinId, nextCount);

    const apiBaseUrl = resolveApiBaseUrl();

    try {
      const response = await fetch(`${apiBaseUrl}/v2/chat/public/${twinId}/${shareToken}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, conversation_id: conversationId }),
      });

      if (response.status === 429) {
        // Server-side rate limit hit — show overlay immediately
        setMessageCount(MAX_ANON_MESSAGES);
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: 'You have reached the anonymous chat limit. Please sign up to continue.',
          },
        ]);
        return;
      }

      if (response.ok) {
        const data = await response.json();
        const newConvId = data.conversation_id as string | null;
        if (newConvId) {
          setConversationId(newConvId);
          // Save immediately to prevent race condition on navigation
          saveConversationId(twinId, newConvId);
        }
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: (data.message as string) || 'No response received.' },
        ]);
      } else {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: "Sorry, I'm having trouble connecting right now. Please try again.",
          },
        ]);
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: "Sorry, I'm having trouble connecting right now. Please try again.",
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    void sendMessage();
  };

  // Build signup URL with conversation continuity
  const convId = readSavedConversationId(twinId) || conversationId;
  const signupUrl = convId
    ? `/auth/signup?redirect=/p/${handle}&conv=${convId}`
    : `/auth/signup?redirect=/p/${handle}`;

  const initials = getInitials(personaName) || 'P';

  return (
    <div
      className="relative rounded-[20px] border overflow-hidden"
      style={{
        borderColor: 'var(--border-default)',
        backgroundColor: 'var(--bg-elevated)',
        boxShadow: 'var(--shadow-lg)',
      }}
    >
      {/* Header bar */}
      <div
        className="flex items-center gap-3 px-4 py-3 border-b"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-subtle)',
        }}
      >
        {/* Avatar */}
        {personaAvatar ? (
          <img
            src={personaAvatar}
            alt={personaName}
            className="h-8 w-8 shrink-0 rounded-full object-cover"
          />
        ) : (
          <div
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white"
            style={{ background: 'linear-gradient(135deg, #F59E0B, #EA580C)' }}
            aria-hidden="true"
          >
            {initials}
          </div>
        )}

        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold leading-tight" style={{ color: 'var(--text-primary)' }}>
            {personaName}
          </p>
        </div>

        {/* Live badge */}
        <span
          className="flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full shrink-0"
          style={{
            backgroundColor: 'rgba(5,150,105,0.1)',
            color: 'var(--accent-emerald)',
          }}
        >
          <span
            className="h-1.5 w-1.5 rounded-full animate-pulse"
            style={{ backgroundColor: 'var(--accent-emerald)' }}
          />
          Live
        </span>
      </div>

      {/* Messages area */}
      <div
        className="max-h-[300px] overflow-y-auto px-4 py-3 space-y-3"
        style={{ backgroundColor: 'var(--bg-base)' }}
        aria-live="polite"
        aria-label="Chat messages"
      >
        {messages.map((msg, i) =>
          msg.role === 'assistant' ? (
            <div key={i} className="flex items-start gap-2">
              {personaAvatar ? (
                <img
                  src={personaAvatar}
                  alt={personaName}
                  className="shrink-0 h-6 w-6 rounded-full object-cover"
                />
              ) : (
                <div
                  className="shrink-0 flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-bold text-white"
                  style={{ background: 'linear-gradient(135deg, #F59E0B, #EA580C)' }}
                  aria-hidden="true"
                >
                  {initials}
                </div>
              )}
              <div
                className="rounded-[14px] rounded-tl-sm px-3 py-2 text-sm border"
                style={{
                  backgroundColor: 'var(--bg-elevated)',
                  borderColor: 'var(--border-subtle)',
                  color: 'var(--text-primary)',
                }}
              >
                {msg.content}
              </div>
            </div>
          ) : (
            <div key={i} className="flex justify-end">
              <div
                className="rounded-[14px] rounded-tr-sm px-3 py-2 text-sm border"
                style={{
                  backgroundColor: 'rgba(13,148,136,0.1)',
                  borderColor: 'rgba(13,148,136,0.2)',
                  color: 'var(--text-primary)',
                }}
              >
                {msg.content}
              </div>
            </div>
          )
        )}

        {/* Thinking indicator */}
        {isLoading && (
          <div className="flex items-start gap-2">
            {personaAvatar ? (
              <img
                src={personaAvatar}
                alt={personaName}
                className="shrink-0 h-6 w-6 rounded-full object-cover"
              />
            ) : (
              <div
                className="shrink-0 flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-bold text-white"
                style={{ background: 'linear-gradient(135deg, #F59E0B, #EA580C)' }}
                aria-hidden="true"
              >
                {initials}
              </div>
            )}
            <div className="flex items-center gap-2 px-3 py-2">
              <div className="flex gap-1">
                <span
                  className="h-1.5 w-1.5 rounded-full animate-pulse"
                  style={{ backgroundColor: 'var(--primary-500)', animationDelay: '0ms' }}
                />
                <span
                  className="h-1.5 w-1.5 rounded-full animate-pulse"
                  style={{ backgroundColor: 'var(--primary-500)', animationDelay: '150ms' }}
                />
                <span
                  className="h-1.5 w-1.5 rounded-full animate-pulse"
                  style={{ backgroundColor: 'var(--primary-500)', animationDelay: '300ms' }}
                />
              </div>
              <span className="text-xs" style={{ color: 'var(--text-tertiary)' }}>
                {personaName} is thinking...
              </span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Message counter */}
      {!showOverlay && (
        <div
          className="px-4 py-1 text-xs text-right"
          style={{ color: 'var(--text-tertiary)', backgroundColor: 'var(--bg-base)' }}
        >
          {MAX_ANON_MESSAGES - messageCount} free {MAX_ANON_MESSAGES - messageCount === 1 ? 'message' : 'messages'} remaining
        </div>
      )}

      {/* Input bar */}
      <form
        onSubmit={handleSubmit}
        className="flex items-center gap-3 px-4 py-3 border-t"
        style={{
          backgroundColor: 'var(--bg-elevated)',
          borderColor: 'var(--border-subtle)',
        }}
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={`Ask ${personaName} anything...`}
          disabled={showOverlay || isLoading}
          className="flex-1 bg-transparent text-sm focus:outline-none"
          style={{ color: 'var(--text-primary)' }}
          aria-label="Message input"
        />
        <button
          type="submit"
          disabled={!input.trim() || isLoading || showOverlay}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-opacity disabled:opacity-40"
          style={{ backgroundColor: 'var(--primary-500)' }}
          aria-label="Send message"
        >
          <svg
            className="h-4 w-4 text-white"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
              d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
            />
          </svg>
        </button>
      </form>

      {/* Rate limit overlay */}
      {showOverlay && (
        <div
          className="absolute inset-0 flex items-center justify-center"
          style={{ backgroundColor: 'var(--bg-overlay)', backdropFilter: 'blur(4px)' }}
        >
          <div
            className="mx-4 rounded-[20px] px-8 py-8 text-center shadow-xl"
            style={{
              backgroundColor: 'var(--bg-elevated)',
              border: '1px solid var(--border-default)',
            }}
          >
            <h3
              className="mb-2 text-lg font-semibold"
              style={{
                fontFamily: "'Playfair Display', Georgia, serif",
                color: 'var(--text-primary)',
              }}
            >
              Enjoying the conversation?
            </h3>
            <p className="mb-5 text-sm" style={{ color: 'var(--text-secondary)' }}>
              Create a free account to keep chatting — your conversation is saved.
            </p>
            <Link
              href={signupUrl}
              className="inline-block rounded-full px-6 py-3 text-sm font-semibold text-white transition-opacity hover:opacity-90"
              style={{ backgroundColor: 'var(--accent-cta)' }}
            >
              Continue for Free
            </Link>
            <p className="mt-3 text-xs" style={{ color: 'var(--text-tertiary)' }}>
              No credit card required
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
