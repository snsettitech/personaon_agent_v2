'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { motion, type Variants } from 'framer-motion';
import { useTwin } from '@/lib/context/TwinContext';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';
import { formatPersonaDisplayName } from '@/lib/branding/personaName';
import VoiceCloneSection from '@/components/settings/VoiceCloneSection';

// ── Types ──────────────────────────────────────────────────────────

interface ScoreBreakdown {
  score: number;
  max: number;
  status: string;
  hint: string | null;
}

interface PersonaScore {
  score: number;
  max: number;
  label: string;
  breakdown: {
    profile: ScoreBreakdown;
    knowledge: ScoreBreakdown;
    interview: ScoreBreakdown;
    voice: ScoreBreakdown;
  };
}

interface InterviewMessage {
  role: 'user' | 'assistant';
  content: string;
}

// ── Animation variants ─────────────────────────────────────────────

const fadeUp: Variants = {
  hidden: { opacity: 0, y: 16 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.35, ease: 'easeOut' as const, delay: i * 0.08 },
  }),
};

// ── Score Card ─────────────────────────────────────────────────────

function ScoreCard({ score, onRefresh }: { score: PersonaScore | null; onRefresh: () => void }) {
  if (!score) {
    return (
      <div
        className="rounded-3xl p-6 animate-pulse"
        style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
      >
        <div className="h-5 w-40 rounded-xl mb-4" style={{ backgroundColor: 'var(--bg-surface)' }} />
        <div className="h-3 w-full rounded-xl" style={{ backgroundColor: 'var(--bg-surface)' }} />
      </div>
    );
  }

  const pct = Math.round((score.score / score.max) * 100);
  const circleColor = pct >= 75 ? 'var(--primary-500)' : pct >= 50 ? 'var(--accent-trust)' : 'var(--accent-cta)';

  const categories = [
    {
      key: 'profile', label: 'Profile', data: score.breakdown.profile,
      icon: <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" /></svg>,
    },
    {
      key: 'knowledge', label: 'Sources', data: score.breakdown.knowledge,
      icon: <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" /></svg>,
    },
    {
      key: 'interview', label: 'Interview', data: score.breakdown.interview,
      icon: <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z" /></svg>,
    },
    {
      key: 'voice', label: 'Voice', data: score.breakdown.voice,
      icon: <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 18.75a6 6 0 006-6v-1.5m-6 7.5a6 6 0 01-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 01-3-3V4.5a3 3 0 116 0v8.25a3 3 0 01-3 3z" /></svg>,
    },
  ];

  return (
    <div
      className="rounded-3xl p-6"
      style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
    >
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>Persona Score</h2>
          <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
            {score.score}/{score.max} —{' '}
            <span className="font-semibold" style={{ color: 'var(--text-secondary)' }}>{score.label}</span>
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={onRefresh}
            className="text-xs px-3 py-1.5 rounded-full transition-colors cursor-pointer"
            style={{ color: 'var(--text-muted)', backgroundColor: 'var(--bg-surface)' }}
          >
            Refresh
          </button>
          <div className="relative h-16 w-16">
            <svg className="h-16 w-16 -rotate-90" viewBox="0 0 36 36">
              <circle cx="18" cy="18" r="15.9" fill="none" stroke="var(--border-default)" strokeWidth="3" />
              <circle
                cx="18" cy="18" r="15.9" fill="none"
                stroke={circleColor}
                strokeWidth="3" strokeDasharray={`${pct} 100`} strokeLinecap="round"
              />
            </svg>
            <span className="absolute inset-0 flex items-center justify-center text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
              {pct}%
            </span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {categories.map(({ key, label, icon, data }, i) => (
          <div
            key={key}
            className="rounded-2xl p-3"
            style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)' }}
          >
            <div className="flex items-center gap-2 mb-2">
              <span style={{ color: 'var(--text-muted)' }}>{icon}</span>
              <span className="text-xs font-semibold" style={{ color: 'var(--text-secondary)' }}>{label}</span>
              <span className="ml-auto text-xs" style={{ color: 'var(--text-muted)' }}>{data.score}/{data.max}</span>
            </div>
            <div className="h-1.5 rounded-full" style={{ backgroundColor: 'var(--border-default)' }}>
              <motion.div
                className="h-1.5 rounded-full"
                style={{ backgroundColor: 'var(--primary-500)' }}
                initial={{ width: 0 }}
                animate={{ width: `${(data.score / data.max) * 100}%` }}
                transition={{ duration: 0.7, ease: 'easeOut' as const, delay: 0.2 + i * 0.1 }}
              />
            </div>
            {data.hint && (
              <p className="mt-1.5 text-[10px]" style={{ color: 'var(--text-muted)' }}>{data.hint}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Interview Section ──────────────────────────────────────────────

function InterviewSection({ twinId }: { twinId: string }) {
  const apiBase = resolveApiBaseUrl();
  const storageKey = `interview_${twinId}`;

  const restored = typeof window !== 'undefined'
    ? (() => {
        try {
          const raw = sessionStorage.getItem(storageKey);
          return raw ? JSON.parse(raw) as { messages: InterviewMessage[]; sessionId: string | null; savedCount: number; started: boolean } : null;
        } catch { return null; }
      })()
    : null;

  const [messages, setMessages] = useState<InterviewMessage[]>(restored?.messages || []);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(restored?.sessionId || null);
  const [savedCount, setSavedCount] = useState(restored?.savedCount || 0);
  const [started, setStarted] = useState(restored?.started || false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      sessionStorage.setItem(storageKey, JSON.stringify({ messages, sessionId, savedCount, started }));
    } catch { /* quota exceeded — ignore */ }
  }, [messages, sessionId, savedCount, started, storageKey]);

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  const sendMessage = useCallback(async (userMessage: string, lastQuestion?: string) => {
    if (streaming) return;
    setStreaming(true);
    const newMessages: InterviewMessage[] = userMessage
      ? [...messages, { role: 'user', content: userMessage }]
      : [...messages];
    setMessages(newMessages);
    try {
      const res = await authFetchStandalone(`${apiBase}/v2/interview/${twinId}/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMessage || 'Start the interview', last_question: lastQuestion || null, session_id: sessionId }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      if (!res.body) throw new Error('No response body');
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let assistantText = '';
      let buffer = '';
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6)) as Record<string, unknown>;
              if ('session_id' in data) {
                setSessionId(data.session_id as string);
                if (data.saved_qa) setSavedCount((c: number) => c + 1);
              }
              if ('text' in data) {
                assistantText += data.text as string;
                setMessages([...newMessages, { role: 'assistant', content: assistantText }]);
              }
            } catch { /* skip malformed */ }
          }
        }
      }
    } catch {
      setMessages([...messages, { role: 'assistant', content: 'Sorry, something went wrong. Try again.' }]);
    } finally {
      setStreaming(false);
    }
  }, [apiBase, twinId, messages, sessionId, streaming]);

  const handleStart = () => { setStarted(true); void sendMessage('Hello, I\'m ready for the interview.'); };
  const handleSend = () => {
    if (!input.trim() || streaming) return;
    const lastAssistantMsg = [...messages].reverse().find(m => m.role === 'assistant');
    void sendMessage(input.trim(), lastAssistantMsg?.content);
    setInput('');
  };

  if (!started) {
    return (
      <div
        className="rounded-3xl p-6"
        style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
      >
        <div className="flex items-start gap-4">
          <div
            className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl"
            style={{ backgroundColor: 'var(--primary-50)', color: 'var(--primary-600)' }}
          >
            <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z" />
            </svg>
          </div>
          <div className="flex-1">
            <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>Interview Mode</h3>
            <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary)' }}>
              An AI interviewer will ask you questions to learn things the web doesn&apos;t know about you — your opinions, stories, expertise, and how you think. Each answer automatically improves your persona.
            </p>
            <motion.button
              onClick={handleStart}
              className="mt-4 rounded-full px-6 py-2.5 text-sm font-semibold text-white cursor-pointer"
              style={{ background: 'linear-gradient(135deg, var(--brand-primary), var(--brand-secondary))' }}
              whileHover={{ scale: 1.03 }}
              whileTap={{ scale: 0.97 }}
            >
              Start Interview
            </motion.button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="rounded-3xl overflow-hidden"
      style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
    >
      <div className="px-4 py-3 flex items-center justify-between" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
        <div>
          <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>Interview Mode</h3>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{savedCount} answers saved to sources</p>
        </div>
        <button
          onClick={() => { setStarted(false); setMessages([]); setSessionId(null); setSavedCount(0); try { sessionStorage.removeItem(storageKey); } catch {} }}
          className="text-xs cursor-pointer transition-colors"
          style={{ color: 'var(--text-muted)' }}
        >
          Reset
        </button>
      </div>

      <div className="max-h-[400px] overflow-y-auto p-4 space-y-3">
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className="max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed"
              style={msg.role === 'user'
                ? { background: 'linear-gradient(135deg, var(--brand-primary), var(--brand-secondary))', color: 'white' }
                : { backgroundColor: 'var(--bg-surface)', color: 'var(--text-primary)' }
              }
            >
              {msg.content}
            </div>
          </div>
        ))}
        {streaming && messages[messages.length - 1]?.role !== 'assistant' && (
          <div className="flex justify-start">
            <div className="rounded-2xl px-4 py-2.5" style={{ backgroundColor: 'var(--bg-surface)' }}>
              <div className="flex gap-1">
                {[0, 0.1, 0.2].map((delay, i) => (
                  <div key={i} className="h-2 w-2 rounded-full animate-bounce" style={{ backgroundColor: 'var(--text-muted)', animationDelay: `${delay}s` }} />
                ))}
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="p-3" style={{ borderTop: '1px solid var(--border-subtle)' }}>
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
            placeholder="Type your answer..."
            disabled={streaming}
            className="flex-1 rounded-xl px-4 py-2.5 text-sm outline-none disabled:opacity-50"
            style={{ backgroundColor: 'var(--bg-base)', border: '1px solid var(--border-subtle)', color: 'var(--text-primary)' }}
          />
          <motion.button
            onClick={handleSend}
            disabled={streaming || !input.trim()}
            className="rounded-full px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50 cursor-pointer"
            style={{ background: 'linear-gradient(135deg, var(--brand-primary), var(--brand-secondary))' }}
            whileHover={{ scale: 1.03 }}
            whileTap={{ scale: 0.97 }}
          >
            Send
          </motion.button>
        </div>
      </div>
    </div>
  );
}

// ── Main Studio Page ───────────────────────────────────────────────

export default function StudioPage() {
  const { activeTwin, isLoading: twinLoading } = useTwin();
  const apiBase = resolveApiBaseUrl();
  const [score, setScore] = useState<PersonaScore | null>(null);
  const twinId = activeTwin?.id;

  const fetchScore = useCallback(async () => {
    if (!twinId) return;
    try {
      const res = await authFetchStandalone(`${apiBase}/v2/twins/${twinId}/score`);
      if (res.ok) setScore(await res.json() as PersonaScore);
    } catch { /* ignore */ }
  }, [apiBase, twinId]);

  useEffect(() => { if (twinId) void fetchScore(); }, [twinId, fetchScore]);

  if (twinLoading) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent" style={{ borderColor: 'var(--brand-primary)', borderTopColor: 'transparent' }} />
      </div>
    );
  }

  if (!twinId) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <div className="text-center max-w-md p-8">
          <h2 className="text-lg font-bold mb-2" style={{ color: 'var(--text-primary)' }}>No Persona Found</h2>
          <p className="mb-5 text-sm" style={{ color: 'var(--text-muted)' }}>Create your persona first to access the Studio.</p>
          <a
            href="/dashboard"
            className="inline-block rounded-full px-6 py-2.5 text-sm font-semibold text-white"
            style={{ background: 'linear-gradient(135deg, var(--brand-primary), var(--brand-secondary))' }}
          >
            Go to Dashboard
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 pb-12 pt-4">
      <motion.div initial="hidden" animate="visible" custom={0} variants={fadeUp}>
        <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--text-primary)' }}>Studio</h1>
        <p className="mt-0.5 text-sm" style={{ color: 'var(--text-secondary)' }}>Refine how your persona thinks and sounds.</p>
      </motion.div>

      <motion.div initial="hidden" animate="visible" custom={1} variants={fadeUp}>
        <ScoreCard score={score} onRefresh={fetchScore} />
      </motion.div>

      <div className="grid gap-5 lg:grid-cols-2">
        <motion.div initial="hidden" animate="visible" custom={2} variants={fadeUp}>
          <InterviewSection twinId={twinId} />
        </motion.div>
        <motion.div initial="hidden" animate="visible" custom={3} variants={fadeUp}>
          <VoiceCloneSection twinId={twinId} twinName={formatPersonaDisplayName(activeTwin?.name)} />
        </motion.div>
      </div>
    </div>
  );
}
