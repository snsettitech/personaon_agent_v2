'use client';

import { useState } from 'react';

import { analytics } from '@/lib/analytics/events';
import { DEMO_QUESTIONS } from '@/lib/experience/types';

const MONO = "'JetBrains Mono', monospace";
const SANS = "'Geist', sans-serif";

export interface AnswerOut {
  id: string;
  prompt: string;
  answer: string;
}

export function QuestionsStep({
  fileName,
  submitting,
  error,
  onBack,
  onSubmit,
}: {
  fileName: string;
  submitting: boolean;
  error: string;
  onBack: () => void;
  onSubmit: (answers: AnswerOut[]) => void;
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({});

  const submit = () => {
    const out = DEMO_QUESTIONS.map((q) => ({ id: q.id, prompt: q.prompt, answer: (answers[q.id] ?? '').trim() }));
    analytics.experienceQuestionsSubmitted({ answered_count: out.filter((a) => a.answer.length > 0).length });
    onSubmit(out);
  };

  return (
    <div>
      <p className="mb-2 text-[10px] uppercase tracking-[0.2em]" style={{ color: 'var(--fg-3)', fontFamily: MONO }}>
        Step 2 — A few questions
      </p>
      <h2 className="text-[26px]" style={{ color: 'var(--ink)', fontFamily: "'Instrument Serif', Georgia, serif", lineHeight: 1.1 }}>
        Make your twin sharper
      </h2>
      <p className="mt-2 text-[14px]" style={{ color: 'var(--fg-2)', fontFamily: SANS }}>
        Optional, but they help. Reading <span style={{ fontWeight: 500, color: 'var(--fg)' }}>{fileName}</span>.
      </p>

      <div className="mt-6 space-y-5">
        {DEMO_QUESTIONS.map((q) => (
          <div key={q.id}>
            <label className="block text-[13.5px]" style={{ color: 'var(--fg)', fontFamily: SANS, fontWeight: 500 }}>
              {q.prompt}
            </label>
            <textarea
              value={answers[q.id] ?? ''}
              onChange={(e) => setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))}
              placeholder={q.placeholder}
              rows={2}
              maxLength={600}
              className="mt-2 w-full resize-none px-4 py-3 text-[14px] outline-none transition-colors focus:border-[color:var(--ink)]"
              style={{
                borderRadius: 16,
                border: '1px solid rgba(29,29,31,0.12)',
                background: 'var(--fog-2)',
                color: 'var(--fg)',
                fontFamily: SANS,
              }}
            />
          </div>
        ))}
      </div>

      {error && (
        <p className="mt-4 text-[13px]" style={{ color: '#c0392b', fontFamily: SANS }}>
          {error}
        </p>
      )}

      <div className="mt-7 flex items-center gap-3">
        <button
          type="button"
          onClick={onBack}
          disabled={submitting}
          className="inline-flex items-center rounded-full px-5 transition-opacity hover:opacity-70 disabled:opacity-40"
          style={{ height: 44, border: '1px solid rgba(29,29,31,0.14)', color: 'var(--fg)', background: 'var(--fog-2)', fontFamily: SANS, fontSize: 14, fontWeight: 500 }}
        >
          Back
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={submitting}
          className="inline-flex items-center rounded-full px-6 transition-opacity hover:opacity-90 disabled:opacity-50"
          style={{ height: 44, background: 'var(--ink)', color: '#fff', fontFamily: SANS, fontSize: 14, fontWeight: 500 }}
        >
          {submitting ? 'Building…' : 'Build my persona'}
        </button>
      </div>
    </div>
  );
}
