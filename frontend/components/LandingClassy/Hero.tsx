'use client';

import Link from 'next/link';
import { FormEvent, useEffect, useRef, useState } from 'react';
import { Mic, Send } from 'lucide-react';
import { analytics } from '@/lib/analytics/events';

const DEMO_TWIN_ID = process.env.NEXT_PUBLIC_DEMO_TWIN_ID || '';
const DEMO_SHARE_TOKEN = process.env.NEXT_PUBLIC_DEMO_SHARE_TOKEN || '';
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';
const MAX_DEMO_MESSAGES = 5;
const STORAGE_KEY = 'personaon_landing_demo_count';

const TRY_ASKING = [
  'What can a portfolio that answers actually do?',
  'What can my page do that LinkedIn can’t?',
  'How is this different from a website builder?',
];

interface Message {
  role: 'persona' | 'user';
  content: string;
}

const OPENING_MESSAGE: Message = {
  role: 'persona',
  content:
    'Hi — I’m a live PersonaOn demo. Ask me what a portfolio that answers can do, how it’s built from your resume, or what visitors experience on your page.',
};

function readStoredCount(): number {
  if (typeof window === 'undefined') return 0;
  try {
    return Number.parseInt(localStorage.getItem(STORAGE_KEY) || '0', 10);
  } catch {
    return 0;
  }
}

function writeStoredCount(count: number): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(STORAGE_KEY, String(count));
  } catch {
    // Storage unavailable in private browsing — accept and continue.
  }
}

function previewReply(input: string): string {
  const n = input.toLowerCase();
  if (n.includes('do') && (n.includes('what can') || n.includes('actually'))) {
    return 'Your page answers questions about your work in your voice, books meetings straight into your calendar, and shows you every conversation — so the people checking you out get real answers instead of a static PDF.';
  }
  if (n.includes('linkedin') || n.includes('profile') || n.includes('resume')) {
    return 'LinkedIn lists what you’ve done. PersonaOn lets people ask about it. The same story, but interactive — a recruiter can ask "tell me about that 2022 launch" and hear it the way you’d explain it.';
  }
  if (n.includes('builder') || n.includes('website') || n.includes('different') || n.includes('chatbot')) {
    return 'A website builder gives you another static page. This one talks back — every reply traces to material you approved, it defers when it doesn’t know, and it never invents. Not a chatbot widget; a portfolio that speaks for you.';
  }
  if (n.includes('create') || n.includes('start') || n.includes('how do i') || n.includes('built')) {
    return 'Paste your resume — or drop the PDF. Your portfolio assembles itself in about a minute. You see it answer a question about you, then claim personaon.com/yourname and share it.';
  }
  return 'PersonaOn is a portfolio that answers for you. The version of you online finally does some of the work — answering questions, booking meetings, and capturing interest while you sleep.';
}

export default function Hero() {
  const isConfigured = Boolean(DEMO_TWIN_ID && DEMO_SHARE_TOKEN && API_BASE_URL);
  const [messages, setMessages] = useState<Message[]>([OPENING_MESSAGE]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [messageCount, setMessageCount] = useState(0);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [hasStarted, setHasStarted] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);

  const demoLimitReached = messageCount >= MAX_DEMO_MESSAGES;
  const hasUserMessage = messages.some((m) => m.role === 'user');

  useEffect(() => {
    setMessageCount(readStoredCount());
  }, []);

  useEffect(() => {
    if (scrollerRef.current) {
      scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
    }
  }, [messages, isLoading]);

  const sendMessage = async (override?: string) => {
    const text = (override ?? input).trim();
    if (!text || isLoading || demoLimitReached) return;

    if (!hasStarted) {
      setHasStarted(true);
      analytics.landingDemoChatStarted();
    }

    setMessages((prev) => [...prev, { role: 'user', content: text }]);
    setInput('');
    setIsLoading(true);

    const nextCount = messageCount + 1;
    setMessageCount(nextCount);
    writeStoredCount(nextCount);

    if (!isConfigured) {
      window.setTimeout(() => {
        setMessages((prev) => [
          ...prev,
          { role: 'persona', content: previewReply(text) },
        ]);
        setIsLoading(false);
      }, 420);
      return;
    }

    try {
      const response = await fetch(
        `${API_BASE_URL}/v2/chat/public/${DEMO_TWIN_ID}/${DEMO_SHARE_TOKEN}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text, conversation_id: conversationId }),
        },
      );

      if (!response.ok) {
        setMessages((prev) => [
          ...prev,
          { role: 'persona', content: previewReply(text) },
        ]);
        return;
      }

      const data = (await response.json()) as {
        message?: string;
        response?: string;
        conversation_id?: string;
      };
      setConversationId(data.conversation_id ?? null);
      setMessages((prev) => [
        ...prev,
        {
          role: 'persona',
          content: data.message || data.response || previewReply(text),
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'persona', content: previewReply(text) },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void sendMessage();
  };

  const onPrimaryClick = () => {
    analytics.landingCtaClicked({ cta_type: 'create_persona', position: 'hero' });
  };

  const onDemoFocus = () => {
    inputRef.current?.focus();
    analytics.landingCtaClicked({ cta_type: 'try_demo', position: 'hero' });
  };

  return (
    <section
      className="relative overflow-hidden"
      style={{ backgroundColor: 'var(--fog)' }}
      id="demo"
    >
      <div className="mx-auto max-w-[1024px] px-6 pt-40 text-center md:pt-48">
        <p
          className="mx-auto inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.2em]"
          style={{
            borderColor: 'rgba(29,29,31,0.10)',
            color: 'var(--fg-2)',
            background: 'rgba(255,255,255,0.6)',
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          <span
            className="inline-block h-1.5 w-1.5 rounded-full"
            style={{ background: 'var(--ink)' }}
          />
          PersonaOn &mdash; the portfolio that answers
        </p>

        <h1
          className="mx-auto mt-7 max-w-[1000px]"
          style={{
            fontFamily: "'Geist', sans-serif",
            fontWeight: 600,
            fontSize: 'clamp(56px, 9.8vw, 132px)',
            lineHeight: 0.96,
            letterSpacing: '-0.045em',
            color: 'var(--ink)',
          }}
        >
          Your portfolio,
          <br />
          <span style={{ color: 'var(--fg-3)' }}>but it answers.</span>
        </h1>

        <p
          className="mx-auto mt-7 max-w-[640px]"
          style={{
            color: 'var(--fg-2)',
            fontFamily: "'Geist', sans-serif",
            fontSize: 'clamp(18px, 1.6vw, 22px)',
            lineHeight: 1.4,
            letterSpacing: '-0.012em',
            fontWeight: 400,
          }}
        >
          Paste your resume. Get a living page that answers questions about your
          work, books your meetings, and captures interest &mdash; in your voice,
          sourced from you, never synthetic.
        </p>

        <div className="mt-9 flex flex-wrap items-center justify-center gap-x-7 gap-y-3">
          <Link
            href="/auth/signup"
            onClick={onPrimaryClick}
            className="inline-flex items-center gap-2 rounded-full px-6 transition-opacity hover:opacity-90"
            style={{
              height: 44,
              background: 'var(--ink)',
              color: '#FFFFFF',
              fontSize: 14,
              fontFamily: "'Geist', sans-serif",
              letterSpacing: '-0.01em',
              fontWeight: 500,
            }}
          >
            Start free
          </Link>
          <Link
            href="#how"
            onClick={onDemoFocus}
            className="inline-flex items-center gap-1 transition-opacity hover:opacity-60"
            style={{
              color: 'var(--ink)',
              fontSize: 14,
              fontFamily: "'Geist', sans-serif",
              letterSpacing: '-0.01em',
              fontWeight: 500,
            }}
          >
            See how it works
            <span aria-hidden style={{ fontSize: 16, lineHeight: 1 }}>
              &rsaquo;
            </span>
          </Link>
        </div>

        <p
          className="mt-5 text-[12px] uppercase tracking-[0.18em]"
          style={{
            color: 'var(--fg-3)',
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          Free &middot; No credit card &middot; Live in under 3 minutes
        </p>
      </div>

      <div className="mx-auto mt-20 max-w-[1100px] px-6 pb-32 md:pb-40">
        <PersonaCard
          messages={messages}
          input={input}
          isLoading={isLoading}
          hasUserMessage={hasUserMessage}
          demoLimitReached={demoLimitReached}
          inputRef={inputRef}
          scrollerRef={scrollerRef}
          onInputChange={setInput}
          onSubmit={handleSubmit}
          onTryAsking={(q) => void sendMessage(q)}
          tryAsking={TRY_ASKING}
        />
      </div>
    </section>
  );
}

interface CardProps {
  messages: Message[];
  input: string;
  isLoading: boolean;
  hasUserMessage: boolean;
  demoLimitReached: boolean;
  inputRef: React.RefObject<HTMLInputElement | null>;
  scrollerRef: React.RefObject<HTMLDivElement | null>;
  onInputChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onTryAsking: (question: string) => void;
  tryAsking: readonly string[];
}

function PersonaCard({
  messages,
  input,
  isLoading,
  hasUserMessage,
  demoLimitReached,
  inputRef,
  scrollerRef,
  onInputChange,
  onSubmit,
  onTryAsking,
  tryAsking,
}: CardProps) {
  return (
    <div className="relative mx-auto" style={{ maxWidth: 980 }}>
      <div
        className="overflow-hidden"
        style={{
          background: 'var(--fog-2)',
          border: '1px solid rgba(29,29,31,0.08)',
          borderRadius: 32,
          boxShadow:
            '0 60px 120px rgba(29,29,31,0.12), 0 8px 24px rgba(29,29,31,0.06)',
        }}
      >
        <div className="grid grid-cols-1 lg:grid-cols-[1.05fr_1fr]">
          <div className="p-9 md:p-12">
            <div className="flex items-start gap-5">
              <div
                className="flex h-16 w-16 flex-shrink-0 items-center justify-center rounded-full text-[24px]"
                style={{
                  background: 'var(--ink)',
                  color: '#FFFFFF',
                  fontFamily: "'Instrument Serif', Georgia, serif",
                }}
              >
                P
              </div>
              <div className="min-w-0">
                <p
                  className="text-[28px]"
                  style={{
                    color: 'var(--ink)',
                    fontFamily: "'Instrument Serif', Georgia, serif",
                    lineHeight: 1.05,
                    letterSpacing: '-0.01em',
                  }}
                >
                  PersonaOn Demo
                </p>
                <p
                  className="mt-1.5 text-[14px]"
                  style={{
                    color: 'var(--fg-2)',
                    fontFamily: "'Geist', sans-serif",
                  }}
                >
                  Live demo &middot; ask anything about how a persona works
                </p>
                <div
                  className="mt-3 inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1"
                  style={{
                    borderColor: 'rgba(29,29,31,0.10)',
                    background: 'rgba(255,255,255,0.7)',
                  }}
                >
                  <span
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ background: '#2BB673' }}
                  />
                  <span
                    className="text-[10px] uppercase tracking-[0.16em]"
                    style={{
                      color: 'var(--fg-2)',
                      fontFamily: "'JetBrains Mono', monospace",
                    }}
                  >
                    Live
                  </span>
                </div>
              </div>
            </div>

            <div className="mt-9">
              <p
                className="mb-3 text-[10px] uppercase tracking-[0.2em]"
                style={{
                  color: 'var(--fg-3)',
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              >
                Imagine your featured
              </p>
              <div className="grid grid-cols-3 gap-2.5">
                {[
                  { tag: 'Essay', label: 'Your writing' },
                  { tag: 'Talk', label: 'Your videos' },
                  { tag: 'Pod', label: 'Your podcasts' },
                ].map((t) => (
                  <div
                    key={t.label}
                    className="flex aspect-[4/5] flex-col justify-end rounded-[16px] p-3"
                    style={{
                      background:
                        'linear-gradient(180deg, #2a2a2e 0%, #1d1d1f 100%)',
                      border: '1px solid rgba(255,255,255,0.06)',
                    }}
                  >
                    <p
                      className="text-[9px] uppercase tracking-[0.18em]"
                      style={{
                        color: 'rgba(255,255,255,0.5)',
                        fontFamily: "'JetBrains Mono', monospace",
                      }}
                    >
                      {t.tag}
                    </p>
                    <p
                      className="mt-0.5 text-[12px]"
                      style={{
                        color: '#FFFFFF',
                        fontFamily: "'Geist', sans-serif",
                        letterSpacing: '-0.005em',
                      }}
                    >
                      {t.label}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div
            className="flex flex-col p-9 md:p-12"
            style={{
              background: 'var(--fog-3)',
              borderTop: '1px solid rgba(29,29,31,0.06)',
              minHeight: 460,
            }}
          >
            {!hasUserMessage ? (
              <div>
                <ChatBubble role="persona" content={messages[0].content} />
                <p
                  className="mb-3 mt-7 text-[10px] uppercase tracking-[0.2em]"
                  style={{
                    color: 'var(--fg-3)',
                    fontFamily: "'JetBrains Mono', monospace",
                  }}
                >
                  Try asking
                </p>
                <div className="flex flex-col gap-2">
                  {tryAsking.map((q) => (
                    <button
                      key={q}
                      type="button"
                      onClick={() => onTryAsking(q)}
                      disabled={isLoading || demoLimitReached}
                      className="flex items-center justify-between gap-3 rounded-[14px] border px-4 py-3 text-left text-[13.5px] transition-colors hover:bg-white disabled:opacity-50"
                      style={{
                        borderColor: 'rgba(29,29,31,0.10)',
                        background: 'var(--fog-2)',
                        color: 'var(--fg)',
                        fontFamily: "'Geist', sans-serif",
                        letterSpacing: '-0.005em',
                      }}
                    >
                      <span>{q}</span>
                      <span aria-hidden style={{ color: 'var(--fg-3)' }}>
                        &rsaquo;
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div
                ref={scrollerRef}
                className="flex flex-1 flex-col gap-3 overflow-y-auto pr-1"
                style={{ maxHeight: 360 }}
              >
                {messages.map((m, i) => (
                  <ChatBubble key={`${m.role}-${i}`} role={m.role} content={m.content} />
                ))}
                {isLoading && <TypingDots />}
              </div>
            )}

            <form onSubmit={onSubmit} className="mt-7 flex items-center gap-2">
              <div
                className="flex flex-1 items-center gap-3 rounded-full border px-4"
                style={{
                  height: 48,
                  borderColor: 'rgba(29,29,31,0.12)',
                  background: 'var(--fog-2)',
                }}
              >
                <Mic size={14} style={{ color: 'var(--fg-2)' }} aria-hidden />
                <input
                  ref={inputRef}
                  value={input}
                  onChange={(e) => onInputChange(e.target.value)}
                  disabled={isLoading || demoLimitReached}
                  placeholder={
                    demoLimitReached
                      ? 'Create your persona to keep going'
                      : 'Ask anything — in your own words'
                  }
                  className="min-w-0 flex-1 bg-transparent text-[13.5px] outline-none"
                  style={{
                    color: 'var(--fg)',
                    fontFamily: "'Geist', sans-serif",
                    letterSpacing: '-0.005em',
                  }}
                  aria-label="Ask the demo persona"
                />
              </div>
              <button
                type="submit"
                disabled={!input.trim() || isLoading || demoLimitReached}
                className="flex h-12 w-12 items-center justify-center rounded-full transition-opacity disabled:opacity-40"
                style={{ background: 'var(--ink)', color: '#FFFFFF' }}
                aria-label="Send"
              >
                <Send size={15} />
              </button>
            </form>

            {demoLimitReached && (
              <Link
                href="/auth/signup"
                className="mt-3 inline-flex items-center justify-center gap-1 self-start text-[13px] underline-offset-4 hover:underline"
                style={{
                  color: 'var(--ink)',
                  fontFamily: "'Geist', sans-serif",
                  fontWeight: 500,
                }}
              >
                Create your persona to keep going
                <span aria-hidden>&rsaquo;</span>
              </Link>
            )}
          </div>
        </div>
      </div>

      <p
        className="mt-4 text-center text-[11px] uppercase tracking-[0.18em]"
        style={{
          color: 'var(--fg-3)',
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        Personaon.com/demo
      </p>
    </div>
  );
}

function ChatBubble({ role, content }: { role: Message['role']; content: string }) {
  if (role === 'user') {
    return (
      <div className="flex justify-end">
        <div
          className="max-w-[82%] rounded-[14px] px-4 py-2.5 text-[13.5px] leading-[1.5]"
          style={{
            background: 'var(--ink)',
            color: '#FFFFFF',
            fontFamily: "'Geist', sans-serif",
          }}
        >
          {content}
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-start gap-2">
      <div
        className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full text-[12px]"
        style={{
          background: 'var(--ink)',
          color: '#FFFFFF',
          fontFamily: "'Instrument Serif', Georgia, serif",
        }}
      >
        P
      </div>
      <div
        className="max-w-[82%] rounded-[14px] px-4 py-2.5 text-[13.5px] leading-[1.5]"
        style={{
          background: 'var(--fog-2)',
          border: '1px solid rgba(29,29,31,0.08)',
          color: 'var(--fg)',
          fontFamily: "'Geist', sans-serif",
        }}
      >
        {content}
      </div>
    </div>
  );
}

function TypingDots() {
  return (
    <div className="flex items-start gap-2">
      <div
        className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full text-[12px]"
        style={{
          background: 'var(--ink)',
          color: '#FFFFFF',
          fontFamily: "'Instrument Serif', Georgia, serif",
        }}
      >
        P
      </div>
      <div
        className="flex items-center gap-1 rounded-[14px] px-4 py-3"
        style={{
          background: 'var(--fog-2)',
          border: '1px solid rgba(29,29,31,0.08)',
        }}
      >
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="h-1.5 w-1.5 rounded-full"
            style={{
              background: 'var(--fg-3)',
              animation: 'pulse-slow 1.4s ease-in-out infinite',
              animationDelay: `${i * 140}ms`,
            }}
          />
        ))}
      </div>
    </div>
  );
}
