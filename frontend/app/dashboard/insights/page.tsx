'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { motion, type Variants } from 'framer-motion';

import { useTwin } from '@/lib/context/TwinContext';
import { useAuthFetch } from '@/lib/hooks/useAuthFetch';

interface AnswerMix {
  direct: number;
  derivable: number;
  insufficient: number;
}

interface DashboardStats {
  conversations: number;
  messages: number;
  userMessages: number;
  assistantMessages: number;
  responseRate: number;
  reviewRate: number;
  citationRate: number;
  unsupportedRate: number;
  answerMix: AnswerMix;
}

interface DailyMetric {
  date: string;
  conversations: number;
  messages: number;
}

interface TopQuestion {
  question: string;
  count: number;
  unique_visitors: number;
  last_asked: string;
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', { weekday: 'short' });
}

// ── Animation variants ──────────────────────────────────────────────────────
const fadeUp: Variants = {
  hidden: { opacity: 0, y: 16 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.35, ease: 'easeOut' as const, delay: i * 0.07 },
  }),
};

const rowIn: Variants = {
  hidden: { opacity: 0, x: -8 },
  visible: (i: number) => ({
    opacity: 1,
    x: 0,
    transition: { duration: 0.25, ease: 'easeOut' as const, delay: 0.1 + i * 0.05 },
  }),
};

// ── Animated bar (width 0 → target) ────────────────────────────────────────
function AnimatedBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="h-2 rounded-full" style={{ backgroundColor: 'var(--bg-surface)' }}>
      <motion.div
        className="h-2 rounded-full"
        style={{ backgroundColor: color }}
        initial={{ width: 0 }}
        animate={{ width: `${Math.min(pct, 100)}%` }}
        transition={{ duration: 0.8, ease: 'easeOut' as const, delay: 0.3 }}
      />
    </div>
  );
}

export default function InsightsPage(): React.JSX.Element {
  const { activeTwin, isLoading: twinLoading } = useTwin();
  const { get } = useAuthFetch();

  const twinId = activeTwin?.id;
  const [timeRange, setTimeRange] = useState<'7d' | '30d' | '90d'>('30d');
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<DashboardStats>({
    conversations: 0,
    messages: 0,
    userMessages: 0,
    assistantMessages: 0,
    responseRate: 0,
    reviewRate: 0,
    citationRate: 0,
    unsupportedRate: 0,
    answerMix: { direct: 0, derivable: 0, insufficient: 0 },
  });
  const [dailyData, setDailyData] = useState<DailyMetric[]>([]);
  const [topQuestions, setTopQuestions] = useState<TopQuestion[]>([]);

  const getDays = useCallback(() => {
    switch (timeRange) {
      case '7d': return 7;
      case '30d': return 30;
      case '90d': return 90;
      default: return 30;
    }
  }, [timeRange]);

  const fetchData = useCallback(async () => {
    if (!twinId) return;
    setLoading(true);
    const days = getDays();
    try {
      const [statsRes, dailyRes, questionsRes] = await Promise.all([
        get(`/metrics/dashboard/${twinId}?days=${days}`),
        get(`/metrics/daily/${twinId}?days=${Math.min(days, 30)}`),
        get(`/metrics/top-questions/${twinId}?limit=5`),
      ]);
      if (statsRes.ok) {
        const data = await statsRes.json() as Record<string, unknown>;
        setStats({
          conversations: (data.conversations as number) ?? 0,
          messages: (data.messages as number) ?? 0,
          userMessages: (data.user_messages as number) ?? 0,
          assistantMessages: (data.assistant_messages as number) ?? 0,
          responseRate: (data.response_rate as number) ?? 0,
          reviewRate: (data.review_rate as number) ?? 0,
          citationRate: (data.citation_rate as number) ?? 0,
          unsupportedRate: (data.unsupported_rate as number) ?? 0,
          answerMix: {
            direct: ((data.answer_mix as AnswerMix)?.direct) ?? 0,
            derivable: ((data.answer_mix as AnswerMix)?.derivable) ?? 0,
            insufficient: ((data.answer_mix as AnswerMix)?.insufficient) ?? 0,
          },
        });
      }
      if (dailyRes.ok) setDailyData(await dailyRes.json() as DailyMetric[]);
      if (questionsRes.ok) setTopQuestions(await questionsRes.json() as TopQuestion[]);
    } catch {
      // silently fail — insights are non-critical
    } finally {
      setLoading(false);
    }
  }, [get, getDays, twinId]);

  useEffect(() => {
    if (twinId) void fetchData();
    else if (!twinLoading) setLoading(false);
  }, [fetchData, twinId, twinLoading]);

  const maxConversations = useMemo(
    () => Math.max(...dailyData.map((d) => d.conversations), 1),
    [dailyData]
  );

  // ── Loading skeleton ──────────────────────────────────────────────────
  if (twinLoading || loading) {
    return (
      <div className="space-y-8 pt-4">
        <div className="h-7 w-32 rounded-2xl animate-pulse" style={{ backgroundColor: 'var(--bg-surface)' }} />
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-28 rounded-3xl animate-pulse" style={{ backgroundColor: 'var(--bg-surface)' }} />
          ))}
        </div>
      </div>
    );
  }

  // ── No twin ───────────────────────────────────────────────────────────
  if (!twinId) {
    return (
      <div className="flex h-96 items-center justify-center">
        <div className="text-center max-w-sm px-8">
          <div className="w-12 h-12 rounded-2xl flex items-center justify-center mx-auto mb-4" style={{ backgroundColor: 'var(--bg-surface)' }}>
            <svg className="w-6 h-6" style={{ color: 'var(--text-muted)' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          </div>
          <h2 className="text-lg font-bold mb-2" style={{ color: 'var(--text-primary)' }}>No persona found</h2>
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Create your persona first to view insights.</p>
        </div>
      </div>
    );
  }

  const metrics = [
    { label: 'Conversations', value: stats.conversations.toLocaleString(), sub: 'Unique chat sessions' },
    { label: 'Messages', value: stats.messages.toLocaleString(), sub: `${stats.userMessages} user · ${stats.assistantMessages} assistant` },
    { label: 'Avg per Chat', value: stats.conversations > 0 ? (stats.messages / stats.conversations).toFixed(1) : '0', sub: 'Messages per conversation' },
    { label: 'Questions', value: topQuestions.reduce((s, q) => s + q.count, 0).toLocaleString(), sub: `${topQuestions.length} unique themes` },
  ];

  const RANGE_LABELS: Record<string, string> = { '7d': '7 days', '30d': '30 days', '90d': '90 days' };

  return (
    <div className="space-y-8 pb-12 pt-4">

      {/* Header + time range */}
      <motion.div
        className="flex items-end justify-between flex-wrap gap-3"
        initial="hidden" animate="visible" custom={0} variants={fadeUp}
      >
        <div>
          <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--text-primary)' }}>
            Insights
          </h1>
          <p className="mt-0.5 text-sm" style={{ color: 'var(--text-secondary)' }}>
            See what the persona answers cleanly, cites often, and still struggles with.
          </p>
        </div>

        {/* Time range pill */}
        <div
          className="flex items-center rounded-full p-1 gap-0.5"
          style={{ backgroundColor: 'var(--bg-elevated)', border: '1px solid var(--border-subtle)' }}
        >
          {(['7d', '30d', '90d'] as const).map((range) => (
            <button
              key={range}
              onClick={() => setTimeRange(range)}
              className="px-4 py-1.5 rounded-full text-xs font-semibold transition-all cursor-pointer"
              style={{
                backgroundColor: timeRange === range ? 'var(--text-primary)' : 'transparent',
                color: timeRange === range ? 'var(--text-inverse)' : 'var(--text-muted)',
              }}
            >
              {RANGE_LABELS[range]}
            </button>
          ))}
        </div>
      </motion.div>

      {/* 4 metric cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {metrics.map((m, i) => (
          <motion.div
            key={m.label}
            custom={i}
            initial="hidden" animate="visible" variants={fadeUp}
            className="rounded-3xl p-5"
            style={{
              backgroundColor: 'var(--bg-card)',
              border: '1px solid var(--border-subtle)',
              boxShadow: 'var(--shadow-sm)',
            }}
            whileHover={{ y: -2, boxShadow: 'var(--shadow-md)' }}
          >
            <p className="text-2xl font-bold tracking-tight" style={{ color: 'var(--text-primary)' }}>{m.value}</p>
            <p className="mt-1 text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>{m.label}</p>
            <p className="mt-1.5 text-xs" style={{ color: 'var(--text-muted)' }}>{m.sub}</p>
          </motion.div>
        ))}
      </div>

      {/* Chart + Engagement */}
      <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">

        {/* Conversation volume bar chart */}
        <motion.div
          className="rounded-3xl p-6"
          style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
          initial="hidden" animate="visible" custom={4} variants={fadeUp}
        >
          <h2 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>Conversation Volume</h2>
          {/* Scrollable bar chart — bars are fixed-width so 30/90-day views don't collapse */}
          <div className="mt-5 overflow-x-auto">
            <div
              className="flex items-end gap-1.5 h-48"
              style={{ minWidth: dailyData.length > 0 ? `${dailyData.length * 32}px` : undefined }}
            >
              {dailyData.length === 0 ? (
                <div className="flex-1 flex items-center justify-center">
                  <p className="text-xs" style={{ color: 'var(--text-muted)' }}>No data for this range</p>
                </div>
              ) : dailyData.map((item, i) => {
                const step = Math.max(1, Math.ceil(dailyData.length / 10));
                const showLabel = i % step === 0 || i === dailyData.length - 1;
                return (
                  <div key={item.date} className="flex w-7 shrink-0 flex-col items-center gap-1.5">
                    <div className="w-full flex items-end h-40 rounded-xl pb-0.5" style={{ backgroundColor: 'var(--bg-surface)' }}>
                      <motion.div
                        className="w-full rounded-lg"
                        style={{ backgroundColor: 'var(--primary-500)' }}
                        initial={{ height: 0 }}
                        animate={{ height: `${(item.conversations / maxConversations) * 100}%` }}
                        transition={{ duration: 0.6, ease: 'easeOut' as const, delay: 0.15 + i * 0.04 }}
                      />
                    </div>
                    <span
                      className="text-[9px] font-medium whitespace-nowrap"
                      style={{ color: 'var(--text-muted)', opacity: showLabel ? 1 : 0 }}
                    >
                      {formatDate(item.date)}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </motion.div>

        {/* Engagement */}
        <motion.div
          className="rounded-3xl p-6"
          style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
          initial="hidden" animate="visible" custom={5} variants={fadeUp}
        >
          <h2 className="text-sm font-bold mb-5" style={{ color: 'var(--text-primary)' }}>Engagement</h2>
          <div className="space-y-5">
            {[
              { label: 'Response Rate', value: `${stats.responseRate.toFixed(1)}%`, pct: stats.responseRate, color: 'var(--accent-emerald)' },
              { label: 'User Messages', value: String(stats.userMessages), pct: stats.messages > 0 ? (stats.userMessages / stats.messages) * 100 : 0, color: 'var(--primary-500)' },
              { label: 'Assistant Messages', value: String(stats.assistantMessages), pct: stats.messages > 0 ? (stats.assistantMessages / stats.messages) * 100 : 0, color: 'var(--accent-cta)' },
            ].map((row) => (
              <div key={row.label}>
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>{row.label}</span>
                  <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{row.value}</span>
                </div>
                <AnimatedBar pct={row.pct} color={row.color} />
              </div>
            ))}
          </div>

          <div className="mt-6 grid grid-cols-2 gap-3">
            {[
              { label: 'Avg per Chat', value: stats.conversations > 0 ? (stats.messages / stats.conversations).toFixed(1) : '0' },
              { label: 'Question Themes', value: String(topQuestions.length) },
            ].map((stat) => (
              <div key={stat.label} className="rounded-2xl p-4" style={{ backgroundColor: 'var(--bg-surface)' }}>
                <div className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>{stat.label}</div>
                <div className="mt-1 text-xl font-bold" style={{ color: 'var(--text-primary)' }}>{stat.value}</div>
              </div>
            ))}
          </div>
        </motion.div>
      </div>

      {/* Top Questions */}
      <motion.div
        className="rounded-3xl p-6"
        style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
        initial="hidden" animate="visible" custom={6} variants={fadeUp}
      >
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>Top Questions</h2>
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Most repeated in this range</span>
        </div>

        <div className="space-y-3">
          {topQuestions.length === 0 ? (
            <div className="rounded-2xl p-6 text-sm text-center" style={{ backgroundColor: 'var(--bg-surface)', color: 'var(--text-muted)' }}>
              No questions recorded yet for this time range.
            </div>
          ) : topQuestions.map((q, i) => (
            <motion.div
              key={`${q.question}-${i}`}
              custom={i}
              initial="hidden" animate="visible" variants={rowIn}
              className="rounded-2xl p-4"
              style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)' }}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>{q.question}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <span
                      className="rounded-full px-2 py-0.5 text-[10px] font-semibold"
                      style={{ backgroundColor: 'var(--primary-50)', color: 'var(--primary-700)' }}
                    >
                      {q.unique_visitors} {q.unique_visitors === 1 ? 'visitor' : 'visitors'}
                    </span>
                    {q.last_asked && (
                      <span
                        className="rounded-full px-2 py-0.5 text-[10px] font-medium"
                        style={{ backgroundColor: 'var(--bg-elevated)', color: 'var(--text-muted)' }}
                      >
                        last asked {new Date(q.last_asked).toLocaleDateString()}
                      </span>
                    )}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>{q.count}</div>
                  <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>times asked</div>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      </motion.div>
    </div>
  );
}
