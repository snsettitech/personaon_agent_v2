'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { useAuthFetch } from '@/lib/hooks/useAuthFetch';
import { useTwin } from '@/lib/context/TwinContext';

interface QueuedQuestion {
  id: string;
  twin_id: string;
  tenant_id: string;
  question: string;
  topic: string | null;
  conversation_id: string | null;
  visitor_user_id: string | null;
  ask_count: number;
  status: 'pending' | 'answered' | 'dismissed';
  owner_answer: string | null;
  answered_at: string | null;
  created_at: string;
  updated_at: string;
}

function formatTimeAgo(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffDays > 0) return `${diffDays}d ago`;
  if (diffHours > 0) return `${diffHours}h ago`;
  if (diffMins > 0) return `${diffMins}m ago`;
  return 'just now';
}

export default function QueuedQuestionsPage() {
  const { get, post } = useAuthFetch();
  const { activeTwin, isLoading: twinLoading } = useTwin();

  const [questions, setQuestions] = useState<QueuedQuestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [answeringId, setAnsweringId] = useState<string | null>(null);
  const [ownerAnswers, setOwnerAnswers] = useState<Record<string, string>>({});

  const fetchQuestions = useCallback(async () => {
    if (!activeTwin?.id) return;
    setLoading(true);
    try {
      const response = await get(
        `/v2/queued-questions?twin_id=${activeTwin.id}&status=pending`
      );
      if (response.ok) {
        const data = await response.json();
        setQuestions(data.questions ?? []);
      }
    } catch (error) {
      console.error('Error fetching queued questions:', error);
    } finally {
      setLoading(false);
    }
  }, [get, activeTwin?.id]);

  useEffect(() => {
    if (!twinLoading) {
      fetchQuestions();
    }
  }, [twinLoading, fetchQuestions]);

  const handleAnswer = useCallback(async (id: string) => {
    const answer = ownerAnswers[id]?.trim();
    if (!answer) return;

    setAnsweringId(id);
    try {
      const response = await post(`/v2/queued-questions/${id}/answer`, { answer });
      if (response.ok) {
        await fetchQuestions();
        setOwnerAnswers((prev) => {
          const next = { ...prev };
          delete next[id];
          return next;
        });
      }
    } catch (error) {
      console.error('Error answering question:', error);
    } finally {
      setAnsweringId(null);
    }
  }, [ownerAnswers, post, fetchQuestions]);

  const handleDismiss = useCallback(async (id: string) => {
    try {
      const response = await post(`/v2/queued-questions/${id}/dismiss`, {});
      if (response.ok) {
        await fetchQuestions();
      }
    } catch (error) {
      console.error('Error dismissing question:', error);
    }
  }, [post, fetchQuestions]);

  if (twinLoading || loading) {
    return (
      <div className="flex min-h-[400px] flex-1 items-center justify-center">
        <div
          className="h-10 w-10 animate-spin rounded-full border-2 border-[#0066cc]/20 border-t-[#0066cc]"
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-6 md:py-8">
      <div className="rounded-[2rem] border border-black/10 bg-white p-6 shadow-[0_18px_60px_rgba(15,23,42,0.06)] md:p-8">
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[#0066cc]">Queued questions</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-[#111111] md:text-4xl">
          Fill the gaps in what your persona can answer.
        </h1>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-[#6e6e73] md:text-base">
          When a visitor asks something your persona cannot answer from approved context, it appears here.
          Add a grounded response once and future conversations can handle it more confidently.
        </p>
      </div>

      {questions.length === 0 ? (
        <div
          className="mt-6 flex flex-col items-center rounded-[2rem] border border-black/10 bg-white px-8 py-16 text-center shadow-sm"
        >
          <div
            className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-[#eef5ff]"
          >
            <svg
              className="w-7 h-7"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              style={{ color: '#0066cc' }}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
          </div>
          <p className="mb-2 text-base font-semibold text-[#111111]">
            No pending questions from visitors yet.
          </p>
          <p className="max-w-sm text-sm text-[#6e6e73]">
            When visitors ask about topics your persona hasn&apos;t covered, their questions will appear
            here.
          </p>
        </div>
      ) : (
        <div className="mt-6 space-y-4">
          {questions.map((q) => (
            <div
              key={q.id}
              className="rounded-[2rem] border border-black/10 bg-white p-6 shadow-sm"
            >
              <div className="mb-4 flex flex-wrap items-center gap-2">
                {q.topic && (
                  <span className="rounded-full border border-[#0066cc]/12 bg-[#eef5ff] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-[#0066cc]">
                    {q.topic}
                  </span>
                )}
                {q.ask_count > 1 && (
                  <span className="rounded-full bg-[#f5f5f7] px-3 py-1 text-xs font-semibold text-[#4b5563]">
                    Asked {q.ask_count} times
                  </span>
                )}
                <span className="ml-auto text-xs font-medium text-[#8e8e93]">
                  {formatTimeAgo(q.created_at)}
                </span>
              </div>

              <p className="mb-4 text-lg font-semibold leading-8 text-[#111111]">
                &ldquo;{q.question}&rdquo;
              </p>

              <textarea
                className="w-full resize-none rounded-[1.4rem] border border-black/10 bg-[#f5f5f7] px-4 py-3 text-sm leading-6 text-[#111111] outline-none transition focus:border-[#0066cc] focus:ring-2 focus:ring-[#0066cc]/20"
                placeholder="Write the response you want saved into approved sources for future answers."
                rows={3}
                value={ownerAnswers[q.id] ?? ''}
                onChange={(e) =>
                  setOwnerAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))
                }
              />

              <div className="mt-4 flex items-center justify-between gap-3">
                <button
                  onClick={() => handleDismiss(q.id)}
                  className="rounded-full border border-black/10 bg-white px-4 py-2 text-sm font-semibold text-[#6e6e73] transition hover:text-[#111111]"
                >
                  Dismiss
                </button>
                <button
                  onClick={() => handleAnswer(q.id)}
                  disabled={answeringId === q.id || !ownerAnswers[q.id]?.trim()}
                  className="rounded-full bg-[#0066cc] px-4 py-2 text-sm font-semibold text-white shadow-[0_12px_24px_rgba(0,102,204,0.22)] transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {answeringId === q.id ? 'Saving...' : 'Save to sources'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
