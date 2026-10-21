'use client';

import { useState } from 'react';
import { Send } from 'lucide-react';

import { analytics } from '@/lib/analytics/events';

import { SignupWall } from './SignupWall';

const MONO = "'JetBrains Mono', monospace";
const SANS = "'Geist', sans-serif";

interface Msg {
  role: 'user' | 'assistant';
  text: string;
}

export function DemoChat({
  token,
  suggestedQuestions,
  chatLimit,
}: {
  token: string;
  suggestedQuestions: string[];
  chatLimit: number;
}) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [remaining, setRemaining] = useState(chatLimit);
  const [locked, setLocked] = useState(false);
  const [error, setError] = useState('');

  const send = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || sending || locked) return;
    const turnNumber = messages.filter((m) => m.role === 'user').length + 1;
    analytics.experienceChatMessageSent({ turn_number: turnNumber, message_length: trimmed.length });
    setMessages((m) => [...m, { role: 'user', text: trimmed }]);
    setInput('');
    setSending(true);
    setError('');
    try {
      const res = await fetch('/api/demo/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, message: trimmed }),
      });
      if (res.status === 403) {
        analytics.experienceChatLimitReached();
        setLocked(true);
        return;
      }
      const data = (await res.json()) as { reply?: string; remaining?: number; locked?: boolean; error?: string };
      if (!res.ok) throw new Error(data.error || 'The persona had trouble replying.');
      setMessages((m) => [...m, { role: 'assistant', text: data.reply ?? '' }]);
      if (typeof data.remaining === 'number') setRemaining(data.remaining);
      if (data.locked) {
        analytics.experienceChatLimitReached();
        setLocked(true);
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : 'The persona had trouble replying.';
      analytics.experienceChatMessageFailed({ error: message });
      setError(message);
    } finally {
      setSending(false);
    }
  };

  return (
    <div style={{ borderRadius: 24, border: '1px solid rgba(29,29,31,0.08)', background: 'var(--fog-2)', overflow: 'hidden' }}>
      <div className="flex items-center gap-2 px-5 py-3.5" style={{ borderBottom: '1px solid rgba(29,29,31,0.06)' }}>
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: '#2BB673' }} aria-hidden />
        <span className="text-[10px] uppercase tracking-[0.16em]" style={{ color: 'var(--fg-2)', fontFamily: MONO }}>
          Chat with this persona
        </span>
        {!locked && (
          <span className="ml-auto text-[11px]" style={{ color: 'var(--fg-3)', fontFamily: MONO }}>
            {remaining} demo replies left
          </span>
        )}
      </div>

      <div className="space-y-3 overflow-y-auto p-5" style={{ maxHeight: 320 }}>
        {messages.length === 0 && (
          <div className="flex flex-col gap-2">
            {suggestedQuestions.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => void send(q)}
                className="flex items-center justify-between gap-3 px-4 py-3 text-left text-[13.5px] transition-colors hover:bg-white"
                style={{ borderRadius: 14, border: '1px solid rgba(29,29,31,0.10)', background: 'var(--fog-3)', color: 'var(--fg)', fontFamily: SANS }}
              >
                <span>{q}</span>
                <span aria-hidden style={{ color: 'var(--fg-3)' }}>
                  &rsaquo;
                </span>
              </button>
            ))}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className="max-w-[82%] px-4 py-2.5 text-[13.5px] leading-[1.5]"
              style={
                m.role === 'user'
                  ? { borderRadius: 14, background: 'var(--ink)', color: '#fff', fontFamily: SANS }
                  : { borderRadius: 14, background: 'var(--fog-3)', border: '1px solid rgba(29,29,31,0.08)', color: 'var(--fg)', fontFamily: SANS }
              }
            >
              {m.text}
            </div>
          </div>
        ))}
        {sending && (
          <p className="text-[12px]" style={{ color: 'var(--fg-3)', fontFamily: MONO }}>
            thinking…
          </p>
        )}
      </div>

      {locked ? (
        <div className="p-5" style={{ borderTop: '1px solid rgba(29,29,31,0.06)' }}>
          <SignupWall
            title="That's the demo limit"
            subtitle="Sign up free to keep the conversation going with your full persona."
            context="chat_locked"
          />
        </div>
      ) : (
        <div className="p-4" style={{ borderTop: '1px solid rgba(29,29,31,0.06)' }}>
          {error && (
            <p className="mb-2 text-[12px]" style={{ color: '#c0392b', fontFamily: SANS }}>
              {error}
            </p>
          )}
          <div className="flex items-center gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void send(input);
              }}
              placeholder="Ask the persona something…"
              disabled={sending}
              className="min-w-0 flex-1 px-4 text-[13.5px] outline-none disabled:opacity-50"
              style={{ height: 46, borderRadius: 999, border: '1px solid rgba(29,29,31,0.12)', background: 'var(--fog-3)', color: 'var(--fg)', fontFamily: SANS }}
            />
            <button
              type="button"
              onClick={() => void send(input)}
              disabled={sending || !input.trim()}
              className="flex items-center justify-center rounded-full transition-opacity disabled:opacity-40"
              style={{ height: 46, width: 46, background: 'var(--ink)', color: '#fff' }}
              aria-label="Send"
            >
              <Send size={15} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
