'use client';

import { useEffect, useState } from 'react';

import Nav from '@/components/LandingClassy/Nav';
import Footer from '@/components/LandingClassy/Footer';
import { analytics } from '@/lib/analytics/events';
import { PersonaReveal } from '@/components/experience/PersonaReveal';
import { QuestionsStep, type AnswerOut } from '@/components/experience/QuestionsStep';
import { SignupWall } from '@/components/experience/SignupWall';
import { UploadStep } from '@/components/experience/UploadStep';
import type { DemoPreview } from '@/lib/experience/types';

type Step = 'upload' | 'questions' | 'analyzing' | 'reveal' | 'limited';

const SANS = "'Geist', sans-serif";
const MONO = "'JetBrains Mono', monospace";
const SERIF = "'Instrument Serif', Georgia, serif";

export default function ExperiencePage(): React.JSX.Element {
  const [step, setStep] = useState<Step>('upload');
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<DemoPreview | null>(null);
  const [token, setToken] = useState('');
  const [error, setError] = useState('');

  // If this browser has already spent its free previews, jump straight to the
  // sign-up wall instead of letting the visitor fill everything out again. This
  // is a UX hint only — the analyze route enforces the limit server-side. Runs
  // before the analytics effect below so a blocked visitor is redirected first.
  useEffect(() => {
    let active = true;
    fetch('/api/demo/quota')
      .then((r) => r.json())
      .then((q: { exhausted?: boolean }) => {
        if (active && q.exhausted) setStep('limited');
      })
      .catch(() => {
        // Non-fatal — enforcement still happens on analyze.
      });
    return () => {
      active = false;
    };
  }, []);

  // Funnel telemetry — fires on every step, including the new 'limited' step.
  useEffect(() => {
    analytics.experienceStepViewed({ step });
  }, [step]);

  const analyze = async (answers: AnswerOut[]) => {
    if (!file) return;
    setStep('analyzing');
    setError('');
    const startedAt = Date.now();
    try {
      const fd = new FormData();
      fd.append('resume', file);
      fd.append('answers', JSON.stringify(answers));
      const res = await fetch('/api/demo/analyze', { method: 'POST', body: fd });
      const data = (await res.json()) as { token?: string; preview?: DemoPreview; error?: string; limit?: boolean };
      if (res.status === 429 && data.limit) {
        setStep('limited');
        return;
      }
      if (!res.ok || !data.token || !data.preview) {
        throw new Error(data.error || 'Failed to build your persona.');
      }
      analytics.experienceAnalyzeSucceeded({ duration_ms: Date.now() - startedAt });
      setToken(data.token);
      setPreview(data.preview);
      setStep('reveal');
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Something went wrong.';
      analytics.experienceAnalyzeFailed({ error: message });
      setError(message);
      setStep('questions');
    }
  };

  return (
    <div className="min-h-screen antialiased" style={{ backgroundColor: 'var(--fog)' }}>
      <Nav />
      <main className="mx-auto max-w-[760px] px-6 pt-36 pb-24 md:pt-44">
        <header className="text-center">
          <p className="text-[11px] uppercase tracking-[0.2em]" style={{ color: 'var(--fg-3)', fontFamily: MONO }}>
            Experience PersonaOn
          </p>
          <h1
            className="mx-auto mt-4 max-w-[640px]"
            style={{ color: 'var(--ink)', fontFamily: SERIF, fontSize: 'clamp(36px, 6vw, 60px)', lineHeight: 1.02, letterSpacing: '-0.01em' }}
          >
            Meet your AI twin in 60 seconds
          </h1>
          <p className="mx-auto mt-4 max-w-[480px] text-[16px]" style={{ color: 'var(--fg-2)', fontFamily: SANS, lineHeight: 1.45 }}>
            Upload your resume, answer a couple of questions, and chat with the persona PersonaOn would build for you.
          </p>
        </header>

        <div
          className="mt-10"
          style={{
            borderRadius: 28,
            border: '1px solid rgba(29,29,31,0.08)',
            background: 'var(--fog-2)',
            boxShadow: '0 40px 90px rgba(29,29,31,0.10), 0 6px 18px rgba(29,29,31,0.05)',
            padding: 32,
          }}
        >
          {step === 'upload' && (
            <UploadStep
              onNext={(f) => {
                setFile(f);
                setStep('questions');
              }}
            />
          )}

          {step === 'questions' && file && (
            <QuestionsStep
              fileName={file.name}
              submitting={false}
              error={error}
              onBack={() => {
                setError('');
                setStep('upload');
              }}
              onSubmit={analyze}
            />
          )}

          {step === 'analyzing' && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div
                className="h-10 w-10 animate-spin rounded-full"
                style={{ border: '2px solid rgba(29,29,31,0.15)', borderTopColor: 'var(--ink)' }}
              />
              <p className="mt-4 text-[15px]" style={{ color: 'var(--ink)', fontFamily: SANS, fontWeight: 500 }}>
                Compiling your digital twin…
              </p>
              <p className="mt-1 text-[12px] uppercase tracking-[0.16em]" style={{ color: 'var(--fg-3)', fontFamily: MONO }}>
                Reading your resume and answers
              </p>
            </div>
          )}

          {step === 'reveal' && preview && <PersonaReveal preview={preview} token={token} />}

          {step === 'limited' && (
            <div className="py-4">
              <p className="mb-4 text-center text-[10px] uppercase tracking-[0.2em]" style={{ color: 'var(--fg-3)', fontFamily: MONO }}>
                Free demo limit reached
              </p>
              <SignupWall
                context="limit_reached"
                title="You've used your free previews"
                subtitle="You've built 2 demo personas on this device. Sign up free to build unlimited personas, keep chatting, and claim your own page."
              />
            </div>
          )}
        </div>

        <p className="mt-6 text-center text-[11px] uppercase tracking-[0.18em]" style={{ color: 'var(--fg-3)', fontFamily: MONO }}>
          Demo · resume processed in memory and discarded · nothing stored
        </p>
      </main>
      <Footer />
    </div>
  );
}
